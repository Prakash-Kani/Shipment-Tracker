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
    n = len(points)

    indices = [
        round(i * (n - 1) / 6)
        for i in range(n_points)
    ]

    selected_points = [points[i] for i in indices]
    selected_points[0], selected_points[-1] = (
    (from_lat, from_lng),
    (to_lat, to_lng)
)

    # First point
    origin = selected_points[0]

    # Last point
    destination = selected_points[-1]

    # Middle 5 points
    waypoints = selected_points[1:-1]

    # Build Google Maps URL
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={origin[0]},{origin[1]}"
        f"&destination={destination[0]},{destination[1]}"
        f"&waypoints={'%7C'.join(f'{lat},{lng}' for lat, lng in waypoints)}"
    )

    print(url)
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
    to_lng
):
    """
    Calculate actual driving distance and travel duration
    between two latitude/longitude coordinates.
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

    n_points = calculate_n_points(distance_km)
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

def calculate_n_points(distance_km, km = 70):
    n_point = 2

    if distance_km <= 100 :       # < 100 m
        n_point += 1
    elif distance_km > 100:       # < 1 km
        n_point += distance_km // km
   

    return n_point


