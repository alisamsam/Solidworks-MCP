"""Uniform scaling of one selected solid body."""

import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for
from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.body_features import scale_body


class Body:
    def __init__(self, selected=True):
        self.selected = selected
        self.calls = []

    def Select2(self, append, data):
        self.calls.append((append, data))
        return self.selected


class Manager:
    def __init__(self, document):
        self.document = document
        self.calls = []
        self.creates = True

    def InsertScale(self, origin, uniform, x, y, z):
        self.calls.append((origin, uniform, x, y, z))
        if not self.creates:
            return None
        feature = Feature("Scale1", "Scale")
        self.document.features.append(feature)
        return feature


class ScaleDocument(Document):
    def __init__(self, bodies=None):
        super().__init__()
        self.bodies = [Body()] if bodies is None else bodies
        self.FeatureManager = Manager(self)

    def GetBodies2(self, body_type, visible):
        assert (body_type, visible) == (0, True)
        return self.bodies


class ScaleBodyTests(unittest.TestCase):
    def test_selects_only_requested_body_and_scales_about_origin(self):
        document = ScaleDocument([Body(), Body()])
        result = scale_body(Automation(document), body_index=1, factor=2, origin="origin")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(OperationClass.MUTATE, operation_class_for("scale_body"))
        self.assertEqual([], document.bodies[0].calls)
        self.assertEqual(1, len(document.bodies[1].calls))
        self.assertEqual([(1, True, 2, 2, 2)], document.FeatureManager.calls)
        self.assertEqual("Scale1", result["data"]["feature_name"])

    def test_invalid_input_precedes_com(self):
        automation = Automation(ScaleDocument())
        for kwargs in ({"body_index": -1, "factor": 2},
                       {"body_index": True, "factor": 2},
                       {"body_index": 0, "factor": 0},
                       {"body_index": 0, "factor": float("nan")},
                       {"body_index": 0, "factor": 2, "origin": "arbitrary"}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(scale_body(automation, **kwargs)["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_missing_body_or_failed_selection_does_not_insert(self):
        document = ScaleDocument([Body(selected=False)])
        self.assertFalse(scale_body(Automation(document), 0, 2)["success"])
        self.assertFalse(scale_body(Automation(document), 2, 2)["success"])
        self.assertEqual([], document.FeatureManager.calls)

    def test_insert_failure_is_reported(self):
        document = ScaleDocument()
        document.FeatureManager.creates = False
        result = scale_body(Automation(document), 0, 2)
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
