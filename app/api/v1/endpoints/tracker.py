from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Request
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse, PlainTextResponse, Response

from app.core.config import settings
from app.tracker.auto_update import send_whatsapp_message, send_status_message, handle_workflow_transition
from app.schemas.tracker import *

import os
import json
from datetime import datetime, timezone
import httpx




router = APIRouter()

VERIFY_TOKEN = settings.verify_token
WHATSAPP_TOKEN = settings.whatsapp_token
PHONE_NUMBER_ID = settings.phone_number_id
# print(WHATSAPP_TOKEN)

async def send_whatsapp_message(to: str, message: str):

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
# async def receive_webhook(request: Request):
#     timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

#     body = await request.json()

#     print(f"\n\nWebhook received {timestamp}\n")
#     print(json.dumps(body, indent=2))

#     return Response(status_code=200)


async def receive_webhook(request: Request):

    body = await request.json()

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(f"\n\nWebhook received {timestamp}\n")
    print(json.dumps(body, indent=2))

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

                    print("Sender:", sender)
                    print("Message type:", message_type)

                    # Only process text messages
                    if message_type == "text":

                        incoming_message = (
                            message
                            .get("text", {})
                            .get("body", "")
                        )

                        print(
                            "Incoming message:",
                            incoming_message
                        )

                        # ----------------------------------
                        # Generate your reply here
                        # ----------------------------------

                        reply = (
                            f"You said: {incoming_message}"
                        )

                        # ----------------------------------
                        # Send reply to WhatsApp
                        # ----------------------------------

                        if sender:
                            sender = '918281993386'
                            await send_whatsapp_message(
                                sender,
                                reply
                            )

    except Exception as e:

        print("Error processing webhook:", e)

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


