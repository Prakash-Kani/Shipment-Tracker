import httpx
from app.core.config import settings
from twilio.rest import Client

WHATSAPP_TOKEN = settings.whatsapp_token
PHONE_NUMBER_ID = settings.phone_number_id
twilio_account_sid = settings.twilio_account_sid
twilio_auth_token = settings.twilio_auth_key

client = Client(
    twilio_account_sid,
    twilio_auth_token
)

async def send_whatsapp_message_meta(to: str, message: str):
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




TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"

import json

async def send_whatsapp_message(to: str, message: str):
    response = client.messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=f"whatsapp:{to}" if not to.startswith("whatsapp:") else to,
        body=message,
    )

    print("Twilio WhatsApp message SID:", response.sid)
    print("Status:", response.status)

    return response




async def send_whatsapp_message(to: str, message: str):
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"

    response = client.messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=to,
        content_sid="HX229f5a04fd0510ce1b071852155d3e75",
        content_variables=json.dumps({
            "1": f'\n\n{message}\n\n'
        }),
    )

    print("Twilio SID:", response.sid)
    print("Status:", response.status)

    return response
