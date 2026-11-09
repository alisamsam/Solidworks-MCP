"""Revolved, swept, lofted and boundary features (M2.1); api-findings §31-32."""

import math
import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tests.test_sweep_loft import (
    Automation, Document, Feature, FeatureManager,
)
from solidworks_mcp.tools.advanced_features import (
    boundary_boss, boundary_cut, loft_cut, revolve_cut, sweep_cut,
)


class CutFeatureManager(FeatureManager):
    def __init__(self, created=True, error_code=0):
        super().__init__(created, error_code)
        self.revolve_args = None
        self.cut_blend_args = None

    def FeatureRevolve2(self, *args):
        self.revolve_args = args
        if not self.created:
            return None
        return Feature("Cut-Revolve1", "RevCut", error_code=self.error_code)

    def InsertCutBlend(self, *args):
        self.cut_blend_args = args
        if not self.created:
            return None
        return Feature("Cut-Loft1", "BlendCut", error_code=self.error_code)


class CutDocument(Document):
    def __init__(self, created=True, error_code=0):
        super().__init__(created, error_code)
        self.FeatureManager = CutFeatureManager(created, error_code)


class CutRegistrationTests(unittest.TestCase):
    def test_the_cuts_are_registered_as_mutations(self):
        tools = {item.name: item for item in registered_tools()}

        for name, required in (
            ("revolve_cut", ["sketch"]),
            ("sweep_cut", ["profile_sketch", "path_sketch"]),
            ("loft_cut", ["profile_sketches"]),
        ):
            with self.subTest(name=name):
                self.assertIn(name, tools)
                self.assertIs(OperationClass.MUTATE, operation_class_for(name))
                self.assertEqual(required, tools[name].inputSchema["required"])


class RevolveCutTests(unittest.TestCase):
    def test_the_named_sketch_is_revolved_as_a_cut(self):
        automation = Automation(CutDocument())

        result = revolve_cut(automation, "Sketch1", angle=90)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 0)], automation.document.profile.select_calls)
        args = automation.document.FeatureManager.revolve_args
        self.assertEqual(20, len(args))
        self.assertIs(True, args[3])  # IsCut
        self.assertAlmostEqual(math.pi / 2, args[8], places=12)
        self.assertEqual("Cut-Revolve1", result["data"]["feature_name"])

    def test_bad_input_is_rejected_before_com(self):
        for call in ({"sketch": " "}, {"sketch": "Sketch1", "angle": 0},
                     {"sketch": "Sketch1", "angle": 361},
                     {"sketch": "Sketch1", "angle": True}):
            with self.subTest(call=call):
                automation = Automation(CutDocument())
                self.assertFalse(revolve_cut(automation, **call)["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_a_missing_sketch_is_reported(self):
        result = revolve_cut(Automation(CutDocument()), "Nope")

        self.assertFalse(result["success"])
        self.assertIn("Nope", result["message"])

    def test_no_feature_is_a_failure(self):
        result = revolve_cut(Automation(CutDocument(created=False)), "Sketch1")

        self.assertFalse(result["success"])


class SweepCutTests(unittest.TestCase):
    def test_the_sweep_cut_definition_is_used(self):
        automation = Automation(CutDocument())

        result = sweep_cut(automation, "Sketch1", "Sketch2")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([18], automation.document.FeatureManager.definition_types)
        self.assertEqual([(False, 1)], automation.document.profile.select_calls)
        self.assertEqual([(True, 4)], automation.document.path.select_calls)


class LoftCutTests(unittest.TestCase):
    def test_profiles_are_selected_in_order_and_cut_blend_is_called(self):
        automation = Automation(CutDocument())

        result = loft_cut(automation, ["Sketch2", "Sketch1"])

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 1)], automation.document.path.select_calls)
        self.assertEqual([(True, 1)], automation.document.profile.select_calls)
        self.assertEqual(12, len(automation.document.FeatureManager.cut_blend_args))
        self.assertEqual("Cut-Loft1", result["data"]["feature_name"])

    def test_a_broken_cut_is_removed(self):
        automation = Automation(CutDocument(error_code=5))

        result = loft_cut(automation, ["Sketch2", "Sketch1"])

        self.assertFalse(result["success"])
        self.assertEqual("FEATURE_REBUILD_FAILED", result["data"]["code"])
        self.assertEqual(1, automation.document.edit_delete_calls)


class NetBlendFeatureManager(FeatureManager):
    """InsertNetBlend returns None even on success (live, SW 2025 SP1.1)."""

    def __init__(self, document, created=True, error_code=0):
        super().__init__(created, error_code)
        self.document = document
        self.curve_data = []
        self.direction_data = []
        self.net_blend_args = None

    def SetNetBlendCurveData(self, *args):
        self.curve_data.append(args)

    def SetNetBlendDirectionData(self, *args):
        self.direction_data.append(args)

    def InsertNetBlend(self, *args):
        self.net_blend_args = args
        if self.created:
            type_name = "NetBlendCut" if args[0] == 3 else "NetBlend"
            self.document.last = Feature("Boundary1", type_name,
                                         error_code=self.error_code)
        return None


class NetBlendDocument(Document):
    def __init__(self, created=True, error_code=0):
        super().__init__(created, error_code)
        self.FeatureManager = NetBlendFeatureManager(self, created, error_code)
        self.last = self.path

    def FeatureByPositionReverse(self, position):
        return self.last


class BoundaryTests(unittest.TestCase):
    def test_boundary_tools_are_registered_as_mutations(self):
        tools = {item.name: item for item in registered_tools()}

        for name in ("boundary_boss", "boundary_cut"):
            with self.subTest(name=name):
                self.assertIs(OperationClass.MUTATE, operation_class_for(name))
                schema = tools[name].inputSchema["properties"]["profile_sketches"]
                self.assertEqual((2, 3), (schema["minItems"], schema["maxItems"]))

    def test_profiles_get_the_direction_one_marks_in_order(self):
        automation = Automation(NetBlendDocument())

        result = boundary_boss(automation, ["Sketch2", "Sketch1"])

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 8193)], automation.document.path.select_calls)
        self.assertEqual([(True, 16385)], automation.document.profile.select_calls)
        manager = automation.document.FeatureManager
        self.assertEqual([0, 1], [args[1] for args in manager.curve_data])
        self.assertEqual(1, manager.net_blend_args[0])  # boss
        self.assertEqual(2, manager.net_blend_args[1])  # curves in direction 1
        self.assertEqual("Boundary1", result["data"]["feature_name"])

    def test_the_cut_uses_type_three(self):
        automation = Automation(NetBlendDocument())

        result = boundary_cut(automation, ["Sketch2", "Sketch1"])

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(3, automation.document.FeatureManager.net_blend_args[0])

    def test_no_new_feature_is_a_failure(self):
        result = boundary_boss(Automation(NetBlendDocument(created=False)),
                               ["Sketch2", "Sketch1"])

        self.assertFalse(result["success"])

    def test_more_than_three_profiles_are_rejected_before_com(self):
        automation = Automation(NetBlendDocument())

        result = boundary_boss(automation, ["A", "B", "C", "D"])

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)
