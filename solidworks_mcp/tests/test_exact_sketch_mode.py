import unittest

from solidworks_mcp.automation.sketches import SketchOperations


class Extension:
    def SelectByID2(self, *args):
        return True


class SketchManager:
    def __init__(self):
        self.AddToDB = False

    def CreateArc(self, *args):
        return object()


class Units:
    def to_meters(self, value, unit):
        return value / 1000.0

    class default_unit:
        value = "mm"


class Document:
    def __init__(self):
        self.Extension = Extension()
        self.SketchManager = SketchManager()
        self.insert_calls = 0

    def InsertSketch2(self, update):
        self.insert_calls += 1

    def ClearSelection2(self, clear_all):
        return True


class Automation(SketchOperations):
    def __init__(self):
        self.document = Document()
        self._units = Units()

    def get_active_doc(self):
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class ExactSketchModeTests(unittest.TestCase):
    def test_create_sketch_enables_exact_geometry_only_when_requested(self):
        automation = Automation()

        result = automation.create_sketch("Front", exact_geometry=True)

        self.assertTrue(result["success"])
        self.assertTrue(automation.document.SketchManager.AddToDB)
        self.assertTrue(result["data"]["exact_geometry"])

    def test_create_sketch_refuses_a_plane_it_does_not_know(self):
        # It used to fall back to Front Plane silently for any other name.
        automation = Automation()

        result = automation.create_sketch("Plane1")

        self.assertFalse(result["success"])
        self.assertIn("create_sketch_on_plane", result["message"])
        self.assertEqual(0, automation.document.insert_calls)

    def test_arc_angle_is_measured_counter_clockwise_from_start_to_end(self):
        # CreateArc runs counter-clockwise: 90 -> 0 degrees is a 270 degree arc.
        result = Automation().draw_arc_center(0, 0, 20, 90, 0, "mm")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(270, result["data"]["arc_angle"])
        self.assertIn("270", result["message"])

    def test_exit_sketch_always_restores_normal_inference_mode(self):
        automation = Automation()
        automation.document.SketchManager.AddToDB = True

        result = automation.exit_sketch()

        self.assertTrue(result["success"])
        self.assertFalse(automation.document.SketchManager.AddToDB)


if __name__ == "__main__":
    unittest.main()
