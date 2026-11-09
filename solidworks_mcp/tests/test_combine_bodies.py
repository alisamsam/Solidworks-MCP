"""Combine add/subtract/common must prove resulting solid geometry."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Feature
from solidworks_mcp.tests.test_delete_body import Body, BodyDocument
from solidworks_mcp.tools.body_features import combine_bodies


class CombineFeature(Feature):
    def __init__(self):
        super().__init__("Combine1", "Combine")

    def GetErrorCode(self):
        return 0


class CombineDocument(BodyDocument):
    def __init__(self):
        super().__init__()
        self.bodies = [Body(4000), Body(4000)]
        self.FeatureManager = self

    def InsertCombineFeature(self, operation_type, main_body, tool_bodies):
        self.operation = operation_type
        self.tools = tool_bodies.value
        self.main = main_body
        self.bodies = [Body(6000 if operation_type == 15903 else 2000)]
        return CombineFeature()


class CombineBodyTests(unittest.TestCase):
    def test_three_operations_have_distinct_verified_results(self):
        for operation, enum, volume, tool_count in (
            ("add", 15903, 6000, 2),
            ("subtract", 15902, 2000, 1),
            ("common", 15901, 2000, 2),
        ):
            with self.subTest(operation=operation):
                doc = CombineDocument()
                result = combine_bodies(Automation(doc), 0, 1, operation)
                self.assertTrue(result["success"], result["message"])
                self.assertEqual(enum, doc.operation)
                self.assertEqual(tool_count, len(doc.tools))
                self.assertAlmostEqual(volume, result["data"]["volume_after_mm3"])
                self.assertEqual(1, result["data"]["bodies_after"])

    def test_same_body_is_rejected_before_com(self):
        sw = Automation(CombineDocument())
        self.assertFalse(combine_bodies(sw, 0, 0, "add")["success"])
        self.assertEqual(0, sw.active_doc_calls)
