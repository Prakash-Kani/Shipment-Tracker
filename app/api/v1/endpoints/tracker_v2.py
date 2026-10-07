from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Request
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse, PlainTextResponse, Response

from app.core.config import settings
from app.tracker.auto_update import  send_status_message, handle_workflow_transition
from app.schemas.tracker import *
from app.tracker.messanger import send_whatsapp_message
from app.tracker.direct_chat import process_shipment_bot
from app.tracker.auto_distance_update_v2 import (
    DistanceTrackingRequest,
    RouteMilestoneRequest,
    ManualAdvanceRequest,
    advance_milestone_manually,

    start_distance_tracking,
    handle_distance_workflow_transition,
    stop_distance_tracking,
    get_distance_tracking_state,
    shutdown_distance_tracking,
    build_route_milestones
)
import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import httpx
import logging
from logging.handlers import RotatingFileHandler

log_dir = "app/logs"
os.makedirs(log_dir, exist_ok=True)

log_file = os.path.join(log_dir, "whatsapp_webhook.log")
# Configure logger
logger = logging.getLogger("app/logs/whatsapp_webhook")
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(
    "app/logs/whatsapp_webhook.log",
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5
)

formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)

handler.setFormatter(formatter)
logger.addHandler(handler)



router = APIRouter()

VERIFY_TOKEN = settings.verify_token

# print(WHATSAPP_TOKEN)



@router.get("/")
async def verify_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
):
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK VERIFIED")
        return PlainTextResponse(content=challenge or "", status_code=200)

    return Response(status_code=403)


@router.post("/")
async def receive_webhook(request: Request):

    

    body = await request.json()

    timestamp = datetime.now(
                                ZoneInfo("Asia/Kuala_Lumpur")
                            ).strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"Webhook received {timestamp}")
    logger.info(json.dumps(body, indent=2))

    try:
        # WhatsApp webhook structure:
        # entry -> changes -> value -> messages

        entry = body.get("entry", [])

        for entry_item in entry:

            changes = entry_item.get("changes", [])

            for change in changes:

                value = change.get("value", {})

                messages = value.get("messages", [])

                for message in messages:

                    # Sender's WhatsApp number
                    sender = message.get("from")

                    # Message type
                    message_type = message.get("type")


                    logger.info(f"Sender: {sender}")
                    logger.info(f"Message type: {message_type}")

                    incoming_message = None


                    incoming_message = None

                    # ----------------------------------
                    # TEXT MESSAGE
                    # ----------------------------------

                    if message_type == "text":

                        incoming_message = (
                            message
                            .get("text", {})
                            .get("body", "")
                        )

                    # ----------------------------------
                    # INTERACTIVE MESSAGE
                    # ----------------------------------

                    elif message_type == "interactive":

                        interactive = message.get("interactive", {})
                        interactive_type = interactive.get("type")

                        logger.info(
                            f"Interactive type: {interactive_type}"
                        )

                        # List selection
                        if interactive_type == "list_reply":

                            list_reply = interactive.get(
                                "list_reply",
                                {}
                            )

                            incoming_message = list_reply.get(
                                "title",
                                ""
                            )

                            logger.info(
                                f"Selected List Item: {incoming_message}"
                            )

                        # Button selection
                        elif interactive_type == "button_reply":

                            button_reply = interactive.get(
                                "button_reply",
                                {}
                            )

                            incoming_message = button_reply.get(
                                "title",
                                ""
                            )

                            logger.info(
                                f"Selected Button: {incoming_message}"
                            )

                    # ----------------------------------
                    # PROCESS MESSAGE
                    # ----------------------------------

                    if incoming_message:

                        logger.info(
                            f"Incoming message: {incoming_message}"
                        )

                        reply = await process_shipment_bot(
                            reply_number=sender,
                            message=incoming_message
                        )

                        if sender and reply:

                            await send_whatsapp_message(
                                sender,
                                reply
                            )

                            logger.info(
                                f"Sending reply to {sender}: {reply}"
                            )

                    # Only process text messages
                    # if message_type == "text":

                    #     incoming_message = (
                    #         message
                    #         .get("text", {})
                    #         .get("body", "")
                    #     )

                        
                        # logger.info(
                        #             f"Incoming message: {incoming_message}"
                        #         )

                        # # ----------------------------------
                        # # Generate your reply here
                        # # ----------------------------------

                        # reply = await process_shipment_bot(reply_number = sender, message = incoming_message)

                        # # ----------------------------------
                        # # Send reply to WhatsApp
                        # # ----------------------------------

                        # if sender and reply:
                        #     await send_whatsapp_message(
                        #         sender,
                        #         reply
                        #     )
                        #     logger.info(
                        #                 f"Sending reply to {sender}: {reply}"
                        #             )

    except Exception as e:

        print("Error processing webhook:", e)
        logger.exception(
                        f"Error processing webhook: {e}"
                    )

        # Still return 200 so WhatsApp doesn't
        # repeatedly retry the webhook.
        return Response(status_code=200)

    return Response(status_code=200)



@router.post("/status/update")
async def create_in_transit_status_endpoint(
    payload: StatusRequest
):
    """
    Manually update a shipment's status, and drive the automatic
    "In Transit" ping:

      - Picked Up                                  -> starts a recurring
                                                        In Transit ping every
                                                        `interval` seconds
      - Delayed / Customs Hold / Breakdown / Weather -> pauses the ping
      - Any other manual status while paused        -> resumes the ping
      - Arrived at Delivery Hub / Delivered /
        Cancelled-Returned                          -> stops it for good
    """
    

    # Always send the message for the status that was actually requested
    # (unchanged behavior).
    message = await send_status_message(
        shipment_status=payload.shipment_status,
        job_number=payload.job_number,
        truck_number=payload.truck_number,
        driver_name=payload.driver_name,
        route_from=payload.route_from,
        route_to=payload.route_to,
        reply_number=payload.reply_number,
        whatsapp=payload.whatsapp
        
    )
    

    # Then update the automatic-workflow bookkeeping for this truck.
    await handle_workflow_transition(payload)

    return {
        "success": True,
        "data": message
    }


@router.post("/status/update/web")
async def create_in_transit_status_endpoint(
    payload: StatusRequest
):
    """
    Manually update a shipment's status, and drive the automatic
    "In Transit" ping:

      - Picked Up                                  -> starts a recurring
                                                        In Transit ping every
                                                        `interval` seconds
      - Delayed / Customs Hold / Breakdown / Weather -> pauses the ping
      - Any other manual status while paused        -> resumes the ping
      - Arrived at Delivery Hub / Delivered /
        Cancelled-Returned                          -> stops it for good
    """

    # Always send the message for the status that was actually requested
    # (unchanged behavior).
    message = await send_status_message(
        shipment_status=payload.shipment_status,
        job_number=payload.job_number,
        truck_number=payload.truck_number,
        driver_name=payload.driver_name,
        route_from=payload.route_from,
        route_to=payload.route_to,
        reply_number=payload.reply_number,
        whatsapp=payload.whatsapp
    )


    # Then update the automatic-workflow bookkeeping for this truck.
    await handle_workflow_transition(payload)

    return {
        "success": True,
        "data": message
    }





@router.post("/distance-tracking/start")
async def start(payload: DistanceTrackingRequest):
    """
    Starts (or restarts) distance-based tracking for ONE (truck_number,
    job_number) pair. A truck can have more than one job tracked at the
    same time - starting a new job_number for a truck that already has a
    DIFFERENT job running does not touch that other job; only calling this
    again with the SAME truck_number + job_number restarts that one job.
    """
    return await start_distance_tracking(payload)


@router.get("/distance-tracking")
async def state(truck_number: str, job_number: Optional[str] = Query(default=None)):
    """
    With ?job_number=...: that one job's tracking snapshot (404-shaped None
    if nothing is tracked under that truck+job).
    Without it: every job currently tracked for this truck, as
    {job_number: snapshot} - useful when you just want "what is this truck
    doing right now" without already knowing which job.
    """
    result = get_distance_tracking_state(truck_number, job_number)
    if job_number is not None and result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No tracker for truck_number={truck_number!r} job_number={job_number!r}.",
        )
    return result


@router.post("/distance-tracking/status")
async def manual_status(truck_number: str, status: ShipmentStatus, job_number: str = Query(...)):
    await handle_distance_workflow_transition(truck_number, job_number, status)
    return {"ok": True}


@router.delete("/distance-tracking")
async def stop(truck_number: str, job_number: str = Query(...)):
    await stop_distance_tracking(truck_number, job_number)
    return {"ok": True}


@router.post("/milestones/build")
async def build_milestones_route(payload: RouteMilestoneRequest):
    """
    Single-pickup/single-delivery route + border-checkpoint preview. For
    multiple pickup/delivery points, call /distance-tracking/start with
    pickup_points/delivery_points instead - it builds and starts tracking
    on the full multi-stop route in one step.
    """
    try:
        return await build_route_milestones(payload)
    except Exception as e:
        logger.exception("Error while building milestones")
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


@router.post("/distance-tracking/advance")
async def advance(
    truck_number: str,
    job_number: str = Query(...),
    payload: ManualAdvanceRequest = ManualAdvanceRequest(),
):
    return await advance_milestone_manually(truck_number, job_number, payload)