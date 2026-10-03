import requests
import math
from app.core.config import settings

GOOGLE_MAPS_API_KEY = settings.gmap_key




def calculate_distance(from_lat, from_lon, to_lat, to_lon):
    """
    Calculate the straight-line distance between two
    latitude/longitude coordinates.

    Returns:
        Distance in kilometers
    """

    R = 6371.0  # Earth's radius in kilometers

    # Convert degrees to radians
    lat1 = math.radians(from_lat)
    lat2 = math.radians(to_lat)

    delta_lat = math.radians(to_lat - from_lat)
    delta_lon = math.radians(to_lon - from_lon)

    # Haversine formula
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c

    return distance



def get_milestone(from_lat,
                from_lng,
                to_lat,
                to_lng,
                points,
                n_points = 7):
    """
    Picks `n_points` evenly-spaced points out of the full decoded polyline
    (always including the exact pickup and delivery coordinates as the
    first/last point), and builds a Google Maps preview URL for them.

    NOTE (bug fix): this used to divide by a hardcoded 6, which only gave
    evenly-spaced points when n_points was exactly 7. It now divides by
    (n_points - 1), so any n_points value - including the configurable
    values calculate_n_points() can now return - spaces the picks evenly
    across the polyline.
    """
    n = len(points)

    if n_points < 2:
        raise ValueError("n_points must be at least 2 (pickup and delivery).")

    denom = max(n_points - 1, 1)
    indices = [
        round(i * (n - 1) / denom)
        for i in range(n_points)
    ]

    selected_points = [points[i] for i in indices]
    selected_points[0], selected_points[-1] = (
        (from_lat, from_lng),
        (to_lat, to_lng),
    )

    # First point
    origin = selected_points[0]

    # Last point
    destination = selected_points[-1]

    # Middle points
    waypoints = selected_points[1:-1]

    # Build Google Maps URL
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={origin[0]},{origin[1]}"
        f"&destination={destination[0]},{destination[1]}"
        f"&waypoints={'%7C'.join(f'{lat},{lng}' for lat, lng in waypoints)}"
    )

    return selected_points, url

def decode_polyline(encoded,
                    from_lat,
                    from_lng,
                    to_lat,
                    to_lng,
                    n_points = 7):
    points = []

    index = 0
    lat = 0
    lng = 0

    while index < len(encoded):
        # Decode latitude
        result = 0
        shift = 0

        while True:
            byte = ord(encoded[index]) - 63
            index += 1

            result |= (byte & 0x1F) << shift
            shift += 5

            if byte < 0x20:
                break

        delta_lat = ~(result >> 1) if result & 1 else (result >> 1)
        lat += delta_lat

        # Decode longitude
        result = 0
        shift = 0

        while True:
            byte = ord(encoded[index]) - 63
            index += 1

            result |= (byte & 0x1F) << shift
            shift += 5

            if byte < 0x20:
                break

        delta_lng = ~(result >> 1) if result & 1 else (result >> 1)
        lng += delta_lng

        points.append((
            lat / 100000.0,
            lng / 100000.0
        ))

    return points



def calculate_driving_distance(
    from_lat,
    from_lng,
    to_lat,
    to_lng,
    milestone_spacing_km=50,
):
    """
    Calculate actual driving distance and travel duration
    between two latitude/longitude coordinates.

    `milestone_spacing_km` controls how far apart generated milestones are
    on long routes - see calculate_n_points(). Pass a smaller value for
    closer-together milestones (more frequent status updates on a long
    haul) or a larger one for sparser milestones.
    """

    url = (
        "https://routes.googleapis.com/"
        "directions/v2:computeRoutes"
    )

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": (
            "routes.distanceMeters,"
            "routes.duration,"
            "routes.legs"
        )
    }

    payload = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": float(from_lat),
                    "longitude": float(from_lng)
                }
            }
        },

        "destination": {
            "location": {
                "latLng": {
                    "latitude": float(to_lat),
                    "longitude": float(to_lng)
                }
            }
        },

        "travelMode": "DRIVE",

        "routingPreference": "TRAFFIC_AWARE"
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    routes = data.get("routes", [])

    if not routes:
        return {
            "success": False,
            "message": "No route found"
        }

    route = routes[0]


    # ----------------------------------------
    # Distance
    # ----------------------------------------

    distance_meters = route.get("distanceMeters", 0)

    distance_km = round(
        distance_meters / 1000,
        2
    )

    # ----------------------------------------
    # Duration
    # ----------------------------------------

    duration = route.get("duration", "0s")

    duration_seconds = int(
        duration.replace("s", "")
    )

    hours = duration_seconds // 3600

    minutes = (
        duration_seconds % 3600
    ) // 60

    if hours > 0:
        duration_text = (
            f"{hours} hr {minutes} min"
        )
    else:
        duration_text = (
            f"{minutes} min"
        )

    n_points = calculate_n_points(distance_km, km=milestone_spacing_km)
    # route polyline points
    encoded = data['routes'][0]['legs'][0]['polyline']['encodedPolyline']
    points = decode_polyline(encoded,
                    from_lat,
                    from_lng,
                    to_lat,
                    to_lng,
                    n_points)

    # get milestone

    milestones, url_ = get_milestone(from_lat,
                from_lng,
                to_lat,
                to_lng,
                points,
                n_points)



    return {
        "success": True,
        "distance_km": distance_km,
        "distance_meters": distance_meters,
        "duration_seconds": duration_seconds,
        "duration_text": duration_text,
        "milestone_points": milestones,
        "route_polylines": points,
        "route_url": url_,
    }


def calculate_n_points(distance_km, km=50):
    """
    Decides how many milestone points to generate along a single leg.

    - Up to and including 100 km: always 3 points total (pickup, one
      mid-point, delivery). Short/medium routes don't need more than that.
    - Beyond 100 km: one extra milestone is added for roughly every `km`
      kilometres past the first 100, so milestones on a long haul stay
      spaced out instead of clustering near the start.

    `km` is the configurable milestone-spacing value - pass a smaller `km`
    (e.g. 25) for more closely-spaced milestones, or a larger one (e.g.
    100) for sparser milestones on very long routes. Previously this value
    was hardcoded; it is now threaded through from the caller
    (calculate_driving_distance(..., milestone_spacing_km=...)).

    (Bug fix: the inline comments here used to say "< 100 m" / "< 1 km",
    which did not match what the code actually checks - both branches
    compare `distance_km` in KILOMETRES, not metres. The comments above
    now describe the real behaviour.)
    """
    if km <= 0:
        raise ValueError("km (milestone spacing) must be a positive number.")

    n_point = 2  # pickup + delivery are always present

    if distance_km <= 100:
        n_point += 1
    else:
        n_point += distance_km // km

    return int(n_point)


def build_multi_point_route(points, milestone_spacing_km=50):
    """
    Builds one combined route across an ORDERED sequence of stops, e.g.:

        [pickup_1, pickup_2, delivery_1, delivery_2]

    This is what makes multiple-pickup / multiple-delivery shipments work:
    the caller decides the visiting order (all pickups first, then all
    deliveries, is the normal case) and this function chains
    calculate_driving_distance() leg by leg between consecutive stops, then
    merges the legs into one continuous route - one total distance/duration,
    one continuous polyline, and one milestone list where every input stop
    is guaranteed to appear as its own milestone (never silently merged
    into a neighbouring leg's points).

    `points`: list of (latitude, longitude) tuples, at least 2 long.
    A 2-point list (one pickup, one delivery) behaves exactly like calling
    calculate_driving_distance() directly - this function is a strict
    generalization of the single-pickup/single-delivery case, not a
    separate code path.

    Returns the same shape as calculate_driving_distance(), plus
    "waypoints" (the original input list) and "leg_boundaries" (the index,
    in the combined milestone_points list, of every input stop - this is
    what lets the caller know which milestones are the "real" pickups vs
    deliveries vs merely the route's own intermediate transit points).
    """
    if len(points) < 2:
        raise ValueError("At least two points (one pickup, one delivery) are required.")

    legs = []
    for (a_lat, a_lon), (b_lat, b_lon) in zip(points, points[1:]):
        leg = calculate_driving_distance(a_lat, a_lon, b_lat, b_lon, milestone_spacing_km)
        if not leg.get("success"):
            return {
                "success": False,
                "message": leg.get("message", f"Could not compute leg {(a_lat, a_lon)} -> {(b_lat, b_lon)}"),
            }
        legs.append(leg)

    total_distance_km = round(sum(l["distance_km"] for l in legs), 2)
    total_distance_m = sum(l["distance_meters"] for l in legs)
    total_duration_s = sum(l["duration_seconds"] for l in legs)

    hours = total_duration_s // 3600
    minutes = (total_duration_s % 3600) // 60
    duration_text = f"{hours} hr {minutes} min" if hours > 0 else f"{minutes} min"

    combined_polyline = []
    combined_milestones = []
    leg_boundaries = [0]  # index in combined_milestones of points[0] (first pickup)

    for i, leg in enumerate(legs):
        poly = leg["route_polylines"]
        # Each leg's polyline starts where the previous leg's ended -
        # drop the duplicate join point for every leg after the first.
        combined_polyline += poly if i == 0 else poly[1:]

        leg_milestones = leg["milestone_points"]
        # Each leg's milestone list starts where the previous leg's ended
        # (that shared point is a real input stop - an intermediate pickup
        # or delivery - and must appear exactly once). Keep the first leg
        # whole; for every later leg, drop its first point since it's the
        # same point as the previous leg's last point, already appended.
        ms = leg_milestones if i == 0 else leg_milestones[1:]

        combined_milestones += ms
        # The point we just finished appending the leg at is exactly the
        # next input stop (points[i+1]) - record its position.
        leg_boundaries.append(len(combined_milestones) - 1)

    return {
        "success": True,
        "distance_km": total_distance_km,
        "distance_meters": total_distance_m,
        "duration_seconds": total_duration_s,
        "duration_text": duration_text,
        "milestone_points": combined_milestones,
        "route_polylines": combined_polyline,
        "waypoints": points,
        "leg_boundaries": leg_boundaries,
    }


def calculate_n_points1(distance_km):
    n_point = 2

    if distance_km <= 200 :       # < 100 m
        n_point += 1
    elif distance_km <= 300:       # < 1 km
        n_point += 2
    elif distance_km <= 500:       # < 1 km
            n_point += 4
    elif distance_km <= 700:       # < 1 km
            n_point += 5
    else:
        n_point += 5

    return n_point