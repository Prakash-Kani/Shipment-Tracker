# ========== Importing Libraries ==========
import asyncio
import inspect
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.tracker.shipment_status import *
from app.schemas.tracker import *
from app.tracker.gps_tracking import get_car_status, gps_login
from app.tracker.status_update_save import update_shipment_status
from app.tracker.messanger import send_whatsapp_message

# Reused (unchanged) from the time-interval workflow so both processes
# build exactly the same messages and share the same exception rules.
# from app.tracker.auto_update import STATUS_FUNCTIONS, EXCEPTION_STATUSES

# >>> ADJUST THIS IMPORT PATH to wherever these two existing helpers live <<<
from app.tracker.distance import calculate_driving_distance, calculate_distance, build_multi_point_route




STATUS_FUNCTIONS = {
    ShipmentStatus.BOOKED.value: create_booked_status,
    ShipmentStatus.AWAITING_PICKUP.value: create_awaiting_pickup_status,
    ShipmentStatus.PICKED_UP.value: create_picked_up_status,
    ShipmentStatus.IN_TRANSIT.value: create_in_transit_status,
    ShipmentStatus.AT_BORDER.value: create_at_border_status,
    ShipmentStatus.CUSTOMS_CLEARANCE.value: create_customs_clearance_status,
    ShipmentStatus.CUSTOMS_HOLD.value: create_customs_hold_status,
    ShipmentStatus.DELAYED.value: create_in_transit_delayed_status,
    ShipmentStatus.VEHICLE_BREAKDOWN.value: create_truck_breakdown_status,
    ShipmentStatus.WEATHER_ROAD_DELAY.value: create_weather_delay_status,
    ShipmentStatus.ARRIVED_AT_DESTINATION_HUB.value: create_arrived_destination_hub_status,
    ShipmentStatus.ARRIVED_AT_PICKUP_HUB.value: create_arrived_pickup_hub_status,
    ShipmentStatus.ARRIVED_AT_DELIVERY_HUB.value: create_arrived_delivery_hub_status,
    ShipmentStatus.OUT_FOR_DELIVERY.value: create_out_for_delivery_status,
    ShipmentStatus.DELIVERY_ATTEMPTED.value: create_delivery_attempted_status,
    ShipmentStatus.DELIVERY_EXCEPTION.value: create_delivery_exception_status,
    ShipmentStatus.DELIVERED.value: create_delivered_status,
    ShipmentStatus.CANCELLED_RETURNED.value: create_cancelled_returned_status,
    ShipmentStatus.WAITING_FOR_PICKUP.value: create_waiting_for_pickup_status,
    ShipmentStatus.PENDING_DELIVERED.value: create_pending_delivery_status,
}

EXCEPTION_STATUSES = {
    ShipmentStatus.DELAYED,
    ShipmentStatus.CUSTOMS_HOLD,
    ShipmentStatus.VEHICLE_BREAKDOWN,
    ShipmentStatus.WEATHER_ROAD_DELAY,
}


# ============ Distance-Based Automatic Shipment-Status Workflow ============
#
#   Get GPS -> distance to ACTIVE milestone -> pick next poll interval
#           -> evaluate milestone rules -> update milestone + shipment status
#           -> complete milestone -> activate next milestone -> repeat
#
# Only ONE milestone (the active one) is ever evaluated per step, so
# milestones are never skipped silently; a forward scan additionally catches
# the case where the truck's GPS jumped past several milestones between
# polls (see _find_target_milestone_index). The polling interval shrinks as
# the truck approaches the active milestone, so far-away trucks cost almost
# no GPS calls.
#
# Every tracked shipment is identified by the PAIR (truck_number,
# job_number), never truck_number alone - a truck can be running more than
# one job at a time, and one job's milestones/tracking must never bleed into
# another job's, even for the same truck. See `_tracker_key()`.


# ============ Configuration (everything tunable lives here) ============

@dataclass(frozen=True)
class DistanceTrackingConfig:
    # ---- GPS polling intervals (seconds) ----
    gps_intervals: Dict[str, int] = field(default_factory=lambda: {
        "FAR": 30 * 60,      # > 100 km      (configurable)
        "NORMAL": 10 * 60,   # 10 - 100 km   (configurable)
        "NEAR": 2 * 60,      # 2 - 10 km     -> every 2 minutes
        "VERY_NEAR": 30,     # 0.5 - 2 km    -> every 30 seconds
        "ARRIVAL": 10,       # < 500 m       -> high-frequency monitoring
    })

    # ---- Distance tier boundaries (km) ----
    far_km: float = 100.0
    normal_km: float = 10.0
    near_km: float = 2.0
    very_near_km: float = 1.0

    # Never sleep longer than half the time the truck needs to cover the
    # remaining distance at `max_speed_kmh`. Stops a long configured interval
    # (e.g. NORMAL) from letting a fast truck jump straight past a milestone.
    adaptive_cap_enabled: bool = True
    max_speed_kmh: float = 100.0
    adaptive_cap_fraction: float = 0.5

    # ---- Arrival radius per milestone type (metres) ----
    arrival_radius_m: Dict[str, float] = field(default_factory=lambda: {
        "pickup": 500.0,
        "pickup_stop": 500.0,   # an intermediate pickup (multi-pickup shipments)
        "transit": 500.0,
        "delivery_stop": 500.0,  # an intermediate delivery (multi-delivery shipments)
        "delivery": 500.0,
        "border": 1000.0,   # crossing zones are bigger than a single GPS point
        "customs": 1000.0,
    })

    # ---- Border-checkpoint matching ----
    # A checkpoint is considered "on this route" when BOTH of its points lie
    # within this distance of the driving-route polyline.
    checkpoint_match_radius_km: float = 2.0
    # Milestone becomes APPROACHING inside this distance (km)
    approach_km: float = 10.0
    # Leaving the radius by more than this factor counts as "really left"
    # (hysteresis against GPS fluctuation at the radius edge).
    exit_hysteresis: float = 1.5

    # ---- Motion detection (protects against GPS jitter) ----
    move_speed_kmh: float = 5.0          # reported speed >= this = moving
    move_min_displacement_m: float = 200.0  # OR moved >= this since last fix

    # ---- Pickup confirmation ----
    # Stage 1 (Arrived at Pickup Hub) fires as soon as the truck enters the
    # pickup milestone's arrival radius - see arrival_radius_m["pickup"].
    # Stage 2 (Waiting for Pickup) fires once the truck has then been seen
    # stationary at the hub for this long.
    pickup_min_dwell_seconds: int = 10 * 60       # must be seen stationary this long
    # Stage 3 (Picked Up / In Transit) fires once the truck then moves
    # continuously for this long, confirming it actually left with the load.
    pickup_move_confirm_seconds: int = 10 * 60    # continuous movement required
    pickup_move_grace_seconds: int = 60           # short stop (gate/traffic) tolerated

    # ---- Delivery confirmation ----
    # Truck must stay inside the delivery radius this long after arriving.
    delivery_confirm_seconds: int = 10 * 60

    # ---- Polling while validating pickup / delivery ----
    validation_moving_interval: int = 30
    validation_stationary_interval: int = 120

    # ---- Transit "pass-by" detection (avoids getting stuck on a missed point) ----
    pass_by_max_min_km: float = 3.0   # truck did come this close...
    pass_by_margin_km: float = 2.0    # ...and is now this much further away

    # ---- Forward skip-scan (catches a GPS jump that skipped SEVERAL
    # milestones at once, e.g. 550m -> 1.03km -> 2.5km between polls, where
    # the single-milestone pass_by check above never gets a chance to fire
    # because the truck was never recorded as "close" to the later ones) ----
    skip_scan_lookahead: int = 5          # how many milestones ahead to look
    skip_scan_arrival_margin: float = 1.5  # treat "within radius * this" as reached

    # ---- Route-deviation detection (human-initiated route change) ----
    # Only evaluated between Picked Up and Arrived at Delivery Hub.
    deviation_window_points: int = 6          # how many recent GPS points we keep
    deviation_min_points: int = 4             # minimum points before judging anything
    deviation_min_speed_kmh: float = 8.0      # ignore points below this (traffic/stop/jitter)
    deviation_consecutive_increases: int = 3  # this many of the window's steps must trend away
    deviation_distance_increase_km: float = 1.5  # AND net distance growth over the window
    default_milestone_spacing_km: float = 50.0   # default km passed to build_multi_point_route

    # ---- GPS session ----
    session_ttl_seconds: int = 2 * 60 * 60
    session_refresh_margin_seconds: int = 5 * 60   # refresh 5 min before expiry
    session_min_relogin_gap_seconds: int = 30      # don't hammer gps_login

    # ---- Errors ----
    error_retry_interval: int = 60

    # What unit does the existing calculate_distance() return? "km" or "m"
    calculate_distance_unit: str = "km"

    default_whatsapp_number: str = "918281993386"


CFG = DistanceTrackingConfig()


# ============ Milestone model ============

class MilestoneState(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    APPROACHING = "APPROACHING"
    ARRIVED = "ARRIVED"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


# Shipment status associated with each milestone type.
#
# "pickup" / "delivery" are the FIRST and LAST stop of a shipment and get
# full validation (5-minute movement rule / dwell confirmation). A shipment
# with more than one pickup or delivery point gets "pickup_stop" /
# "delivery_stop" milestones for the intermediate ones - these are
# pass-through, like a transit point, but carry their own status so the
# message correctly says a pickup/delivery happened rather than "In Transit".
MILESTONE_EVENT_LABEL = {
    "pickup": ShipmentStatus.WAITING_FOR_PICKUP.value,
    "pickup_stop": ShipmentStatus.PICKED_UP.value,
    "transit": ShipmentStatus.IN_TRANSIT.value,
    "delivery_stop": ShipmentStatus.PENDING_DELIVERED.value,
    "delivery": ShipmentStatus.ARRIVED_AT_DELIVERY_HUB.value,
    "border": ShipmentStatus.AT_BORDER.value,
    "customs": ShipmentStatus.CUSTOMS_CLEARANCE.value,
}

# Milestone types that need nothing beyond "arrived -> emit status -> complete"
# (unlike the FIRST pickup/LAST delivery, which need dwell/movement
# validation). This set also defines which milestone types are eligible to
# be skip-scanned or skip-origins in _find_target_milestone_index, and which
# types the route-deviation check is allowed to run against.
PASS_THROUGH_MILESTONE_STATUS = {
    "pickup_stop": ShipmentStatus.PICKED_UP,
    "transit": ShipmentStatus.IN_TRANSIT,
    "delivery_stop": ShipmentStatus.PENDING_DELIVERED,
    "border": ShipmentStatus.AT_BORDER,
    "customs": ShipmentStatus.CUSTOMS_CLEARANCE,
}

# Manual statuses that end the distance tracking for good
TERMINAL_STATUSES_DISTANCE = {
    ShipmentStatus.PENDING_DELIVERED,
    ShipmentStatus.CANCELLED_RETURNED,
}

# Shipment-status values during which route-deviation detection is active
# ("Picked Up -> Arrived at Delivery Hub", per the requirement). Note
# PICKED_UP itself is included since In Transit is emitted in the same
# breath as Picked Up; ARRIVED_AT_DELIVERY_HUB/DELIVERED/PENDING_DELIVERED
# are excluded because the truck is meant to be stationary by then.
_DEVIATION_INELIGIBLE_STATUSES = {
    ShipmentStatus.BOOKED,
    ShipmentStatus.WAITING_FOR_PICKUP,
    ShipmentStatus.AWAITING_PICKUP,
    ShipmentStatus.ARRIVED_AT_DELIVERY_HUB,
    ShipmentStatus.PENDING_DELIVERED,
    ShipmentStatus.DELIVERED,
}


# ============ Border-checkpoint registry ============
#
# Each checkpoint has exactly two GPS points - one on each side of the
# crossing (e.g. the exit-country booth and the entry-country booth).
# Which point becomes "At Border" and which becomes "Customs Clearance" is
# NOT fixed: it is worked out per-shipment from the direction of travel
# (whichever point the route reaches first is "At Border").
#
# Add more corridors here (e.g. Malaysia <-> Thailand) the same way.
CHECKPOINTS: Dict[str, List[Tuple[float, float]]] = {
    "Tuas Checkpoint": [
        (1.3473137, 103.632754),
        (1.350822, 103.632993),
    ],
    "Woodlands Crossing": [
        (1.443037, 103.768157),
        (1.452786, 103.769093),
    ],
    "Second link CIQ": [
        (1.376594, 103.601376),
        (1.379333, 103.595744)
    ],
    "Johor Bahru Checkpoint CIQ": [
        (1.459125, 103.767396),
        (1.467766, 103.768494)
    ],
    "Thailand": [
            (6.508181, 100.420908),
            (6.579055, 100.411309)
        ],
}


# ============ save_milestone(): dedicated milestone persistence hook ============
#
# Requirement: "Create a dedicated function for saving milestone information
# ... for now the function only needs to print/log the milestone data ...
# structure it so the print/logging implementation can be replaced with an
# API call in the future."
#
# Call sites in this file (see below): milestone creation (status="pending"
# or whatever status a resumed job's milestone already had), milestone
# completion/skip (_complete), and route-deviation regeneration
# (status="skipped" for obsoleted milestones, status="updated" for the newly
# generated ones).
def save_milestone(job_number: str, truck_number: str, milestone_data: dict) -> None:
    """
    Persists ONE milestone record for a specific job_number + truck_number.

    This is a stub: it logs the record. Replace the body with a real
    API/DB call later - keep the signature (job_number, truck_number,
    milestone_data) and the shape of `milestone_data` as the contract, so
    every call site in this file keeps working unchanged.

    `milestone_data` should always identify the job/truck explicitly (not
    rely on it being inferred from context), include the milestone's
    sequence/type/lat/lon, and a `status` field using this vocabulary:
        "pending"   - milestone created, not yet reached
        "completed" - milestone reached and validated normally
        "skipped"   - milestone passed without stopping, or made obsolete
                       by a route recalculation
        "updated"   - milestone (re)generated by a route recalculation
    Historical milestones (completed/skipped) are never deleted or
    overwritten in place by this function - every call is its own record,
    which is what "keep historical milestone information" means in
    practice once this is backed by a real store: write new rows, don't
    mutate old ones.
    """
    record = {
        "job_number": job_number,
        "truck_number": truck_number,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        **milestone_data,
    }
    print(
        f"[MILESTONE SAVE] job={job_number} truck={truck_number} "
        f"seq={record.get('sequence')} type={record.get('type')} "
        f"status={record.get('status')} -> {record}"
    )


def label_milestone_points(points: List[tuple]) -> List[Tuple[float, float, str]]:
    """
    Returns milestone points as (lat, lon, status_label):

        [(1.2968101, 103.8947034, 'Awaiting Pickup'),
         (1.9128, 103.20684, 'In Transit'),
         ...
         (5.7998387, 102.5685984, 'Arrived at Delivery Hub')]

    First point = pickup, last point = delivery, everything else = transit.
    Points that already carry a label are kept as they are, so it is safe to
    call this on the output of an already-updated calculate_driving_distance().

    This is the SINGLE-pickup/SINGLE-delivery labelling helper (kept for
    backward compatibility with build_route_milestones() /
    build_milestones_with_checkpoints()). For shipments with more than one
    pickup or delivery point, use _type_route_items() instead, which knows
    about "pickup_stop" / "delivery_stop".
    """
    labelled = []
    last = len(points) - 1
    for i, p in enumerate(points):
        lat, lon = float(p[0]), float(p[1])
        if len(p) >= 3 and p[2]:
            label = str(p[2])
        else:
            m_type = "pickup" if i == 0 else "delivery" if i == last else "transit"
            label = MILESTONE_EVENT_LABEL[m_type]
        labelled.append((lat, lon, label))
    return labelled


def _type_route_items(points: List[Any], pickup_count: int = 1, delivery_count: int = 1) -> List[dict]:
    """
    Types a sequence of route points for the GENERAL multi-pickup /
    multi-delivery case:

        points[0]                      -> "pickup"       (full validation)
        points[1 .. pickup_count-1]    -> "pickup_stop"   (pass-through)
        points[pickup_count .. -delivery_count-1] -> "transit"
        points[-delivery_count .. -2]  -> "delivery_stop" (pass-through)
        points[-1]                     -> "delivery"      (full validation)

    pickup_count=1, delivery_count=1 (the default) reduces to the original
    single-pickup/single-delivery behaviour: just points[0]="pickup",
    points[-1]="delivery", everything else "transit".
    """
    n = len(points)
    if pickup_count < 1 or delivery_count < 1:
        raise ValueError("pickup_count and delivery_count must each be at least 1.")
    if pickup_count + delivery_count > n:
        raise ValueError(
            f"pickup_count ({pickup_count}) + delivery_count ({delivery_count}) "
            f"can't exceed the number of route points ({n})."
        )

    items = []
    for i, p in enumerate(points):
        lat, lon = float(p[0]), float(p[1])

        if i == 0:
            m_type = "pickup"
        elif i < pickup_count:
            m_type = "pickup_stop"
        elif i == n - 1:
            m_type = "delivery"
        elif i >= n - delivery_count:
            m_type = "delivery_stop"
        else:
            m_type = "transit"

        existing_label = None
        if isinstance(p, dict):
            existing_label = p.get("shipment_status")
        elif len(p) > 2 and p[2]:
            existing_label = str(p[2])

        items.append({
            "latitude": lat,
            "longitude": lon,
            "type": m_type,
            "shipment_status": existing_label or MILESTONE_EVENT_LABEL[m_type],
        })
    return items


def _latlon_to_local_km(lat: float, lon: float, ref_lat: float) -> Tuple[float, float]:
    """Small-area equirectangular projection (good enough for one polyline segment)."""
    import math
    r = 6371.0
    return r * math.radians(lon) * math.cos(math.radians(ref_lat)), r * math.radians(lat)


def _point_to_segment(p: tuple, a: tuple, b: tuple) -> Tuple[float, float]:
    """Returns (distance_km, t) where t in [0, 1] is how far along segment a->b the
    projection of p falls (0 = at a, 1 = at b)."""
    ref_lat = (p[0] + a[0] + b[0]) / 3
    px, py = _latlon_to_local_km(p[0], p[1], ref_lat)
    ax, ay = _latlon_to_local_km(a[0], a[1], ref_lat)
    bx, by = _latlon_to_local_km(b[0], b[1], ref_lat)
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    t = 0.0 if seg_len2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    proj_x, proj_y = ax + t * dx, ay + t * dy
    return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5, t


def nearest_polyline_index(polyline: List[tuple], lat: float, lon: float) -> Tuple[float, float]:
    """
    Returns (route_position, distance_km) of the point on `polyline` closest to
    (lat, lon), where route_position is a fractional index (e.g. 4.3 = 30% of
    the way from vertex 4 to vertex 5). Using the fractional position (rather
    than snapping to the nearest vertex) is what lets two closely-spaced
    points - such as a border checkpoint's two sides, only a few hundred
    metres apart - be ordered correctly even on a coarse polyline.
    """
    if len(polyline) == 1:
        p = polyline[0]
        return 0.0, _distance_km(lat, lon, float(p[0]), float(p[1]))

    best_pos, best_d = 0.0, float("inf")
    for i in range(len(polyline) - 1):
        a, b = polyline[i], polyline[i + 1]
        d, t = _point_to_segment((lat, lon), (float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
        if d < best_d:
            best_d, best_pos = d, i + t
    return best_pos, best_d


def match_checkpoints_to_route(
    route_polyline: List[tuple],
    checkpoints: Dict[str, List[Tuple[float, float]]] = None,
    radius_km: float = None,
) -> List[dict]:
    """
    Finds which border checkpoints this particular route actually crosses, and
    in which direction it crosses them.

    A checkpoint is "on the route" only when BOTH of its points fall within
    `radius_km` of the driving-route polyline - this is what lets a
    Singapore<->Malaysia checkpoint be silently skipped for a route that
    never goes near it, and lets the same registry serve every direction and
    every corridor (Thailand, etc.) without extra branching.

    For a matched checkpoint, the point the route reaches FIRST becomes
    "At Border" and the one it reaches SECOND becomes "Customs Clearance".
    Reverse the direction of travel (Malaysia -> Singapore instead of
    Singapore -> Malaysia) and the two labels swap automatically, because
    the ordering is driven by position along the route, not by which point
    happens to be listed first in CHECKPOINTS.

    Returns matches ordered by where they occur along the route.
    """
    checkpoints = CHECKPOINTS if checkpoints is None else checkpoints
    radius_km = CFG.checkpoint_match_radius_km if radius_km is None else radius_km

    matches = []
    for name, points in checkpoints.items():
        if len(points) != 2:
            raise ValueError(f"Checkpoint {name!r} must have exactly two points.")

        resolved = []
        for lat, lon in points:
            idx, dist = nearest_polyline_index(route_polyline, lat, lon)
            resolved.append({"latitude": lat, "longitude": lon, "route_index": idx, "distance_km": dist})

        if any(r["distance_km"] > radius_km for r in resolved):
            continue  # this checkpoint is not on this route

        resolved.sort(key=lambda r: r["route_index"])  # earlier index = reached first
        matches.append({
            "checkpoint": name,
            "at_border": resolved[0],
            "customs_clearance": resolved[1],
            "route_index": (resolved[0]["route_index"] + resolved[1]["route_index"]) / 2,
        })

    matches.sort(key=lambda m: m["route_index"])
    return matches


def insert_border_checkpoints(
    route_items: List[dict],
    route_polyline: List[tuple],
    checkpoints: Dict[str, List[Tuple[float, float]]] = None,
    radius_km: float = None,
) -> List[dict]:
    """
    Takes an ALREADY-TYPED list of route items (as produced by
    _type_route_items() or the single-pickup/delivery equivalent below),
    finds every border checkpoint the route's polyline actually crosses, and
    inserts "At Border" + "Customs Clearance" milestones at the correct
    position and with the correct lat/lon for the direction of travel.

    The first and last items (whatever their type - pickup, or a synthetic
    "current position" anchor during route-deviation recalculation) are
    always kept first and last; everything else is free to be reordered by
    where it actually falls along the route.
    """
    if not route_polyline:
        raise ValueError("route_polyline is required to place border checkpoints.")
    if len(route_items) < 2:
        raise ValueError("At least two route items (start and end) are required.")

    route_items = [dict(it) for it in route_items]  # don't mutate the caller's list
    for item in route_items:
        idx, _ = nearest_polyline_index(route_polyline, item["latitude"], item["longitude"])
        item["route_index"] = idx

    first, last = route_items[0], route_items[-1]
    middle = route_items[1:-1]

    for match in match_checkpoints_to_route(route_polyline, checkpoints, radius_km):
        middle.append({
            "latitude": match["at_border"]["latitude"],
            "longitude": match["at_border"]["longitude"],
            "type": "border",
            "shipment_status": MILESTONE_EVENT_LABEL["border"],
            "checkpoint": match["checkpoint"],
            "route_index": match["at_border"]["route_index"],
        })
        middle.append({
            "latitude": match["customs_clearance"]["latitude"],
            "longitude": match["customs_clearance"]["longitude"],
            "type": "customs",
            "shipment_status": MILESTONE_EVENT_LABEL["customs"],
            "checkpoint": match["checkpoint"],
            "route_index": match["customs_clearance"]["route_index"],
        })

    middle.sort(key=lambda it: it["route_index"])
    ordered = [first] + middle + [last]

    for i, item in enumerate(ordered):
        item["sequence"] = i + 1
        item.pop("route_index", None)
        item.setdefault("status", "PENDING")
        item.setdefault("arrived_at", None)
        item.setdefault("departed_at", None)
        item.setdefault("completed_at", None)
    return ordered


def build_milestones_with_checkpoints(
    milestone_points: List[tuple],
    route_polyline: List[tuple],
    checkpoints: Dict[str, List[Tuple[float, float]]] = None,
    radius_km: float = None,
) -> List[dict]:
    """
    SINGLE-pickup/SINGLE-delivery convenience wrapper around
    insert_border_checkpoints(), kept for backward compatibility with
    build_route_milestones() / RouteMilestoneRequest and anyone already
    calling this function directly. For multi-pickup/multi-delivery
    shipments, use build_milestones_for_route() instead.
    """
    labelled = label_milestone_points(milestone_points)
    last = len(labelled) - 1
    route_items = [
        {
            "latitude": lat, "longitude": lon,
            "type": "pickup" if i == 0 else "delivery" if i == last else "transit",
            "shipment_status": label,
        }
        for i, (lat, lon, label) in enumerate(labelled)
    ]
    return insert_border_checkpoints(route_items, route_polyline, checkpoints, radius_km)


def build_milestones_for_route(
    points: List[Any],
    pickup_count: int = 1,
    delivery_count: int = 1,
    route_polyline: Optional[List[tuple]] = None,
    include_border_checkpoints: bool = True,
    checkpoints: Dict[str, List[Tuple[float, float]]] = None,
    radius_km: float = None,
) -> List[dict]:
    """
    General entry point covering all four shipment shapes:
        single pickup  -> single delivery   (pickup_count=1, delivery_count=1)
        multiple pickup -> single delivery   (pickup_count=N, delivery_count=1)
        single pickup  -> multiple delivery  (pickup_count=1, delivery_count=M)
        multiple pickup -> multiple delivery (pickup_count=N, delivery_count=M)
    """
    route_items = _type_route_items(points, pickup_count, delivery_count)
    if include_border_checkpoints and route_polyline:
        return insert_border_checkpoints(route_items, route_polyline, checkpoints, radius_km)

    for i, item in enumerate(route_items):
        item["sequence"] = i + 1
        item.setdefault("status", "PENDING")
        item.setdefault("arrived_at", None)
        item.setdefault("departed_at", None)
        item.setdefault("completed_at", None)
    return route_items


def _tail_route_items(points: List[Any], delivery_stop_coords: Set[Tuple[float, float]]) -> List[dict]:
    """
    Types a RECALCULATED route used after a route-deviation: points[0] is
    just the truck's CURRENT POSITION (not a real business stop - it must
    never be typed "pickup" or it would re-trigger the 5-minute pickup
    validation), and the rest lead to whichever delivery stop(s) are still
    outstanding. Every point is "transit" except: a point whose coordinates
    match one of `delivery_stop_coords` -> "delivery_stop", and the final
    point, which is always "delivery" so the normal dwell-confirmation rule
    still applies to the real final destination.
    """
    last = len(points) - 1
    items = []
    for i, p in enumerate(points):
        lat, lon = float(p[0]), float(p[1])
        key = (round(lat, 6), round(lon, 6))

        if i == last:
            m_type = "delivery"
        elif key in delivery_stop_coords:
            m_type = "delivery_stop"
        else:
            m_type = "transit"

        existing_label = None
        if isinstance(p, dict):
            existing_label = p.get("shipment_status")
        elif len(p) > 2 and p[2]:
            existing_label = str(p[2])

        items.append({
            "latitude": lat, "longitude": lon, "type": m_type,
            "shipment_status": existing_label or MILESTONE_EVENT_LABEL[m_type],
        })
    return items


@dataclass
class Milestone:
    sequence: int
    latitude: float
    longitude: float
    type: str                      # "pickup" | "pickup_stop" | "transit" | "border" | "customs" | "delivery_stop" | "delivery"
    shipment_status: str           # status/event tied to this milestone
    state: MilestoneState = MilestoneState.PENDING
    arrived_at: Optional[datetime] = None
    departed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    min_distance_km: float = float("inf")

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "type": self.type,
            "status": self.state.value,
            "shipment_status": self.shipment_status,
            "arrived_at": self.arrived_at.isoformat() if self.arrived_at else None,
            "departed_at": self.departed_at.isoformat() if self.departed_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _milestones_from_dicts(items: List[dict]) -> List[Milestone]:
    """
    Builds milestones from objects like the ones returned by get_distance_tracking_state():
    {"sequence", "latitude", "longitude", "type", "status", "shipment_status",
     "arrived_at", "departed_at", "completed_at"}
    Lets a shipment resume mid-route (e.g. pickup already COMPLETED).
    """
    items = sorted(items, key=lambda d: d.get("sequence", 0))
    last = len(items) - 1
    milestones = []
    for i, d in enumerate(items):
        default_type = "pickup" if i == 0 else "delivery" if i == last else "transit"
        m_type = d.get("type") or default_type
        if m_type not in MILESTONE_EVENT_LABEL:
            raise ValueError(f"Unknown milestone type: {m_type!r}")
        try:
            state = MilestoneState(str(d.get("status", "PENDING")).upper())
        except ValueError:
            raise ValueError(f"Unknown milestone status: {d.get('status')!r}")
        milestones.append(
            Milestone(
                sequence=i + 1,
                latitude=float(d["latitude"]),
                longitude=float(d["longitude"]),
                type=m_type,
                shipment_status=d.get("shipment_status") or MILESTONE_EVENT_LABEL[m_type],
                state=state,
                arrived_at=_parse_dt(d.get("arrived_at")),
                departed_at=_parse_dt(d.get("departed_at")),
                completed_at=_parse_dt(d.get("completed_at")),
            )
        )
    return milestones


def build_milestones(milestone_points: List[Any]) -> List[Milestone]:
    if not milestone_points or len(milestone_points) < 2:
        raise ValueError("At least a pickup and a delivery milestone are required.")

    if isinstance(milestone_points[0], dict):
        return _milestones_from_dicts(milestone_points)

    milestones = []
    last = len(milestone_points) - 1
    for i, (lat, lon, label) in enumerate(label_milestone_points(milestone_points)):
        m_type = "pickup" if i == 0 else "delivery" if i == last else "transit"
        milestones.append(
            Milestone(
                sequence=i + 1,
                latitude=lat,
                longitude=lon,
                type=m_type,
                shipment_status=label,
            )
        )
    return milestones


# ============ GPS helpers ============

@dataclass
class GPSReading:
    latitude: float
    longitude: float
    timestamp: Optional[str]
    speed: float
    direction: Optional[float]
    address: Optional[str]
    vehicle_status: Optional[int]
    raw: dict


def parse_car_status(response: Any) -> Optional[GPSReading]:
    """Converts get_car_status() output into a GPSReading (or None)."""
    if not isinstance(response, dict) or not response.get("result"):
        return None
    r = response["result"][0]
    # The API returns micro-degrees: 103444728 -> 103.444728
    return GPSReading(
        longitude=r["logGisx"] / 1_000_000,
        latitude=r["logGisy"] / 1_000_000,
        timestamp=r.get("logDTime"),
        speed=float(r.get("logSpeed") or 0.0),
        direction=r.get("direct"),
        address=r.get("address"),
        vehicle_status=r.get("status"),
        raw=r,
    )


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    value = float(calculate_distance(lat1, lon1, lat2, lon2))
    return value / 1000.0 if CFG.calculate_distance_unit == "m" else value


async def _maybe_await(func, **kwargs):
    if inspect.iscoroutinefunction(func):
        return await func(**kwargs)
    return await asyncio.to_thread(func, **kwargs)


def _extract_session_id(login_response: Any) -> str:
    if isinstance(login_response, str) and login_response:
        return login_response
    if isinstance(login_response, dict):
        for key in ("session_id", "sessionId", "sessionid"):
            if login_response.get(key):
                return str(login_response[key])
        for key in ("result", "data"):
            inner = login_response.get(key)
            if inner:
                try:
                    return _extract_session_id(inner)
                except RuntimeError:
                    pass
    raise RuntimeError(f"Could not read a session_id from gps_login() response: {login_response!r}")


# ============ GPS session management (auto-refresh every ~2 hours) ============

class GPSSessionManager:
    """
    One shared GPS session for every tracked truck/job.

    - Logs in lazily on first use.
    - Reuses the session while valid.
    - Refreshes automatically shortly BEFORE the 2-hour expiry.
    - Can be invalidated when the API rejects the session early.
    - A lock guarantees that many trucks polling at once trigger only one login.
    """

    def __init__(self):
        self._session_id: Optional[str] = None
        self._created_at: Optional[datetime] = None
        self._expires_at: Optional[datetime] = None
        self._lock = asyncio.Lock()

    def _is_valid(self) -> bool:
        if not self._session_id or not self._expires_at:
            return False
        margin = timedelta(seconds=CFG.session_refresh_margin_seconds)
        return datetime.now(timezone.utc) < self._expires_at - margin

    async def _login(self):
        response = await _maybe_await(gps_login)
        self._session_id = _extract_session_id(response)
        self._created_at = datetime.now(timezone.utc)
        self._expires_at = self._created_at + timedelta(seconds=CFG.session_ttl_seconds)
        print(f"[GPS] New session created, expires at {self._expires_at.isoformat()}")

    async def get_session_id(self) -> str:
        async with self._lock:
            if not self._is_valid():
                await self._login()
            return self._session_id

    async def invalidate(self, failed_session_id: str):
        """Called when the API rejected `failed_session_id` before it expired."""
        async with self._lock:
            if self._session_id != failed_session_id:
                return  # someone already refreshed it
            age = (datetime.now(timezone.utc) - self._created_at).total_seconds()
            if age < CFG.session_min_relogin_gap_seconds:
                return  # brand-new session: the problem is not the session
            self._session_id = None
            self._expires_at = None

    async def get_truck_reading(self, truck_number: str) -> Optional[GPSReading]:
        """Fetches the live position; re-authenticates once if the session looks dead."""
        for attempt in range(2):
            session_id = await self.get_session_id()
            try:
                response = await self._call_get_car_status(truck_number, session_id)
            except Exception as exc:
                print(f"[{truck_number}] get_car_status failed: {exc}")
                response = None

            session_rejected = (
                not isinstance(response, dict) or response.get("result") is None
            )
            if not session_rejected:
                return parse_car_status(response)   # empty list -> None (no data)

            if attempt == 0:
                await self.invalidate(session_id)
        return None

    @staticmethod
    async def _call_get_car_status(truck_number: str, session_id: str):
        kwargs = {"car_number": truck_number}
        try:
            if "session_id" in inspect.signature(get_car_status).parameters:
                kwargs["session_id"] = session_id
        except (TypeError, ValueError):
            pass
        return await _maybe_await(get_car_status, **kwargs)


gps_session = GPSSessionManager()


# ============ Polling interval selection ============

def select_gps_interval(distance_km: float) -> Tuple[str, int]:
    """Returns (tier_name, seconds) for the distance to the active milestone."""
    if distance_km > CFG.far_km:
        tier = "FAR"
    elif distance_km > CFG.normal_km:
        tier = "NORMAL"
    elif distance_km > CFG.near_km:
        tier = "NEAR"
    elif distance_km > CFG.very_near_km:
        tier = "VERY_NEAR"
    else:
        tier = "ARRIVAL"

    seconds = CFG.gps_intervals[tier]

    if CFG.adaptive_cap_enabled and tier != "ARRIVAL":
        radius_km = CFG.arrival_radius_m["transit"] / 1000
        eta_seconds = max(distance_km - radius_km, 0) / CFG.max_speed_kmh * 3600
        cap = max(int(eta_seconds * CFG.adaptive_cap_fraction), CFG.gps_intervals["ARRIVAL"])
        seconds = min(seconds, cap)

    return tier, seconds


# ============ Per-shipment tracking state ============

class DistanceTrackingState:
    def __init__(
        self,
        truck_number: str,
        job_number: str,
        driver_name: str,
        route_from: str,
        route_to: str,
        reply_number: str,
        whatsapp: bool,
        milestones: List[Milestone],
    ):
        self.truck_number = truck_number
        self.job_number = job_number
        self.driver_name = driver_name
        self.route_from = route_from
        self.route_to = route_to
        self.reply_number = reply_number
        self.whatsapp = whatsapp

        self.milestones = milestones

        # Start at the first milestone that is not already COMPLETED/SKIPPED
        # (normally index 0; later when resuming a shipment that is already in transit).
        done = (MilestoneState.COMPLETED, MilestoneState.SKIPPED)
        start = next((i for i, m in enumerate(milestones) if m.state not in done), None)
        if start is None:
            raise ValueError("Every milestone is already completed - nothing to track.")
        self.current_milestone_index = start
        if self.milestones[start].state == MilestoneState.PENDING:
            self.milestones[start].state = MilestoneState.ACTIVE

        # Pickup already done -> shipment is In Transit; skip Booked/Awaiting/Picked Up
        self.shipment_status: ShipmentStatus = (
            ShipmentStatus.IN_TRANSIT if start > 0 else ShipmentStatus.BOOKED
        )
        self.current_distance_km: Optional[float] = None
        self.poll_tier: Optional[str] = None
        self.last_interval: int = CFG.gps_intervals["NORMAL"]

        self.last_gps_check: Optional[datetime] = None
        self.next_gps_check: datetime = datetime.now(timezone.utc)

        self.last_reading: Optional[GPSReading] = None
        self.stale_readings = 0

        # pickup validation (first pickup only): Arrived at Pickup Hub (on
        # radius entry) -> Waiting for Pickup (after pickup_min_dwell_seconds
        # stationary) -> Picked Up / In Transit (after continuous movement).
        self.pickup_stationary_since: Optional[datetime] = None
        self.movement_started_at: Optional[datetime] = None
        self.last_moving_at: Optional[datetime] = None
        self.waiting_for_pickup_sent = start > 0
        self.picked_up_sent = start > 0

        # delivery validation (final delivery only)
        self.delivery_inside_since: Optional[datetime] = None

        # route-deviation detection: rolling window of recent tracking points
        # (requirement #5). Each entry: {timestamp, latitude, longitude,
        # speed, vehicle_status, distance_to_expected_km, milestone_index}.
        self.tracking_history: List[dict] = []
        self.deviation_count = 0
        self.last_deviation_at: Optional[datetime] = None

        self.paused = False
        self.finished = False
        self.task: Optional[asyncio.Task] = None

    @property
    def active(self) -> Milestone:
        return self.milestones[self.current_milestone_index]

    def activate_next(self):
        """Current milestone is done -> next one becomes the only active one."""
        if self.current_milestone_index >= len(self.milestones) - 1:
            self.finished = True
            return
        self.current_milestone_index += 1
        self.active.state = MilestoneState.ACTIVE

    def to_dict(self) -> dict:
        ms = self.active
        return {
            "shipment_id": self.job_number,
            "job_number": self.job_number,
            "truck_number": self.truck_number,
            "shipment_status": self.shipment_status.value,
            "current_milestone_index": self.current_milestone_index,
            "current_milestone": {
                "latitude": ms.latitude,
                "longitude": ms.longitude,
                "type": ms.type,
            },
            "current_distance_km": self.current_distance_km,
            "poll_tier": self.poll_tier,
            "last_gps_check": self.last_gps_check.isoformat() if self.last_gps_check else None,
            "next_gps_check": self.next_gps_check.isoformat(),
            "milestone_status": ms.state.value,
            "pickup_stationary_since": (
                self.pickup_stationary_since.isoformat() if self.pickup_stationary_since else None
            ),
            "movement_started_at": (
                self.movement_started_at.isoformat() if self.movement_started_at else None
            ),
            "deviation_count": self.deviation_count,
            "last_deviation_at": self.last_deviation_at.isoformat() if self.last_deviation_at else None,
            "paused": self.paused,
            "milestones": [m.to_dict() for m in self.milestones],
        }


def _tracker_key(truck_number: str, job_number: str) -> str:
    """
    One truck can run several jobs at once, so every tracker is keyed by the
    PAIR (truck_number, job_number), never by truck_number alone - that is
    what keeps one job's milestones/tracking from ever overwriting another
    job's data for the same truck.
    """
    return f"{truck_number}::{job_number}"


# One entry per (truck, job) with an active or paused distance workflow
distance_trackers: Dict[str, DistanceTrackingState] = {}

# Protects the shared `distance_trackers` dictionary
distance_trackers_lock = asyncio.Lock()


def list_jobs_for_truck(truck_number: str) -> List[str]:
    """All job_numbers currently tracked (running or paused) for this truck."""
    prefix = f"{truck_number}::"
    return [
        t.job_number for key, t in distance_trackers.items()
        if key.startswith(prefix)
    ]


def _log(t: DistanceTrackingState, message: str):
    print(f"[job={t.job_number} truck={t.truck_number}] {message}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============ Status emission (message + DB save + WhatsApp) ============

async def emit_status(
    t: DistanceTrackingState,
    status: ShipmentStatus,
    reading: Optional[GPSReading],
):
    """
    Same building blocks as send_status_message() in auto_update.py
    (STATUS_FUNCTIONS -> update_shipment_status -> WhatsApp), but it reuses the
    GPS reading we already fetched instead of calling the GPS API again.
    """
    if reading is None:
        reading = await gps_session.get_truck_reading(t.truck_number)

    if reading is not None:
        latitude, longitude = reading.latitude, reading.longitude
        current_location, speed = reading.address, reading.speed
    else:
        ms = t.active
        latitude, longitude = ms.latitude, ms.longitude
        current_location, speed = "Location unavailable", 0.0

    message = STATUS_FUNCTIONS[status](
        job_number=t.job_number,
        truck_number=t.truck_number,
        driver_name=t.driver_name,
        route_from=t.route_from,
        route_to=t.route_to,
        current_location=current_location,
    )

    update_shipment_status(
        job_number=t.job_number,
        truck_number=t.truck_number,
        shipment_status=status,
        message=message,
        longitude=str(longitude),
        latitude=str(latitude),
        current_location=current_location,
        speed=str(round(speed, 2)),
    )
    t.shipment_status = status
    _log(t, f"Status -> {status.value}")

    if t.whatsapp:
        try:
            await send_whatsapp_message(
                to=t.reply_number or CFG.default_whatsapp_number, message=message
            )
        except Exception as exc:
            # The status is already saved; a WhatsApp failure must not cause a re-send loop.
            _log(t, f"WhatsApp send failed (status was saved): {exc}")


# ============ Motion detection ============

def is_moving(previous: Optional[GPSReading], current: GPSReading) -> bool:
    """Moving = reported speed is meaningful OR the fix jumped clearly more than jitter."""
    if current.speed >= CFG.move_speed_kmh:
        return True
    if previous is None:
        return False
    displacement_m = _distance_km(
        previous.latitude, previous.longitude, current.latitude, current.longitude
    ) * 1000
    return displacement_m >= CFG.move_min_displacement_m


# ============ Milestone rules ============

def _complete(t: DistanceTrackingState, ms: Milestone, now: datetime, skipped: bool = False):
    ms.state = MilestoneState.SKIPPED if skipped else MilestoneState.COMPLETED
    ms.completed_at = now
    if ms.departed_at is None and ms.type in ("transit", "border", "customs"):
        ms.departed_at = now
    save_milestone(t.job_number, t.truck_number, {
        **ms.to_dict(),
        "status": "skipped" if skipped else "completed",
    })
    t.activate_next()


async def _validate_pickup(t, ms, reading, moving, now) -> bool:
    """
    Pickup is a three-stage sequence:
      1. Arrived at Pickup Hub - already fired (in _evaluate_milestone's
         ARRIVED branch) the moment the truck entered the pickup radius.
      2. Waiting for Pickup - fired here once the truck has been seen
         stationary at the hub for CFG.pickup_min_dwell_seconds (10 min).
      3. Picked Up / In Transit - fired once it then moves continuously for
         CFG.pickup_move_confirm_seconds, confirming an actual departure
         rather than a brief manoeuvre. A short stop (gate / traffic light)
         inside that window is tolerated via CFG.pickup_move_grace_seconds.
    """
    # 1) wait for the truck to stop at pickup
    if t.pickup_stationary_since is None:
        if not moving:
            t.pickup_stationary_since = now
        t.movement_started_at = None
        return False

    dwell = (now - t.pickup_stationary_since).total_seconds()
    if dwell < CFG.pickup_min_dwell_seconds:
        if moving:                       # just a blip / still manoeuvring
            t.pickup_stationary_since = None
            t.waiting_for_pickup_sent = False
        return False

    if not t.waiting_for_pickup_sent:
        await emit_status(t, ShipmentStatus.WAITING_FOR_PICKUP, reading)
        t.waiting_for_pickup_sent = True

    # 2) continuous movement
    if moving:
        t.last_moving_at = now
        if t.movement_started_at is None:
            t.movement_started_at = now
            _log(t, "Movement started after pickup stop - validating 5-minute rule")
    else:
        gap = (now - t.last_moving_at).total_seconds() if t.last_moving_at else float("inf")
        if gap > CFG.pickup_move_grace_seconds:
            t.movement_started_at = None      # movement was not continuous
        return False

    if (now - t.movement_started_at).total_seconds() < CFG.pickup_move_confirm_seconds:
        return False

    # Confirmed: Waiting for Pickup -> Picked Up -> In Transit
    if not t.picked_up_sent:
        await emit_status(t, ShipmentStatus.PICKED_UP, reading)
        t.picked_up_sent = True
    await emit_status(t, ShipmentStatus.IN_TRANSIT, reading)

    ms.departed_at = t.movement_started_at
    _complete(t, ms, now)
    return True


async def _validate_delivery(t, ms, dist_km, reading, now) -> bool:
    """Delivered once the truck has stayed inside the delivery radius long enough."""
    radius_km = CFG.arrival_radius_m["delivery"] / 1000

    if dist_km <= radius_km * CFG.exit_hysteresis:
        if t.delivery_inside_since is None:
            t.delivery_inside_since = now
        if (now - t.delivery_inside_since).total_seconds() >= CFG.delivery_confirm_seconds:
            await emit_status(t, ShipmentStatus.PENDING_DELIVERED, reading)
            ms.departed_at = now
            _complete(t, ms, now)      # last milestone -> t.finished = True
            return True
    else:
        # Truck left the hub before delivery was confirmed: go back to approaching
        t.delivery_inside_since = None
        ms.state = MilestoneState.APPROACHING
        _log(t, "Truck left delivery radius before confirmation - re-monitoring")
    return False


async def _evaluate_milestone(t, ms, dist_km, reading, moving, now) -> bool:
    """
    Applies the rules of the ACTIVE milestone.
    Returns True when the milestone finished and the next one is now active.
    """
    radius_km = CFG.arrival_radius_m[ms.type] / 1000
    ms.min_distance_km = min(ms.min_distance_km, dist_km)

    # --- PENDING/ACTIVE/APPROACHING: distance-driven transitions ---
    if ms.state in (MilestoneState.ACTIVE, MilestoneState.APPROACHING):
        if dist_km <= radius_km:
            ms.state = MilestoneState.ARRIVED
            ms.arrived_at = now
            _log(t, f"Arrived at {ms.type} milestone #{ms.sequence} ({dist_km * 1000:.0f} m)")
        elif dist_km <= CFG.approach_km:
            ms.state = MilestoneState.APPROACHING
        else:
            ms.state = MilestoneState.ACTIVE

        # Pass-through point passed without entering the radius -> don't get stuck
        # (applies to transit points, border/customs checkpoints, and
        # intermediate pickup_stop/delivery_stop points alike).
        if (
            ms.state != MilestoneState.ARRIVED
            and ms.type in PASS_THROUGH_MILESTONE_STATUS
            and ms.min_distance_km <= CFG.pass_by_max_min_km
            and dist_km - ms.min_distance_km >= CFG.pass_by_margin_km
        ):
            _log(t, f"{ms.type} milestone #{ms.sequence} passed by - marking SKIPPED")
            _complete(t, ms, now, skipped=True)
            return True

    # --- ARRIVED: type-specific business rule ---
    if ms.state == MilestoneState.ARRIVED:
        if ms.type in PASS_THROUGH_MILESTONE_STATUS:
            await emit_status(t, PASS_THROUGH_MILESTONE_STATUS[ms.type], reading)
            _complete(t, ms, now)
            return True

        if ms.type == "pickup":
            if t.shipment_status != ShipmentStatus.ARRIVED_AT_PICKUP_HUB:
                await emit_status(t, ShipmentStatus.ARRIVED_AT_PICKUP_HUB, reading)
            t.pickup_stationary_since = None
            t.movement_started_at = None
            t.last_moving_at = None
            t.waiting_for_pickup_sent = False
            ms.state = MilestoneState.VALIDATING

        elif ms.type == "delivery":
            if t.shipment_status != ShipmentStatus.ARRIVED_AT_DELIVERY_HUB:
                await emit_status(t, ShipmentStatus.ARRIVED_AT_DELIVERY_HUB, reading)
            t.delivery_inside_since = None
            ms.state = MilestoneState.VALIDATING

    # --- VALIDATING: pickup 5-minute movement / delivery dwell ---
    if ms.state == MilestoneState.VALIDATING:
        if ms.type == "pickup":
            return await _validate_pickup(t, ms, reading, moving, now)
        if ms.type == "delivery":
            return await _validate_delivery(t, ms, dist_km, reading, now)

    return False


# ============ Forward skip-scan: catch a jump over SEVERAL milestones ============

def _find_target_milestone_index(t: DistanceTrackingState, reading: GPSReading) -> Tuple[int, float]:
    """
    Normally only the current active milestone is checked each cycle. But a
    large gap between two GPS polls can mean the truck drove straight past
    one or more milestones without ever registering as "close" to them - for
    example the previous poll showed 550m, the next shows 1.03km, the one
    after that 2.5km. The single-milestone pass-by check in
    _evaluate_milestone requires having recorded a close approach first, so
    a milestone that was NEVER close (because it was skipped entirely
    between two polls) would otherwise sit ACTIVE forever.

    This scans a limited window ahead of the current milestone and returns
    the FURTHEST-ahead eligible milestone the truck is now within (or just
    outside) its own arrival zone of, so several milestones can be skipped
    in one jump when that's genuinely what happened.

    Pickup and delivery (the first/last, fully-validated milestones) are
    never skip targets and never skip sources - the scan stops as soon as it
    would have to cross one, so their validation is never bypassed.
    """
    start = t.current_milestone_index
    cur = t.milestones[start]

    if cur.type not in PASS_THROUGH_MILESTONE_STATUS:
        cur_dist = _distance_km(reading.latitude, reading.longitude, cur.latitude, cur.longitude)
        return start, cur_dist

    best_idx = start
    best_dist = _distance_km(reading.latitude, reading.longitude, cur.latitude, cur.longitude)

    end = min(start + CFG.skip_scan_lookahead, len(t.milestones) - 1)
    for i in range(start + 1, end + 1):
        ms = t.milestones[i]
        if ms.type not in PASS_THROUGH_MILESTONE_STATUS:
            break  # don't scan past the next pickup/delivery boundary
        if ms.state in (MilestoneState.COMPLETED, MilestoneState.SKIPPED):
            continue

        d = _distance_km(reading.latitude, reading.longitude, ms.latitude, ms.longitude)
        radius_km = CFG.arrival_radius_m[ms.type] / 1000
        if d <= radius_km * CFG.skip_scan_arrival_margin and d < best_dist:
            best_idx, best_dist = i, d

    return best_idx, best_dist


def _apply_milestone_jump_if_needed(t: DistanceTrackingState, reading: GPSReading, now: datetime) -> None:
    """Marks any milestones the forward scan found to be already-passed as SKIPPED."""
    target_idx, _ = _find_target_milestone_index(t, reading)
    if target_idx <= t.current_milestone_index:
        return

    skipped_over = t.milestones[t.current_milestone_index:target_idx]
    for m in skipped_over:
        m.state = MilestoneState.SKIPPED
        m.completed_at = now
        save_milestone(t.job_number, t.truck_number, {
            **m.to_dict(), "status": "skipped",
            "reason": "GPS jump - truck found closer to a later milestone than to this one",
        })

    _log(
        t,
        f"GPS jump detected: skipping {len(skipped_over)} milestone(s) "
        f"(#{skipped_over[0].sequence}-#{skipped_over[-1].sequence}), "
        f"jumping to milestone #{t.milestones[target_idx].sequence}",
    )
    t.current_milestone_index = target_idx
    if t.milestones[target_idx].state == MilestoneState.PENDING:
        t.milestones[target_idx].state = MilestoneState.ACTIVE


# ============ Route-deviation detection (human-initiated route change) ============

def _record_tracking_point(t: DistanceTrackingState, reading: GPSReading, dist_km: float, now: datetime) -> None:
    """
    Requirement #5: for every live-tracking update, keep enough history
    (job_number/truck_number are implicit in `t`; everything else recorded
    explicitly) to judge whether the truck is still heading toward the
    expected milestone or has deviated onto its own route.
    """
    t.tracking_history.append({
        "timestamp": now,
        "latitude": reading.latitude,
        "longitude": reading.longitude,
        "speed": reading.speed,
        "vehicle_status": reading.vehicle_status,
        "current_milestone_index": t.current_milestone_index,
        "expected_milestone_type": t.active.type,
        "distance_to_expected_km": dist_km,
    })
    if len(t.tracking_history) > CFG.deviation_window_points:
        t.tracking_history.pop(0)


def _in_deviation_eligible_stage(t: DistanceTrackingState) -> bool:
    """
    Requirement: deviation detection only applies between Picked Up and
    Arrived at Delivery Hub. It also only makes sense against a
    pass-through-type active milestone (transit/border/customs/
    pickup_stop/delivery_stop) - the first pickup and final delivery have
    their own dedicated stationary/dwell validation and aren't "routes" to
    deviate from in the same sense.
    """
    if t.shipment_status in _DEVIATION_INELIGIBLE_STATUSES:
        return False
    return t.active.type in PASS_THROUGH_MILESTONE_STATUS


def _detect_route_deviation(t: DistanceTrackingState) -> bool:
    """
    Looks at the recent tracking-point window and decides whether the truck
    has genuinely left the expected route toward the active milestone - as
    opposed to GPS noise, a temporary stop, slow traffic, a brief U-turn, or
    a single bad GPS jump.

    False-positive guards:
      - requires a minimum number of points (deviation_min_points) before
        judging anything at all;
      - only compares points that still target the SAME active milestone -
        a milestone change (including the skip-scan jump above) resets the
        baseline, so switching milestones is never mistaken for deviation;
      - drops points where the truck was moving below deviation_min_speed_kmh
        (stationary/slow traffic/jitter) - if too much of the window is like
        that, the window is inconclusive rather than being used anyway;
      - requires BOTH a minimum count of consecutive "got further away"
        steps AND a minimum net distance increase across the window, so a
        single noisy point or a brief U-turn that nets back out doesn't
        trigger it by itself.
    """
    if not _in_deviation_eligible_stage(t):
        return False

    hist = t.tracking_history
    if len(hist) < CFG.deviation_min_points:
        return False

    same_target = [p for p in hist if p["current_milestone_index"] == t.current_milestone_index]
    if len(same_target) < CFG.deviation_min_points:
        return False

    moving_points = [p for p in same_target if p["speed"] >= CFG.deviation_min_speed_kmh]
    if len(moving_points) < CFG.deviation_min_points:
        return False  # too much of the window was stationary/slow -> inconclusive

    increases = sum(
        1 for prev, curr in zip(same_target, same_target[1:])
        if curr["distance_to_expected_km"] > prev["distance_to_expected_km"]
    )
    net_change_km = same_target[-1]["distance_to_expected_km"] - same_target[0]["distance_to_expected_km"]

    return (
        increases >= CFG.deviation_consecutive_increases
        and net_change_km >= CFG.deviation_distance_increase_km
    )


async def _handle_route_deviation(t: DistanceTrackingState) -> None:
    """
    Recalculates the route from the truck's CURRENT position to the
    remaining real stops (any outstanding intermediate delivery points, then
    the final delivery), regenerates the milestones for that remaining
    stretch, marks every not-yet-completed milestone from the current one
    onward as obsolete (SKIPPED, via save_milestone), and preserves
    everything already COMPLETED/SKIPPED as history. New milestones are
    logged via save_milestone with status "updated".

    Route recalculation itself is isolated in build_multi_point_route() /
    calculate_driving_distance() (distance.py) so it can be swapped for a
    different routing provider or strategy later without touching this
    deviation-handling logic.
    """
    last_reading = t.last_reading
    if last_reading is None:
        return

    _log(t, "Route deviation detected - truck is moving away from the expected milestone. Recalculating from current position.")

    remaining_real_stops = [
        m for m in t.milestones[t.current_milestone_index:]
        if m.type in ("pickup", "pickup_stop", "delivery", "delivery_stop")
    ]
    if not remaining_real_stops:
        remaining_real_stops = [t.milestones[-1]]

    delivery_stop_coords: Set[Tuple[float, float]] = {
        (round(m.latitude, 6), round(m.longitude, 6))
        for m in remaining_real_stops if m.type == "delivery_stop"
    }

    # Mark every not-yet-completed milestone from the current one onward as
    # obsolete. History (already COMPLETED/SKIPPED) is left untouched.
    for m in t.milestones[t.current_milestone_index:]:
        if m.state not in (MilestoneState.COMPLETED, MilestoneState.SKIPPED):
            m.state = MilestoneState.SKIPPED
            m.completed_at = _now()
            save_milestone(t.job_number, t.truck_number, {
                **m.to_dict(), "status": "skipped",
                "reason": "obsoleted by route deviation",
            })

    recalc_points = [(last_reading.latitude, last_reading.longitude)] + [
        (m.latitude, m.longitude) for m in remaining_real_stops
    ]

    try:
        route = await asyncio.to_thread(
            build_multi_point_route, recalc_points, CFG.default_milestone_spacing_km,
        )
    except Exception as exc:
        _log(t, f"Route deviation detected but recalculation failed ({exc}) - tracking continues toward the last known milestone.")
        return

    if not route or not route.get("success"):
        _log(t, "Route deviation detected but recalculation failed - tracking continues toward the last known milestone.")
        return

    items = _tail_route_items(route["milestone_points"], delivery_stop_coords)
    if route.get("route_polylines"):
        try:
            items = insert_border_checkpoints(items, route["route_polylines"])
        except ValueError:
            pass  # nothing to insert / no polyline - keep the plain items

    items = items[1:]  # drop the synthetic "current position" anchor
    if not items:
        _log(t, "Route deviation recalculation produced no remaining milestones - keeping existing plan.")
        return

    for item in items:
        item.setdefault("status", "PENDING")
        item.setdefault("arrived_at", None)
        item.setdefault("departed_at", None)
        item.setdefault("completed_at", None)

    new_milestones = build_milestones(items)

    base_seq = t.milestones[t.current_milestone_index - 1].sequence if t.current_milestone_index > 0 else 0
    kept = t.milestones[:t.current_milestone_index]
    for i, m in enumerate(new_milestones):
        m.sequence = base_seq + i + 1
        save_milestone(t.job_number, t.truck_number, {
            **m.to_dict(), "status": "updated",
            "reason": "generated after route deviation",
        })

    t.milestones = kept + new_milestones
    t.current_milestone_index = len(kept)
    t.milestones[t.current_milestone_index].state = MilestoneState.ACTIVE
    t.tracking_history.clear()
    t.deviation_count += 1
    t.last_deviation_at = _now()

    _log(t, f"New route applied: {len(new_milestones)} milestone(s) remaining from current position to final delivery.")


# ============ One GPS cycle ============

async def process_gps_update(t: DistanceTrackingState) -> int:
    """Runs one full cycle and returns the number of seconds until the next GPS check."""

    # Shipment stays BOOKED (silently) until the truck actually reaches the
    # pickup hub - no status is sent just for the job starting. The first
    # message in the pickup sequence is "Arrived at Pickup Hub", fired by
    # _evaluate_milestone() once the truck enters the pickup radius.
    reading = await gps_session.get_truck_reading(t.truck_number)
    now = _now()
    t.last_gps_check = now

    if reading is None:
        _log(t, "No GPS data - retrying shortly")
        return CFG.error_retry_interval

    # Same fix as last time = device did not report anew; don't evaluate old data
    # on top of itself (milestones/distance stay exactly as they were), but
    # DO log it - otherwise a device that goes quiet for a while leaves no
    # trace at all in the console, and current_distance_km/milestone state
    # just sits frozen with no explanation of why.
    if (
        t.last_reading is not None
        and reading.timestamp
        and reading.timestamp == t.last_reading.timestamp
    ):
        t.stale_readings += 1
        _log(
            t,
            f"GPS fix unchanged since last poll (device last reported at "
            f"{reading.timestamp}, stale_readings={t.stale_readings}) - "
            f"distance to milestone #{t.active.sequence}({t.active.type}) still "
            f"{t.current_distance_km if t.current_distance_km is not None else '?'} km, "
            f"retrying in {t.last_interval}s.",
        )
        return t.last_interval

    moving = is_moving(t.last_reading, reading)
    t.last_reading = reading
    t.stale_readings = 0

    _log(
        t,
        f"GPS fix: lat={reading.latitude:.6f} lon={reading.longitude:.6f} "
        f"speed={reading.speed:.1f}km/h status={reading.vehicle_status} "
        f"expected_milestone=#{t.active.sequence}({t.active.type})",
    )

    # --- Catch a GPS jump that skipped one or more milestones at once ---
    _apply_milestone_jump_if_needed(t, reading, now)

    # --- Record this point and check for a human-initiated route deviation ---
    ms = t.active
    dist_km = _distance_km(reading.latitude, reading.longitude, ms.latitude, ms.longitude)
    t.current_distance_km = dist_km
    _record_tracking_point(t, reading, dist_km, now)

    if _detect_route_deviation(t):
        await _handle_route_deviation(t)

    # Evaluate the ACTIVE milestone; if it completes, the next one is evaluated
    # straight away (covers milestones that lie within one GPS fix of each other).
    for _ in range(len(t.milestones)):
        ms = t.active
        dist_km = _distance_km(reading.latitude, reading.longitude, ms.latitude, ms.longitude)
        t.current_distance_km = dist_km

        advanced = await _evaluate_milestone(t, ms, dist_km, reading, moving, now)
        if t.finished:
            return 0
        if not advanced:
            break

    ms = t.active
    dist_km = t.current_distance_km

    # Choose the next polling interval
    if ms.state == MilestoneState.VALIDATING:
        t.poll_tier = "VALIDATION"
        if ms.type == "pickup" and t.movement_started_at is not None:
            interval = CFG.validation_moving_interval
        else:
            interval = CFG.validation_stationary_interval
    else:
        t.poll_tier, interval = select_gps_interval(dist_km)

    _log(
        t,
        f"milestone #{ms.sequence}/{len(t.milestones)} [{ms.type}:{ms.state.value}] "
        f"distance={dist_km:.2f} km -> next check in {interval}s ({t.poll_tier})",
    )
    return interval


# ============ Background task ============

async def run_distance_tracking(t: DistanceTrackingState):
    """
    Background task: waits until `next_gps_check`, runs a GPS cycle, then
    schedules the next check from the truck's distance to the active milestone.
    Ends on delivery, or when paused / stopped / cancelled.
    """
    key = _tracker_key(t.truck_number, t.job_number)
    try:
        while not t.finished:
            delay = (t.next_gps_check - _now()).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)

            try:
                interval = await process_gps_update(t)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Transient failure (API, DB...) must not kill tracking; the milestone
                # state is only advanced after a status was emitted, so a retry is safe.
                _log(t, f"GPS cycle failed: {exc}")
                interval = CFG.error_retry_interval

            if t.finished:
                break

            t.last_interval = interval
            t.next_gps_check = _now() + timedelta(seconds=interval)

        _log(t, "Distance tracking finished (delivered).")

    except asyncio.CancelledError:
        _log(t, f"Distance tracking cancelled (paused={t.paused}).")
        raise

    finally:
        # A paused record must survive so it can be resumed later. Only ever
        # touch THIS job's own entry - never another job on the same truck.
        async with distance_trackers_lock:
            current = distance_trackers.get(key)
            if current is t and not t.paused:
                distance_trackers.pop(key, None)


# ============ Public API ============

class RouteMilestoneRequest(BaseModel):
    """Computes the milestone list for a SINGLE pickup / SINGLE delivery route, with border checkpoints inserted."""
    pickup_latitude: float
    pickup_longitude: float
    delivery_latitude: float
    delivery_longitude: float

    # Optional: restrict/override the checkpoint registry and match radius for this call.
    checkpoint_names: Optional[List[str]] = None   # subset of CHECKPOINTS to consider
    checkpoint_match_radius_km: Optional[float] = None
    milestone_spacing_km: Optional[float] = None


async def build_route_milestones(payload: RouteMilestoneRequest) -> dict:
    """
    Endpoint body for POST /milestones/build (see routing example below).

    Calculates the driving route between pickup and delivery, then works out
    which registered border checkpoints that route actually crosses and in
    which direction, and returns the full milestone list - pickup, transit
    points, "At Border" / "Customs Clearance" pairs for every crossing found,
    and delivery - in the correct travel order.

    For multiple pickup/delivery points, use /distance-tracking/start with
    pickup_points / delivery_points instead - this endpoint remains the
    single-pickup/single-delivery preview helper.
    """
    route = await asyncio.to_thread(
        calculate_driving_distance,
        payload.pickup_latitude, payload.pickup_longitude,
        payload.delivery_latitude, payload.delivery_longitude,
        payload.milestone_spacing_km or CFG.default_milestone_spacing_km,
    )
    if not route or not route.get("success"):
        raise HTTPException(status_code=502, detail="Could not calculate the route.")

    polyline = route.get("route_polylines")
    if not polyline:
        raise HTTPException(status_code=502, detail="Route has no polyline to match checkpoints against.")

    checkpoints = CHECKPOINTS
    if payload.checkpoint_names is not None:
        unknown = set(payload.checkpoint_names) - set(CHECKPOINTS)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown checkpoint(s): {sorted(unknown)}")
        checkpoints = {k: v for k, v in CHECKPOINTS.items() if k in payload.checkpoint_names}

    try:
        milestones = build_milestones_with_checkpoints(
            route["milestone_points"], polyline, checkpoints, payload.checkpoint_match_radius_km,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "distance_km": route.get("distance_km"),
        "duration_text": route.get("duration_text"),
        "milestone_points": milestones,
    }


class LatLon(BaseModel):
    latitude: float
    longitude: float


class DistanceTrackingRequest(BaseModel):
    job_number: str
    truck_number: str
    driver_name: str
    route_from: str
    route_to: str
    reply_number: str = ""
    whatsapp: bool = False

    # Single pickup/delivery (back-compat). Needed only when neither
    # milestone_points NOR pickup_points/delivery_points are supplied.
    pickup_latitude: Optional[float] = None
    pickup_longitude: Optional[float] = None
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None

    # Multiple pickup / delivery points, in visiting order. When given,
    # these take priority over the singular pickup_*/delivery_* fields
    # above. Covers all four shipment shapes:
    #   len(pickup_points)==1, len(delivery_points)==1 -> single/single
    #   len(pickup_points)>1,  len(delivery_points)==1 -> multi-pickup
    #   len(pickup_points)==1, len(delivery_points)>1  -> multi-delivery
    #   len(pickup_points)>1,  len(delivery_points)>1  -> multi/multi
    pickup_points: Optional[List[LatLon]] = None
    delivery_points: Optional[List[LatLon]] = None

    # Spacing (km) passed through to the milestone-count calculation on long
    # routes. Defaults to CFG.default_milestone_spacing_km when omitted.
    milestone_spacing_km: Optional[float] = None

    # When the route is calculated for you (no milestone_points given), border
    # checkpoints such as customs clearance are inserted automatically. Set to
    # False to get plain pickup/transit/delivery milestones instead.
    include_border_checkpoints: bool = True

    # Optional: supply milestones yourself instead of routing. Either
    #   - [lat, lon, label] tuples, or
    #   - milestone objects ({"sequence", "latitude", "longitude", "type", "status", ...});
    #     milestones with status COMPLETED/SKIPPED are treated as done and tracking
    #     resumes from the first unfinished milestone.
    milestone_points: Optional[List[Any]] = Field(default=None)


async def start_distance_tracking(payload: DistanceTrackingRequest) -> dict:
    """
    Call this right after the shipment is manually created as
    "Booked / Shipment Created". Everything after that is automatic:
    Awaiting Pickup -> Picked Up -> In Transit -> (At Border -> Customs
    Clearance, per crossing) -> ... -> Arrived -> Delivered.

    Identifies the shipment by (truck_number, job_number). Starting a job
    for a truck that already has a DIFFERENT job running does NOT cancel
    that other job - both are tracked independently. Calling this again
    with the SAME (truck_number, job_number) restarts that one job only.
    """
    points = payload.milestone_points

    if not points:
        pickup_list = (
            [(p.latitude, p.longitude) for p in payload.pickup_points]
            if payload.pickup_points else
            ([(payload.pickup_latitude, payload.pickup_longitude)]
             if payload.pickup_latitude is not None and payload.pickup_longitude is not None else [])
        )
        delivery_list = (
            [(p.latitude, p.longitude) for p in payload.delivery_points]
            if payload.delivery_points else
            ([(payload.delivery_latitude, payload.delivery_longitude)]
             if payload.delivery_latitude is not None and payload.delivery_longitude is not None else [])
        )

        if not pickup_list or not delivery_list:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Provide milestone_points, or pickup_points/delivery_points, "
                    "or pickup_latitude/longitude and delivery_latitude/longitude."
                ),
            )

        spacing_km = payload.milestone_spacing_km or CFG.default_milestone_spacing_km
        all_points = pickup_list + delivery_list

        route = await asyncio.to_thread(build_multi_point_route, all_points, spacing_km)
        if not route or not route.get("success"):
            raise HTTPException(
                status_code=502,
                detail=route.get("message", "Could not calculate the route/milestones.") if route else "Could not calculate the route/milestones.",
            )

        points = build_milestones_for_route(
            route["milestone_points"],
            pickup_count=len(pickup_list),
            delivery_count=len(delivery_list),
            route_polyline=route.get("route_polylines"),
            include_border_checkpoints=payload.include_border_checkpoints,
        )

    try:
        milestones = build_milestones(points)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    tracker = DistanceTrackingState(
        truck_number=payload.truck_number,
        job_number=payload.job_number,
        driver_name=payload.driver_name,
        route_from=payload.route_from,
        route_to=payload.route_to,
        reply_number=payload.reply_number,
        whatsapp=payload.whatsapp,
        milestones=milestones,
    )

    for m in milestones:
        save_milestone(payload.job_number, payload.truck_number, {
            **m.to_dict(), "status": m.state.value.lower() if m.state in (MilestoneState.COMPLETED, MilestoneState.SKIPPED) else "pending",
        })

    key = _tracker_key(payload.truck_number, payload.job_number)

    async with distance_trackers_lock:
        existing = distance_trackers.get(key)
        if existing and existing.task:
            # Only the SAME (truck, job) pair is replaced. A different job
            # already running on this truck is left completely untouched.
            existing.paused = True          # so its cleanup doesn't pop the new record
            existing.task.cancel()
        distance_trackers[key] = tracker

    # Shipment stays BOOKED (silently) until the truck is actually within
    # the pickup radius - the pickup sequence is Arrived at Pickup Hub ->
    # Waiting for Pickup -> Picked Up / In Transit, and none of those fire
    # just because the job was started.
    tracker.task = asyncio.create_task(run_distance_tracking(tracker))
    _log(tracker, f"Tracking started ({len(milestones)} milestone(s)).")
    return tracker.to_dict()


async def handle_distance_workflow_transition(truck_number: str, job_number: str, status: ShipmentStatus):
    """
    Manual status change for a (truck, job) pair that is being
    distance-tracked - e.g. an operator marking it Delayed, Customs Hold,
    Vehicle Breakdown, or Weather/Road Delay.

    Unlike handle_workflow_transition() in auto_update.py - which only does
    bookkeeping, because its caller (the /status/update router) always
    calls send_status_message() separately first - THIS function also sends
    the status message itself. The distance-tracking router's manual
    /status endpoint has no separate call for that, so calling this IS the
    whole point: it both emits the message (DB save + WhatsApp) AND applies
    the matching bookkeeping:

      - exception status (Delayed / Customs Hold / Breakdown / Weather) -> pause
      - Delivered / Cancelled-Returned                                  -> stop for good
      - any other manual status while paused (issue resolved)           -> resume
      - any other manual status while NOT paused                        -> message sent, no bookkeeping change
    """
    key = _tracker_key(truck_number, job_number)
    async with distance_trackers_lock:
        existing = distance_trackers.get(key)
    if not existing:
        return

    # Always send the message for the status that was actually requested -
    # this is a manual override, so nothing else in the pipeline will emit
    # it. (emit_status also updates existing.shipment_status.)
    await emit_status(existing, status, None)

    async with distance_trackers_lock:
        if status in EXCEPTION_STATUSES:
            existing.paused = True
            if existing.task:
                existing.task.cancel()
                existing.task = None

        elif status in TERMINAL_STATUSES_DISTANCE:
            existing.paused = False
            existing.finished = True
            if existing.task:
                existing.task.cancel()
            distance_trackers.pop(key, None)

        elif existing.paused:
            existing.paused = False
            existing.next_gps_check = _now()
            existing.task = asyncio.create_task(run_distance_tracking(existing))


async def stop_distance_tracking(truck_number: str, job_number: str):
    key = _tracker_key(truck_number, job_number)
    async with distance_trackers_lock:
        existing = distance_trackers.pop(key, None)
        if existing:
            existing.paused = False
            existing.finished = True
            if existing.task:
                existing.task.cancel()


class ManualAdvanceRequest(BaseModel):
    # Optional: resume automatic GPS-based tracking from the new active
    # milestone right after this call. Defaults to staying in manual mode so
    # repeated /advance calls keep walking the shipment forward on demand.
    resume_gps_tracking: bool = False


async def advance_milestone_manually(truck_number: str, job_number: str, payload: ManualAdvanceRequest = None) -> dict:
    """
    Manually completes the CURRENT active milestone (for this truck+job) and
    sends its status message (DB save + WhatsApp), without waiting for GPS.
    Each call moves the shipment forward by exactly one step:

        Booked -> [call] -> Arrived at Pickup Hub
        Arrived at Pickup Hub -> [call] -> Waiting for Pickup
        Waiting for Pickup -> [call] -> Picked Up + In Transit
        (pickup_stop / transit / border / customs / delivery_stop milestone)
            -> [call] -> that milestone's status, next becomes active
        Arrived-at-delivery step -> [call] -> Arrived at Delivery Hub
        Arrived at Delivery Hub -> [call] -> Delivered (shipment finishes)

    Pickup is three calls (arrived, waiting, then completion) and delivery
    is two (arrival, then completion), because those are the distinct
    business events in the spec; every other milestone is one call.
    Pauses/stops GPS polling for this truck+job unless resume_gps_tracking=True.
    """
    payload = payload or ManualAdvanceRequest()
    key = _tracker_key(truck_number, job_number)

    async with distance_trackers_lock:
        t = distance_trackers.get(key)
    if not t:
        raise HTTPException(
            status_code=404,
            detail="No active tracker for this truck+job. Call /distance-tracking/start first.",
        )
    if t.finished:
        raise HTTPException(status_code=400, detail="This shipment is already finished.")

    if t.task:
        t.task.cancel()
        t.task = None
    t.paused = True

    now = _now()
    ms = t.active

    if ms.type == "pickup":
        if t.shipment_status not in (ShipmentStatus.ARRIVED_AT_PICKUP_HUB, ShipmentStatus.WAITING_FOR_PICKUP):
            ms.arrived_at = ms.arrived_at or now
            await emit_status(t, ShipmentStatus.ARRIVED_AT_PICKUP_HUB, None)
        elif t.shipment_status == ShipmentStatus.ARRIVED_AT_PICKUP_HUB:
            await emit_status(t, ShipmentStatus.WAITING_FOR_PICKUP, None)
        else:  # WAITING_FOR_PICKUP
            if not t.picked_up_sent:
                await emit_status(t, ShipmentStatus.PICKED_UP, None)
                t.picked_up_sent = True
            await emit_status(t, ShipmentStatus.IN_TRANSIT, None)
            ms.departed_at = now
            _complete(t, ms, now)

    elif ms.type == "delivery":
        if t.shipment_status != ShipmentStatus.ARRIVED_AT_DELIVERY_HUB:
            ms.arrived_at = ms.arrived_at or now
            await emit_status(t, ShipmentStatus.ARRIVED_AT_DELIVERY_HUB, None)
        else:
            await emit_status(t, ShipmentStatus.PENDING_DELIVERED, None)
            ms.departed_at = now
            _complete(t, ms, now)  # last milestone -> t.finished = True

    else:  # pickup_stop / transit / border / customs / delivery_stop - one call, one status, move on
        status = PASS_THROUGH_MILESTONE_STATUS[ms.type]
        ms.arrived_at = ms.arrived_at or now
        await emit_status(t, status, None)
        ms.departed_at = now
        _complete(t, ms, now)

    if payload.resume_gps_tracking and not t.finished:
        t.paused = False
        t.next_gps_check = _now()
        t.task = asyncio.create_task(run_distance_tracking(t))
    elif t.finished:
        async with distance_trackers_lock:
            distance_trackers.pop(key, None)

    return t.to_dict()


def _log_full_state(t: DistanceTrackingState) -> None:
    """
    Logs the same kind of line process_gps_update() prints during a live
    GPS cycle, but for EVERY milestone, not just the active one - so a
    status lookup (GET /distance-tracking/...) leaves a full trail in the
    server log on demand, instead of only ever showing up when the next
    automatic poll happens to fire.
    """
    if t.last_reading is not None:
        _log(
            t,
            f"GPS fix (last known): lat={t.last_reading.latitude:.6f} lon={t.last_reading.longitude:.6f} "
            f"speed={t.last_reading.speed:.1f}km/h status={t.last_reading.vehicle_status} "
            f"expected_milestone=#{t.active.sequence}({t.active.type})",
        )
    else:
        _log(t, "No GPS fix received yet.")

    for m in t.milestones:
        is_active = (m.sequence - 1) == t.current_milestone_index
        if is_active and t.current_distance_km is not None:
            note = f"distance={t.current_distance_km:.2f} km"
        elif m.state in (MilestoneState.COMPLETED, MilestoneState.SKIPPED) and m.min_distance_km != float("inf"):
            note = f"min_distance_seen={m.min_distance_km:.2f} km"
        else:
            note = "-"
        _log(
            t,
            f"milestone #{m.sequence}/{len(t.milestones)} [{m.type}:{m.state.value}] "
            f"lat={m.latitude:.6f} lon={m.longitude:.6f} {note}",
        )

    if t.paused:
        _log(t, "Tracking is PAUSED (no automatic polling until resumed).")
    elif t.poll_tier:
        remaining = max(int((t.next_gps_check - _now()).total_seconds()), 0)
        _log(t, f"Tracking RUNNING - next check in {remaining}s ({t.poll_tier}).")
    else:
        _log(t, "Tracking RUNNING - first GPS poll not completed yet.")


def get_distance_tracking_state(truck_number: str, job_number: Optional[str] = None):
    """
    With job_number: snapshot of that one job's tracking state (shape
    follows the requirement's tracking_state). Also logs a full-state
    summary (every milestone, not just the active one) to the console,
    exactly like an automatic GPS cycle would - so simply polling this
    endpoint gives you the same visibility as watching the live tracker run.

    Without job_number: a {job_number: state} map of EVERY job currently
    tracked for this truck, since a truck can now have more than one. This
    is the convenient "what is this truck doing right now" view; pass
    job_number explicitly whenever you already know which job you want.
    Every job found this way is logged the same way.
    """
    if job_number is not None:
        tracker = distance_trackers.get(_tracker_key(truck_number, job_number))
        if tracker:
            _log_full_state(tracker)
        return tracker.to_dict() if tracker else None

    for key, t in distance_trackers.items():
        if key.startswith(f"{truck_number}::"):
            _log_full_state(t)

    return {
        t.job_number: t.to_dict()
        for key, t in distance_trackers.items()
        if key.startswith(f"{truck_number}::")
    }


async def shutdown_distance_tracking():
    """Cancel every running tracker, for every truck and every job (call from the app's shutdown hook)."""
    async with distance_trackers_lock:
        for tracker in list(distance_trackers.values()):
            tracker.paused = False
            if tracker.task:
                tracker.task.cancel()
        distance_trackers.clear()