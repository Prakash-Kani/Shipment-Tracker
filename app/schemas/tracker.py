from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ShipmentStatus(str, Enum):
    BOOKED = "Booked / Shipment Created"
    AWAITING_PICKUP = "Awaiting Pickup"
    PICKED_UP = "Picked Up"
    IN_TRANSIT = "In Transit"
    AT_BORDER = "At Border"
    CUSTOMS_CLEARANCE = "Customs Clearance"
    CUSTOMS_HOLD = "Customs Hold"
    DELAYED = "Delayed"
    VEHICLE_BREAKDOWN = "Vehicle Breakdown"
    WEATHER_ROAD_DELAY = "Weather/Road Delay"
    ARRIVED_AT_DESTINATION_HUB = "Arrived at Destination Hub"
    ARRIVED_AT_DELIVERY_HUB = "Arrived at Delivery Hub"
    OUT_FOR_DELIVERY = "Out for Delivery"
    DELIVERY_ATTEMPTED = "Delivery Attempted"
    DELIVERY_EXCEPTION = "Delivery Exception"
    DELIVERED = "Delivered"
    CANCELLED_RETURNED = "Cancelled / Returned"


class StatusRequest(BaseModel):
    shipment_status: str = ShipmentStatus.IN_TRANSIT
    job_number: str
    truck_number: str
    driver_name: str
    route_from: str
    route_to: str
    reply_number: str
    whatsapp: bool
    interval: Optional[int] = Field(default=None, gt=0)
