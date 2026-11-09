"""User-visible behavior of the shared parameter workspace, without CAD."""

import tempfile
import json
import threading
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from solidworks_mcp.workspace.parameter_store import Conflict, ParameterStore, ValidationError
from solidworks_mcp.workspace.parameter_http import create_server
from solidworks_mcp import server as mcp_server


class ParameterWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "workspace.sqlite3"
        self.store = ParameterStore(self.path)
        self.project = self.store.create_project("Stopnice A")
        self.root = self.store.add_owner(self.project["id"], {
            "kind": "assembly", "name": "Stopnice", "document_id": "assembly-1",
            "configuration": "Default"})

    def test_persists_draft_owner_and_request_across_instances(self):
        railing = self.store.add_owner(self.project["id"], {
            "kind": "occurrence", "name": "Levi steber", "parent_id": self.root["id"],
            "document_id": "part-1", "instance_path": "Ograja/Steber-1",
            "configuration": "Default"})
        height = self.store.add_parameter(self.project["id"], {
            "owner_id": railing["id"], "key": "height", "label": "Višina stebra",
            "value_type": "number", "unit": "mm", "role": "input",
            "binding": {"selector": "D1@Sketch1", "document_id": "part-1"}})
        request = self.store.add_request(self.project["id"], "Spremeni višino", railing["id"])
        self.store.set_draft(self.project["id"], height["id"], "1040,5")
        reopened = ParameterStore(self.path).snapshot(self.project["id"])
        self.assertEqual(reopened["parameters"][0]["draft_value"], 1040.5)
        self.assertEqual(reopened["parameters"][0]["availability"], "draft_only")
        self.assertEqual(reopened["owners"][1]["instance_path"], "Ograja/Steber-1")
        self.assertEqual(reopened["requests"][0]["id"], request["id"])
        self.assertGreaterEqual(len(reopened["history"]), 4)

    def test_derived_and_missing_values_recalculate_and_remain_read_only(self):
        total = self.store.add_parameter(self.project["id"], {
            "owner_id": self.root["id"], "key": "total", "label": "Skupna višina",
            "value_type": "number", "unit": "mm", "role": "input"})
        count = self.store.add_parameter(self.project["id"], {
            "owner_id": self.root["id"], "key": "risers", "label": "Število višin",
            "value_type": "integer", "role": "input", "observed_value": 16})
        rise = self.store.add_parameter(self.project["id"], {
            "owner_id": self.root["id"], "key": "rise", "label": "Višina stopnice",
            "value_type": "number", "unit": "mm", "role": "derived",
            "formula": {"op": "divide", "inputs": [total["id"], count["id"]]}})
        self.assertEqual(self.store.snapshot(self.project["id"])["parameters"][2]["completeness"], "missing_input")
        self.store.set_draft(self.project["id"], total["id"], "2800")
        params = {p["id"]: p for p in self.store.snapshot(self.project["id"])["parameters"]}
        self.assertEqual(params[rise["id"]]["computed_value"], 175)
        with self.assertRaises(ValidationError):
            self.store.set_draft(self.project["id"], rise["id"], 180)

    def test_revision_conflict_keeps_existing_draft(self):
        item = self.store.add_parameter(self.project["id"], {
            "owner_id": self.root["id"], "key": "width", "label": "Širina",
            "value_type": "number", "unit": "mm", "role": "input"})
        revision = self.store.snapshot(self.project["id"])["revision"]
        self.store.set_draft(self.project["id"], item["id"], 1000, expected_revision=revision)
        with self.assertRaises(Conflict):
            self.store.set_draft(self.project["id"], item["id"], 900, expected_revision=revision)
        self.assertEqual(self.store.snapshot(self.project["id"])["parameters"][0]["draft_value"], 1000)

    def test_rejects_invalid_owner_reference_formula_and_value(self):
        with self.assertRaises(ValidationError):
            self.store.add_parameter(self.project["id"], {
                "owner_id": "unknown", "key": "x", "label": "X", "value_type": "number"})
        x = self.store.add_parameter(self.project["id"], {
            "owner_id": self.root["id"], "key": "x", "label": "X", "value_type": "number"})
        with self.assertRaises(ValidationError):
            self.store.set_draft(self.project["id"], x["id"], "NaN")
        with self.assertRaises(ValidationError):
            self.store.add_parameter(self.project["id"], {
                "owner_id": self.root["id"], "key": "cycle", "label": "Cycle",
                "value_type": "number", "role": "derived",
                "formula": {"op": "divide", "inputs": [x["id"], "unknown"]}})

    def test_agent_can_track_request_without_claiming_cad_execution(self):
        request = self.store.add_request(self.project["id"], "Preveri sidranje", self.root["id"])
        updated = self.store.update_request(self.project["id"], request["id"], "needs_info")
        self.assertEqual(updated["status"], "needs_info")
        self.assertEqual(self.store.snapshot(self.project["id"])["requests"][0]["status"], "needs_info")
        with self.assertRaises(ValidationError):
            self.store.update_request(self.project["id"], request["id"], "cad_applied")

    def test_formula_rejects_incompatible_units(self):
        width = self.store.add_parameter(self.project["id"], {
            "owner_id": self.root["id"], "key": "width", "label": "Širina",
            "value_type": "number", "unit": "mm"})
        angle = self.store.add_parameter(self.project["id"], {
            "owner_id": self.root["id"], "key": "angle", "label": "Kot",
            "value_type": "number", "unit": "deg"})
        with self.assertRaises(ValidationError):
            self.store.add_parameter(self.project["id"], {
                "owner_id": self.root["id"], "key": "sum", "label": "Vsota",
                "value_type": "number", "unit": "mm", "role": "derived",
                "formula": {"op": "add", "inputs": [width["id"], angle["id"]]}})

    def test_stair_railing_template_has_named_owners_and_unassumed_measurements(self):
        project = self.store.create_stair_railing_project("Vzorec")
        state = self.store.snapshot(project["id"])
        self.assertTrue(any(o["kind"] == "occurrence" and "steber" in o["name"].lower()
                            for o in state["owners"]))
        self.assertTrue(any(p["role"] == "derived" and p["formula"]
                            for p in state["parameters"]))
        self.assertTrue(all(p["observed_value"] is None for p in state["parameters"]))

    def test_clear_and_discard_draft_are_distinct_and_preserve_observation(self):
        p = self.store.add_parameter(self.project["id"], {
            "owner_id": self.root["id"], "key": "width", "label": "Širina",
            "value_type": "number", "observed_value": 100})
        self.store.set_draft(self.project["id"], p["id"], "")
        state = self.store.snapshot(self.project["id"])
        self.assertTrue(state["parameters"][0]["has_draft"])
        self.assertEqual(state["parameters"][0]["completeness"], "missing")
        self.assertEqual(state["parameters"][0]["observed_value"], 100)
        self.store.discard_draft(self.project["id"], p["id"], expected_revision=state["revision"])
        restored = self.store.snapshot(self.project["id"])["parameters"][0]
        self.assertFalse(restored["has_draft"])
        self.assertEqual(restored["effective_value"], 100)

    def test_malformed_payloads_return_validation_errors_and_leave_revision_unchanged(self):
        valid = {"owner_id": self.root["id"], "key": "invalid", "label": "X", "value_type": "number"}
        revision = self.store.snapshot(self.project["id"])["revision"]
        for changes in [{"formula": {"op": "add"}}, {"role": []}, {"owner_id": {}},
                        {"required": "false"}, {"value_type": {}},
                        {"observed_value": -2, "minimum": 0}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.store.add_parameter(self.project["id"], {**valid, **changes})
        self.assertEqual(self.store.snapshot(self.project["id"])["revision"], revision)

    def test_integers_are_not_silently_rounded_by_float_conversion(self):
        p = self.store.add_parameter(self.project["id"], {
            "owner_id": self.root["id"], "key": "count", "label": "Število", "value_type": "integer"})
        for value in ["9007199254740993", "2.0000000000000001"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.store.set_draft(self.project["id"], p["id"], value)

    def test_zero_division_explains_error_and_cleared_input_does_not_use_observation(self):
        a = self.store.add_parameter(self.project["id"], {"owner_id": self.root["id"], "key": "a",
            "label": "A", "value_type": "number", "observed_value": 100})
        b = self.store.add_parameter(self.project["id"], {"owner_id": self.root["id"], "key": "b",
            "label": "B", "value_type": "number", "observed_value": 0})
        self.store.add_parameter(self.project["id"], {"owner_id": self.root["id"], "key": "result",
            "label": "Rezultat", "value_type": "number", "role": "derived",
            "formula": {"op": "divide", "inputs": [a["id"], b["id"]]}})
        result = self.store.snapshot(self.project["id"])["parameters"][2]
        self.assertEqual(result["completeness"], "invalid_input")
        self.assertIn("nič", result["calculation_error"])
        self.store.set_draft(self.project["id"], b["id"], 2)
        self.store.set_draft(self.project["id"], a["id"], None)
        result = self.store.snapshot(self.project["id"])["parameters"][2]
        self.assertIsNone(result["computed_value"])
        self.assertEqual(result["completeness"], "missing_input")


class ParameterHttpTests(unittest.TestCase):
    def test_local_api_uses_same_store_and_rejects_unauthorized_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ParameterStore(Path(folder) / "workspace.sqlite3")
            server, token = create_server(store, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            base = f"http://127.0.0.1:{server.server_port}"
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(base + "/api/projects"))
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(base + "/api/projects", headers={"Authorization": "Bearer " + token,
                    "Origin": "https://foreign.example"}))
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
            payload = json.dumps({"name": "Ograja"}).encode()
            request = Request(base + "/api/projects", data=payload, method="POST",
                              headers={"Authorization": "Bearer " + token,
                                       "Content-Type": "application/json"})
            with urlopen(request) as response:
                created = json.load(response)
            self.assertEqual(store.list_projects()[0]["id"], created["id"])
            with urlopen(Request(base + "/api/projects/" + created["id"],
                                 headers={"Authorization": "Bearer " + token})) as response:
                self.assertEqual(json.load(response)["project"]["name"], "Ograja")
            with urlopen(base + "/?token=" + token) as response:
                self.assertIn(b"Konstrukcijski parametri", response.read())
            with urlopen(base + "/app.js?token=" + token) as response:
                self.assertIn(b"renderParameters", response.read())
            with urlopen(base + "/state.js?token=" + token) as response:
                self.assertIn(b"ParameterEditBuffer", response.read())
            owner = store.add_owner(created["id"], {"name": "Del", "kind": "part"})
            parameter = store.add_parameter(created["id"], {"owner_id": owner["id"],
                "key": "x", "label": "X", "value_type": "number", "observed_value": 10})
            store.set_draft(created["id"], parameter["id"], None)
            request = Request(base + "/api/projects/" + created["id"] + "/discard-draft",
                data=json.dumps({"parameter_id": parameter["id"],
                    "expected_revision": store.snapshot(created["id"])["revision"]}).encode(),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            with urlopen(request) as response:
                self.assertFalse(json.load(response)["has_draft"])
            self.assertEqual(store.snapshot(created["id"])["parameters"][0]["effective_value"], 10)

    def test_mcp_and_browser_share_register_without_cad_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ParameterStore(Path(folder) / "workspace.sqlite3")
            with patch("solidworks_mcp.tools.parameter_workspace.ParameterStore", return_value=store), \
                 patch.object(mcp_server.sw_automation, "get_active_doc", side_effect=AssertionError("CAD touched")):
                created = asyncio.run(mcp_server.call_tool("write_parameter_workspace", {
                    "action": "create_project", "payload": {"name": "Skupni register"}}))
                self.assertIn("[SUCCESS]", created[0].text)
                read = asyncio.run(mcp_server.call_tool("read_parameter_workspace", {}))
                self.assertIn("Skupni register", read[0].text)
                self.assertEqual(store.list_projects()[0]["name"], "Skupni register")


if __name__ == "__main__":
    unittest.main()
