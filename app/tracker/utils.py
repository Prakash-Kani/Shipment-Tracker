import requests


from app.core.config import settings
from app.schemas.tracker import ShipmentStatus


async def get_status_function(func):
    STATUS_FUNCTIONS = {
        ShipmentStatus.BOOKED.value: func.create_booked_status,
        ShipmentStatus.AWAITING_PICKUP.value: func.create_awaiting_pickup_status,
        ShipmentStatus.PICKED_UP.value: func.create_picked_up_status,
        ShipmentStatus.IN_TRANSIT.value: func.create_in_transit_status,
        ShipmentStatus.AT_BORDER.value: func.create_at_border_status,
        ShipmentStatus.CUSTOMS_CLEARANCE.value: func.create_customs_clearance_status,
        ShipmentStatus.CUSTOMS_HOLD.value: func.create_customs_hold_status,
        ShipmentStatus.DELAYED.value: func.create_in_transit_delayed_status,
        ShipmentStatus.VEHICLE_BREAKDOWN.value: func.create_truck_breakdown_status,
        ShipmentStatus.WEATHER_ROAD_DELAY.value: func.create_weather_delay_status,
        ShipmentStatus.ARRIVED_AT_DESTINATION_HUB.value: func.create_arrived_destination_hub_status,
        ShipmentStatus.ARRIVED_AT_PICKUP_HUB.value: func.create_arrived_pickup_hub_status,
        ShipmentStatus.ARRIVED_AT_DELIVERY_HUB.value: func.create_arrived_delivery_hub_status,
        ShipmentStatus.OUT_FOR_DELIVERY.value: func.create_out_for_delivery_status,
        ShipmentStatus.DELIVERY_ATTEMPTED.value: func.create_delivery_attempted_status,
        ShipmentStatus.DELIVERY_EXCEPTION.value: func.create_delivery_exception_status,
        ShipmentStatus.DELIVERED.value: func.create_delivered_status,
        ShipmentStatus.CANCELLED_RETURNED.value: func.create_cancelled_returned_status,
        ShipmentStatus.WAITING_FOR_PICKUP.value: func.create_waiting_for_pickup_status,
        ShipmentStatus.PENDING_DELIVERED.value: func.create_pending_delivery_status,
    }
    return STATUS_FUNCTIONS


async def get_whatsapp_last_24_chat_person():
    url = f"{settings.tcard_base_url}/Apicard/whatsapp_last_24_chat_person"

    try:
        response = requests.get(url, timeout=30)
        # response.raise_for_status()
        response = response.json()
        if 'record' in response:
            return [number['sender_wa_id'] for number in response['record']]
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"API request failed: {e}")
        return None

    except ValueError as e:
        print(f"Invalid JSON response: {e}")
        return None

    