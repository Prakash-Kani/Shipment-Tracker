from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Request
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse, PlainTextResponse, Response

from app.core.config import settings
from app.tracker.auto_update import  send_status_message, handle_workflow_transition
from app.schemas.tracker import *
from app.tracker.messanger import send_whatsapp_message
from app.tracker.direct_chat import process_shipment_bot
import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import httpx
import logging
from logging.handlers import RotatingFileHandler

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


