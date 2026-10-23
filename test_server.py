import json
import unittest

from server import (
    FLIGHT_ID,
    execute_approved_action,
    find_alternatives,
    find_pickup_options,
    find_recovery_options,
    get_calendar_events,
    get_delivery_status,
    get_travel_status,
    get_user_constraints,
    mcp,
    prepare_recovery_context,
    propose_recovery_plan,
    reset_demo_scenario,
    set_demo_scenario,
    verify_action_status,
)
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS


class RippleToolsTests(unittest.TestCase):
    def setUp(self):
        reset_demo_scenario()

    def test_mcp_server_advertises_ripple_recovery_tools(self):
        names = {tool.name for tool in mcp._tool_manager.list_tools()}
        self.assertEqual(
            names,
            {
                "get_user_constraints",
                "get_calendar_events",
                "get_delivery_status",
                "get_travel_status",
                "find_alternatives",
                "propose_recovery_plan",
                "execute_approved_action",
                "verify_action_status",
                "find_recovery_options",
                "set_demo_scenario",
                "prepare_recovery_context",
                "find_pickup_options",
                "reset_demo_scenario",
            },
        )
        self.assertIn("2025-11-25", SUPPORTED_PROTOCOL_VERSIONS)

    def test_mock_services_describe_the_disruption_and_protected_plans(self):
        travel = json.loads(get_travel_status(FLIGHT_ID))
        constraints = json.loads(get_user_constraints())
        events = json.loads(get_calendar_events())
        delivery = json.loads(get_delivery_status())
        alternatives = json.loads(find_alternatives("dinner"))

        self.assertEqual(travel["updated_arrival"], "8:10 PM")
        self.assertTrue(any(item["id"] == "keep-dinner" and item["protected"] for item in constraints))
        self.assertIn("Dinner with Maya", [event["title"] for event in events])
        self.assertEqual(delivery["status"], "scheduled")
        self.assertEqual(alternatives[0]["time"], "8:45 PM")

    def test_actions_require_explicit_approval_and_are_verified(self):
        get_travel_status(FLIGHT_ID, 120)
        plan = json.loads(propose_recovery_plan(120))
        plan_id = plan["plan_id"]

        refused = json.loads(execute_approved_action(plan_id, "message-pickup", False))
        self.assertEqual(refused["status"], "declined")
        refusal_verification = json.loads(verify_action_status(plan_id, "message-pickup"))
        self.assertFalse(refusal_verification["verified"])
        self.assertIn("no change", refusal_verification["evidence"])

        executed = json.loads(execute_approved_action(plan_id, "reservation-dinner", True))
        self.assertEqual(executed["status"], "executed")
        verification = json.loads(verify_action_status(plan_id, "reservation-dinner"))
        self.assertTrue(verification["verified"])
        self.assertEqual(verification["status"], "verified")

    def test_scenarios_generate_distinct_plans_and_delivery_recovery_succeeds(self):
        flight_cancelled = json.loads(set_demo_scenario("flight_cancelled"))
        self.assertEqual(flight_cancelled["status"], "configured")
        cancelled_plan = json.loads(propose_recovery_plan())
        self.assertEqual(cancelled_plan["scenario"], "flight_cancelled")
        self.assertEqual(
            {action["id"] for action in cancelled_plan["actions"]},
            {"flight-rebook", "message-pickup", "calendar-reminder"},
        )

        delivery_selected = json.loads(set_demo_scenario("delivery_disruption"))
        self.assertEqual(delivery_selected["scenario"], "delivery_disruption")
        delivery_plan = json.loads(propose_recovery_plan())
        self.assertEqual(delivery_plan["scenario"], "delivery_disruption")
        self.assertEqual(
            {action["id"] for action in delivery_plan["actions"]},
            {"delivery-reschedule", "message-delivery", "calendar-reminder"},
        )
        plan_id = delivery_plan["plan_id"]
        execution = json.loads(execute_approved_action(plan_id, "delivery-reschedule", True))
        verification = json.loads(verify_action_status(plan_id, "delivery-reschedule"))
        self.assertEqual(execution["status"], "executed")
        self.assertTrue(verification["verified"])
        self.assertEqual(json.loads(get_delivery_status())["status"], "rescheduled")

        set_demo_scenario("meeting_overrun")
        meeting_plan = json.loads(propose_recovery_plan())
        self.assertEqual(meeting_plan["scenario"], "meeting_overrun")
        self.assertEqual(
            {action["id"] for action in meeting_plan["actions"]},
            {"reservation-dinner", "message-maya", "calendar-reminder"},
        )

    def test_unknown_scenario_is_rejected_without_changing_state(self):
        invalid = json.loads(set_demo_scenario("earthquake"))
        self.assertIn("error", invalid)
        self.assertEqual(json.loads(propose_recovery_plan())["scenario"], "flight_delay")

    def test_simulated_provider_failure_is_reported_and_original_stays_scheduled(self):
        prepare_recovery_context(delivery_provider_available=False)
        get_travel_status(FLIGHT_ID, 120)
        plan = json.loads(propose_recovery_plan(120))
        failure = json.loads(execute_approved_action(plan["plan_id"], "delivery-reschedule", True))
        verification = json.loads(verify_action_status(plan["plan_id"], "delivery-reschedule"))

        self.assertEqual(failure["status"], "failed")
        self.assertFalse(verification["verified"])
        self.assertIn("original delivery remains scheduled", verification["evidence"])
        self.assertEqual(json.loads(get_delivery_status())["status"], "scheduled")

    def test_context_tool_returns_configured_inputs_in_one_result(self):
        context = json.loads(
            prepare_recovery_context(
                scenario="flight_delay",
                delay_minutes=180,
                keep_dinner=False,
                delivery_provider_available=False,
                dinner_option_index=1,
            )
        )
        self.assertEqual(context["flight"]["updated_arrival"], "9:10 PM")
        self.assertFalse(context["constraints"][0]["protected"])
        self.assertEqual(context["dinner_alternatives"][0]["time"], "9:15 PM")
        self.assertFalse(context["delivery"]["provider_available"])

        plan = json.loads(propose_recovery_plan(180))
        dinner_action = next(action for action in plan["actions"] if action["id"] == "reservation-dinner")
        delivery_action = next(action for action in plan["actions"] if action["id"] == "delivery-reschedule")
        self.assertIn("9:15 PM", dinner_action["title"])
        self.assertIn("unavailable", delivery_action["impact"])

    def test_failed_action_can_discover_and_execute_approved_backup(self):
        context = json.loads(
            prepare_recovery_context(
                scenario="delivery_disruption",
                delivery_provider_available=False,
                delivery_backup_available=True,
            )
        )
        self.assertFalse(context["delivery"]["provider_available"])
        self.assertTrue(context["delivery"]["backup_provider_available"])
        plan = json.loads(propose_recovery_plan())
        plan_id = plan["plan_id"]

        primary = json.loads(execute_approved_action(plan_id, "delivery-reschedule", True))
        primary_check = json.loads(verify_action_status(plan_id, "delivery-reschedule"))
        self.assertEqual(primary["status"], "failed")
        self.assertFalse(primary_check["verified"])

        recovery = json.loads(find_recovery_options(plan_id, "delivery-reschedule"))
        self.assertEqual(len(recovery["options"]), 1)
        fallback = recovery["options"][0]
        self.assertEqual(fallback["id"], "delivery-reschedule-backup")
        accepted = json.loads(execute_approved_action(plan_id, fallback["id"], True))
        verified = json.loads(verify_action_status(plan_id, fallback["id"]))
        self.assertEqual(accepted["status"], "executed")
        self.assertTrue(verified["verified"])
        self.assertIn("QuickBasket", verified["evidence"])

    def test_unavailable_mock_module_is_visible_and_its_actions_are_omitted(self):
        context = json.loads(
            prepare_recovery_context(
                scenario="flight_delay",
                calendar_available=False,
                messaging_available=False,
            )
        )
        self.assertIsNone(context["calendar"])
        self.assertFalse(context["service_availability"]["calendar"])
        plan = json.loads(propose_recovery_plan())
        self.assertNotIn("calendar-reminder", {action["id"] for action in plan["actions"]})
        self.assertNotIn("message-pickup", {action["id"] for action in plan["actions"]})
        self.assertEqual(len(plan["blockers"]), 2)

    def test_recovery_tool_does_not_offer_an_unavailable_backup(self):
        prepare_recovery_context(
            scenario="delivery_disruption",
            delivery_provider_available=False,
            delivery_backup_available=False,
        )
        plan = json.loads(propose_recovery_plan())
        execute_approved_action(plan["plan_id"], "delivery-reschedule", True)
        verify_action_status(plan["plan_id"], "delivery-reschedule")
        recovery = json.loads(find_recovery_options(plan["plan_id"], "delivery-reschedule"))
        self.assertEqual(recovery["options"], [])
        self.assertIn("No available fallback", recovery["message"])

    def test_cannot_execute_unknown_or_duplicate_actions(self):
        get_travel_status(FLIGHT_ID, 120)
        plan = json.loads(propose_recovery_plan(120))
        self.assertIn("error", json.loads(execute_approved_action(plan["plan_id"], "unknown", True)))
        execute_approved_action(plan["plan_id"], "calendar-reminder", True)
        self.assertIn(
            "error",
            json.loads(execute_approved_action(plan["plan_id"], "calendar-reminder", True)),
        )

    def test_invalid_flight_and_delay_are_not_silently_accepted(self):
        self.assertIn("error", json.loads(get_travel_status("ZZ000")))
        self.assertIn("error", json.loads(get_travel_status(FLIGHT_ID, 500)))
        self.assertIn("error", json.loads(propose_recovery_plan(90)))

    def test_pickup_risk_compares_options_and_requires_individual_approval(self):
        context = json.loads(
            prepare_recovery_context(scenario="pickup_risk", delay_minutes=40)
        )
        self.assertEqual(context["pickup"]["expected_arrival"], "6:20 PM")
        self.assertTrue(any(event["id"] == "school-pickup" for event in context["calendar"]))

        comparison = json.loads(find_pickup_options("6:00 PM", 25))
        self.assertEqual(comparison["priority"], "high")
        self.assertEqual(comparison["minutes_late"], 20)
        self.assertTrue(all(option["eligible"] for option in comparison["options"]))
        self.assertEqual(comparison["recommendation"]["objective"], "lowest_cost")
        self.assertEqual(comparison["recommendation"]["option_id"], "trusted_contact")
        self.assertIn("$18 more", comparison["recommendation"]["tradeoff"])
        self.assertIn("7 extra minutes", comparison["recommendation"]["tradeoff"])
        self.assertEqual(
            next(option for option in comparison["options"] if option["id"] == "rideshare")["cost"],
            18,
        )
        buffer_comparison = json.loads(
            find_pickup_options("6:00 PM", 25, objective="arrival_buffer")
        )
        self.assertEqual(buffer_comparison["recommendation"]["option_id"], "rideshare")
        self.assertIn("10 minutes before the deadline", buffer_comparison["recommendation"]["reason"])

        plan = json.loads(propose_recovery_plan(pickup_option_id="trusted_contact"))
        self.assertEqual(plan["scenario"], "pickup_risk")
        self.assertEqual([action["id"] for action in plan["actions"]], ["pickup-notify-contact"])
        declined = json.loads(
            execute_approved_action(plan["plan_id"], "pickup-notify-contact", False)
        )
        self.assertEqual(declined["status"], "declined")
        self.assertFalse(
            json.loads(verify_action_status(plan["plan_id"], "pickup-notify-contact"))["verified"]
        )

        ride_plan = json.loads(propose_recovery_plan(pickup_option_id="rideshare"))
        executed = json.loads(
            execute_approved_action(ride_plan["plan_id"], "pickup-book-transport", True)
        )
        verification = json.loads(
            verify_action_status(ride_plan["plan_id"], "pickup-book-transport")
        )
        self.assertEqual(executed["status"], "executed")
        self.assertTrue(verification["verified"])
        self.assertIn("not the physical school handoff", verification["evidence"])

    def test_pickup_option_is_blocked_when_over_budget_past_deadline_or_offline(self):
        prepare_recovery_context(scenario="pickup_risk", delay_minutes=40)
        comparison = json.loads(find_pickup_options("6:00 PM", 10))
        ride = next(option for option in comparison["options"] if option["id"] == "rideshare")
        self.assertFalse(ride["eligible"])
        self.assertTrue(ride["meets_deadline"])
        self.assertFalse(ride["within_budget"])
        blocked_budget = json.loads(propose_recovery_plan(pickup_option_id="rideshare"))
        self.assertEqual(blocked_budget["status"], "blocked")
        self.assertFalse(blocked_budget["actions"])
        self.assertIn("budget", blocked_budget["blockers"][0])

        comparison = json.loads(find_pickup_options("5:45 PM", 25))
        self.assertFalse(any(option["eligible"] for option in comparison["options"]))
        blocked_deadline = json.loads(propose_recovery_plan(pickup_option_id="trusted_contact"))
        self.assertEqual(blocked_deadline["status"], "blocked")
        self.assertIn("after the 5:45 PM pickup deadline", blocked_deadline["blockers"][0])

        prepare_recovery_context(
            scenario="pickup_risk",
            delay_minutes=40,
            messaging_available=False,
        )
        comparison = json.loads(find_pickup_options("6:00 PM", 25))
        contact = next(option for option in comparison["options"] if option["id"] == "trusted_contact")
        self.assertFalse(contact["service_available"])
        blocked_service = json.loads(propose_recovery_plan(pickup_option_id="trusted_contact"))
        self.assertEqual(blocked_service["status"], "blocked")
        self.assertIn("Messaging MCP module is offline", blocked_service["blockers"][0])

    def test_pickup_recommendation_respects_eligibility_and_rejects_unknown_objectives(self):
        prepare_recovery_context(scenario="pickup_risk", delay_minutes=40)
        no_buffer_choice = json.loads(
            find_pickup_options("6:00 PM", 10, objective="arrival_buffer")
        )
        self.assertEqual(no_buffer_choice["recommendation"]["option_id"], "trusted_contact")
        self.assertIn("$0", no_buffer_choice["recommendation"]["reason"])

        no_eligible_options = json.loads(
            find_pickup_options("5:45 PM", 25, objective="arrival_buffer")
        )
        self.assertIsNone(no_eligible_options["recommendation"]["option_id"])
        self.assertIn("No option meets", no_eligible_options["recommendation"]["reason"])

        invalid = json.loads(find_pickup_options("6:00 PM", 25, objective="fastest"))
        self.assertIn("error", invalid)

    def test_reset_restores_mock_services_and_discards_plans(self):
        get_travel_status(FLIGHT_ID, 240)
        plan = json.loads(propose_recovery_plan(240))
        result = json.loads(reset_demo_scenario())
        self.assertEqual(result["status"], "reset")
        self.assertEqual(json.loads(get_travel_status())["delay_minutes"], 120)
        self.assertIn(
            "error",
            json.loads(execute_approved_action(plan["plan_id"], "calendar-reminder", True)),
        )
        self.assertEqual(json.loads(get_delivery_status())["status"], "scheduled")


if __name__ == "__main__":
    unittest.main()
