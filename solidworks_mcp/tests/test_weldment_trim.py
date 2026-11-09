"""Public-tool tests for trimming two library-profile weldment bodies."""

import unittest
from unittest.mock import patch

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.weldments import trim_weldment_members


class Body:
    def __init__(self, name):
        self.Name = name


class Manager:
    def __init__(self):
        self.calls = []
        self.feature = type("Feature", (), {
            "Name": "Trim/Extend1",
            "GetTypeName2": lambda self: "WeldCornerFeat",
            "GetNextFeature": lambda self: None,
        })()

    def InsertWeldmentTrimFeature2(self, *args):
        self.calls.append(args)
        return self.feature


class Document:
    Name = "Weldment"

    def __init__(self, names=("Member A", "Member B"), weldment=True):
        self.bodies = [Body(name) for name in names]
        self.FeatureManager = Manager()
        self.clears = []
        self.weldment = weldment
        self.in_tree = True

    def FirstFeature(self):
        if not self.weldment:
            return None
        return self

    def GetTypeName2(self):
        return "WeldmentFeature"

    def GetNextFeature(self):
        return self.FeatureManager.feature if self.in_tree else None

    def GetType(self):
        return 1

    def GetBodies2(self, body_type, visible_only):
        assert body_type == 0 and visible_only is False
        return self.bodies

    def ForceRebuild3(self, top_only):
        return True

    def ClearSelection2(self, clear_all):
        self.clears.append(clear_all)


class Automation:
    def __init__(self, doc):
        self.doc = doc

    def get_active_doc(self):
        return self.doc, None

    @staticmethod
    def _result(success, message, error=None, data=None):
        return {"success": success, "message": message, "error": error,
                "data": data}


class WeldmentTrimTests(unittest.TestCase):
    def test_miter_passes_exact_bodies_zero_gap_and_explicit_weld_gap_option(self):
        doc = Document()
        sw = Automation(doc)
        with patch("solidworks_mcp.tools.weldments.win32com.client.VARIANT",
                   side_effect=lambda kind, bodies: (kind, bodies)) as variant:
            result = trim_weldment_members(sw, "Member A", "Member B")

        self.assertTrue(result["success"], result)
        self.assertEqual("Trim/Extend1", result["data"]["feature"])
        self.assertEqual(2, variant.call_count)
        self.assertEqual(1, len(doc.FeatureManager.calls))
        end_condition, options, gap, trimmed, boundary = doc.FeatureManager.calls[0]
        self.assertEqual(1, end_condition)  # swEndConditionMiter
        self.assertEqual(8, options & 8)  # explicit zero WeldGap, not last UI value
        self.assertEqual(0.0, gap)
        self.assertIs(doc.bodies[0], trimmed[1][0])
        self.assertIs(doc.bodies[1], boundary[1][0])
        self.assertEqual([True, True], doc.clears)

    def test_unknown_or_identical_bodies_never_call_feature_manager(self):
        for a, b in (("Missing", "Member B"), ("Member A", "Member A")):
            with self.subTest(a=a, b=b):
                doc = Document()
                result = trim_weldment_members(Automation(doc), a, b)
                self.assertFalse(result["success"])
                self.assertFalse(doc.FeatureManager.calls)

    def test_non_weldment_part_is_rejected_without_mutation(self):
        doc = Document(weldment=False)
        result = trim_weldment_members(Automation(doc), "Member A", "Member B")
        self.assertFalse(result["success"])
        self.assertFalse(doc.FeatureManager.calls)

    def test_com_failure_is_reported_and_selection_is_cleared(self):
        doc = Document()
        doc.FeatureManager.feature = None
        result = trim_weldment_members(Automation(doc), "Member A", "Member B")
        self.assertFalse(result["success"])
        self.assertEqual([True, True], doc.clears)

    def test_com_proxy_without_feature_in_tree_is_not_reported_as_success(self):
        doc = Document()
        doc.in_tree = False
        result = trim_weldment_members(Automation(doc), "Member A", "Member B")
        self.assertFalse(result["success"])

    def test_tool_is_registered_as_mutating_only_the_active_part(self):
        self.assertIn("trim_weldment_members", [tool.name for tool in registered_tools()])
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("trim_weldment_members"))


if __name__ == "__main__":
    unittest.main()
