import unittest

from solidworks_mcp.automation.sketches import SketchOperations


class SketchManager:
    def __init__(self):
        self.args = None

    def Create3PointArc(self, *args):
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


class ThreePointArcTests(unittest.TestCase):
    def test_arc_passes_start_end_and_point_on_arc_in_meters(self):
        automation = Automation()

        result = automation.draw_arc_3point(0, 0, 20, 0, 10, 8, "mm")

        self.assertTrue(result["success"])
        self.assertEqual((0.0, 0.0, 0.0, 0.02, 0.0, 0.0, 0.01, 0.008, 0.0),
                         automation.document.SketchManager.args)


if __name__ == "__main__":
    unittest.main()
