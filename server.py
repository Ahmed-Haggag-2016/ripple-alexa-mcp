"""Ripple disruption-recovery demo with a stateful mock-services MCP server."""

from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

APP_DIR = Path(__file__).resolve().parent
FLIGHT_ID = "AA417"


def _initial_state() -> dict:
    return {
        "scenario": "flight_delay",
        "flight": {
            "flight_id": FLIGHT_ID,
            "airline": "Northstar Air",
            "route": "SFO → SEA",
            "scheduled_arrival": "6:10 PM",
            "delay_minutes": 120,
            "updated_arrival": "8:10 PM",
            "status": "Delayed",
        },
        "constraints": [
            {"id": "keep-dinner", "text": "Keep dinner; do not cancel it.", "protected": True},
            {"id": "ask-before-message", "text": "Ask before sending any message.", "protected": True},
            {"id": "delivery-fallback", "text": "Reschedule groceries rather than leave them unattended.", "protected": False},
        ],
        "calendar": [
            {
                "id": "dinner",
                "title": "Dinner with Maya",
                "time": "7:00 PM",
                "kind": "reservation",
                "protected": True,
                "status": "unchanged",
            },
            {
                "id": "pickup",
                "title": "Maya picks you up at the airport",
                "time": "6:10 PM",
                "kind": "pickup",
                "protected": False,
                "status": "unchanged",
            },
            {
                "id": "dinner-reminder",
                "title": "Leave for dinner",
                "time": "6:15 PM",
                "kind": "reminder",
                "protected": False,
                "status": "unchanged",
            },
        ],
        "delivery": {
            "id": "groceries",
            "title": "Grocery delivery",
            "window": "7:00–9:00 PM tonight",
            "alternatives": ["Tomorrow, 6:00–8:00 PM"],
            "status": "scheduled",
            "provider_available": True,
            "backup_provider_available": True,
            "provider": "FreshCart",
        },
        "service_availability": {
            "travel": True,
            "calendar": True,
            "delivery": True,
            "reservations": True,
            "messaging": True,
        },
        "alternatives": [
            {"time": "8:45 PM", "venue": "Cedar Table", "availability": "Available"},
            {"time": "9:15 PM", "venue": "Cedar Table", "availability": "Available"},
        ],
        "pickup": {
            "child_name": "Sam",
            "school": "Maple Grove School",
            "commute": "Northstar train",
            "scheduled_arrival": "5:40 PM",
            "delay_minutes": 40,
            "expected_arrival": "6:20 PM",
            "deadline": "6:00 PM",
            "max_cost": 25,
            "options": [],
            "selected_option_id": None,
            "status": "needs_coverage",
        },
        "plans": {},
        "actions": {},
    }


STATE = _initial_state()

INSTRUCTIONS = """\
Ripple is a voice-first disruption recovery coordinator. It uses mock calendar,
travel, delivery, reservation and messaging integrations in this demo.
Discover tools before use. Read the user's constraints and relevant events
before proposing changes. Never cancel a protected commitment. Draft messages
but never send without explicit user approval. Never report an action as
completed until verify_action_status confirms its result. The demo integrations
do not contact real people or change real accounts.
"""

mcp = FastMCP(
    name="Ripple",
    instructions=INSTRUCTIONS,
    host=os.environ.get("DOMINOMIND_HOST", "127.0.0.1"),
    port=int(os.environ.get("DOMINOMIND_PORT", "8000")),
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            *[value.strip() for value in os.environ.get("DOMINOMIND_ALLOWED_HOSTS", "").split(",") if value.strip()],
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            *[value.strip() for value in os.environ.get("DOMINOMIND_ALLOWED_ORIGINS", "").split(",") if value.strip()],
        ],
    ),
)


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False)


def _arrival_time(delay_minutes: int) -> str:
    arrival = datetime(2025, 1, 1, 18, 10) + timedelta(minutes=delay_minutes)
    return arrival.strftime("%I:%M %p").lstrip("0")


def _pickup_time(delay_minutes: int) -> str:
    arrival = datetime(2025, 1, 1, 17, 40) + timedelta(minutes=delay_minutes)
    return arrival.strftime("%I:%M %p").lstrip("0")


def _minutes_after_five(time_label: str) -> int:
    parsed = datetime.strptime(time_label, "%I:%M %p")
    return (parsed.hour * 60 + parsed.minute) - (17 * 60)


@mcp.tool()
def get_travel_status(flight_id: str = FLIGHT_ID, delay_minutes: int | None = None) -> str:
    """Retrieve the simulated flight status and record a newly reported delay."""
    if flight_id != FLIGHT_ID:
        return _json({"error": "This simulation only contains flight AA417."})
    if delay_minutes is not None:
        if not 0 <= delay_minutes <= 360:
            return _json({"error": "Delay must be between 0 and 360 minutes."})
        flight = STATE["flight"]
        flight["delay_minutes"] = delay_minutes
        flight["updated_arrival"] = _arrival_time(delay_minutes)
        flight["status"] = "On time" if delay_minutes == 0 else "Delayed"
    return _json(deepcopy(STATE["flight"]))


@mcp.tool()
def get_user_constraints() -> str:
    """Read the user's mock preferences and protected commitments."""
    return _json(deepcopy(STATE["constraints"]))


@mcp.tool()
def get_calendar_events() -> str:
    """Read relevant mock calendar events for tonight."""
    return _json(deepcopy(STATE["calendar"]))


@mcp.tool()
def get_delivery_status() -> str:
    """Check the simulated grocery delivery window and alternatives."""
    return _json(deepcopy(STATE["delivery"]))


@mcp.tool()
def find_alternatives(kind: str = "dinner") -> str:
    """Find mock alternatives for a dinner reservation or delivery window."""
    if kind == "dinner":
        return _json(deepcopy(STATE["alternatives"]))
    if kind == "delivery":
        return _json(deepcopy(STATE["delivery"]["alternatives"]))
    return _json({"error": "Choose dinner or delivery alternatives."})


def _configure_scenario(
    scenario: str,
    delay_minutes: int = 120,
    keep_dinner: bool = True,
    delivery_provider_available: bool = True,
    delivery_backup_available: bool = True,
    dinner_option_index: int = 0,
    travel_available: bool = True,
    calendar_available: bool = True,
    delivery_available: bool = True,
    reservations_available: bool = True,
    messaging_available: bool = True,
) -> dict:
    global STATE
    supported = {"pickup_risk", "flight_delay", "flight_cancelled", "delivery_disruption", "meeting_overrun"}
    if scenario not in supported:
        return {"error": "Choose pickup_risk, flight_delay, flight_cancelled, delivery_disruption, or meeting_overrun."}
    if not isinstance(delay_minutes, int) or not 0 <= delay_minutes <= 360:
        return {"error": "Delay must be between 0 and 360 minutes."}
    availability = {
        "travel": travel_available,
        "calendar": calendar_available,
        "delivery": delivery_available,
        "reservations": reservations_available,
        "messaging": messaging_available,
    }
    if not isinstance(keep_dinner, bool) or not isinstance(delivery_provider_available, bool):
        return {"error": "Preference and provider availability settings must be boolean."}
    if not isinstance(delivery_backup_available, bool):
        return {"error": "Backup provider availability must be boolean."}
    if not all(isinstance(value, bool) for value in availability.values()):
        return {"error": "Mock service availability settings must be boolean."}
    if dinner_option_index not in (0, 1):
        return {"error": "Choose one of the two available dinner alternatives."}

    STATE = _initial_state()
    STATE["scenario"] = scenario
    STATE["flight"]["delay_minutes"] = delay_minutes
    STATE["flight"]["updated_arrival"] = _arrival_time(delay_minutes)
    STATE["flight"]["status"] = "On time" if delay_minutes == 0 else "Delayed"
    STATE["constraints"][0]["protected"] = keep_dinner
    STATE["constraints"][0]["text"] = (
        "Keep dinner; do not cancel it." if keep_dinner else "Dinner can be moved or cancelled if needed."
    )
    STATE["delivery"]["provider_available"] = delivery_provider_available
    STATE["delivery"]["backup_provider_available"] = delivery_backup_available
    STATE["service_availability"] = availability
    STATE["alternatives"][0], STATE["alternatives"][dinner_option_index] = (
        STATE["alternatives"][dinner_option_index],
        STATE["alternatives"][0],
    )

    if scenario == "pickup_risk":
        STATE["pickup"]["delay_minutes"] = delay_minutes
        STATE["pickup"]["expected_arrival"] = _pickup_time(delay_minutes)
        STATE["pickup"]["deadline"] = "6:00 PM"
        STATE["pickup"]["options"] = []
        STATE["pickup"]["selected_option_id"] = None
        STATE["constraints"] = [
            {
                "id": "pickup-deadline",
                "text": "Sam must be collected by 6:00 PM.",
                "protected": True,
            },
            {
                "id": "pickup-budget",
                "text": "Do not exceed the user's transport budget.",
                "protected": True,
            },
            {
                "id": "contact-approval",
                "text": "Ask before contacting the approved pickup backup.",
                "protected": True,
            },
        ]
        STATE["calendar"].append(
            {
                "id": "school-pickup",
                "title": "Pick up Sam at Maple Grove School",
                "time": STATE["pickup"]["deadline"],
                "kind": "protected_pickup",
                "protected": True,
                "status": "needs_coverage",
            }
        )
    elif scenario == "flight_cancelled":
        STATE["flight"]["status"] = "Cancelled"
        STATE["flight"]["updated_arrival"] = "No arrival scheduled"
        STATE["calendar"].append(
            {
                "id": "arrival-reminder",
                "title": "Airport pickup",
                "time": "6:10 PM",
                "kind": "reminder",
                "protected": False,
                "status": "unchanged",
            }
        )
    elif scenario == "delivery_disruption":
        STATE["delivery"]["status"] = "delayed"
        STATE["delivery"]["window"] = "9:30–11:00 PM tonight"
        STATE["calendar"].append(
            {
                "id": "delivery-reminder",
                "title": "Bring groceries inside",
                "time": "7:00 PM",
                "kind": "reminder",
                "protected": False,
                "status": "unchanged",
            }
        )
    elif scenario == "meeting_overrun":
        STATE["calendar"].append(
            {
                "id": "project-meeting",
                "title": "Project meeting (running late)",
                "time": "5:30–7:30 PM",
                "kind": "meeting",
                "protected": False,
                "status": "running_late",
            }
        )
    return {"status": "configured", "scenario": scenario}


@mcp.tool()
def set_demo_scenario(scenario: str) -> str:
    """Select one of the available mock disruptions and restore its starting state."""
    result = _configure_scenario(scenario, delay_minutes=40 if scenario == "pickup_risk" else 120)
    return _json(result)


@mcp.tool()
def prepare_recovery_context(
    scenario: str = "flight_delay",
    delay_minutes: int = 120,
    keep_dinner: bool = True,
    delivery_provider_available: bool = True,
    delivery_backup_available: bool = True,
    dinner_option_index: int = 0,
    travel_available: bool = True,
    calendar_available: bool = True,
    delivery_available: bool = True,
    reservations_available: bool = True,
    messaging_available: bool = True,
) -> str:
    """Configure the editable demo inputs and return all service data in one MCP call."""
    result = _configure_scenario(
        scenario,
        delay_minutes,
        keep_dinner,
        delivery_provider_available,
        delivery_backup_available,
        dinner_option_index,
        travel_available,
        calendar_available,
        delivery_available,
        reservations_available,
        messaging_available,
    )
    if "error" in result:
        return _json(result)
    return _json(
        {
            **result,
            "flight": deepcopy(STATE["flight"]) if STATE["service_availability"]["travel"] else None,
            "constraints": deepcopy(STATE["constraints"]),
            "calendar": deepcopy(STATE["calendar"]) if STATE["service_availability"]["calendar"] else None,
            "delivery": deepcopy(STATE["delivery"]) if STATE["service_availability"]["delivery"] else None,
            "dinner_alternatives": (
                deepcopy(STATE["alternatives"]) if STATE["service_availability"]["reservations"] else None
            ),
            "pickup": deepcopy(STATE["pickup"]) if scenario == "pickup_risk" else None,
            "service_availability": deepcopy(STATE["service_availability"]),
        }
    )


@mcp.tool()
def find_pickup_options(
    deadline: str = "6:00 PM",
    max_cost: int = 25,
    objective: str = "lowest_cost",
) -> str:
    """Compare mock pickup options and recommend one that matches the user's priority."""
    if STATE["scenario"] != "pickup_risk":
        return _json({"error": "Pickup options are only available for the pickup_risk scenario."})
    if deadline not in {"5:45 PM", "6:00 PM", "6:15 PM"}:
        return _json({"error": "Choose a pickup deadline of 5:45 PM, 6:00 PM, or 6:15 PM."})
    if not isinstance(max_cost, int) or max_cost not in {0, 10, 25, 50}:
        return _json({"error": "Choose a maximum transport budget of $0, $10, $25, or $50."})
    if objective not in {"lowest_cost", "arrival_buffer"}:
        return _json({"error": "Choose lowest_cost or arrival_buffer as the pickup objective."})
    STATE["pickup"]["deadline"] = deadline
    STATE["pickup"]["max_cost"] = max_cost
    for constraint in STATE["constraints"]:
        if constraint["id"] == "pickup-deadline":
            constraint["text"] = f"Sam must be collected by {deadline}."
        elif constraint["id"] == "pickup-budget":
            constraint["text"] = f"Do not exceed the ${max_cost} transport budget."
    pickup_event = next(
        (event for event in STATE["calendar"] if event["id"] == "school-pickup"),
        None,
    )
    if pickup_event:
        pickup_event["time"] = deadline
    deadline_minutes = _minutes_after_five(deadline)
    commute_minutes = _minutes_after_five(STATE["pickup"]["expected_arrival"])
    options = [
        {
            "id": "trusted_contact",
            "title": "Ask Jordan, your approved pickup backup",
            "provider": "Jordan · approved contact",
            "arrives_at": "5:57 PM",
            "cost": 0,
            "service": "Messaging",
            "detail": "Jordan has confirmed they can collect Sam. Ripple will only send pickup details after you approve.",
        },
        {
            "id": "rideshare",
            "title": "Book a CityRide pickup",
            "provider": "CityRide · mock transport",
            "arrives_at": "5:50 PM",
            "cost": 18,
            "service": "Transport",
            "detail": "Mock quote: $18. No ride is requested until you approve.",
        },
    ]
    service_available = {
        "Messaging": STATE["service_availability"]["messaging"],
        "Transport": STATE["service_availability"]["travel"],
    }
    for option in options:
        minutes_before_deadline = deadline_minutes - _minutes_after_five(option["arrives_at"])
        option["minutes_before_deadline"] = minutes_before_deadline
        option["meets_deadline"] = minutes_before_deadline >= 0
        option["within_budget"] = option["cost"] <= max_cost
        option["service_available"] = service_available[option["service"]]
        option["eligible"] = (
            option["meets_deadline"] and option["within_budget"] and option["service_available"]
        )
    STATE["pickup"]["options"] = options
    STATE["pickup"]["selected_option_id"] = None
    STATE["pickup"]["status"] = (
        "at_risk" if commute_minutes > deadline_minutes else "on_track"
    )
    minutes_late = max(0, commute_minutes - deadline_minutes)
    priority = "critical" if minutes_late >= 30 else "high" if minutes_late > 0 else "watch"
    eligible = [option for option in options if option["eligible"]]
    lowest_cost = min(
        eligible,
        key=lambda option: (option["cost"], -option["minutes_before_deadline"], option["arrives_at"]),
        default=None,
    )
    largest_buffer = min(
        eligible,
        key=lambda option: (-option["minutes_before_deadline"], option["cost"], option["arrives_at"]),
        default=None,
    )
    tradeoff = None
    if lowest_cost and largest_buffer and lowest_cost["id"] != largest_buffer["id"]:
        extra_cost = largest_buffer["cost"] - lowest_cost["cost"]
        extra_buffer = largest_buffer["minutes_before_deadline"] - lowest_cost["minutes_before_deadline"]
        if extra_buffer > 0 and extra_cost > 0:
            tradeoff = (
                f"Pay ${extra_cost} more for {largest_buffer['title']} to get "
                f"{extra_buffer} extra minutes of buffer versus {lowest_cost['title']}."
            )
        elif extra_buffer > 0:
            tradeoff = (
                f"{largest_buffer['title']} gives you {extra_buffer} extra minutes "
                f"of buffer at the same cost as {lowest_cost['title']}."
            )
        elif extra_cost:
            tradeoff = (
                f"{largest_buffer['title']} costs ${extra_cost} more than "
                f"{lowest_cost['title']} with no added arrival buffer."
            )
        else:
            tradeoff = "These eligible options have the same cost and deadline buffer."
    if objective == "lowest_cost":
        recommended = lowest_cost
        reason = (
            f"{recommended['title']} is the lowest-cost eligible option at "
            f"${recommended['cost']} and arrives at {recommended['arrives_at']}, "
            f"{recommended['minutes_before_deadline']} minutes before the deadline."
            if recommended
            else "No option meets the deadline, budget, and service-availability checks."
        )
    else:
        recommended = largest_buffer
        reason = (
            f"{recommended['title']} gives you the largest arrival buffer: "
            f"{recommended['minutes_before_deadline']} minutes before the deadline, "
            f"at ${recommended['cost']}."
            if recommended
            else "No option meets the deadline, budget, and service-availability checks."
        )
    return _json(
        {
            "scenario": "pickup_risk",
            "commute": STATE["pickup"]["commute"],
            "expected_arrival": STATE["pickup"]["expected_arrival"],
            "deadline": deadline,
            "minutes_late": minutes_late,
            "priority": priority,
            "max_cost": max_cost,
            "recommendation": {
                "objective": objective,
                "option_id": recommended["id"] if recommended else None,
                "reason": reason,
                "tradeoff": tradeoff,
            },
            "options": deepcopy(options),
            "constraints": deepcopy(STATE["constraints"]),
        }
    )


@mcp.tool()
def propose_recovery_plan(
    delay_minutes: int = 120,
    pickup_option_id: str | None = None,
) -> str:
    """Build a scenario-specific recovery plan from the selected mock disruption."""
    if not isinstance(delay_minutes, int) or not 0 <= delay_minutes <= 360:
        return _json({"error": "Delay must be between 0 and 360 minutes."})
    scenario = STATE["scenario"]
    if scenario == "flight_delay" and STATE["flight"]["delay_minutes"] != delay_minutes:
        return _json({"error": "Read and update the flight status before proposing a plan."})

    pickup_priority = None
    blockers = []
    if scenario == "pickup_risk":
        options = STATE["pickup"]["options"]
        selected = next((option for option in options if option["id"] == pickup_option_id), None)
        actions = []
        if not selected:
            blockers.append("Choose a pickup option from the latest MCP comparison before preparing an approval request.")
        elif not selected["eligible"]:
            reasons = []
            if not selected["meets_deadline"]:
                reasons.append(f"it arrives after the {STATE['pickup']['deadline']} pickup deadline")
            if not selected["within_budget"]:
                reasons.append(f"its ${selected['cost']} cost exceeds the ${STATE['pickup']['max_cost']} budget")
            if not selected["service_available"]:
                reasons.append(f"the {selected['service']} MCP module is offline")
            blockers.append(f"{selected['title']} is not eligible because {' and '.join(reasons)}.")
        else:
            is_contact = selected["id"] == "trusted_contact"
            actions = [
                {
                    "id": "pickup-notify-contact" if is_contact else "pickup-book-transport",
                    "service": selected["service"],
                    "title": (
                        "Send Sam’s pickup details to Jordan"
                        if is_contact
                        else "Request the CityRide pickup"
                    ),
                    "detail": (
                        f"Jordan is the pre-confirmed backup and is estimated to arrive at {selected['arrives_at']}. "
                        "Approve only if you want the mock messaging service to send pickup details."
                        if is_contact
                        else f"Mock quote ${selected['cost']}; estimated pickup arrival {selected['arrives_at']}. "
                        "Approve only if you want to place this simulated ride request."
                    ),
                    "impact": (
                        "The mock message will be sent only after approval. Sending details does not verify the physical handoff."
                        if is_contact
                        else "The mock transport service will record a ride request only after approval; this does not verify the physical handoff."
                    ),
                    "metadata": (
                        f"${selected['cost']} · ETA {selected['arrives_at']} · "
                        f"{selected['minutes_before_deadline']} min before deadline"
                    ),
                    "status": "proposed",
                }
            ]
        deadline_minutes = _minutes_after_five(STATE["pickup"]["deadline"])
        commute_minutes = _minutes_after_five(STATE["pickup"]["expected_arrival"])
        minutes_late = max(0, commute_minutes - deadline_minutes)
        pickup_priority = "critical" if minutes_late >= 30 else "high" if minutes_late > 0 else "watch"
    elif scenario == "flight_delay" and delay_minutes == 0:
        actions = []
    elif scenario == "flight_delay":
        arrival = STATE["flight"]["updated_arrival"]
        dinner = STATE["alternatives"][0]
        actions = [
            {
                "id": "reservation-dinner",
                "service": "Reservations",
                "title": f"Move dinner to {dinner['time']}",
                "detail": f"Keep dinner with Maya at {dinner['venue']}; the original 7:00 PM reservation is protected.",
                "impact": "Preserves dinner; does not cancel the reservation.",
                "status": "proposed",
            },
            {
                "id": "message-pickup",
                "service": "Messaging",
                "title": "Draft a pickup update for Maya",
                "detail": f"“My flight is delayed. Could we move pickup to {arrival}?”",
                "impact": "A draft only. Ripple will not send it without your approval.",
                "status": "proposed",
            },
            {
                "id": "delivery-reschedule",
                "service": "Deliveries",
                "title": "Move groceries to tomorrow",
                "detail": f"Request {STATE['delivery']['alternatives'][0]} instead of tonight’s window.",
                "impact": (
                    "The configured mock provider is available; this can be rescheduled after approval."
                    if STATE["delivery"]["provider_available"]
                    else "The configured mock provider is unavailable; the original window will remain unchanged."
                ),
                "status": "proposed",
            },
            {
                "id": "calendar-reminder",
                "service": "Calendar",
                "title": f"Move the dinner reminder to {dinner['time']}",
                "detail": "Update the reminder only after you approve this plan.",
                "impact": "Changes a mock calendar event; it will be verified separately.",
                "status": "proposed",
            },
        ]
    elif scenario == "flight_cancelled":
        actions = [
            {
                "id": "flight-rebook",
                "service": "Travel",
                "title": "Rebook on the next available flight",
                "detail": "Choose the simulated 9:20 PM departure and update the arrival estimate.",
                "impact": "Replaces the cancelled flight in the mock travel service.",
                "status": "proposed",
            },
            {
                "id": "message-pickup",
                "service": "Messaging",
                "title": "Draft a pickup change for Maya",
                "detail": "Explain the cancellation and ask to coordinate a new pickup time.",
                "impact": "Nothing is sent unless you approve this message.",
                "status": "proposed",
            },
            {
                "id": "calendar-reminder",
                "service": "Calendar",
                "title": "Update tonight’s arrival reminder",
                "detail": "Keep the reminder aligned with the replacement flight.",
                "impact": "Only the mock arrival reminder is changed.",
                "status": "proposed",
            },
        ]
    elif scenario == "delivery_disruption":
        actions = [
            {
                "id": "delivery-reschedule",
                "service": "Deliveries",
                "title": "Move groceries to tomorrow",
                "detail": f"Replace the late {STATE['delivery']['window']} window with {STATE['delivery']['alternatives'][0]}.",
                "impact": (
                    "The configured mock provider is available; this can be rescheduled after approval."
                    if STATE["delivery"]["provider_available"]
                    else "The configured mock provider is unavailable; the current window will remain unchanged."
                ),
                "status": "proposed",
            },
            {
                "id": "message-delivery",
                "service": "Messaging",
                "title": "Draft a grocery update for the household",
                "detail": "Let the household know the groceries are coming tomorrow instead.",
                "impact": "Nothing is sent unless you approve this message.",
                "status": "proposed",
            },
            {
                "id": "calendar-reminder",
                "service": "Calendar",
                "title": "Move the grocery reminder",
                "detail": "Update “Bring groceries inside” to the new delivery window.",
                "impact": "Only the mock delivery reminder is changed.",
                "status": "proposed",
            },
        ]
    else:
        actions = [
            {
                "id": "reservation-dinner",
                "service": "Reservations",
                "title": "Move dinner after the meeting",
                "detail": f"Keep dinner with Maya and request the {STATE['alternatives'][0]['time']} table.",
                "impact": "Preserves dinner; does not cancel the reservation.",
                "status": "proposed",
            },
            {
                "id": "message-maya",
                "service": "Messaging",
                "title": "Draft a note to Maya",
                "detail": "Explain that the meeting is running late and propose the later dinner time.",
                "impact": "Nothing is sent unless you approve this message.",
                "status": "proposed",
            },
            {
                "id": "calendar-reminder",
                "service": "Calendar",
                "title": f"Move the dinner reminder to {STATE['alternatives'][0]['time']}",
                "detail": "Update the reminder only after you approve this plan.",
                "impact": "Changes a mock calendar event; it will be verified separately.",
                "status": "proposed",
            },
        ]

    availability_by_service = {
        "Travel": "travel",
        "Transport": "travel",
        "Calendar": "calendar",
        "Deliveries": "delivery",
        "Reservations": "reservations",
        "Messaging": "messaging",
    }
    blocked_actions = [
        action for action in actions
        if not STATE["service_availability"][availability_by_service[action["service"]]]
    ]
    actions = [
        action for action in actions
        if STATE["service_availability"][availability_by_service[action["service"]]]
    ]
    blockers.extend([
        f"{action['service']} MCP module is simulated as offline; “{action['title']}” was not proposed."
        for action in blocked_actions
    ])

    plan_id = f"ripple-{uuid.uuid4().hex[:8]}"
    plan = {
        "plan_id": plan_id,
        "flight_id": FLIGHT_ID,
        "scenario": scenario,
        "priority": pickup_priority,
        "pickup": deepcopy(STATE["pickup"]) if scenario == "pickup_risk" else None,
        "delay_minutes": delay_minutes if scenario == "flight_delay" else None,
        "updated_arrival": STATE["flight"]["updated_arrival"],
        "summary": (
            f"A {delay_minutes // 60}h {delay_minutes % 60}m flight delay affects "
            f"{len(actions)} evening commitments."
            if scenario == "flight_delay" and delay_minutes
            else "Your flight is on time. No changes are needed."
            if scenario == "flight_delay"
            else {
                "pickup_risk": (
                    f"Pickup for {STATE['pickup']['child_name']} is at "
                    f"{STATE['pickup']['deadline']}; the commute is expected at "
                    f"{STATE['pickup']['expected_arrival']}."
                ),
                "flight_cancelled": f"The cancelled flight needs a new booking and coordinated updates across {len(actions)} services.",
                "delivery_disruption": f"The late grocery window affects {len(actions)} household plans.",
                "meeting_overrun": f"The late meeting conflicts with dinner and affects {len(actions)} follow-up plans.",
            }[scenario]
        ),
        "actions": actions,
        "blockers": blockers,
        "status": (
            "awaiting_approval"
            if actions
            else "blocked"
            if blockers
            else "no_changes_needed"
        ),
    }
    STATE["plans"][plan_id] = plan
    STATE["actions"].update(
        {
            f"{plan_id}:{action['id']}": {
                "plan_id": plan_id,
                "status": "proposed",
                "verification": None,
            }
            for action in actions
        }
    )
    return _json(deepcopy(plan))


@mcp.tool()
def execute_approved_action(plan_id: str, action_id: str, user_approved: bool) -> str:
    """Execute one mock action only after the user explicitly approves it."""
    plan = STATE["plans"].get(plan_id)
    action = STATE["actions"].get(f"{plan_id}:{action_id}")
    if not plan or action_id not in {item["id"] for item in plan["actions"]} or not action:
        return _json({"error": "Unknown recovery plan or action."})
    if action["status"] != "proposed":
        return _json({"error": f"Action already resolved with status '{action['status']}'."})
    if not user_approved:
        action["status"] = "declined"
        return _json({"action_id": action_id, "status": "declined", "message": "No change was made."})

    scenario = plan["scenario"]
    plan_item = next(item for item in plan["actions"] if item["id"] == action_id)
    availability_key = {
        "Travel": "travel",
        "Transport": "travel",
        "Calendar": "calendar",
        "Deliveries": "delivery",
        "Reservations": "reservations",
        "Messaging": "messaging",
    }[plan_item["service"]]
    if not STATE["service_availability"][availability_key]:
        action["status"] = "failed"
        action["verification"] = f"{plan_item['service']} mock service is offline; no change was made."
        return _json({"action_id": action_id, "status": "failed", "message": action["verification"]})
    if action_id == "delivery-reschedule" and not STATE["delivery"]["provider_available"]:
        action["status"] = "failed"
        action["verification"] = "Primary delivery provider is unavailable; original delivery remains scheduled."
        return _json(
            {
                "action_id": action_id,
                "status": "failed",
                "message": action["verification"],
            }
        )
    if action_id == "delivery-reschedule-backup" and not STATE["delivery"]["backup_provider_available"]:
        action["status"] = "failed"
        action["verification"] = "Backup delivery provider is unavailable; original delivery remains scheduled."
        return _json({"action_id": action_id, "status": "failed", "message": action["verification"]})

    action["status"] = "executed"
    if action_id == "reservation-dinner":
        STATE["calendar"][0]["time"] = STATE["alternatives"][0]["time"]
        STATE["calendar"][0]["status"] = "rescheduled"
        action["verification"] = f"Dinner reservation now shows {STATE['calendar'][0]['time']}."
    elif action_id == "pickup-notify-contact":
        STATE["pickup"]["status"] = "details_sent_handoff_unverified"
        action["verification"] = (
            "Mock messaging service confirms pickup details were sent to Jordan. "
            "The physical school handoff is not independently verified."
        )
    elif action_id == "pickup-book-transport":
        STATE["pickup"]["status"] = "ride_requested_handoff_unverified"
        ride = next(option for option in STATE["pickup"]["options"] if option["id"] == "rideshare")
        action["verification"] = (
            "Mock transport service confirms the CityRide request for "
            f"{ride['arrives_at']}. "
            "This verifies the simulated booking only, not the physical school handoff."
        )
    elif action_id in {"message-pickup", "message-maya", "message-delivery"}:
        recipient = "the household" if action_id == "message-delivery" else "Maya"
        action["verification"] = f"Mock messaging service confirms the approved message was sent to {recipient}."
    elif action_id == "flight-rebook":
        STATE["flight"]["status"] = "Rebooked"
        STATE["flight"]["updated_arrival"] = "11:10 PM"
        action["verification"] = "Mock travel service confirms the 9:20 PM replacement flight."
    elif action_id == "calendar-reminder":
        event_id = (
            "delivery-reminder"
            if scenario == "delivery_disruption"
            else "arrival-reminder"
            if scenario == "flight_cancelled"
            else "dinner-reminder"
        )
        event = next((item for item in STATE["calendar"] if item["id"] == event_id), None)
        if event:
            event["time"] = (
                STATE["delivery"]["alternatives"][0]
                if scenario == "delivery_disruption"
                else STATE["flight"]["updated_arrival"]
                if scenario == "flight_cancelled"
                else STATE["alternatives"][0]["time"]
            )
            event["status"] = "updated"
            action["verification"] = f"Calendar confirms “{event['title']}” was updated to {event['time']}."
    elif action_id in {"delivery-reschedule", "delivery-reschedule-backup"}:
        if action_id == "delivery-reschedule-backup":
            STATE["delivery"]["provider"] = "QuickBasket backup"
        STATE["delivery"]["status"] = "rescheduled"
        STATE["delivery"]["window"] = STATE["delivery"]["alternatives"][0]
        action["verification"] = (
            f"{STATE['delivery']['provider']} confirms the new window: {STATE['delivery']['window']}."
        )
    return _json(
        {
            "action_id": action_id,
            "status": "executed",
            "message": "Mock action executed. Verify its status before reporting completion.",
        }
    )


@mcp.tool()
def verify_action_status(plan_id: str, action_id: str) -> str:
    """Verify a mock action and return evidence for success or failure."""
    plan = STATE["plans"].get(plan_id)
    action = STATE["actions"].get(f"{plan_id}:{action_id}")
    if not plan or action_id not in {item["id"] for item in plan["actions"]} or not action:
        return _json({"error": "Unknown recovery plan or action."})
    status = action["status"]
    if status == "executed":
        verified = True
        evidence = action.get("verification") or "The mock service confirms the approved change."
    elif status == "failed":
        verified = False
        evidence = action["verification"]
    elif status == "declined":
        verified = False
        evidence = "The user declined this action; no change was made."
    else:
        return _json({"error": "Action has not been approved or declined yet."})

    action["verification"] = evidence
    action["status"] = "verified" if verified else status
    for item in plan["actions"]:
        if item["id"] == action_id:
            item["status"] = action["status"]
    return _json(
        {
            "plan_id": plan_id,
            "action_id": action_id,
            "verified": verified,
            "status": action["status"],
            "evidence": evidence,
        }
    )


@mcp.tool()
def find_recovery_options(plan_id: str, action_id: str) -> str:
    """Discover a viable mock fallback after a proposed action fails."""
    plan = STATE["plans"].get(plan_id)
    action = STATE["actions"].get(f"{plan_id}:{action_id}")
    if not plan or not action or action["status"] != "failed":
        return _json({"error": "Recovery options are available only for a failed action in a known plan."})

    options = []
    if (
        action_id == "delivery-reschedule"
        and STATE["service_availability"]["delivery"]
        and STATE["delivery"]["backup_provider_available"]
        and f"{plan_id}:delivery-reschedule-backup" not in STATE["actions"]
    ):
        fallback = {
            "id": "delivery-reschedule-backup",
            "service": "Deliveries",
            "title": "Retry grocery reschedule with QuickBasket",
            "detail": f"Use the backup provider to request {STATE['delivery']['alternatives'][0]}.",
            "impact": "New proposal from a discovered fallback tool; requires your separate approval.",
            "status": "proposed",
        }
        plan["actions"].append(fallback)
        STATE["actions"][f"{plan_id}:delivery-reschedule-backup"] = {
            "plan_id": plan_id,
            "status": "proposed",
            "verification": None,
        }
        options.append(deepcopy(fallback))
    return _json(
        {
            "plan_id": plan_id,
            "failed_action_id": action_id,
            "options": options,
            "message": (
                "A backup provider can attempt this recovery; it still needs your approval."
                if options
                else "No available fallback tool can recover this action."
            ),
        }
    )


@mcp.tool()
def reset_demo_scenario() -> str:
    """Reset the in-memory mock pickup, flight, calendar, delivery and plan state."""
    global STATE
    STATE = _initial_state()
    return _json({"status": "reset", "flight_id": FLIGHT_ID})


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def serve_demo(_request):
    from starlette.responses import FileResponse

    return FileResponse(APP_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@mcp.custom_route("/logs", methods=["GET"], include_in_schema=False)
async def serve_logs(_request):
    from starlette.responses import FileResponse

    return FileResponse(APP_DIR / "logs.html", headers={"Cache-Control": "no-cache"})


@mcp.custom_route("/styles.css", methods=["GET"], include_in_schema=False)
async def serve_styles(_request):
    from starlette.responses import FileResponse

    return FileResponse(
        APP_DIR / "styles.css",
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


@mcp.custom_route("/app.js", methods=["GET"], include_in_schema=False)
async def serve_app_script(_request):
    from starlette.responses import FileResponse

    return FileResponse(
        APP_DIR / "app.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@mcp.custom_route("/mcp-client.js", methods=["GET"], include_in_schema=False)
async def serve_mcp_script(_request):
    from starlette.responses import FileResponse

    return FileResponse(
        APP_DIR / "mcp-client.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@mcp.custom_route("/logs.js", methods=["GET"], include_in_schema=False)
async def serve_logs_script(_request):
    from starlette.responses import FileResponse

    return FileResponse(
        APP_DIR / "logs.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@mcp.custom_route("/assets/{asset_name}", methods=["GET"], include_in_schema=False)
async def serve_demo_asset(request):
    from starlette.responses import FileResponse, Response

    asset_name = request.path_params.get("asset_name")
    if asset_name not in {"ripple-purpose.gif", "ripple-how-to.gif"}:
        return Response(status_code=404)
    return FileResponse(APP_DIR / "assets" / asset_name, media_type="image/gif")


@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def health_check(_request):
    from starlette.responses import JSONResponse

    return JSONResponse(
        {
            "status": "ok",
            "name": "Ripple",
            "transport": "Streamable HTTP",
            "protocolVersion": "2025-11-25",
            "endpoint": "/mcp",
        }
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
