import unittest

from solidworks_mcp.automation.sketches import SketchOperations


class SketchManager:
    def __init__(self):
        self.args = None

    def CreateSketchSlot(self, *args):
        self.args = args
        return object()


class Document:
    def __init__(self):
        self.SketchManager = SketchManager()


class Units:
    default_unit = type("Default", (), {"value": "mm"})()

    @staticmethod
    def to_meters(value, unit):
        return value / 1000


class Automation(SketchOperations):
    def __init__(self):
        self.document = Document()
        self._units = Units()

    def get_active_doc(self):
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class SlotToolTests(unittest.TestCase):
    def test_center_to_center_slot_uses_expected_solidworks_signature(self):
        automation = Automation()

        result = automation.draw_slot(-20, 0, 20, 0, 10, "mm")

        self.assertTrue(result["success"])
        self.assertEqual(
            (0, 0, 0.01, -0.02, 0.0, 0.0, 0.02, 0.0, 0.0,
             0.0, 0.0, 0.0, 1, False),
            automation.document.SketchManager.args,
        )

    def test_slot_rejects_non_positive_width(self):
        automation = Automation()

        result = automation.draw_slot(-20, 0, 20, 0, 0, "mm")

        self.assertFalse(result["success"])
        self.assertIsNone(automation.document.SketchManager.args)

    def test_slot_rejects_identical_center_points(self):
        automation = Automation()

        result = automation.draw_slot(5, 5, 5, 5, 10, "mm")

        self.assertFalse(result["success"])
        self.assertIsNone(automation.document.SketchManager.args)


if __name__ == "__main__":
    unittest.main()
