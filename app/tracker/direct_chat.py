from enum import Enum
from typing import Dict, Optional
from zoneinfo import ZoneInfo
from datetime import datetime
from app.core.config import settings
from app.tracker.shipment_status import *
from app.schemas.tracker import *
from app.tracker.gps_tracking import get_car_status
import threading

import requests
from datetime import datetime

user_sessions: Dict[str, Dict] = {}
user_sessions_lock = threading.Lock()


def get_session(number: str) -> Dict:
    with user_sessions_lock:
        if number not in user_sessions:
            user_sessions[number] = {"state": "NEW", "job_number": None}
        return user_sessions[number]


def set_session(number: str, **kwargs):
    with user_sessions_lock:
        session = user_sessions.setdefault(
            number, {"state": "NEW", "job_number": None}
        )
        session.update(kwargs)


def reset_session(number: str):
    with user_sessions_lock:
        user_sessions[number] = {"state": "NEW", "job_number": None}


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

def get_status(status):
    url = f"{settings.tcard_base_url}/api/status"

    response = requests.get(url,
                            params={
                                        "status": status
                                    })

    response.raise_for_status()

    return response.json()['data']



def build_shipment_status_message(job_number: str, truck_number: str) -> Optional[str]:
    """
    Looks up the truck's current status and formats it using the same
    STATUS_FUNCTIONS templates used by the manual/automatic workflow.
    """

    # truck_data = TRUCK_DIRECTORY.get(truck_number)
    truck_data = get_trucks_current_status_t_cart(job_number,truck_number)
    trucks, truck_details = get_trucks_jobs_number(
                                        job_number
                                    )
    if truck_number not in trucks:
        return menu_truck_not_found()

    if not truck_data:
        return menu_truck_not_found()

    location_response = get_car_status(car_number=truck_number)
    current_location = None
    if location_response.get("result"):
        location_res = location_response['result'][0]
        longitude = str(location_res['logGisx']/ 1000000)
        latitude  = str(location_res['logGisy']/ 1000000)
        current_location = location_res['address']
        speed = str(round(location_res['logSpeed'], 2))
        # current_location = location_response["result"][0]["address"]

    if truck_data["shipment_status"].value in STATUS_FUNCTIONS:
    
        function = STATUS_FUNCTIONS[truck_data[0]["truck_tracking_status_name"]]
        truck_data = truck_data[0]
        print(truck_data)
        return function(
            job_number=job_number,
            truck_number=truck_number,
            driver_name=truck_data["truck_tracking_tmr_driver_name"],
            route_from=truck_data["rtf_from"],
            route_to=truck_data["rtf_to"],
            current_location=current_location,
        )

    elif truck_data["shipment_status"].value in STATUS_FUNCTIONS:
        truck_data = truck_data[0]

        status_data = get_status(truck_data["shipment_status"].value.lower())
        latest_updated = status_data['remarks']
        estimated_arrival = status_data['estimated_arrival']
        shipment_status = status_data['status']



        return create_common_status(
            job_number=job_number,
            truck_number=truck_number,
            driver_name=truck_data["truck_tracking_tmr_driver_name"],
            route_from=truck_data["rtf_from"],
            route_to=truck_data["rtf_to"],
            current_location=current_location,
            shipment_status= shipment_status,
            latest_updated= latest_updated,
            estimated_arrival=estimated_arrival
        )


def get_greetings():
    dt = datetime.now(ZoneInfo("Asia/Kuala_Lumpur"))

    hour = dt.hour

    if 5 <= hour < 12:
        greeting = "Good morning!"
    elif 12 <= hour < 17:
        greeting = "Good afternoon!"
    else:
        greeting = "Good evening!"

    return greeting

# ---- Menu text builders (mirrors the WhatsApp UI mock-ups) ----

def menu_welcome() -> str:
    return (
        f"👋 {get_greetings()}\n"
        "Welcome to *Glow Freight Shipment Tracker*.\n\n"
        "Would you like to track your shipment?\n\n"
        "1️⃣ YES\n"
        "2️⃣ NO"
    )

DEMO_PHONE_NUMBER = "019-5228960"


def get_jobs_by_mobile_number(phone: str):

    phone = DEMO_PHONE_NUMBER



    url = f"{settings.tcard_base_url}/Apicard/client_job_list/{phone}"
  

    response = requests.get(
        url,
        timeout=30
    )

    response.raise_for_status()

    result = response.json()

    jobs = result.get(
        "data",
        []
    )


    # --------------------------------------------------------
    # Sort jobs by pickup date
    # --------------------------------------------------------

    jobs_sorted = sorted(
        jobs,
        key=lambda x: datetime.strptime(
            x["rtf_datepickup"],
            "%Y-%m-%d %H:%M:%S"
        )
    )

    job_ids = [
        job["rtf_jobno"]
        for job in jobs_sorted
        # if job['planning_status'] != "0"
    ]

    jobs_ = [
        job
        for job in jobs_sorted
        if job['planning_status'] != "0"
    ]
    

    return job_ids, jobs_


def menu_job_selection() -> str:

    jobs, job_details = get_jobs_by_mobile_number(
                phone= DEMO_PHONE_NUMBER
            )
    jobs = "\n".join(f"🔹 {job}" for job in jobs)
    # jobs = "\n".join(f"🔹 {job}" for job in JOB_TRUCK_MAP)
    return (
        "Kindly select your *Job Number* from the options below:\n\n"
        f"{jobs}\n\n"
        "(Reply with the Job Number, e.g. GFS/0000T/MM/YY)"
    )



def get_trucks_jobs_number(job_no: str):


    url = f"{settings.tcard_base_url}/Apicard/client_job_truck_list"



    response = requests.get(
        url,
        params={
            "jobno": job_no
        },
        timeout=15
    )


    response.raise_for_status()


    result = response.json()


    trucks = result.get(
        "data",
        []
    )


    # --------------------------------------------------------
    # Sort trucks by pickup date
    # --------------------------------------------------------

    trucks_sorted = sorted(
        trucks,
        key=lambda x: datetime.strptime(
            x["rtf_datepickup"],
            "%Y-%m-%d %H:%M:%S"
        )
    )
    trucks_ids = [
        truck["rtf_truck_no_text"]
        for truck in trucks_sorted
        if truck["common_flag"] != "0"
    ]

    truck_details = [
        truck
        for truck in trucks_sorted
        if truck["common_flag"] != "0"
    ]

    return trucks_ids, truck_details



def get_trucks_current_status_t_cart(job_no: str, truck_number:str):

    url = f"{settings.tcard_base_url}/Apicard/client_job_truck_details"
    


    response = requests.get(
        url,
        params={
            "jobno": job_no,
            "truckno": truck_number
        },
        timeout=35
    )


    response.raise_for_status()


    result = response.json()


    trucks = result.get(
        "data",
        []
    )


    # --------------------------------------------------------
    # Sort trucks by pickup date
    # --------------------------------------------------------

    trucks_sorted = sorted(
        trucks,
        key=lambda x: datetime.strptime(
            x["rtf_datepickup"],
            "%Y-%m-%d %H:%M:%S"
        )
    )
    

    
    return trucks_sorted



def menu_truck_selection(job_number: str, trucks: list) -> str:
    print('working')
    trucks, truck_details = get_trucks_jobs_number(
                job_number
            )

    truck_list = "\n".join(f"🚚 {truck}" for truck in trucks)
    return (
        f"Job *{job_number}* has multiple trucks.\n"
        "Kindly select a truck to view its shipment status:\n\n"
        f"{truck_list}\n\n"
        "(Reply with the Truck Number, e.g. XXX0000)\n\n"
        "↩️ BACK TO JOB SELECTION\n"
        "🏠 MAIN MENU"
    )


def menu_job_not_found() -> str:
    return (
        "Sorry, we couldn't find a shipment associated with that Job Number.\n"
        "Please check the Job Number and try again.\n\n"
        "🔁 TRY AGAIN\n"
        "📞 CONTACT SUPPORT\n"
        "🏠 MAIN MENU"
    )


def menu_truck_not_found() -> str:
    return (
        "We couldn't find truck information for this Job Number at the "
        "moment.\nPlease try again later or contact Glow Freight support.\n\n"
        "🔁 TRY AGAIN\n"
        "📞 CONTACT SUPPORT\n"
        "↩️ BACK TO JOB SELECTION"
    )


def menu_post_status() -> str:
    return "\n\n📦 TRACK ANOTHER SHIPMENT\n🏠 MAIN MENU"


def menu_main() -> str:
    return (
        "Welcome to *Glow Freight Shipment Tracker*.\n"
        "Please choose an option below:\n\n"
        "1️⃣ TRACK SHIPMENT\n"
        "2️⃣ MY JOB HISTORY\n"
        "3️⃣ CONTACT SUPPORT\n"
        "4️⃣ ABOUT GLOW FREIGHT"
    )


def menu_contact_support() -> str:
    return (
        "You can reach our support team through the following:\n\n"
        "📞 +65 6741 3366\n"
        "✉️ support@glowfreight.com\n"
        "🌐 www.glowfreight.com\n\n"
        "Our team is available Mon - Fri (9:00 AM - 6:00 PM)\n\n"
        "🏠 BACK TO MAIN MENU"
    )


def menu_about() -> str:
    return (
        "*Glow Freight* - Safe, Secure, On Time.\n"
        "We provide real-time shipment tracking and logistics solutions "
        "across Singapore and Malaysia.\n\n"
        "🏠 BACK TO MAIN MENU"
    )


def menu_job_history() -> str:
    return "📖 *My Job History*\nThis feature is coming soon.\n\n🏠 BACK TO MAIN MENU"


def menu_goodbye() -> str:
    return (
        "No worries! Feel free to message us anytime you'd like to track "
        "a shipment. 👋"
    )


def process_shipment_bot(reply_number: str, message: str) -> str:
    """
    Drives the button-style WhatsApp conversation flow: welcome -> job
    selection -> (truck selection) -> shipment status -> main menu /
    contact support / about / job history, plus "not found" fallbacks.
    """

    text = (message or "").strip()
    text_upper = text.upper()
    session = get_session(reply_number)

    # ---- Global commands, available from (almost) any state ----
    if text_upper in ("MAIN MENU", "BACK TO MAIN MENU", "4"):
        set_session(reply_number, state="MAIN_MENU", job_number=None)
        return menu_main()

    if text_upper in ("CONTACT SUPPORT", "3"):
        set_session(reply_number, state="CONTACT_SUPPORT")
        return menu_contact_support()

    if text_upper == "ABOUT GLOW FREIGHT":
        set_session(reply_number, state="ABOUT")
        return menu_about()

    if text_upper in ("TRACK SHIPMENT", "TRACK ANOTHER SHIPMENT", "1"):
        set_session(reply_number, state="AWAIT_JOB", job_number=None)
        return menu_job_selection()

    if text_upper in ("MY JOB HISTORY", "2"):
        set_session(reply_number, state="MAIN_MENU")
        return menu_job_history()

    if text_upper == "BACK TO JOB SELECTION":
        set_session(reply_number, state="AWAIT_JOB", job_number=None)
        return menu_job_selection()

    if text_upper == "TRY AGAIN":
        if session.get("job_number") and session.get("state") == "AWAIT_TRUCK":
            trucks, truck_details = get_trucks_jobs_number(
                        job_number
                    )
            return menu_truck_selection(
                session["job_number"], trucks
            )
        set_session(reply_number, state="AWAIT_JOB", job_number=None)
        return menu_job_selection()

    # ---- State-specific handling ----
    state = session.get("state", "NEW")

    if state == "NEW":
        set_session(reply_number, state="AWAIT_START")
        return menu_welcome()

    if state == "AWAIT_START":
        if text_upper == "YES":
            set_session(reply_number, state="AWAIT_JOB")
            return menu_job_selection()
        if text_upper == "NO":
            reset_session(reply_number)
            return menu_goodbye()
        return menu_welcome()

    if state == "AWAIT_JOB":
        job_number = text_upper
        trucks, truck_details = get_trucks_jobs_number(
                            job_number
                        )

        print("AWAIT_JOB", trucks)
        if len(trucks) == 0:
        # if job_number not in trucks:
            return menu_job_not_found()

        

        if not trucks:
            set_session(reply_number, state="AWAIT_JOB", job_number=None)
            return menu_truck_not_found()

        if len(trucks) == 1:
            status_message = build_shipment_status_message(job_number, trucks[0])
            set_session(reply_number, state="POST_STATUS", job_number=job_number)
            return status_message + menu_post_status()

        set_session(reply_number, state="AWAIT_TRUCK", job_number=job_number)
        return menu_truck_selection(job_number, trucks)

    if state == "AWAIT_TRUCK":
        job_number = session.get("job_number")
        truck_number = text_upper
        trucks, truck_details = get_trucks_jobs_number(
                                    job_number
                                )
        # trucks = JOB_TRUCK_MAP.get(job_number, [])

        if truck_number not in trucks:
            return menu_truck_not_found()

        status_message = build_shipment_status_message(job_number, truck_number)
        set_session(reply_number, state="POST_STATUS", job_number=job_number)
        print('status', job_number, truck_number, status_message)
        return status_message + menu_post_status()

    if state in ("POST_STATUS", "MAIN_MENU", "CONTACT_SUPPORT", "ABOUT"):
        # Unrecognized input while idle: show the main menu again.
        set_session(reply_number, state="MAIN_MENU")
        return menu_main()

    reset_session(reply_number)
    return menu_welcome()




