# ========== Importing Libraries ==========
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Optional

import httpx
from fastapi import  HTTPException
from pydantic import BaseModel, Field

# from gps_tracking import get_car_status
from app.core.config import settings
from app.tracker.shipment_status import *
from app.schemas.tracker import *
from app.tracker.gps_tracking import get_car_status
from app.tracker.status_update_save import update_shipment_status
from app.tracker.direct_chat import get_status

# from direct_chat import process_shipment_bot
# Conversation context

conversation_context = {}
conversation_context_limit = 6

# Protect the shared dictionary when multiple requests arrive
conversation_lock = threading.Lock()

WHATSAPP_TOKEN = settings.whatsapp_token
PHONE_NUMBER_ID = settings.phone_number_id

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


# ============ Automatic Shipment-Status Workflow ============
#
# Only "In Transit" gets automatic, repeating updates. Once a truck is
# Picked Up, we ping "In Transit" every `interval` seconds indefinitely —
# there's no chain of intermediate statuses to progress through.
#
#   Picked Up -> (wait interval) -> In Transit -> (wait interval)
#             -> In Transit -> (wait interval) -> In Transit -> ...
#
# Exception statuses pause that repeating ping. A manual status update
# that resolves the exception resumes it. Reaching a terminal status
# (Arrived at Delivery Hub / Delivered / Cancelled-Returned) ends it.

# Statuses that pause the automatic In Transit updates.
EXCEPTION_STATUSES = {
    ShipmentStatus.DELAYED,
    ShipmentStatus.CUSTOMS_HOLD,
    ShipmentStatus.VEHICLE_BREAKDOWN,
    ShipmentStatus.WEATHER_ROAD_DELAY,
}

# Statuses that end the automatic workflow for good.
TERMINAL_STATUSES = {
    ShipmentStatus.ARRIVED_AT_DELIVERY_HUB,
    ShipmentStatus.DELIVERED,
    ShipmentStatus.CANCELLED_RETURNED,
}


class TruckWorkflowState:
    """
    Tracks the automatic "In Transit" ping for a single truck/shipment.
    """

    def __init__(
        self,
        truck_number: str,
        job_number: str,
        driver_name: str,
        route_from: str,
        route_to: str,
        reply_number: str,
        interval: int,
    ):
        self.truck_number = truck_number
        self.job_number = job_number
        self.driver_name = driver_name
        self.route_from = route_from
        self.route_to = route_to
        self.reply_number = reply_number

        self.interval = interval

        self.paused = False
        self.next_update_at = (
            datetime.now(timezone.utc) + timedelta(seconds=interval)
        )
        self.task: Optional[asyncio.Task] = None


# One entry per truck/shipment with an active or paused automatic workflow
trucks: Dict[str, TruckWorkflowState] = {}

# Protects the shared `trucks` dictionary
trucks_lock = asyncio.Lock()


async def send_status_message_normal(
    shipment_status: ShipmentStatus,
    job_number: str,
    truck_number: str,
    driver_name: str,
    route_from: str,
    route_to: str,
    reply_number: str,
) -> str:
    """
    Builds the WhatsApp message for a given shipment status and sends it
    through the existing /whatsapp route. Shared by both the manual
    endpoint and the automatic background workflow so the two never
    duplicate logic (or drift apart).
    """

    location_response = get_car_status(car_number=truck_number)

    current_location = None
    if location_response.get("result"):
        location_res = location_response['result'][0]
        longitude = str(location_res['logGisx']/ 1000000)
        latitude  = str(location_res['logGisy']/ 1000000)
        current_location = location_res['address']
        speed = str(round(location_res['logSpeed'], 2))
        # current_location = location_response["result"][0]["address"]

    function = STATUS_FUNCTIONS[shipment_status]

    message = function(
        job_number=job_number,
        truck_number=truck_number,
        driver_name=driver_name,
        route_from=route_from,
        route_to=route_to,
        current_location=current_location,
    )

    # async with httpx.AsyncClient() as client:
    #     response = await client.post(
    #         "http://localhost:8000/whatsapp",
    #         data={
    #             "reply_number": reply_number,
    #             "message": message,
    #             "ShipmentUpdate": message,
    #             "Status": shipment_status,
    #         },
    #     )

    # response.raise_for_status()

    save_response = update_shipment_status(job_number = job_number,
                           truck_number = truck_number,
                           shipment_status= shipment_status,
                           message = message,
                           longitude = longitude,
                           latitude = latitude,
                           current_location = current_location,
                           speed = speed)

    return message


async def send_whatsapp_message_normal(to: str, message: str):

    url = (
        f"https://graph.facebook.com/v23.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        },
    }
    return None
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload,
        )

    print("WhatsApp API response:", response.status_code)
    print(response.text)

    response.raise_for_status()

    return response


async def send_whatsapp_message(to: str, message: str):
    # return "please uncomment send whatsapp message function"

    url = (
        f"https://graph.facebook.com/v23.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload,
        )

    print("WhatsApp API response:", response.status_code)
    print(response.text)

    response.raise_for_status()

    return response

async def send_status_message(
    shipment_status: ShipmentStatus,
    job_number: str,
    truck_number: str,
    driver_name: str,
    route_from: str,
    route_to: str,
    reply_number: str,
    whatsapp: bool,
) -> str:
    """
    Builds the WhatsApp message for a given shipment status and sends it
    through the existing /whatsapp route. Shared by both the manual
    endpoint and the automatic background workflow so the two never
    duplicate logic (or drift apart).
    """

    location_response = get_car_status(car_number=truck_number)

    current_location = None
    if location_response.get("result"):
        location_res = location_response['result'][0]
        longitude = str(location_res['logGisx']/ 1000000)
        latitude  = str(location_res['logGisy']/ 1000000)
        current_location = location_res['address']
        speed = str(round(location_res['logSpeed'], 2))
        # current_location = location_response["result"][0]["address"]
    if shipment_status in STATUS_FUNCTIONS:
        function = STATUS_FUNCTIONS[shipment_status]

        message = function(
            job_number=job_number,
            truck_number=truck_number,
            driver_name=driver_name,
            route_from=route_from,
            route_to=route_to,
            current_location=current_location,
        )
    elif shipment_status not in STATUS_FUNCTIONS:

        status_data = get_status(shipment_status.lower())
        # print("status_data", status_data)
        latest_updated = status_data['remarks']
        estimated_arrival = status_data['estimated_arrival']
        shipment_status = status_data['status']
            
        message = create_common_status(
            job_number=job_number,
            truck_number=truck_number,
            driver_name=driver_name,
            route_from=route_from,
            route_to=route_to,
            shipment_status= shipment_status,
            current_location=current_location,
            estimated_arrival= estimated_arrival,
            latest_updated=latest_updated
        )

    save_response = update_shipment_status(job_number = job_number,
                               truck_number = truck_number,
                               shipment_status= shipment_status,
                               message = message,
                               longitude = longitude,
                               latitude = latitude,
                               current_location = current_location,
                               speed = speed)
    
    if whatsapp:
        response = await send_whatsapp_message(to = '918281993386', message=message)
        print(response)
    return message



async def run_auto_in_transit_updates(truck: TruckWorkflowState):
    """
    Background task: every `interval` seconds, sends an "In Transit"
    update for this truck. Runs indefinitely until paused by an
    exception status, stopped by a terminal status, or cancelled at
    shutdown — it never advances to any other status on its own.
    """

    try:
        while True:
            await asyncio.sleep(truck.interval)

            try:
                await send_status_message(
                    shipment_status=ShipmentStatus.IN_TRANSIT,
                    job_number=truck.job_number,
                    truck_number=truck.truck_number,
                    driver_name=truck.driver_name,
                    route_from=truck.route_from,
                    route_to=truck.route_to,
                    reply_number=truck.reply_number,
                )
            except Exception as exc:
                # Don't let a transient send failure kill the loop —
                # log it and retry on the next interval.
                print(
                    f"[{truck.truck_number}] Failed to send automatic "
                    f"In Transit update: {exc}"
                )
                continue

            truck.next_update_at = (
                datetime.now(timezone.utc) + timedelta(seconds=truck.interval)
            )

            print(f"[{truck.truck_number}] Auto In Transit ping sent.")

    except asyncio.CancelledError:
        print(
            f"[{truck.truck_number}] Automatic In Transit task cancelled "
            f"(paused={truck.paused})."
        )
        raise

    finally:
        # Only drop the truck's record if it isn't paused — a paused
        # record must survive so we know to resume it later.
        async with trucks_lock:
            current = trucks.get(truck.truck_number)
            if current is truck and not truck.paused:
                trucks.pop(truck.truck_number, None)


async def handle_workflow_transition(payload: "StatusRequest"):
    """
    Starts, pauses, resumes, or stops the automatic "In Transit" ping for
    a truck based on the status just received. The WhatsApp message for
    the *requested* status itself is always sent by the caller before
    this runs — this only manages the background task bookkeeping.
    """

    truck_number = payload.truck_number
    status = payload.shipment_status

    async with trucks_lock:
        existing = trucks.get(truck_number)

        # --- Picked Up: send it, then start the recurring In Transit ping ---
        if status == ShipmentStatus.PICKED_UP:
            if existing and existing.task:
                existing.task.cancel()

            if not payload.interval:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "An 'interval' is required to start the automatic "
                        "In Transit updates when shipment_status is Picked Up."
                    ),
                )

            truck = TruckWorkflowState(
                truck_number=truck_number,
                job_number=payload.job_number,
                driver_name=payload.driver_name,
                route_from=payload.route_from,
                route_to=payload.route_to,
                reply_number=payload.reply_number,
                interval=payload.interval,
            )
            trucks[truck_number] = truck
            truck.task = asyncio.create_task(run_auto_in_transit_updates(truck))

        # --- Exception (Delayed / Customs Hold / Breakdown / Weather): pause ---
        elif status in EXCEPTION_STATUSES:
            if existing:
                existing.paused = True
                if existing.task:
                    existing.task.cancel()
                    existing.task = None
            # If there's no tracked truck, there's nothing to pause — the
            # exception message itself was already sent by the caller.

        # --- Terminal (Arrived at Delivery Hub / Delivered / Cancelled): stop for good ---
        elif status in TERMINAL_STATUSES:
            if existing:
                existing.paused = False
                if existing.task:
                    existing.task.cancel()
                trucks.pop(truck_number, None)

        # --- Any other manual status while paused = issue resolved -> resume ---
        elif existing and existing.paused:
            existing.paused = False
            existing.job_number = payload.job_number
            existing.driver_name = payload.driver_name
            existing.route_from = payload.route_from
            existing.route_to = payload.route_to
            existing.reply_number = payload.reply_number
            if payload.interval:
                existing.interval = payload.interval

            existing.next_update_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=existing.interval)
            )
            existing.task = asyncio.create_task(
                run_auto_in_transit_updates(existing)
            )

        # --- Anything else doesn't touch the automatic ping ---
        else:
            pass
