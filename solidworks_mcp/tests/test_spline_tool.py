import unittest
from unittest.mock import patch

from solidworks_mcp.automation.sketches import SketchOperations


class SketchManager:
    def __init__(self):
        self.CreateSpline = None
        self.flagged = []
        self.points = None

    def _FlagAsMethod(self, name):
        self.flagged.append(name)
        self.CreateSpline = self._create_spline

    def _create_spline(self, points):
        self.points = points
        return object()


class Document:
    def __init__(self):
        self.SketchManager = SketchManager()


class Units:
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


class SplineToolTests(unittest.TestCase):
    def test_spline_flags_solidworks_2025_property_as_method(self):
        automation = Automation()

        with patch("solidworks_mcp.automation.sketches.win32com.client.VARIANT", side_effect=lambda kind, value: value):
            result = automation.draw_spline([[0, 0], [10, 5], [20, 0]], "mm")

        self.assertTrue(result["success"])
        self.assertEqual(["CreateSpline"], automation.document.SketchManager.flagged)
        self.assertEqual([0.0, 0.0, 0.0, 0.01, 0.005, 0.0, 0.02, 0.0, 0.0],
                         automation.document.SketchManager.points)


if __name__ == "__main__":
    unittest.main()
