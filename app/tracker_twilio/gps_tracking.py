import os
import re
import requests
from dotenv import load_dotenv
from app.core.config import settings

# ============================================================
# LOAD ENVIRONMENT
# ============================================================



ACCESS_TOKEN = settings.gps_key

BASE_URL = settings.gps_base_url


def clean_truck_no(text, pattern = r'\b([A-Z]{3})\s?(\d{4})\b'):
    

    matches = re.findall(pattern, text, re.IGNORECASE)

    result = [
        letters + numbers
        for letters, numbers in matches
    ]

    if result:
        return result[0]
    else:
        pattern = r'\b([A-Z]{3})\s?(\d{3})\b'
        return clean_truck_no(text, pattern)


def gps_login():
    """
    Get SessionID using the API token.

    POST:
        /login/session?token=<token>

    Returns:
        session_id (str)
    """

    url = f"{BASE_URL}/login/session"

    response = requests.post(
        url,
        params={
            "token": ACCESS_TOKEN
        },
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if data.get("responseMsg") != "SUCCESS":
        raise RuntimeError(f"Login failed: {data}")

    session_id = data["result"]["sessionId"]

    return session_id


def get_car_status(car_number="", session_id = gps_login()):
    """
    Get current car/vehicle status.

    GET:
        /car/log_data/car_status

    Args:
        session_id: SessionID returned by login()
        car_number: Vehicle number, e.g. BPW6290.
                    Empty string returns all vehicle data.

    Returns:
        JSON response
    """

    url = f"{BASE_URL}/car/log_data/car_status"

    car_number = clean_truck_no(car_number).upper()
    print("car_number", car_number)

    headers = {
        "Authorization": f"Bearer {session_id}",
        "Accept": "application/json",
    }

    params = {
        "carNumber": car_number
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    return response.json()





