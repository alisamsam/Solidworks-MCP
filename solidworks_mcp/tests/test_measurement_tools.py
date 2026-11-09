import unittest

from solidworks_mcp.tools.measurements import (
    get_body_bounding_box,
    get_mass_properties,
    measure_distance,
)


class MassProperty:
    Volume = 1e-6
    SurfaceArea = 6e-4
    Mass = 0.00785
    Density = 7850.0
    CenterOfMass = (0.001, 0.002, 0.003)


class Extension:
    def CreateMassProperty(self):
        return MassProperty()


class Document:
    Extension = Extension()


class Automation:
    def get_active_doc(self):
        return Document(), None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class Body:
    def __init__(self, name, box):
        self.Name = name
        self.GetBodyBox = box


class BodyDocument:
    def GetBodies2(self, body_type, visible_only):
        return [
            Body("Body1", (0.0, -0.01, -0.02, 0.03, 0.01, 0.02)),
            Body("Body2", (0.04, -0.005, -0.005, 0.05, 0.005, 0.005)),
        ]


class BodyAutomation(Automation):
    def get_active_doc(self):
        return BodyDocument(), None


class Face:
    class Surface:
        IsPlane = True

    GetSurface = Surface()

    def __init__(self):
        self.select_calls = []

    def Select4(self, append, data):
        self.select_calls.append(append)
        return True


class FaceBody:
    def __init__(self, faces):
        self.GetFaces = faces


class Measure:
    Distance = 0.1
    DeltaX = 0.1
    DeltaY = 0.0
    DeltaZ = 0.0
    NormalDistance = 0.1
    IsIntersect = False
    IsParallel = True

    def __init__(self):
        self.entities = None
        self.flagged_methods = []

    def _FlagAsMethod(self, name):
        self.flagged_methods.append(name)

    def Calculate(self, entities):
        self.entities = entities
        return True


class MeasurementExtension:
    def __init__(self):
        self.measure = Measure()

    def CreateMeasure(self):
        return self.measure


class FaceDocument:
    def __init__(self):
        self.faces = [Face(), Face()]
        self.Extension = MeasurementExtension()
        self.clear_calls = []

    def GetBodies2(self, body_type, visible_only):
        return [FaceBody(self.faces)]

    def ClearSelection2(self, clear_all):
        self.clear_calls.append(clear_all)


class FaceAutomation(Automation):
    def __init__(self):
        self.document = FaceDocument()

    def get_active_doc(self):
        return self.document, None


class MeasurementToolTests(unittest.TestCase):
    def test_mass_properties_include_si_display_values_and_density_evidence(self):
        result = get_mass_properties(Automation(), "mm")

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(1e-6, data["si"]["volume_m3"])
        self.assertEqual(1000.0, data["display"]["volume"])
        self.assertEqual("mm^3", data["display"]["volume_unit"])
        self.assertEqual([1.0, 2.0, 3.0], data["display"]["center_of_mass"])
        self.assertEqual(7850.0, data["material_evidence"]["density_kg_m3"])
        self.assertEqual("IMassProperty", data["material_evidence"]["source"])

    def test_bounding_box_aggregates_all_bodies_and_marks_accuracy(self):
        result = get_body_bounding_box(BodyAutomation(), "mm")

        self.assertTrue(result["success"])
        combined = result["data"]["combined"]
        self.assertEqual({"x": 50.0, "y": 20.0, "z": 40.0}, combined["size"])
        self.assertEqual("approximate", result["data"]["accuracy"])
        self.assertEqual(2, len(result["data"]["bodies"]))

    def test_measure_distance_reports_kernel_minimum_and_axis_deltas(self):
        automation = FaceAutomation()

        result = measure_distance(automation, 0, 1, "mm")

        self.assertTrue(result["success"])
        self.assertIsNone(automation.document.Extension.measure.entities)
        self.assertEqual([False], automation.document.faces[0].select_calls)
        self.assertEqual([True], automation.document.faces[1].select_calls)
        self.assertEqual(["Calculate"],
                         automation.document.Extension.measure.flagged_methods)
        self.assertEqual([True, True], automation.document.clear_calls)
        self.assertEqual(100.0, result["data"]["distance"])
        self.assertEqual({"x": 100.0, "y": 0.0, "z": 0.0},
                         result["data"]["delta"])
        self.assertEqual("minimum", result["data"]["distance_kind"])
        self.assertEqual("kernel", result["data"]["accuracy"])
        self.assertTrue(result["data"]["is_parallel"])

    def test_measure_distance_rejects_missing_or_identical_faces(self):
        automation = FaceAutomation()

        same = measure_distance(automation, 0, 0, "mm")
        missing = measure_distance(automation, 0, 3, "mm")

        self.assertFalse(same["success"])
        self.assertFalse(missing["success"])


if __name__ == "__main__":
    unittest.main()
