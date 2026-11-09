import math
import unittest

from solidworks_mcp.automation.features import FeatureOperations


class FeatureManager:
    def __init__(self):
        self.args = None

    def FeatureRevolve2(self, *args):
        self.args = args
        return type("Feature", (), {"Name": "Revolve1"})()


class Document:
    def __init__(self):
        self.FeatureManager = FeatureManager()


class Automation(FeatureOperations):
    def __init__(self):
        self.document = Document()

    def get_active_doc(self):
        return self.document, None

    def _close_and_select_sketch(self, doc):
        return True, "Sketch1", ""

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class RevolveFeatureTests(unittest.TestCase):
    def test_revolve_uses_solid_centerline_profile_contract(self):
        automation = Automation()

        result = automation.revolve_sketch(180, "centerline")

        self.assertTrue(result["success"])
        self.assertEqual(
            (True, True, False, False, False, False, 0, 0,
             math.pi, 0.0, False, False, 0.0, 0.0, 0,
             0.0, 0.0, True, True, True),
            automation.document.FeatureManager.args,
        )
        self.assertEqual("Revolve1", result["data"]["feature_name"])

    def test_revolve_rejects_angle_outside_supported_range(self):
        automation = Automation()

        zero = automation.revolve_sketch(0, "centerline")
        too_large = automation.revolve_sketch(361, "centerline")

        self.assertFalse(zero["success"])
        self.assertFalse(too_large["success"])
        self.assertIsNone(automation.document.FeatureManager.args)

    def test_revolve_rejects_unsupported_axis_mode(self):
        automation = Automation()

        result = automation.revolve_sketch(360, "x")

        self.assertFalse(result["success"])
        self.assertIsNone(automation.document.FeatureManager.args)


if __name__ == "__main__":
    unittest.main()
