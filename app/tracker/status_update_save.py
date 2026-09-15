import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.config import settings


def get_trucks_current_status_t_cart(
    job_no: str,
    truck_number: str
):
    url = f"{settings.tcard_base_url}Apicard/client_job_truck_details"


    response = requests.get(
        url,
        params={
            "jobno": job_no,
            "truckno": truck_number
        },
        timeout=35
    )


    response.raise_for_status()

    try:
        result = response.json()
    except requests.exceptions.JSONDecodeError:
        print("Invalid JSON response:")
        print(repr(response.text))
        return []

    if not result.get("status"):
        return []

    trucks = result.get("data") or []

    trucks_sorted = sorted(
        trucks,
        key=lambda x: datetime.strptime(
            x["rtf_datepickup"],
            "%Y-%m-%d %H:%M:%S"
        )
    )

    return trucks_sorted


def update_shipment_status(job_number: str,
                           truck_number: str,
                           shipment_status: str,
                           message: str,
                           longitude: str,
                           latitude: str,
                           current_location: str,
                           speed: str):

    dt = datetime.now(ZoneInfo("Asia/Kuala_Lumpur"))
    occurred_at = dt.strftime("%Y-%m-%dT%H:%M")

    truck_data = get_trucks_current_status_t_cart(job_number, truck_number)


    if not truck_data:
        return 'TRUCK DETAILS IS NOT FOUND!, RECHECK THE JOB AND TRUCK NUMBER.'

    if truck_data:
        truck_data = truck_data[0]

    latest_update = message.split("*Latest Update:*", 1)[1].strip().replace("\n", " ")



    payload = {
    "main_job_id": truck_data['sub_refer_rtf_id'],
    "sub_job_id": truck_data['rtf_id'],
    "ta_refer_id": truck_data['ta_refer_id'],
    "stage": shipment_status if type(shipment_status) ==str else shipment_status.value,
    "status_detail": shipment_status if type(shipment_status) ==str else shipment_status.value,
    "location": current_location,
    "remarks": latest_update,
    "occurred_at": occurred_at,
    "latitude": latitude,
    "longitude": longitude,
    "speed": speed,
    "user_id": "1",
    "user_name": "admin",
    "subscriber_id": "1"
  }
    url = f"{settings.tcard_base_url}/Apicard/truck_update_save"

    headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

    print(payload)
    # return payload
    response = requests.post(
        url,
        headers=headers,
        json=payload,
    )

    print(response.status_code)
    print(response.text)

    return response



    