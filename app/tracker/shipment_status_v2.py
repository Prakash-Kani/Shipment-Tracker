
def create_arrived_pickup_hub_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has arrived at the pickup hub and is being processed for pickup.",
    estimated_arrival="Today",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_pickup": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "arrived_pickup_hub",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_waiting_for_pickup_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="The shipment is ready for pickup and is currently waiting for the assigned driver to collect it. The shipment will move to the next location after pickup.",
    estimated_pickup="Today",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_pickup,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "waiting_for_pickup",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_picked_up_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has been picked up from the origin location and is ready to begin transit.",
    estimated_arrival="As scheduled",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "picked_up",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_in_transit_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Truck is currently in transit and proceeding towards the destination as scheduled.",
    estimated_arrival="On schedule",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "shipment_status": "In Transit",
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "transit",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_in_transit_delayed_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment is currently in transit but has been delayed due to traffic congestion and extended border clearance time.",
    estimated_arrival="Delayed by 1 day",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "shipmentstatus": "In Transit – Delayed",
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "in_transit_delayed",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_truck_breakdown_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Truck has experienced a mechanical issue during transit. A service team is attending to the vehicle, and the estimated arrival time may be revised.",
    estimated_arrival="Delayed",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "in_transit_vehicle_issue",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_traffic_road_closure_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment is currently delayed due to heavy traffic/road restrictions. The truck will continue once the route is cleared.",
    estimated_arrival="Delayed",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "delayed_trafficroad_conditions",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_weather_delay_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment movement has been temporarily affected by adverse weather conditions. Transit will resume when conditions permit.",
    estimated_arrival="Delayed",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "delayed_weather_conditions",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_arrived_delivery_hub_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has arrived at the delivery hub and is being processed for final delivery.",
    estimated_arrival="Today",
    mode="Local Delivery",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "arrived_delivery_hub",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_pending_delivery_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="The shipment has reached the delivery area and is waiting to be delivered to the customer.",
    mode="Road Delivery",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "pending_delivery_",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_delivered_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has been successfully delivered to the consignee.",
    mode="Road Delivery",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "delivered",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }


def create_at_border_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has reached the border and is currently awaiting border processing before continuing towards the destination.",
    estimated_arrival="Subject to border processing",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "at_border",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_customs_hold_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment is temporarily on hold pending customs documentation/inspection. Further movement will resume once the issue is resolved.",
    estimated_arrival="Pending clearance",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "customs_hold",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_customs_clearance_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has arrived at the border and is currently undergoing customs clearance. Delivery will continue once clearance is completed.",
    estimated_arrival="Subject to clearance",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "customs_clearance_",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }

def create_cancelled_returned_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has been cancelled and is being returned to the origin location.",
    estimated_arrival="Return in progress",
    mode="Road Trucking",
    job_enc=""
):
    parameters = {
        "jobnumber": job_number,
        "trucknumber": truck_number,
        "drivername": driver_name,
        "route": f"{route_from} → {route_to}",
        "mode": mode,
        "currentlocation": current_location,
        "estimated_arrival": estimated_arrival,
        "latest_updated": latest_updated,
    }

    # Build the template components
    components = [
        {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "parameter_name": name,
                    "text": str(value),
                }
                for name, value in parameters.items()
            ],
        },
        {
            # Dynamic URL button: {{1}} = job_enc
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [
                {
                    "type": "text",
                    "text": str(job_enc),
                }
            ],
        },
    ]

    return {
        "messaging_product": "whatsapp",
        "to": "",
        "type": "template",
        "template": {
            "name": "cancelled_returned",
            "language": {
                "code": "en",
            },
            "components": components,
        },
    }



def create_common_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    shipment_status,
    current_location,
    latest_updated,
    estimated_arrival,
    mode="Road Trucking"
):
    return f"""*🔵 Shipment Status: {shipment_status}*
*Job Number:* {job_number}
*Truck Number:* {truck_number}
*Driver Name:* {driver_name}
*Route:* {route_from} → {route_to}
*Mode:* {mode}
*Current Location:*  {current_location}
*Estimated Arrival:*  {estimated_arrival}
*Latest Update:*
{latest_updated}
"""

def create_booked_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has been booked and the truck is scheduled for pickup as planned.",
    estimated_arrival="As scheduled",
    mode="Road Trucking"
):
    return f"""*🔵 Shipment Status: Booked / Shipment Created*
*Job Number:* {job_number}
*Truck Number:* {truck_number}
*Driver Name:* {driver_name}
*Route:* {route_from} → {route_to}
*Mode:* {mode}
*Current Location:*  {current_location}
*Estimated Arrival:*  {estimated_arrival}
*Latest Update:*
{latest_updated}
"""



def create_arrived_destination_hub_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has arrived at the destination hub and is being processed for final delivery.",
    estimated_arrival="Today",
    mode="Road Trucking"
):
    return f"""*🟣 Shipment Status: Arrived at Destination Hub*
*Job Number:* {job_number}
*Truck Number:* {truck_number}
*Driver Name:* {driver_name}
*Route:* {route_from} → {route_to}
*Mode:* {mode}
*Current Location:*  {current_location}
*Estimated Arrival:*  {estimated_arrival}
*Latest Update:*
{latest_updated}
"""


def create_out_for_delivery_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has been dispatched from the destination hub and is currently out for delivery.",
    estimated_arrival="Today",
    mode="Local Delivery"
):
    return f"""*🟢 Shipment Status: Out for Delivery*
*Job Number:* {job_number}
*Truck Number:* {truck_number}
*Driver Name:* {driver_name}
*Route:* {route_from} → {route_to}
*Mode:* {mode}
*Current Location:*  {current_location}
*Estimated Arrival:*  {estimated_arrival}
*Latest Update:*
{latest_updated}
"""




def create_transshipment_status(
    job_number,
    previous_truck,
    new_truck,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment has arrived at the transfer hub and is being transferred to another vehicle for the next leg of transportation.",
    estimated_arrival="On schedule",
    mode="Road Trucking"
):
    return f"""*🔵 Shipment Status: Transshipment in Progress*
*Job Number:* {job_number}
*Previous Truck:* {previous_truck}
*New Truck:* {new_truck}
*Driver Name:* {driver_name}
*Route:* {route_from} → {route_to}
*Mode:* {mode}
*Current Location:*  {current_location}
*Estimated Arrival:*  {estimated_arrival}
*Latest Update:*
{latest_updated}
"""


def create_awaiting_pickup_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Shipment is ready for pickup and is awaiting collection by the assigned carrier.",
    estimated_pickup="Today",
    mode="Road Trucking"
):
    return f"""*⚪ Shipment Status: Awaiting Pickup*
*Job Number:* {job_number}
*Truck Number:* {truck_number}
*Driver Name:* {driver_name}
*Route:* {route_from} → {route_to}
*Mode:* {mode}
*Current Location:*  {current_location}
*Estimated Pickup:* {estimated_pickup}
*Latest Update:*
{latest_updated}
"""



def create_delivery_attempted_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Delivery was attempted but could not be completed. Another delivery attempt will be scheduled.",
    estimated_arrival="Next business day",
    mode="Local Delivery"
):
    return f"""*🟠 Shipment Status: Delivery Attempted*
*Job Number:* {job_number}
*Truck Number:* {truck_number}
*Driver Name:* {driver_name}
*Route:* {route_from} → {route_to}
*Mode:* {mode}
*Current Location:*  {current_location}
*Estimated Arrival:*  {estimated_arrival}
*Latest Update:*
{latest_updated}
"""


def create_delivery_exception_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    latest_updated="Delivery could not be completed due to an unexpected issue. The shipment is being reviewed and the next delivery action will be updated shortly.",
    estimated_arrival="To be confirmed",
    mode="Road Delivery"
):
    return f"""*🔴 Shipment Status: Delivery Exception*
*Job Number:* {job_number}
*Truck Number:* {truck_number}
*Driver Name:* {driver_name}
*Route:* {route_from} → {route_to}
*Mode:* {mode}
*Current Location:*  {current_location}
*Estimated Arrival:*  {estimated_arrival}
*Latest Update:*
{latest_updated}
"""



def create_delivery_completed_status(
    job_number,
    truck_number,
    driver_name,
    route_from,
    route_to,
    current_location,
    delivery_time,
    latest_updated="Shipment has been successfully delivered to the consignee and the delivery has been completed.",
    mode="Road Delivery"
):
    return f"""*✅ Shipment Status: Delivery Completed*
*Job Number:* {job_number}
*Truck Number:* {truck_number}
*Driver Name:* {driver_name}
*Route:* {route_from} → {route_to}
*Mode:* {mode}
*Delivered Location:* {current_location}
*Delivery Time:* {delivery_time}
*Latest Update:*
{latest_updated}
"""

