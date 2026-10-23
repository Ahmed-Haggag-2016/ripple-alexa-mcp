import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent


class RippleMcpHttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]

        environment = os.environ.copy()
        environment["DOMINOMIND_HOST"] = "127.0.0.1"
        environment["DOMINOMIND_PORT"] = str(cls.port)
        cls.process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.endpoint = f"{cls.base_url}/mcp"

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                raise RuntimeError("Ripple MCP server exited during integration test setup.")
            try:
                with urlopen(f"{cls.base_url}/healthz", timeout=1) as response:
                    if response.status == 200:
                        return
            except (OSError, URLError):
                time.sleep(0.1)
        cls.process.terminate()
        cls.process.wait(timeout=5)
        raise RuntimeError("Ripple MCP server did not become healthy in time.")

    @classmethod
    def tearDownClass(cls):
        if cls.process.poll() is None:
            cls.process.terminate()
            cls.process.wait(timeout=5)

    def test_home_page_and_health_route_describe_ripple(self):
        with urlopen(f"{self.base_url}/", timeout=3) as response:
            html = response.read().decode("utf-8")
            self.assertIn("no-cache", response.headers.get("Cache-Control", ""))
        self.assertIn("One problem.", html)
        self.assertIn("Decide each proposal separately", html)
        self.assertIn("MCP CONTROL ROOM", html)
        self.assertIn("WHY RIPPLE · HOW TO USE IT", html)
        self.assertIn("/assets/ripple-purpose.gif", html)
        self.assertIn("/assets/ripple-how-to.gif", html)
        self.assertIn('data-scenario="pickup_risk"', html)
        self.assertIn('id="pickup-options-panel"', html)
        self.assertIn('id="flight-delay-label"', html)
        self.assertIn('href="/logs"', html)
        self.assertIn('target="_blank"', html)
        self.assertNotIn('id="activity-feed"', html)
        self.assertNotIn("YOUR DAILY CHECK-IN", html)

        with urlopen(f"{self.base_url}/logs", timeout=3) as response:
            logs_html = response.read().decode("utf-8")
            self.assertIn("no-cache", response.headers.get("Cache-Control", ""))
        self.assertIn("Tool requests &amp; results", logs_html)
        self.assertIn("id=\"activity-feed\"", logs_html)
        with urlopen(f"{self.base_url}/logs.js", timeout=3) as response:
            logs_script = response.read().decode("utf-8")
        self.assertIn("ripple-mcp-activity-v1", logs_script)
        self.assertIn("storage", logs_script)

        for asset in ("ripple-purpose.gif", "ripple-how-to.gif"):
            with urlopen(f"{self.base_url}/assets/{asset}", timeout=3) as response:
                self.assertEqual(response.headers.get_content_type(), "image/gif")
                self.assertTrue(response.read(6).startswith(b"GIF8"))

        with urlopen(f"{self.base_url}/app.js", timeout=3) as response:
            script = response.read().decode("utf-8")
        self.assertIn("Approve and verify:", script)
        self.assertIn("Decline and verify:", script)
        self.assertIn("verify_action_status", script)

        with urlopen(f"{self.base_url}/healthz", timeout=3) as response:
            health = json.load(response)
        self.assertEqual(health["name"], "Ripple")
        self.assertEqual(health["endpoint"], "/mcp")

    def test_real_mcp_discovery_and_approved_recovery_round_trip(self):
        async def exercise():
            async with streamable_http_client(self.endpoint) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.protocolVersion, "2025-11-25")

                    listed = await session.list_tools()
                    names = {tool.name for tool in listed.tools}
                    expected_tools = {
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
                    }
                    self.assertEqual(names, expected_tools)

                    async def call(name, args=None):
                        result = await session.call_tool(name, args or {})
                        self.assertFalse(result.isError)
                        return json.loads(result.content[0].text)

                    await call("reset_demo_scenario")
                    context = await call(
                        "prepare_recovery_context",
                        {
                            "scenario": "flight_delay",
                            "delay_minutes": 120,
                            "keep_dinner": True,
                            "delivery_provider_available": False,
                            "dinner_option_index": 0,
                        },
                    )
                    self.assertEqual(len(context["calendar"]), 3)
                    self.assertFalse(context["delivery"]["provider_available"])
                    travel = await call("get_travel_status", {"flight_id": "AA417", "delay_minutes": 120})
                    constraints = await call("get_user_constraints")
                    events = await call("get_calendar_events")
                    delivery = await call("get_delivery_status")
                    alternatives = await call("find_alternatives", {"kind": "dinner"})
                    self.assertEqual(travel["updated_arrival"], "8:10 PM")
                    self.assertTrue(any(item["protected"] for item in constraints))
                    self.assertEqual(len(events), 3)
                    self.assertEqual(delivery["status"], "scheduled")
                    self.assertTrue(alternatives)

                    plan = await call("propose_recovery_plan", {"delay_minutes": 120})
                    self.assertEqual(len(plan["actions"]), 4)
                    plan_id = plan["plan_id"]

                    denied = await call(
                        "execute_approved_action",
                        {"plan_id": plan_id, "action_id": "message-pickup", "user_approved": False},
                    )
                    self.assertEqual(denied["status"], "declined")
                    denied_check = await call(
                        "verify_action_status",
                        {"plan_id": plan_id, "action_id": "message-pickup"},
                    )
                    self.assertFalse(denied_check["verified"])

                    success = await call(
                        "execute_approved_action",
                        {"plan_id": plan_id, "action_id": "calendar-reminder", "user_approved": True},
                    )
                    self.assertEqual(success["status"], "executed")
                    verified = await call(
                        "verify_action_status",
                        {"plan_id": plan_id, "action_id": "calendar-reminder"},
                    )
                    self.assertTrue(verified["verified"])

                    failure = await call(
                        "execute_approved_action",
                        {"plan_id": plan_id, "action_id": "delivery-reschedule", "user_approved": True},
                    )
                    self.assertEqual(failure["status"], "failed")
                    failed_check = await call(
                        "verify_action_status",
                        {"plan_id": plan_id, "action_id": "delivery-reschedule"},
                    )
                    self.assertFalse(failed_check["verified"])
                    self.assertEqual((await call("get_delivery_status"))["status"], "scheduled")
                    recovery = await call(
                        "find_recovery_options",
                        {"plan_id": plan_id, "action_id": "delivery-reschedule"},
                    )
                    self.assertEqual(recovery["options"][0]["id"], "delivery-reschedule-backup")
                    fallback = await call(
                        "execute_approved_action",
                        {
                            "plan_id": plan_id,
                            "action_id": "delivery-reschedule-backup",
                            "user_approved": True,
                        },
                    )
                    self.assertEqual(fallback["status"], "executed")
                    fallback_check = await call(
                        "verify_action_status",
                        {"plan_id": plan_id, "action_id": "delivery-reschedule-backup"},
                    )
                    self.assertTrue(fallback_check["verified"])
                    self.assertIn("QuickBasket", fallback_check["evidence"])

                    await call("set_demo_scenario", {"scenario": "delivery_disruption"})
                    delivery_plan = await call("propose_recovery_plan")
                    self.assertEqual(delivery_plan["scenario"], "delivery_disruption")
                    self.assertEqual(
                        {action["id"] for action in delivery_plan["actions"]},
                        {"delivery-reschedule", "message-delivery", "calendar-reminder"},
                    )
                    rescheduled = await call(
                        "execute_approved_action",
                        {
                            "plan_id": delivery_plan["plan_id"],
                            "action_id": "delivery-reschedule",
                            "user_approved": True,
                        },
                    )
                    self.assertEqual(rescheduled["status"], "executed")
                    delivery_check = await call(
                        "verify_action_status",
                        {
                            "plan_id": delivery_plan["plan_id"],
                            "action_id": "delivery-reschedule",
                        },
                    )
                    self.assertTrue(delivery_check["verified"])

        asyncio.run(exercise())

    def test_pickup_risk_mcp_round_trip_enforces_budget_and_verification_scope(self):
        async def exercise():
            async with streamable_http_client(self.endpoint) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    async def call(name, args=None):
                        result = await session.call_tool(name, args or {})
                        self.assertFalse(result.isError)
                        return json.loads(result.content[0].text)

                    await call("reset_demo_scenario")
                    context = await call(
                        "prepare_recovery_context",
                        {"scenario": "pickup_risk", "delay_minutes": 40},
                    )
                    self.assertEqual(context["pickup"]["expected_arrival"], "6:20 PM")
                    comparison = await call(
                        "find_pickup_options",
                        {"deadline": "6:00 PM", "max_cost": 10},
                    )
                    ride = next(option for option in comparison["options"] if option["id"] == "rideshare")
                    self.assertFalse(ride["eligible"])

                    blocked = await call(
                        "propose_recovery_plan",
                        {"delay_minutes": 40, "pickup_option_id": "rideshare"},
                    )
                    self.assertEqual(blocked["status"], "blocked")
                    self.assertFalse(blocked["actions"])

                    contact_plan = await call(
                        "propose_recovery_plan",
                        {"delay_minutes": 40, "pickup_option_id": "trusted_contact"},
                    )
                    self.assertEqual(len(contact_plan["actions"]), 1)
                    sent = await call(
                        "execute_approved_action",
                        {
                            "plan_id": contact_plan["plan_id"],
                            "action_id": "pickup-notify-contact",
                            "user_approved": True,
                        },
                    )
                    self.assertEqual(sent["status"], "executed")
                    checked = await call(
                        "verify_action_status",
                        {
                            "plan_id": contact_plan["plan_id"],
                            "action_id": "pickup-notify-contact",
                        },
                    )
                    self.assertTrue(checked["verified"])
                    self.assertIn("not independently verified", checked["evidence"])

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
