# ========== Importing Libraries ==========
import asyncio
import inspect
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

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
from app.tracker.distance import calculate_driving_distance, calculate_distance




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
    ShipmentStatus.ARRIVED_AT_DELIVERY_HUB.value: create_arrived_delivery_hub_status,
    ShipmentStatus.OUT_FOR_DELIVERY.value: create_out_for_delivery_status,
    ShipmentStatus.DELIVERY_ATTEMPTED.value: create_delivery_attempted_status,
    ShipmentStatus.DELIVERY_EXCEPTION.value: create_delivery_exception_status,
    ShipmentStatus.DELIVERED.value: create_delivered_status,
    ShipmentStatus.CANCELLED_RETURNED.value: create_cancelled_returned_status,
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
# Only ONE milestone (the active one) is ever evaluated, so milestones can
# never be skipped by accident. The polling interval shrinks as the truck
# approaches the active milestone, so far-away trucks cost almost no GPS calls.


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
    very_near_km: float = 0.5

    # Never sleep longer than half the time the truck needs to cover the
    # remaining distance at `max_speed_kmh`. Stops a long configured interval
    # (e.g. NORMAL) from letting a fast truck jump straight past a milestone.
    adaptive_cap_enabled: bool = True
    max_speed_kmh: float = 100.0
    adaptive_cap_fraction: float = 0.5

    # ---- Arrival radius per milestone type (metres) ----
    arrival_radius_m: Dict[str, float] = field(default_factory=lambda: {
        "pickup": 500.0,
        "transit": 500.0,
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
    pickup_min_dwell_seconds: int = 60        # must be seen stationary first
    pickup_move_confirm_seconds: int = 5 * 60  # continuous movement required
    pickup_move_grace_seconds: int = 60       # short stop (gate/traffic) tolerated

    # ---- Delivery confirmation ----
    # Truck must stay inside the delivery radius this long after arriving.
    delivery_confirm_seconds: int = 10 * 60

    # ---- Polling while validating pickup / delivery ----
    validation_moving_interval: int = 30
    validation_stationary_interval: int = 120

    # ---- Transit "pass-by" detection (avoids getting stuck on a missed point) ----
    pass_by_max_min_km: float = 3.0   # truck did come this close...
    pass_by_margin_km: float = 2.0    # ...and is now this much further away

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


# Shipment status associated with each milestone type
MILESTONE_EVENT_LABEL = {
    "pickup": ShipmentStatus.AWAITING_PICKUP.value,
    "transit": ShipmentStatus.IN_TRANSIT.value,
    "delivery": ShipmentStatus.ARRIVED_AT_DELIVERY_HUB.value,
    "border": ShipmentStatus.AT_BORDER.value,
    "customs": ShipmentStatus.CUSTOMS_CLEARANCE.value,
}

# Milestone types that need nothing beyond "arrived -> emit status -> complete"
# (unlike pickup/delivery, which need dwell/movement validation).
PASS_THROUGH_MILESTONE_STATUS = {
    "transit": ShipmentStatus.IN_TRANSIT,
    "border": ShipmentStatus.AT_BORDER,
    "customs": ShipmentStatus.CUSTOMS_CLEARANCE,
}

# Manual statuses that end the distance tracking for good
TERMINAL_STATUSES_DISTANCE = {
    ShipmentStatus.DELIVERED,
    ShipmentStatus.CANCELLED_RETURNED,
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
}


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


def build_milestones_with_checkpoints(
    milestone_points: List[tuple],
    route_polyline: List[tuple],
    checkpoints: Dict[str, List[Tuple[float, float]]] = None,
    radius_km: float = None,
) -> List[dict]:
    """
    Takes the plain route milestones (pickup / transit / delivery) plus the
    route's polyline, finds every border checkpoint this route actually
    crosses, and inserts "At Border" + "Customs Clearance" milestones at the
    correct position and with the correct lat/lon for the direction of
    travel. Pickup stays first and delivery stays last regardless.

    Returns a list of milestone dicts, sequenced, ready to pass straight into
    build_milestones() / DistanceTrackingRequest.milestone_points.
    """
    if not route_polyline:
        raise ValueError("route_polyline is required to place border checkpoints.")

    labelled = label_milestone_points(milestone_points)
    last = len(labelled) - 1

    route_items = []
    for i, (lat, lon, label) in enumerate(labelled):
        m_type = "pickup" if i == 0 else "delivery" if i == last else "transit"
        idx, _ = nearest_polyline_index(route_polyline, lat, lon)
        route_items.append({
            "latitude": lat, "longitude": lon, "type": m_type,
            "shipment_status": label, "route_index": idx,
        })

    pickup, delivery = route_items[0], route_items[-1]
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
    ordered = [pickup] + middle + [delivery]

    for i, item in enumerate(ordered):
        item["sequence"] = i + 1
        item.pop("route_index", None)
        item.setdefault("status", "PENDING")
        item.setdefault("arrived_at", None)
        item.setdefault("departed_at", None)
        item.setdefault("completed_at", None)
    return ordered


@dataclass
class Milestone:
    sequence: int
    latitude: float
    longitude: float
    type: str                      # "pickup" | "transit" | "delivery"
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
    One shared GPS session for every tracked truck.

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

        # pickup validation
        self.pickup_stationary_since: Optional[datetime] = None
        self.movement_started_at: Optional[datetime] = None
        self.last_moving_at: Optional[datetime] = None
        self.picked_up_sent = start > 0

        # delivery validation
        self.delivery_inside_since: Optional[datetime] = None

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
            "paused": self.paused,
            "milestones": [m.to_dict() for m in self.milestones],
        }


# One entry per truck/shipment with an active or paused distance workflow
distance_trackers: Dict[str, DistanceTrackingState] = {}

# Protects the shared `distance_trackers` dictionary
distance_trackers_lock = asyncio.Lock()


def _log(t: DistanceTrackingState, message: str):
    print(f"[{t.truck_number}] {message}")


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
    if ms.departed_at is None and ms.type == "transit":
        ms.departed_at = now
    t.activate_next()


async def _validate_pickup(t, ms, reading, moving, now) -> bool:
    """
    Pickup is confirmed only when:
      1. the truck was seen stationary at pickup (for a minimum dwell), and
      2. it then moves continuously for 5 minutes.
    A short stop (gate / traffic light) inside that window is tolerated.
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
        return False

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

    # Confirmed: Awaiting Pickup -> Picked Up -> In Transit
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
            await emit_status(t, ShipmentStatus.DELIVERED, reading)
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
        # (applies to transit points and to border/customs checkpoints alike).
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
            t.pickup_stationary_since = None
            t.movement_started_at = None
            t.last_moving_at = None
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


# ============ One GPS cycle ============

async def process_gps_update(t: DistanceTrackingState) -> int:
    """Runs one full cycle and returns the number of seconds until the next GPS check."""

    # Shipment was created manually as BOOKED -> now enters pickup monitoring
    if t.shipment_status == ShipmentStatus.BOOKED:
        await emit_status(t, ShipmentStatus.AWAITING_PICKUP, None)

    reading = await gps_session.get_truck_reading(t.truck_number)
    now = _now()
    t.last_gps_check = now

    if reading is None:
        _log(t, "No GPS data - retrying shortly")
        return CFG.error_retry_interval

    # Same fix as last time = device did not report anew; don't evaluate old data
    if (
        t.last_reading is not None
        and reading.timestamp
        and reading.timestamp == t.last_reading.timestamp
    ):
        t.stale_readings += 1
        return t.last_interval

    moving = is_moving(t.last_reading, reading)
    t.last_reading = reading
    t.stale_readings = 0

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
        # A paused record must survive so it can be resumed later.
        async with distance_trackers_lock:
            current = distance_trackers.get(t.truck_number)
            if current is t and not t.paused:
                distance_trackers.pop(t.truck_number, None)


# ============ Public API ============

class RouteMilestoneRequest(BaseModel):
    """Computes the milestone list for a route, with border checkpoints inserted."""
    pickup_latitude: float
    pickup_longitude: float
    delivery_latitude: float
    delivery_longitude: float

    # Optional: restrict/override the checkpoint registry and match radius for this call.
    checkpoint_names: Optional[List[str]] = None   # subset of CHECKPOINTS to consider
    checkpoint_match_radius_km: Optional[float] = None


async def build_route_milestones(payload: RouteMilestoneRequest) -> dict:
    """
    Endpoint body for POST /milestones/build (see routing example below).

    Calculates the driving route between pickup and delivery, then works out
    which registered border checkpoints that route actually crosses and in
    which direction, and returns the full milestone list - pickup, transit
    points, "At Border" / "Customs Clearance" pairs for every crossing found,
    and delivery - in the correct travel order.
    """
    route = await asyncio.to_thread(
        calculate_driving_distance,
        payload.pickup_latitude, payload.pickup_longitude,
        payload.delivery_latitude, payload.delivery_longitude,
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


class DistanceTrackingRequest(BaseModel):
    job_number: str
    truck_number: str
    driver_name: str
    route_from: str
    route_to: str
    reply_number: str = ""
    whatsapp: bool = False

    # Needed only when milestone_points is NOT supplied (route is calculated for you)
    pickup_latitude: Optional[float] = None
    pickup_longitude: Optional[float] = None
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None

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
    """
    points = payload.milestone_points
    if not points:
        coords = (payload.pickup_latitude, payload.pickup_longitude,
                  payload.delivery_latitude, payload.delivery_longitude)
        if any(c is None for c in coords):
            raise HTTPException(
                status_code=400,
                detail="Provide milestone_points, or all pickup/delivery latitude & longitude.",
            )
        route = await asyncio.to_thread(
            calculate_driving_distance,
            payload.pickup_latitude,
            payload.pickup_longitude,
            payload.delivery_latitude,
            payload.delivery_longitude,
        )
        if not route or not route.get("success"):
            raise HTTPException(status_code=502, detail="Could not calculate the route/milestones.")

        if payload.include_border_checkpoints and route.get("route_polylines"):
            points = build_milestones_with_checkpoints(
                route["milestone_points"], route["route_polylines"],
            )
        else:
            points = route["milestone_points"]

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

    async with distance_trackers_lock:
        existing = distance_trackers.get(payload.truck_number)
        if existing and existing.task:
            existing.paused = True          # so its cleanup doesn't pop the new record
            existing.task.cancel()
        distance_trackers[payload.truck_number] = tracker
        tracker.task = asyncio.create_task(run_distance_tracking(tracker))

    return tracker.to_dict()


async def handle_distance_workflow_transition(truck_number: str, status: ShipmentStatus):
    """
    Same idea as handle_workflow_transition() in auto_update.py, for manual
    status changes made while a truck is being distance-tracked:

      - exception status (Delayed / Customs Hold / Breakdown / Weather) -> pause
      - Delivered / Cancelled-Returned                                  -> stop for good
      - any other manual status while paused (issue resolved)           -> resume
    """
    async with distance_trackers_lock:
        existing = distance_trackers.get(truck_number)
        if not existing:
            return

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
            distance_trackers.pop(truck_number, None)

        elif existing.paused:
            existing.paused = False
            existing.shipment_status = status
            existing.next_gps_check = _now()
            existing.task = asyncio.create_task(run_distance_tracking(existing))


async def stop_distance_tracking(truck_number: str):
    async with distance_trackers_lock:
        existing = distance_trackers.pop(truck_number, None)
        if existing:
            existing.paused = False
            existing.finished = True
            if existing.task:
                existing.task.cancel()


def get_distance_tracking_state(truck_number: str) -> Optional[dict]:
    """Snapshot of the tracking state (shape follows the requirement's tracking_state)."""
    tracker = distance_trackers.get(truck_number)
    return tracker.to_dict() if tracker else None


async def shutdown_distance_tracking():
    """Cancel every running tracker (call from the app's shutdown hook)."""
    async with distance_trackers_lock:
        for tracker in list(distance_trackers.values()):
            tracker.paused = False
            if tracker.task:
                tracker.task.cancel()
        distance_trackers.clear()