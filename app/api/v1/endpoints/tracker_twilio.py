from fastapi import APIRouter, Depends, Form, HTTPException, status, Query, Path, Request
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse, PlainTextResponse, Response

from app.core.config import settings
from app.tracker_twilio.auto_update import send_status_message, handle_workflow_transition
from app.schemas.tracker import *
from app.tracker_twilio.messanger import send_whatsapp_message
from app.tracker_twilio.direct_chat import process_shipment_bot

from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import os
import json
from datetime import datetime, timezone
import threading

router = APIRouter()

VERIFY_TOKEN = settings.verify_token

twilio_account_sid = settings.twilio_account_sid
twilio_auth_token = settings.twilio_auth_key

twilio_client = Client(
    twilio_account_sid,
    twilio_auth_token
)

# print(WHATSAPP_TOKEN)



conversation_context = {}
conversation_context_limit = 6

# Protect the shared dictionary when multiple requests arrive
conversation_lock = threading.Lock()

def store_chat(number: str, message: str, role: str):
    """
    Store a user or assistant message in conversation history.
    """

    with conversation_lock:

        if number in conversation_context:
            cur_chat = conversation_context[number]

            if len(cur_chat) >= conversation_context_limit:
                cur_chat.pop(0)

            cur_chat.append({
                "role": role,
                "content": message
            })

        else:
            conversation_context[number] = [
                {
                    "role": role,
                    "content": message
                }
            ]


def get_chat(number: str):
    """
    Return the conversation history for a phone number.
    """

    with conversation_lock:
        return conversation_context.get(number, []).copy()




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

    print(request)

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



@router.post("/whatsapp/webhook1")
async def whatsapp_update_shipment_status(
    From: str = Form(...),
    Body: str = Form(...),
    ShipmentUpdate: Optional[str] = Form(None),
    Status: Optional[str] = Form(None),
):
    
    """
    Incoming WhatsApp message endpoint.

    Returns a TwiML response that Twilio can use
    to reply to the WhatsApp user.
    """
    reply_number = From
    message = Body



    print("msg:", message)

    # Store user message
    store_chat(
        reply_number,
        message,
        "user"
    )

    if ShipmentUpdate == None and Status == None:

        assistant_message = process_shipment_bot(reply_number, message)

        print("ans:", assistant_message)

    else:
        assistant_message = ShipmentUpdate
        # assistant_message = 'working'
        

    # Store LLM response
    store_chat(
        reply_number,
        assistant_message,
        "assistant"
    )

    # Create Twilio response
    resp = MessagingResponse()
    resp.message(assistant_message)

    # Return TwiML XML
    return Response(
        content=str(resp),
        media_type="application/xml"
    )


@router.post("/whatsapp/webhook")
async def whatsapp_update_shipment_status(
    From: str = Form(...),
    Body: str = Form(...),
    ShipmentUpdate: Optional[str] = Form(None),
    Status: Optional[str] = Form(None),
):
    print("From:", From)
    print("Body:", Body)
    print("ShipmentUpdate:", ShipmentUpdate)
    print("Status:", Status)

    # Store incoming message
    store_chat(
        From,
        Body,
        "user"
    )

    # Generate reply
    if ShipmentUpdate is None and Status is None:
        assistant_message = process_shipment_bot(From, Body)
    else:
        assistant_message = ShipmentUpdate

    # Make absolutely sure we have text
    assistant_message = str(assistant_message or "Sorry, I couldn't generate a response.")

    print("ANSWER:", repr(assistant_message))

    # Store response
    store_chat(
        From,
        assistant_message,
        "assistant"
    )

    # Generate TwiML
    resp = MessagingResponse()
    resp.message(assistant_message)

    twiml = str(resp)

    print("TWIML:")
    print(twiml)

    return Response(
        content=twiml,
        media_type="text/xml",
        status_code=200
    )

