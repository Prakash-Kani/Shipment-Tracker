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



async def send_whatsapp_template_with_params(
    to: str,
    template_name: str,
    parameters: list,
    language_code: str = "en"
):
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
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code
            },
            "components": [
                {
                    "type": "body",
                    "parameters": parameters
                }
            ]
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload,
        )

    print("WhatsApp Template API response:", response.status_code)
    print(response.text)

    response.raise_for_status()

    return response

async def send_job_list(
    to: str,
    job_numbers: list[str]
):
    url = (
        f"https://graph.facebook.com/v25.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    rows = []

    for job_number in job_numbers:
        rows.append({
            "id": job_number,
            "title": job_number
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",

            

            "body": {
                "text": (
                    "You can check your shipment status "
                    "by selecting an available Job Number."
                    "Kindly select your *Job Number* from the options below:"
                )
            },

            

            "action": {
                "button": "Select Job Number",
                "sections": [
                    {
                        "title": "Available Jobs",
                        "rows": rows
                    }
                ]
            }
        }
    }

    # print(json.dumps(payload, indent=2))

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload
        )

    print("WhatsApp API response:", response.status_code)
    print(response.text)

    response.raise_for_status()

    return response


import json
import httpx


async def send_whatsapp_interactive(
    to: str,
    values: list[str],
    interactive_type: str = "list",
    body_text: str = (
        "Welcome to GFS Shipment Tracker.\n\n"
        "You can check your shipment status "
        "by selecting an available Job Number."
    ),
    
    button_text: str = "Select Job Number",
    list_title: str = "Available Jobs"
):
    """
    Send dynamic WhatsApp interactive buttons or list.

    interactive_type:
        "button" -> maximum 3 reply buttons
        "list"   -> dynamic list

    values:
        List of dynamic values, e.g.
        [
            "GFS/2215T/09/26",
            "GFS/2216T/09/26",
            "GFS/2217T/09/26"
        ]
    """

    if not values:
        raise ValueError("values cannot be empty")

    if interactive_type not in ["button", "list"]:
        raise ValueError(
            "interactive_type must be 'button' or 'list'"
        )

    # --------------------------------------------------
    # WhatsApp API URL
    # --------------------------------------------------

    url = (
        f"https://graph.facebook.com/v25.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    # --------------------------------------------------
    # BUTTON TYPE
    # --------------------------------------------------

    if interactive_type == "button":

        # WhatsApp allows only 3 reply buttons
        if len(values) > 3:
            raise ValueError(
                "Button type supports a maximum of 3 values. "
                "Use interactive_type='list' for more values."
            )

        buttons = []

        for index, value in enumerate(values):

            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"option_{index + 1}",
                    "title": str(value)
                }
            })

        interactive = {
            "type": "button",

            "body": {
                "text": body_text
            },

            "action": {
                "buttons": buttons
            }
        }

        # Header
       
    # --------------------------------------------------
    # LIST TYPE
    # --------------------------------------------------

    else:

        rows = []

        for index, value in enumerate(values):

            rows.append({
                "id": f"option_{index + 1}",
                "title": str(value)
            })

        interactive = {
            "type": "list",

            "body": {
                "text": body_text
            },

            "action": {
                "button": button_text,
                "sections": [
                    {
                        "title": list_title,
                        "rows": rows
                    }
                ]
            }
        }

    # --------------------------------------------------
    # FINAL PAYLOAD
    # --------------------------------------------------

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": interactive
    }

    # --------------------------------------------------
    # LOG
    # --------------------------------------------------

    print("\n========== WHATSAPP INTERACTIVE ==========")
    print("To:", to)
    print("Type:", interactive_type)
    print("Values:", values)
    print("Payload:")
    print(json.dumps(payload, indent=2))

    # --------------------------------------------------
    # SEND
    # --------------------------------------------------

    async with httpx.AsyncClient() as client:

        response = await client.post(
            url,
            headers=headers,
            json=payload
        )

    print("\nWhatsApp API response:")
    print("Status:", response.status_code)
    print("Response:", response.text)

    response.raise_for_status()

    return response

