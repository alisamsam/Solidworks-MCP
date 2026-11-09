"""Reference axis from the intersection of two named planes."""

import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for
from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.reference_geometry import create_reference_axis


class AxisExtension:
    def __init__(self):
        self.calls = []

    def SelectByID2(self, *args):
        self.calls.append(args)
        return True


class AxisDocument(Document):
    def __init__(self):
        super().__init__()
        self.Extension = AxisExtension()

    def InsertAxis2(self, auto_size):
        self.features.append(Feature("Axis1", "RefAxis"))
        return True


class ReferenceAxisTests(unittest.TestCase):
    def test_selects_two_planes_and_checks_new_axis(self):
        doc = AxisDocument()
        result = create_reference_axis(Automation(doc), "Front Plane", "Top Plane")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(OperationClass.MUTATE, operation_class_for("create_reference_axis"))
        self.assertEqual(["Front Plane", "Top Plane"],
                         [call[0] for call in doc.Extension.calls])
        self.assertEqual([False, True], [call[5] for call in doc.Extension.calls])
        self.assertEqual("Axis1", result["data"]["feature_name"])

    def test_validation_precedes_com(self):
        automation = Automation(AxisDocument())
        result = create_reference_axis(automation, "Top Plane", "Top Plane")
        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)
