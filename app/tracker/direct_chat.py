from enum import Enum
from typing import Dict, Optional
from zoneinfo import ZoneInfo
from datetime import datetime
from app.core.config import settings
from app.tracker.shipment_status import *
from app.schemas.tracker import *
from app.tracker.gps_tracking import get_car_status
from app.tracker.messanger import *
import threading

import requests

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


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def get_trucks_current_status_t_cart(job_no: str, truck_number: str):
    url = f"{settings.tcard_base_url}/Apicard/client_job_truck_details"

    response = requests.get(
        url,
        params={
            "jobno": job_no,
            "truckno": truck_number,
        },
        timeout=35,
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
            "%Y-%m-%d %H:%M:%S",
        ),
    )

    return trucks_sorted


def get_status(status):
    url = f"{settings.tcard_base_url}/api/status"

    response = requests.get(url, params={"status": status})

    response.raise_for_status()

    return response.json()["data"]


def get_jobs_by_mobile_number(phone: str):
    phone = DEMO_PHONE_NUMBER

    # url = f"{settings.tcard_base_url}/Apicard/client_job_list/{phone}"
    url = f"{settings.tcard_base_url}/Apicard/client_job_list"

    response = requests.get(url, timeout=30)

    response.raise_for_status()

    result = response.json()

    jobs = result.get("data", [])

    # Sort jobs by pickup date
    jobs_sorted = sorted(
        jobs,
        key=lambda x: datetime.strptime(
            x["rtf_datepickup"],
            "%Y-%m-%d %H:%M:%S",
        ),
    )

    job_ids = [
        job["rtf_jobno"]
        for job in jobs_sorted
        # if job['planning_status'] != "0"
    ]

    jobs_ = [
        job
        for job in jobs_sorted
        if job["planning_status"] != "0"
    ]

    return job_ids, jobs_


def get_trucks_jobs_number(job_no: str):
    url = f"{settings.tcard_base_url}/Apicard/client_job_truck_list"

    response = requests.get(
        url,
        params={"jobno": job_no},
        timeout=15,
    )

    response.raise_for_status()

    result = response.json()

    trucks = result.get("data", [])

    # Sort trucks by pickup date
    trucks_sorted = sorted(
        trucks,
        key=lambda x: datetime.strptime(
            x["rtf_datepickup"],
            "%Y-%m-%d %H:%M:%S",
        ),
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


def build_shipment_status_message(job_number: str, truck_number: str) -> Optional[str]:
    """
    Looks up the truck's current status and formats it using the same
    STATUS_FUNCTIONS templates used by the manual/automatic workflow.
    Returns None when the truck / status cannot be found; the caller is
    responsible for sending the "not found" message.
    """

    truck_data = get_trucks_current_status_t_cart(job_number, truck_number)
    trucks, truck_details = get_trucks_jobs_number(job_number)

    if truck_number not in trucks and truck_number.lower() not in trucks:
        return None

    if not truck_data:
        return None

    current_location = None
    location_response = get_car_status(car_number=truck_number)
    if location_response.get("result"):
        location_res = location_response["result"][0]
        current_location = location_res["address"]

    status_name = truck_data[0]["truck_tracking_status_name"]
    truck_row = truck_data[0]

    driver_name = (
        truck_row.get("rtf_driver_name_text")
        or truck_row.get("truck_tracking_tmr_driver_name")
    )

    if status_name in STATUS_FUNCTIONS:
        function = STATUS_FUNCTIONS[status_name]
        return function(
            job_number=job_number,
            truck_number=truck_number,
            driver_name=driver_name,
            route_from=truck_row["rtf_from"],
            route_to=truck_row["rtf_to"],
            current_location=current_location,
        )

    # Fallback for statuses not in STATUS_FUNCTIONS
    status_data = get_status(status_name.lower())
    return create_common_status(
        job_number=job_number,
        truck_number=truck_number,
        driver_name=driver_name,
        route_from=truck_row["rtf_from"],
        route_to=truck_row["rtf_to"],
        current_location=current_location,
        shipment_status=status_data["status"],
        latest_updated=status_data["remarks"],
        estimated_arrival=status_data["estimated_arrival"],
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


DEMO_PHONE_NUMBER = "019-5228960"


# ---------------------------------------------------------------------------
# Menu senders (WhatsApp interactive messages)
# ---------------------------------------------------------------------------

async def menu_welcome(reply_number: str, message: str):
    await send_whatsapp_interactive(
        to=reply_number,
        values=["YES", "NO"],
        interactive_type="button",
        body_text="Welcome to *Glow Freight Shipment Tracker*.\nWould you like to track your shipment?",
        button_text="Select Job Number",
        list_title="Available Jobs",
    )
    return None


async def menu_job_selection(reply_number: str, message: str):
    jobs, job_details = get_jobs_by_mobile_number(phone=DEMO_PHONE_NUMBER)

    await send_whatsapp_interactive(
        to=reply_number,
        values=jobs,
        interactive_type="list" if len(jobs) > 3 else "button",
        body_text=(
            "You can check your shipment status by selecting an available Job Number.\n"
            " Please select your *Job Number* from the options below."
        ),
        button_text="Select Job Number",
        list_title="Available Jobs",
    )
    return None


async def menu_truck_selection(job_number: str, trucks: list, reply_number: str):
    trucks, truck_details = get_trucks_jobs_number(job_number)

    trucks_ = [t.upper() for t in trucks]
    trucks_.extend(["BACK TO JOB LIST", "MAIN MENU"])

    response = await send_whatsapp_interactive(
        to=reply_number,
        values=trucks_,
        interactive_type="list" if len(trucks_) > 3 else "button",
        body_text=f"Job *{job_number}* has multiple trucks.\nKindly select a truck to view its shipment status.",
        button_text="Select Truck Number",
        list_title="Available Truck",
    )

    print(response)
    return None


async def menu_job_not_found(reply_number: str):
    response = await send_whatsapp_interactive(
        to=reply_number,
        values=["🔁 TRY AGAIN", "📞 CONTACT SUPPORT", "🏠 MAIN MENU"],
        interactive_type="button",
        body_text=(
            "Sorry, we couldn't find a shipment associated with that Job Number.\n"
            "Please check the Job Number and try again."
        ),
        button_text="Select Truck Number",
        list_title="Available Truck",
    )

    print(response)
    return None


async def menu_truck_not_found(reply_number: str):
    response = await send_whatsapp_interactive(
        to=reply_number,
        values=["🔁 TRY AGAIN", "📞 CONTACT SUPPORT", "↩️ BACK TO JOB LIST"],
        interactive_type="button",
        body_text=(
            "We couldn't find truck information for this Job Number at the moment.\n"
            "Please try again later or contact Glow Freight support."
        ),
        button_text="Select Truck Number",
        list_title="Available Truck",
    )

    print(response)
    return None


async def menu_main(reply_number: str):
    await send_whatsapp_interactive(
        to=reply_number,
        values=["TRACK SHIPMENT", "CONTACT SUPPORT", "ABOUT GLOW FREIGHT"],
        interactive_type="button",
        body_text="Welcome to *Glow Freight Shipment Tracker*.\nPlease choose an option below:",
        button_text="Select Option",
        list_title="Available Jobs",
    )
    return None


async def menu_contact_support(reply_number: str):
    await send_whatsapp_interactive(
        to=reply_number,
        values=["BACK TO MAIN MENU"],
        interactive_type="button",
        body_text=(
            "You can reach our support team through the following:\n\n"
            "📞 +65 6741 3366\n"
            "✉️ cs@glowfreight.com.my\n"
            "🌐 https://www.glowfreight.com.my\n\n"
            "Our team is available Mon - Sun: 9:00am - 10:00pm\n\n"
        ),
        button_text="Select Option",
        list_title="Available Jobs",
    )
    return None


async def menu_about(reply_number: str):
    await send_whatsapp_interactive(
        to=reply_number,
        values=["BACK TO MAIN MENU"],
        interactive_type="button",
        body_text=(
            "*Glow Freight* - Safe, Secure, On Time.\n"
            "We provide real-time shipment tracking and logistics solutions "
            "across Singapore and Malaysia."
        ),
        button_text="Select Job Number",
        list_title="Available Jobs",
    )
    return None


def menu_job_history() -> str:
    return "📖 *My Job History*\nThis feature is coming soon.\n\n🏠 BACK TO MAIN MENU"


def menu_goodbye() -> str:
    return (
        "No worries! Feel free to message us anytime you'd like to track "
        "a shipment. 👋"
    )


# ---------------------------------------------------------------------------
# Flow helpers
# ---------------------------------------------------------------------------

async def send_truck_status(
    reply_number: str,
    job_number: str,
    truck_number: str,
    multi_truck: bool,
):
    """Show tracking for one truck. 'TRACK ANOTHER TRUCK' is offered only
    when the job has more than one truck."""
    status_message = build_shipment_status_message(job_number, truck_number)
    if not status_message:
        return await menu_truck_not_found(reply_number)

    set_session(reply_number, state="POST_STATUS", job_number=job_number)

    buttons = ["TRACK ANOTHER JOB", "MAIN MENU"]
    if multi_truck:
        # WhatsApp allows max 3 reply buttons, titles max 20 chars
        buttons.insert(0, "TRACK ANOTHER TRUCK")

    await send_whatsapp_interactive(
        to=reply_number,
        values=buttons,
        interactive_type="button",
        body_text=status_message,
        button_text="Select Options",
        list_title="Available Jobs",
    )
    return None


async def handle_job_selected(reply_number: str, job_number: str):
    """A job was chosen (by the user or auto-selected):
    0 trucks -> not found, 1 truck -> tracking, >1 trucks -> truck list."""
    trucks, _ = get_trucks_jobs_number(job_number)

    if not trucks:
        set_session(reply_number, state="AWAIT_JOB", job_number=None)
        return await menu_job_not_found(reply_number)

    if len(trucks) == 1:
        return await send_truck_status(
            reply_number, job_number, trucks[0], multi_truck=False
        )

    set_session(reply_number, state="AWAIT_TRUCK", job_number=job_number)
    return await menu_truck_selection(job_number, trucks, reply_number)


async def start_job_selection(reply_number: str, message: str):
    """Skip the job list when there is only one job."""
    jobs, _ = get_jobs_by_mobile_number(phone=DEMO_PHONE_NUMBER)

    if len(jobs) == 1:
        return await handle_job_selected(reply_number, jobs[0])

    set_session(reply_number, state="AWAIT_JOB", job_number=None)
    return await menu_job_selection(reply_number, message)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def process_shipment_bot(reply_number: str, message: str):
    """
    Drives the button-style WhatsApp conversation flow: welcome -> job
    selection -> (truck selection) -> shipment status -> main menu /
    contact support / about / job history, plus "not found" fallbacks.
    """

    text = (message or "").strip()
    text_upper = text.upper()
    session = get_session(reply_number)

    # ---- Global commands, available from (almost) any state ----
    if text_upper in ("MAIN MENU", "🏠 MAIN MENU", "BACK TO MAIN MENU", "4"):
        set_session(reply_number, state="MAIN_MENU", job_number=None)
        return await menu_main(reply_number)

    if text_upper in ("CONTACT SUPPORT", "📞 CONTACT SUPPORT", "3"):
        set_session(reply_number, state="CONTACT_SUPPORT")
        return await menu_contact_support(reply_number)

    if text_upper == "ABOUT GLOW FREIGHT":
        set_session(reply_number, state="ABOUT")
        return await menu_about(reply_number)

    if text_upper in (
        "TRACK SHIPMENT",
        "TRACK ANOTHER JOB",
        "BACK TO JOB LIST",
        "↩️ BACK TO JOB LIST",
        "1",
    ):
        set_session(reply_number, state="AWAIT_JOB", job_number=None)
        return await start_job_selection(reply_number, message)

    # Track another truck within the same job (multi-truck jobs only)
    if text_upper == "TRACK ANOTHER TRUCK":
        job_number = session.get("job_number")
        if not job_number:
            return await start_job_selection(reply_number, message)
        return await handle_job_selected(reply_number, job_number)

    if text_upper in ("MY JOB HISTORY", "2"):
        set_session(reply_number, state="MAIN_MENU")
        return menu_job_history()

    if text_upper in ("TRY AGAIN", "🔁 TRY AGAIN"):
        job_number = session.get("job_number")
        if job_number and session.get("state") == "AWAIT_TRUCK":
            return await handle_job_selected(reply_number, job_number)
        return await start_job_selection(reply_number, message)

    # ---- State-specific handling ----
    state = session.get("state", "NEW")

    if state == "NEW":
        set_session(reply_number, state="AWAIT_START")
        return await menu_welcome(reply_number, message)

    if state == "AWAIT_START":
        if text_upper == "YES":
            return await start_job_selection(reply_number, message)
        if text_upper == "NO":
            reset_session(reply_number)
            return menu_goodbye()
        return await menu_welcome(reply_number, message)

    if state == "AWAIT_JOB":
        return await handle_job_selected(reply_number, text_upper)

    if state == "AWAIT_TRUCK":
        job_number = session.get("job_number")
        trucks, _ = get_trucks_jobs_number(job_number)

        # Case-insensitive match; keep original casing for API calls
        matched = next((t for t in trucks if t.upper() == text_upper), None)
        if not matched:
            return await menu_truck_not_found(reply_number)

        return await send_truck_status(
            reply_number, job_number, matched, multi_truck=len(trucks) > 1
        )

    if state in ("POST_STATUS", "MAIN_MENU", "CONTACT_SUPPORT", "ABOUT"):
        # Unrecognized input while idle: show the main menu again.
        set_session(reply_number, state="MAIN_MENU")
        return await menu_main(reply_number)

    reset_session(reply_number)
    return await menu_welcome(reply_number, message)