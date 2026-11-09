"""Delete/Keep Body must change both count and volume."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.body_features import delete_body


class Body:
    def __init__(self, volume):
        self.volume = volume
        self.selected = []

    def Select2(self, append, selection):
        self.selected.append(append)
        return True

    def GetMassProperties(self, accuracy):
        return [0, 0, 0, self.volume / 1e9]


class BodySelection:
    def CreateSelectData(self):
        return object()


class BodyDocument(Document):
    def __init__(self):
        super().__init__()
        self.bodies = [Body(100), Body(200), Body(300)]
        self.SelectionManager = BodySelection()
        self.FeatureManager = self

    def GetBodies2(self, kind, visible):
        return self.bodies[:]

    def InsertDeleteBody2(self, keep):
        selected = next(body for body in self.bodies if body.selected)
        self.bodies = [selected] if keep else [body for body in self.bodies if body is not selected]
        return Feature("DeleteBody1", "DeleteBody")


class DeleteBodyTests(unittest.TestCase):
    def test_delete_selected_body(self):
        doc = BodyDocument()
        result = delete_body(Automation(doc), 1)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(2, result["data"]["bodies_after"])
        self.assertAlmostEqual(400, result["data"]["volume_after_mm3"])

    def test_keep_only_selected_body(self):
        doc = BodyDocument()
        result = delete_body(Automation(doc), 1, keep_only=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, result["data"]["bodies_after"])
        self.assertAlmostEqual(200, result["data"]["volume_after_mm3"])

    def test_bad_index_precedes_com(self):
        sw = Automation(BodyDocument())
        self.assertFalse(delete_body(sw, -1)["success"])
        self.assertEqual(0, sw.active_doc_calls)
