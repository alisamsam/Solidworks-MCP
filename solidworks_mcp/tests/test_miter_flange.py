"""S3 miter flange: select a real profile AND an edge, then prove geometry."""

import unittest
from types import MethodType

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tests.test_edge_flange import (
    Automation, Feature, Sketch, SketchLine, fixture,
)
from solidworks_mcp.tools.sheetmetal import create_miter_flange


class MiterManager:
    def __init__(self, document):
        self.document = document
        self.calls = []

    def InsertSheetMetalMiterFlange(self, *args):
        self.calls.append(args)
        self.document.apply_flange()
        return self.document.returned_feature


def miter_fixture(**kwargs):
    doc, edge = fixture(gained_mm3=1990.607, gained_faces=32, **kwargs)
    doc.returned_feature = Feature("Miter Flange1", "SMMiteredFlange")
    doc.sketch_feature = Feature("Sketch6", "ProfileFeature", sketch=Sketch([
        SketchLine((0.001, 0.050), (0.01039, 0.050)),
        SketchLine((0.01039, 0.050), (0.012226, 0.051886)),
        SketchLine((0.012226, 0.051886), (0.012226, 0.057039)),
        SketchLine((0.012226, 0.057039), (0.01039, 0.058397)),
    ]))
    doc.sheet_metal.next = doc.sketch_feature
    doc.feature_manager = MiterManager(doc)
    doc.FeatureManager = doc.feature_manager
    doc.GetActiveSketch2 = MethodType(lambda self: None, doc)
    return doc, edge


class MiterFlangeUnitTests(unittest.TestCase):
    def test_selects_edge_and_existing_sketch_and_proves_added_material(self):
        doc, edge = miter_fixture()
        result = create_miter_flange(Automation(doc), 0, "Sketch6")

        self.assertTrue(result["success"], result)
        self.assertEqual([False], edge.selected)
        self.assertEqual(1, doc.sketch_feature.selects)
        self.assertEqual(1, len(doc.feature_manager.calls))
        call = doc.feature_manager.calls[0]
        self.assertEqual(14, len(call))
        self.assertEqual((True, 0.001, 0.00025, True, False, 0.05,
                          0.0, 0.0, 1, False, 1, 0.0, 0.0), call[:-1])
        self.assertIsNone(call[-1].value)
        self.assertEqual("SMMiteredFlange", result["data"]["feature_type"])
        self.assertEqual("Sketch6", result["data"]["sketch"])
        self.assertEqual("Sheet", result["data"]["edge_body"])
        self.assertAlmostEqual(1990.607, result["data"]["gained_mm3"], places=3)
        self.assertAlmostEqual(5000, result["data"]["volume_before_mm3"])
        self.assertAlmostEqual(6990.607, result["data"]["volume_after_mm3"])
        self.assertEqual((6, 38), (result["data"]["faces_before"],
                                     result["data"]["faces_after"]))

    def test_invalid_input_never_calls_feature_manager(self):
        for edge, sketch in [(-1, "Sketch6"), (True, "Sketch6"),
                             (0, ""), (0, None)]:
            with self.subTest(edge=edge, sketch=sketch):
                doc, _ = miter_fixture()
                result = create_miter_flange(Automation(doc), edge, sketch)
                self.assertFalse(result["success"])
                self.assertFalse(doc.feature_manager.calls)

    def test_missing_sheet_metal_edge_or_valid_profile_is_rejected(self):
        for setup in ("no sheet", "missing edge", "missing sketch", "empty",
                      "zero length"):
            with self.subTest(setup=setup):
                doc, _ = miter_fixture()
                if setup == "no sheet":
                    doc.head = None
                elif setup == "missing sketch":
                    doc.sketch_feature.Name = "OtherSketch"
                elif setup == "empty":
                    doc.sketch_feature.sketch.lines = []
                elif setup == "zero length":
                    doc.sketch_feature.sketch.lines[0] = SketchLine((0, 0), (0, 0))
                index = 100 if setup == "missing edge" else 0
                result = create_miter_flange(Automation(doc), index, "Sketch6")
                self.assertFalse(result["success"], (setup, result))
                self.assertFalse(doc.feature_manager.calls)

    def test_no_feature_or_no_geometry_is_not_success(self):
        for setup in ("none", "no volume", "no faces"):
            with self.subTest(setup=setup):
                doc, _ = miter_fixture()
                if setup == "none":
                    doc.returned_feature = None
                elif setup == "no volume":
                    doc.gained_mm3 = 0
                else:
                    doc.gained_faces = 0
                result = create_miter_flange(Automation(doc), 0, "Sketch6")
                self.assertFalse(result["success"], result)

    def test_registered_as_mutation(self):
        self.assertIn("create_miter_flange",
                      [tool.name for tool in registered_tools()])
        self.assertEqual(OperationClass.MUTATE,
                         operation_class_for("create_miter_flange"))


if __name__ == "__main__":
    unittest.main()
