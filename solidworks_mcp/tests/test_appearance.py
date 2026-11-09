"""Part appearance should retain requested RGB components without altering others."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document
from solidworks_mcp.tools.appearance import set_appearance


class AppearanceDocument(Document):
    def __init__(self):
        super().__init__()
        self.MaterialPropertyValues = [0.5] * 9
        self.redraws = 0

    def GraphicsRedraw2(self):
        self.redraws += 1

    def __setattr__(self, name, value):
        if name == "MaterialPropertyValues" and hasattr(value, "value"):
            value = list(value.value)
        super().__setattr__(name, value)


class AppearanceTests(unittest.TestCase):
    def test_rgb_readback_preserves_other_values(self):
        doc = AppearanceDocument()
        result = set_appearance(Automation(doc), 1, 0.2, 0)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([1, 0.2, 0], result["data"]["rgb"])
        self.assertEqual([0.5] * 6, doc.MaterialPropertyValues[3:])
        self.assertEqual(1, doc.redraws)

    def test_bad_component_is_rejected_without_com(self):
        sw = Automation(AppearanceDocument())
        self.assertFalse(set_appearance(sw, float("nan"), 0, 0)["success"])
        self.assertEqual(0, sw.active_doc_calls)
