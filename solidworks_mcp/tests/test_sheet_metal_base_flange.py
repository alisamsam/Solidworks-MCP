import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.sheetmetal import (
    create_sheet_metal_base_flange, export_flat_pattern,
)


class Feature:
    def __init__(self, type_name, name="Feature"):
        self.type_name = type_name
        self.feature_name = name
        self.next = None

    def GetNextFeature(self):
        return self.next

    def GetTypeName2(self):
        return self.type_name

    def Name(self):
        return self.feature_name


class FeatureManager:
    def __init__(self, document, result_type="SheetMetal"):
        self.document = document
        self.calls = []
        self.result_type = result_type

    def InsertSheetMetalBaseFlange(self, *args):
        self.calls.append(args)
        if self.result_type is None:
            return None
        self.document.features = [Feature(self.result_type, "Sheet-Metal1")]
        return Feature("SMBaseFlange", "Base-Flange1")


class Document:
    def __init__(self, features=(), path="", result_type="SheetMetal"):
        self.FeatureManager = FeatureManager(self, result_type)
        self.features = list(features)
        self.path = path
        self.export_calls = []

    def FirstFeature(self):
        if not self.features:
            return None
        for current, following in zip(self.features, self.features[1:]):
            current.next = following
        return self.features[0]

    def GetPathName(self):
        return self.path

    def ExportToDWG2(self, *args):
        self.export_calls.append(args)
        return True


class Automation:
    def __init__(self, document=None, sketch_ok=True):
        self.document = document or Document()
        self.sketch_ok = sketch_ok

    def get_active_doc(self):
        return self.document, None

    def _close_and_select_sketch(self, doc):
        return (self.sketch_ok, "Sketch1", "" if self.sketch_ok else "no sketch")

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message,
                "error_code": int(error_code), "data": data or {}}


class BaseFlangeRegistrationTests(unittest.TestCase):
    def test_registered_as_mutation(self):
        names = {item.name for item in registered_tools()}

        self.assertIn("create_sheet_metal_base_flange", names)
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("create_sheet_metal_base_flange"))


class BaseFlangeTests(unittest.TestCase):
    def test_creates_feature_with_converted_metre_arguments(self):
        automation = Automation()

        result = create_sheet_metal_base_flange(automation, 2.0,
                                               bend_radius_mm=1.0,
                                               width_mm=100.0)

        self.assertTrue(result["success"], result["message"])
        (thickness, thicken_dir, radius, dist1, dist2, flip, ec1, ec2,
         dir_use, callout, use_default_relief, relief_type, relief_width,
         relief_depth, relief_ratio, use_relief_ratio) = \
            automation.document.FeatureManager.calls[0]
        self.assertAlmostEqual(0.002, thickness)
        self.assertAlmostEqual(0.001, radius)
        self.assertAlmostEqual(0.05, dist1)
        self.assertAlmostEqual(0.05, dist2, msg="width is split on both sides")
        self.assertFalse(thicken_dir)
        self.assertFalse(flip)
        self.assertEqual(2.0, result["data"]["thickness_mm"])
        self.assertEqual("Sheet-Metal1", result["data"]["sheet_metal_feature"])

    def test_bend_radius_defaults_to_thickness(self):
        automation = Automation()

        create_sheet_metal_base_flange(automation, 3.0)

        self.assertAlmostEqual(0.003,
                               automation.document.FeatureManager.calls[0][2])

    def test_feature_returned_without_sheet_metal_is_a_failure(self):
        automation = Automation(Document(result_type="BossExtrude"))

        result = create_sheet_metal_base_flange(automation, 2.0)

        self.assertFalse(result["success"])
        self.assertEqual("FEATURE_CREATE_FAILED", result["data"]["code"])

    def test_existing_sheet_metal_feature_is_rejected(self):
        automation = Automation(
            Document(features=[Feature("SheetMetal", "Sheet-Metal1")]))

        result = create_sheet_metal_base_flange(automation, 2.0)

        self.assertFalse(result["success"])
        self.assertEqual("ALREADY_SHEET_METAL", result["data"]["code"])
        self.assertEqual([], automation.document.FeatureManager.calls)

    def test_input_validation_happens_before_com(self):
        automation = Automation()

        for kwargs in ({"thickness_mm": 0}, {"thickness_mm": -1},
                       {"thickness_mm": 2.0, "width_mm": 0},
                       {"thickness_mm": 2.0, "bend_radius_mm": -1}):
            with self.subTest(kwargs=kwargs):
                result = create_sheet_metal_base_flange(automation, **kwargs)
                self.assertFalse(result["success"])
                self.assertEqual("VALIDATION_FAILED", result["data"]["code"])
        self.assertEqual([], automation.document.FeatureManager.calls)

    def test_missing_sketch_is_reported(self):
        automation = Automation(sketch_ok=False)

        result = create_sheet_metal_base_flange(automation, 2.0)

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.FeatureManager.calls)


class FlatPatternExportTests(unittest.TestCase):
    def test_unsaved_model_is_rejected_before_exporting(self):
        automation = Automation(Document(features=[Feature("SheetMetal")],
                                         path=""))

        result = export_flat_pattern(automation, "C:/out/part.dxf")

        self.assertFalse(result["success"])
        self.assertEqual("UNSAVED_DOCUMENT", result["data"]["code"])
        self.assertEqual([], automation.document.export_calls)

    def test_saved_model_exports_with_its_path_as_base_name(self):
        automation = Automation(Document(features=[Feature("SheetMetal")],
                                         path="C:/models/part.SLDPRT"))

        result = export_flat_pattern(automation, "C:/out/part.dxf")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual("C:/models/part.SLDPRT",
                         automation.document.export_calls[0][1])


if __name__ == "__main__":
    unittest.main()
