"""RT3 bounded native update_routing_connection_point: MUTATE, gate first, direct set.

These tests pin the safety boundaries the brief requires: the Routing
configuration gate is checked before any COM access; direct handler arguments are
bounded before COM; a saved part needs an approved write policy before any feature
or definition access; only an exact existing top-level ``ConnectionPoint`` in the
active part's current configuration can be edited; only ``RouteDiameter``,
``StubLength`` and/or the native ``PortID`` are assigned directly on its feature
definition (never via ``AccessSelections``/``ModifyDefinition``); ``ForceRebuild3``
(false) follows; and a fresh ``GetDefinition`` readback asserts the requested value
persisted while location, direction, route type/subtype and the unsupplied editable
fields stayed unchanged. ``port_id`` is a bounded BSTR (128 characters, no control
characters, no surrounding whitespace, Unicode accepted, empty clears) verified by
an exact readback match. A failed rebuild or a readback/invariant mismatch fails
with partial-mutation evidence and no automatic rollback.
"""

import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jsonschema import Draft7Validator

from solidworks_mcp import catalog
from solidworks_mcp.constants import SwErrors
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, _load
from solidworks_mcp.tools import routing_edit

_TOOL_NAME = "update_routing_connection_point"

# Exercise the production registration path without changing the shared registry.
_load()
_ENTRY = _TOOLS[_TOOL_NAME]


class Definition:
    """IConnectionPointFeatureData fake: writable fields, strict member access.

    It deliberately exposes none of AccessSelections/ModifyDefinition/
    ReleaseSelectionAccess: the documented native path must not call them, so a
    stray call raises through this strict ``__getattr__`` and fails the test.
    """

    _CPOINT_FIELDS = ("Location", "Direction", "RouteDiameter", "StubLength",
                      "RouteType", "RouteSubType", "PortID")

    def __init__(self, *, diameter_m=0.0508, stub_m=0.0, location=(0.0, 0.0, -0.00635),
                 direction=(0.0, 0.0, -1.0), route_type=2, route_sub_type=20, port_id=""):
        object.__setattr__(self, "Location", location)
        object.__setattr__(self, "Direction", direction)
        object.__setattr__(self, "RouteDiameter", diameter_m)
        object.__setattr__(self, "StubLength", stub_m)
        object.__setattr__(self, "RouteType", route_type)
        object.__setattr__(self, "RouteSubType", route_sub_type)
        object.__setattr__(self, "PortID", port_id)
        object.__setattr__(self, "_writes", [])
        object.__setattr__(self, "fail_write", None)
        object.__setattr__(self, "drop_write", None)

    def __setattr__(self, name, value):
        if name in type(self)._CPOINT_FIELDS:
            if self.__dict__.get("fail_write") == name:
                raise RuntimeError(f"write refused: {name}")
            object.__getattribute__(self, "_writes").append(name)
            if self.__dict__.get("drop_write") == name:
                return  # silently not persisted, like a lost edit
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected definition access: {name}")


class Feature:
    def __init__(self, name="CPoint1", kind="ConnectionPoint", definition=None):
        self.Name = name
        self.kind = kind
        self.definition = definition
        self.definition_reads = 0

    def GetTypeName2(self):
        return self.kind

    def GetDefinition(self):
        self.definition_reads += 1
        return self.definition

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected feature access: {name}")


class Part:
    def __init__(self, features=(), kind=1, title="fitting", path="C:/fixture/fitting.sldprt"):
        self._features = {feature.Name: feature for feature in features}
        self.kind = kind
        self.title = title
        self.path = path
        self.get_type_calls = 0
        self.feature_by_name_calls = []
        self.force_rebuild_calls = []
        self.rebuild_result = True
        self.rebuild_hook = None

    def GetType(self):
        self.get_type_calls += 1
        return self.kind

    def GetTitle(self):
        return self.title

    def GetPathName(self):
        return self.path

    def FeatureByName(self, name):
        self.feature_by_name_calls.append(name)
        return self._features.get(name)

    def ForceRebuild3(self, top_only):
        self.force_rebuild_calls.append(top_only)
        if self.rebuild_hook is not None:
            self.rebuild_hook()
        return self.rebuild_result

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected document access: {name}")


class App:
    def __init__(self, document=None, error=None):
        self._document = document
        self._error = error
        self.active_doc_reads = 0

    @property
    def ActiveDoc(self):
        self.active_doc_reads += 1
        if isinstance(self._error, Exception):
            raise self._error
        return self._document

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected app access: {name}")


class SW:
    def __init__(self, document=None, app=None):
        self.is_connected = True
        self.app = app if app is not None else App(document)
        # Saved fixtures have a path, so an approved write policy is required;
        # individual tests override it with None / a denying policy.
        self._path_policy = SimpleNamespace(require_write=lambda path, operation: path)

    def _result(self, success, message, error=SwErrors.swSuccess, data=None):
        return {"success": success, "message": message, "error_name": error.name,
                "error_code": int(error), "data": data if data is not None else {}}

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected automation access: {name}")


class BlockedSW:
    """Fails loudly if anything but _result() is touched before input validation."""

    @property
    def is_connected(self):
        raise AssertionError("gate/validation must reject before any COM access")

    def _result(self, success, message, error=SwErrors.swSuccess, data=None):
        return {"success": success, "message": message, "error_name": error.name,
                "error_code": int(error), "data": data if data is not None else {}}

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected automation access: {name}")


def _point(definition=None, name="CPoint1", kind="ConnectionPoint"):
    return Feature(name=name, kind=kind, definition=definition if definition is not None else Definition())


class RoutingEditRegistrationTests(unittest.TestCase):
    def test_registration_is_mutate_com_without_postflight(self):
        self.assertIs(_ENTRY["operation_class"], OperationClass.MUTATE)
        self.assertTrue(_ENTRY["com"])
        self.assertIsNone(_ENTRY["postflight"])
        self.assertIs(_ENTRY["handler"], routing_edit.update_routing_connection_point)
        self.assertEqual(_ENTRY["handler"].__module__, "solidworks_mcp.tools.routing_edit")

    def test_schema_is_closed_and_requires_a_bounded_update(self):
        schema = _ENTRY["tool"].inputSchema
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(["feature_name"], schema["required"])
        self.assertEqual({"feature_name", "diameter_mm", "stub_length_mm", "port_id"},
                         set(schema["properties"]))
        self.assertEqual(0, schema["properties"]["diameter_mm"]["exclusiveMinimum"])
        self.assertEqual(0, schema["properties"]["stub_length_mm"]["minimum"])
        self.assertEqual(128, schema["properties"]["port_id"]["maxLength"])
        self.assertEqual([{"required": ["diameter_mm"]}, {"required": ["stub_length_mm"]},
                          {"required": ["port_id"]}],
                         schema["anyOf"])

    def test_schema_has_no_route_enum_direction_or_selection_options(self):
        properties = set(_ENTRY["tool"].inputSchema["properties"])
        for forbidden in ("route_type", "route_subtype", "direction",
                          "location", "name", "new_name", "component", "selection",
                          "edit_original", "configuration", "reverse_direction"):
            self.assertNotIn(forbidden, properties)

    def test_schema_rejects_missing_or_unbounded_updates(self):
        validator = Draft7Validator(_ENTRY["tool"].inputSchema)
        self.assertFalse(list(validator.iter_errors(
            {"feature_name": "CPoint1", "diameter_mm": 1.0})))
        self.assertFalse(list(validator.iter_errors(
            {"feature_name": "CPoint1", "stub_length_mm": 0})))
        self.assertFalse(list(validator.iter_errors(
            {"feature_name": "CPoint1", "port_id": "PORT-A"})))
        self.assertFalse(list(validator.iter_errors(
            {"feature_name": "CPoint1", "port_id": ""})))
        for invalid in ({"feature_name": "CPoint1"},
                        {"feature_name": "CPoint1", "diameter_mm": 0},
                        {"feature_name": "CPoint1", "diameter_mm": -1},
                        {"feature_name": "CPoint1", "stub_length_mm": -0.5},
                        {"feature_name": "CPoint1", "diameter_mm": 1, "route_type": 2},
                        {"feature_name": "CPoint1", "port_id": "x" * 129},
                        {"feature_name": "CPoint1", "port_id": 5},
                        {"port_id": "PORT-A"},
                        {"diameter_mm": 1.0}):
            with self.subTest(arguments=invalid):
                self.assertTrue(list(validator.iter_errors(invalid)))


class RoutingEditGateTests(unittest.TestCase):
    def test_disabled_gate_rejects_before_any_document_access(self):
        with patch.object(catalog, "routing_enabled", return_value=False):
            result = routing_edit.update_routing_connection_point(
                BlockedSW(), feature_name="CPoint1", diameter_mm=10.0)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])
        self.assertEqual("swInvalidInput", result["error_name"])

    def test_gate_precedes_input_validation(self):
        # No feature_name would fail validation, but the disabled gate must win first.
        with patch.object(catalog, "routing_enabled", return_value=False):
            result = routing_edit.update_routing_connection_point(BlockedSW())
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])


class RoutingEditInputTests(unittest.TestCase):
    def _reject(self, **kwargs):
        with patch.object(catalog, "routing_enabled", return_value=True):
            return routing_edit.update_routing_connection_point(BlockedSW(), **kwargs)

    def test_invalid_inputs_are_rejected_before_com(self):
        for arguments in (
            {}, {"feature_name": ""}, {"feature_name": "   "},
            {"feature_name": "CPoint1"},
            {"feature_name": "CPoint1", "diameter_mm": 0},
            {"feature_name": "CPoint1", "diameter_mm": -1.0},
            {"feature_name": "CPoint1", "diameter_mm": float("nan")},
            {"feature_name": "CPoint1", "diameter_mm": float("inf")},
            {"feature_name": "CPoint1", "diameter_mm": float("-inf")},
            {"feature_name": "CPoint1", "diameter_mm": True},
            {"feature_name": "CPoint1", "diameter_mm": "10"},
            {"feature_name": "CPoint1", "stub_length_mm": -0.1},
            {"feature_name": "CPoint1", "stub_length_mm": float("nan")},
            {"feature_name": "CPoint1", "stub_length_mm": float("inf")},
            {"feature_name": "CPoint1", "stub_length_mm": True},
            {"feature_name": "CPoint1", "port_id": "x" * 129},
            {"feature_name": "CPoint1", "port_id": " PORT-A"},
            {"feature_name": "CPoint1", "port_id": "PORT-A "},
            {"feature_name": "CPoint1", "port_id": "   "},
            {"feature_name": "CPoint1", "port_id": "\t"},
            {"feature_name": "CPoint1", "port_id": "bad\x00id"},
            {"feature_name": "CPoint1", "port_id": "bad\x1fid"},
            {"feature_name": "CPoint1", "port_id": "bad\x7fid"},
            {"feature_name": "CPoint1", "port_id": 5},
            {"feature_name": "CPoint1", "port_id": True},
        ):
            with self.subTest(arguments=arguments):
                result = self._reject(**arguments)
                self.assertFalse(result["success"])
                self.assertEqual("ROUTING_INPUT_INVALID", result["data"]["code"])

    def test_zero_stub_length_is_allowed(self):
        part = Part([_point()])
        with patch.object(catalog, "routing_enabled", return_value=True):
            result = routing_edit.update_routing_connection_point(
                SW(part), feature_name="CPoint1", stub_length_mm=0)
        self.assertTrue(result["success"], result)

    def test_port_id_alone_and_empty_clear_are_allowed(self):
        for port_id in ("PORT-A", ""):
            with self.subTest(port_id=port_id):
                part = Part([_point()])
                with patch.object(catalog, "routing_enabled", return_value=True):
                    result = routing_edit.update_routing_connection_point(
                        SW(part), feature_name="CPoint1", port_id=port_id)
                self.assertTrue(result["success"], result)

    def test_max_length_and_unicode_port_ids_are_allowed(self):
        for port_id in ("x" * 128, "Port-\u03a9-\u00c4\u00df-01"):
            with self.subTest(port_id=port_id):
                definition = Definition()
                with patch.object(catalog, "routing_enabled", return_value=True):
                    result = routing_edit.update_routing_connection_point(
                        SW(Part([_point(definition)])), feature_name="CPoint1",
                        port_id=port_id)
                self.assertTrue(result["success"], result)
                self.assertEqual(port_id, definition.PortID)


class RoutingEditDocumentTests(unittest.TestCase):
    def _run(self, sw, **kwargs):
        with patch.object(catalog, "routing_enabled", return_value=True):
            return routing_edit.update_routing_connection_point(sw, **kwargs)

    def test_disconnected_never_auto_connects(self):
        part = Part([_point()])
        sw = SW(part)
        sw.is_connected = False
        result = self._run(sw, feature_name="CPoint1", diameter_mm=10.0)
        self.assertEqual("swConnectionError", result["error_name"])
        self.assertEqual(0, sw.app.active_doc_reads)
        self.assertEqual([], part.feature_by_name_calls)

    def test_connection_loss_during_active_doc_read_is_reported(self):
        part = Part([_point()])
        app = App(part, error=RuntimeError("connection lost"))
        result = self._run(SW(app=app), feature_name="CPoint1", diameter_mm=10.0)
        self.assertEqual("swConnectionError", result["error_name"])
        self.assertEqual(1, app.active_doc_reads)
        self.assertEqual([], part.feature_by_name_calls)

    def test_no_active_document(self):
        app = App(None)
        result = self._run(SW(app=app), feature_name="CPoint1", diameter_mm=10.0)
        self.assertEqual("swNoActiveDocument", result["error_name"])
        self.assertEqual(1, app.active_doc_reads)

    def test_wrong_document_type_rejected_before_feature_lookup(self):
        part = Part([_point()], kind=2)
        result = self._run(SW(part), feature_name="CPoint1", diameter_mm=10.0)
        self.assertEqual("swInvalidFileType", result["error_name"])
        self.assertEqual(1, part.get_type_calls)
        self.assertEqual([], part.feature_by_name_calls)


class RoutingEditTargetTests(unittest.TestCase):
    def _run(self, part, **kwargs):
        with patch.object(catalog, "routing_enabled", return_value=True):
            return routing_edit.update_routing_connection_point(SW(part), **kwargs)

    def test_missing_feature_is_reported_without_definition_access(self):
        existing = _point()
        part = Part([existing])
        result = self._run(part, feature_name="Ghost", diameter_mm=10.0)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_CONNECTION_POINT_NOT_FOUND", result["data"]["code"])
        self.assertIs(result["data"]["document_may_be_modified"], False)
        self.assertEqual(["Ghost"], part.feature_by_name_calls)
        self.assertEqual([], part.force_rebuild_calls)
        self.assertEqual(0, existing.definition_reads)

    def test_non_connection_point_feature_is_rejected(self):
        feature = _point(kind="RefPlane", name="Plane1")
        part = Part([feature])
        result = self._run(part, feature_name="Plane1", diameter_mm=10.0)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_CONNECTION_POINT_TYPE_MISMATCH", result["data"]["code"])
        self.assertEqual(0, feature.definition_reads)
        self.assertEqual([], part.force_rebuild_calls)

    def test_unreadable_definition_fails_before_write_and_rebuild(self):
        feature = Feature(definition=None)
        part = Part([feature])
        result = self._run(part, feature_name="CPoint1", diameter_mm=10.0)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_CONNECTION_POINT_UNREADABLE", result["data"]["code"])
        self.assertEqual([], part.force_rebuild_calls)


class RoutingEditMutationTests(unittest.TestCase):
    def _run(self, part, **kwargs):
        with patch.object(catalog, "routing_enabled", return_value=True):
            return routing_edit.update_routing_connection_point(SW(part), **kwargs)

    def test_diameter_is_converted_to_metres_rebuilt_and_read_back(self):
        definition = Definition(stub_m=0.0)
        feature = _point(definition)
        part = Part([feature])
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4)
        self.assertTrue(result["success"], result)
        self.assertAlmostEqual(0.0254, definition.RouteDiameter)
        self.assertEqual(["RouteDiameter"], definition._writes)
        self.assertEqual([False], part.force_rebuild_calls)
        self.assertIs(result["data"]["rebuild"], True)
        self.assertEqual({"diameter_mm": 25.4}, result["data"]["requested"])
        self.assertAlmostEqual(25.4, result["data"]["after"]["nominal_diameter_mm"])
        self.assertFalse(result["data"]["saved"])
        self.assertFalse(result["data"]["automatic_rollback"])
        self.assertEqual("active_configuration", result["data"]["scope"])
        self.assertTrue(result["data"]["invariants_unchanged"])
        self.assertIn("stub_length_mm", result["data"]["invariants_checked"])

    def test_stub_length_only_preserves_diameter(self):
        definition = Definition(diameter_m=0.0508)
        part = Part([_point(definition)])
        result = self._run(part, feature_name="CPoint1", stub_length_mm=12.0)
        self.assertTrue(result["success"], result)
        self.assertAlmostEqual(0.012, definition.StubLength)
        self.assertAlmostEqual(0.0508, definition.RouteDiameter)
        self.assertEqual(["StubLength"], definition._writes)
        self.assertEqual([False], part.force_rebuild_calls)
        self.assertAlmostEqual(12.0, result["data"]["after"]["stub_length_mm"])
        self.assertIn("nominal_diameter_mm", result["data"]["invariants_checked"])

    def test_both_properties_updated_together(self):
        definition = Definition()
        part = Part([_point(definition)])
        result = self._run(part, feature_name="CPoint1", diameter_mm=50.8, stub_length_mm=5.0)
        self.assertTrue(result["success"], result)
        self.assertAlmostEqual(0.0508, definition.RouteDiameter)
        self.assertAlmostEqual(0.005, definition.StubLength)
        self.assertEqual(["RouteDiameter", "StubLength"], definition._writes)
        self.assertEqual([False], part.force_rebuild_calls)

    def test_other_connection_point_properties_are_preserved(self):
        definition = Definition(location=(0.1, -0.2, 0.3), direction=(1.0, 0.0, 0.0),
                                route_type=2, route_sub_type=20, port_id="PORT-A")
        result = self._run(Part([_point(definition)]), feature_name="CPoint1", diameter_mm=25.4)
        self.assertTrue(result["success"], result)
        self.assertEqual((0.1, -0.2, 0.3), definition.Location)
        self.assertEqual((1.0, 0.0, 0.0), definition.Direction)
        self.assertEqual(2, definition.RouteType)
        self.assertEqual(20, definition.RouteSubType)
        self.assertEqual("PORT-A", definition.PortID)
        after = result["data"]["after"]
        self.assertEqual([100.0, -200.0, 300.0], after["position_mm"])
        self.assertEqual([1.0, 0.0, 0.0], after["direction"])
        self.assertEqual(2, after["route_type_raw"])
        self.assertEqual(20, after["route_subtype_raw"])
        self.assertEqual("PORT-A", after["port_id"])
        self.assertEqual(result["data"]["before"]["nominal_diameter_mm"], 50.8)

    def test_document_identity_is_reported(self):
        part = Part([_point()], title="flange", path="C:/fixture/flange.sldprt")
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4)
        self.assertEqual({"title": "flange", "path": "C:/fixture/flange.sldprt"},
                         result["data"]["document"])

    def test_definition_is_read_once_for_set_and_once_for_readback(self):
        definition = Definition()
        feature = _point(definition)
        self.assertTrue(self._run(Part([feature]), feature_name="CPoint1", diameter_mm=25.4)["success"])
        # before read + set + after read == three fresh GetDefinition calls.
        self.assertEqual(3, feature.definition_reads)


class RoutingEditPortIdTests(unittest.TestCase):
    def _run(self, part, **kwargs):
        with patch.object(catalog, "routing_enabled", return_value=True):
            return routing_edit.update_routing_connection_point(SW(part), **kwargs)

    def test_port_id_only_is_set_as_exact_string_not_metres(self):
        definition = Definition(port_id="")
        feature = _point(definition)
        part = Part([feature])
        result = self._run(part, feature_name="CPoint1", port_id="PORT-A")
        self.assertTrue(result["success"], result)
        self.assertEqual("PORT-A", definition.PortID)
        self.assertEqual(["PortID"], definition._writes)
        self.assertEqual([False], part.force_rebuild_calls)
        self.assertEqual({"port_id": "PORT-A"}, result["data"]["requested"])
        self.assertEqual(["port_id"], result["data"]["properties_written"])
        self.assertEqual("PORT-A", result["data"]["after"]["port_id"])
        # The unsupplied editable dimensions are still checked; port_id is not.
        self.assertIn("nominal_diameter_mm", result["data"]["invariants_checked"])
        self.assertIn("stub_length_mm", result["data"]["invariants_checked"])
        self.assertNotIn("port_id", result["data"]["invariants_checked"])

    def test_empty_port_id_clears_existing_value(self):
        definition = Definition(port_id="OLD-PORT")
        result = self._run(Part([_point(definition)]), feature_name="CPoint1", port_id="")
        self.assertTrue(result["success"], result)
        self.assertEqual("", definition.PortID)
        self.assertEqual("", result["data"]["after"]["port_id"])

    def test_port_id_combined_with_diameter(self):
        definition = Definition(port_id="")
        part = Part([_point(definition)])
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4, port_id="P-42")
        self.assertTrue(result["success"], result)
        self.assertAlmostEqual(0.0254, definition.RouteDiameter)
        self.assertEqual("P-42", definition.PortID)
        self.assertEqual(["RouteDiameter", "PortID"], definition._writes)
        self.assertEqual({"diameter_mm": 25.4, "port_id": "P-42"}, result["data"]["requested"])

    def test_untouched_port_id_is_still_checked_as_invariant(self):
        # A change to an untouched port_id is caught by verification...
        definition = Definition(port_id="PORT-A")
        feature = _point(definition)
        part = Part([feature])
        part.rebuild_hook = lambda: setattr(definition, "PortID", "PORT-B")
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_VERIFICATION_FAILED", result["data"]["code"])
        changes = result["data"]["invariant_changes"]
        self.assertEqual(1, len(changes))
        self.assertEqual("port_id", changes[0]["field"])
        self.assertEqual("PORT-A", changes[0]["before"])
        self.assertEqual("PORT-B", changes[0]["after"])
        # ...and an unchanged port_id is still reported among the checked invariants.
        ok = self._run(Part([_point(Definition(port_id="PORT-A"))]),
                       feature_name="CPoint1", diameter_mm=25.4)
        self.assertTrue(ok["success"], ok)
        self.assertIn("port_id", ok["data"]["invariants_checked"])

    def test_port_id_write_that_does_not_persist_fails_verification(self):
        definition = Definition(port_id="")
        definition.drop_write = "PortID"
        part = Part([_point(definition)])
        result = self._run(part, feature_name="CPoint1", port_id="PORT-A")
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_VERIFICATION_FAILED", result["data"]["code"])
        mismatches = result["data"]["mismatches"]
        self.assertEqual(1, len(mismatches))
        self.assertEqual("port_id", mismatches[0]["field"])
        self.assertEqual("PORT-A", mismatches[0]["requested"])
        self.assertEqual("", mismatches[0]["readback"])
        self.assertIs(result["data"]["automatic_rollback"], False)
        self.assertEqual([False], part.force_rebuild_calls)


class RoutingEditWritePolicyTests(unittest.TestCase):
    def _run(self, sw, **kwargs):
        with patch.object(catalog, "routing_enabled", return_value=True):
            return routing_edit.update_routing_connection_point(sw, **kwargs)

    def test_saved_part_without_write_policy_is_denied_before_feature_access(self):
        feature = _point()
        part = Part([feature])
        sw = SW(part)
        sw._path_policy = None
        result = self._run(sw, feature_name="CPoint1", diameter_mm=10.0)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_WRITE_DENIED", result["data"]["code"])
        self.assertIs(result["data"]["document_may_be_modified"], False)
        self.assertEqual([], part.feature_by_name_calls)
        self.assertEqual(0, feature.definition_reads)
        self.assertEqual([], part.force_rebuild_calls)

    def test_saved_part_with_denying_policy_is_denied_before_feature_access(self):
        def deny(path, operation):
            raise PermissionError("outside approved output roots")

        feature = _point()
        part = Part([feature])
        sw = SW(part)
        sw._path_policy = SimpleNamespace(require_write=deny)
        result = self._run(sw, feature_name="CPoint1", port_id="PORT-A")
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_WRITE_DENIED", result["data"]["code"])
        self.assertEqual([], part.feature_by_name_calls)
        self.assertEqual(0, feature.definition_reads)

    def test_approved_policy_is_consulted_with_the_document_path_and_mutate(self):
        calls = []
        sw = SW(Part([_point()]))
        sw._path_policy = SimpleNamespace(
            require_write=lambda path, operation: calls.append((path, operation)))
        result = self._run(sw, feature_name="CPoint1", diameter_mm=10.0)
        self.assertTrue(result["success"], result)
        self.assertEqual(1, len(calls))
        self.assertEqual(OperationClass.MUTATE, calls[0][1])
        self.assertIsInstance(calls[0][0], Path)
        self.assertEqual("C:/fixture/fitting.sldprt", calls[0][0].as_posix())

    def test_unsaved_part_needs_no_write_policy(self):
        feature = _point()
        part = Part([feature], path="")
        sw = SW(part)
        sw._path_policy = None
        result = self._run(sw, feature_name="CPoint1", diameter_mm=25.4)
        self.assertTrue(result["success"], result)
        self.assertIsNone(result["data"]["document"]["path"])


class RoutingEditFailureTests(unittest.TestCase):
    def _run(self, part, **kwargs):
        with patch.object(catalog, "routing_enabled", return_value=True):
            return routing_edit.update_routing_connection_point(SW(part), **kwargs)

    def test_failed_rebuild_reports_evidence_and_keeps_the_write(self):
        definition = Definition()
        part = Part([_point(definition)])
        part.rebuild_result = False
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_REBUILD_FAILED", result["data"]["code"])
        self.assertIs(result["data"]["rebuild"], False)
        self.assertIs(result["data"]["document_may_be_modified"], True)
        self.assertEqual(["diameter_mm"], result["data"]["properties_written"])
        self.assertEqual([False], part.force_rebuild_calls)
        self.assertAlmostEqual(0.0254, definition.RouteDiameter)

    def test_readback_mismatch_fails_without_rollback(self):
        definition = Definition(diameter_m=0.0508)
        definition.drop_write = "RouteDiameter"  # assigned but not persisted
        part = Part([_point(definition)])
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_VERIFICATION_FAILED", result["data"]["code"])
        self.assertIs(result["data"]["document_may_be_modified"], True)
        self.assertIs(result["data"]["automatic_rollback"], False)
        mismatches = result["data"]["mismatches"]
        self.assertEqual(1, len(mismatches))
        self.assertEqual("diameter_mm", mismatches[0]["field"])
        self.assertAlmostEqual(25.4, mismatches[0]["requested"])
        self.assertAlmostEqual(50.8, mismatches[0]["readback"])
        self.assertEqual([False], part.force_rebuild_calls)  # no corrective second pass
        self.assertAlmostEqual(0.0508, definition.RouteDiameter)

    def test_unrelated_field_change_fails_verification(self):
        definition = Definition()
        feature = _point(definition)
        part = Part([feature])
        part.rebuild_hook = lambda: setattr(definition, "Direction", (0.0, 1.0, 0.0))
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_VERIFICATION_FAILED", result["data"]["code"])
        changes = result["data"]["invariant_changes"]
        self.assertEqual(1, len(changes))
        self.assertEqual("direction", changes[0]["field"])
        self.assertEqual([0.0, 0.0, -1.0], changes[0]["before"])
        self.assertEqual([0.0, 1.0, 0.0], changes[0]["after"])

    def test_unsupplied_editable_dimension_change_fails_verification(self):
        definition = Definition(stub_m=0.0)
        feature = _point(definition)
        part = Part([feature])
        part.rebuild_hook = lambda: setattr(definition, "StubLength", 0.099)
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_VERIFICATION_FAILED", result["data"]["code"])
        changes = result["data"]["invariant_changes"]
        self.assertEqual(1, len(changes))
        self.assertEqual("stub_length_mm", changes[0]["field"])
        self.assertAlmostEqual(99.0, changes[0]["after"])

    def test_unconfirmed_readback_after_rebuild_fails(self):
        definition = Definition()
        feature = _point(definition)
        part = Part([feature])
        part.rebuild_hook = lambda: setattr(feature, "definition", None)
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_VERIFICATION_FAILED", result["data"]["code"])
        self.assertIs(result["data"]["document_may_be_modified"], True)
        self.assertEqual([False], part.force_rebuild_calls)

    def test_property_write_exception_reports_only_written_properties(self):
        definition = Definition()
        feature = _point(definition)
        definition.fail_write = "StubLength"
        part = Part([feature])
        result = self._run(part, feature_name="CPoint1", diameter_mm=25.4, stub_length_mm=5.0)
        self.assertFalse(result["success"])
        self.assertEqual("ROUTING_UPDATE_FAILED", result["data"]["code"])
        self.assertEqual(["diameter_mm"], result["data"]["properties_written"])
        self.assertIs(result["data"]["document_may_be_modified"], True)
        self.assertIsNone(result["data"]["rebuild"])
        self.assertEqual([], part.force_rebuild_calls)
        self.assertAlmostEqual(0.0254, definition.RouteDiameter)

    def test_conversion_stores_exact_metres(self):
        definition = Definition()
        result = self._run(Part([_point(definition)]), feature_name="CPoint1", diameter_mm=25.4)
        self.assertTrue(result["success"], result)
        self.assertTrue(math.isclose(0.0254, definition.RouteDiameter, rel_tol=0, abs_tol=1e-12))


if __name__ == "__main__":
    unittest.main()
