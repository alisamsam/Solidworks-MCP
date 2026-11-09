"""Filled surface patches a closed sketch boundary with a single sheet."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.surface_features import filled_surface


class Segment:
    def Select4(self, append, data):
        raise AssertionError("filled_surface must select the sketch via SelectByID2, not segments")


class SketchFeature(Feature):
    def __init__(self, segments):
        super().__init__("Sketch3", "ProfileFeature")
        self.segments = segments

    def GetSpecificFeature2(self):
        return self

    def GetSketchSegments(self):
        return self.segments


class SurfaceFeature(Feature):
    def __init__(self):
        super().__init__("Surface-Fill1", "Filled Surface")

    def GetErrorCode(self):
        return 0


class Face:
    def __init__(self, area):
        self.area = area

    def GetArea(self):
        return self.area


class Sheet:
    def __init__(self, area):
        self.faces = [Face(area)]

    def GetFaces(self):
        return self.faces


class Extension:
    def __init__(self, succeeds=True):
        self.succeeds = succeeds
        self.calls = []

    def SelectByID2(self, name, type_name, x, y, z, append, mark, callout, error):
        self.calls.append((name, type_name, mark))
        return self.succeeds


class FilledDocument(Document):
    def __init__(self, segment_count=3, created=True, select_succeeds=True):
        super().__init__()
        self.segments = [Segment() for _ in range(segment_count)]
        self.features.append(SketchFeature(self.segments))
        self.sheets = []
        self.created = created
        self.Extension = Extension(select_succeeds)
        self.FeatureManager = self

    def GetBodies2(self, kind, visible):
        return self.sheets

    def InsertFillSurface(self, options):
        self.options = options
        if self.created:
            self.sheets.append(Sheet(900 / 1e6))
            return SurfaceFeature()
        return None


class FilledSurfaceTests(unittest.TestCase):
    def test_selects_sketch_boundary_by_id_and_fills_patch(self):
        document = FilledDocument()
        result = filled_surface(Automation(document), "Sketch3")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("Surface-Fill1", result["data"]["feature_name"])
        self.assertEqual(3, result["data"]["boundary_segments"])
        self.assertEqual([("Sketch3", "SKETCH", 1)], document.Extension.calls)
        self.assertEqual(0, document.options)
        self.assertAlmostEqual(900, result["data"]["area_after_mm2"])

    def test_invalid_input_and_creation_failure(self):
        automation = Automation(FilledDocument())
        self.assertFalse(filled_surface(automation, " ")["success"])
        self.assertEqual(0, automation.active_doc_calls)
        result = filled_surface(Automation(FilledDocument(created=False)), "Sketch3")
        self.assertFalse(result["success"])

    def test_missing_sketch_is_rejected(self):
        result = filled_surface(Automation(FilledDocument()), "NoSuchSketch")
        self.assertFalse(result["success"])

    def test_selection_failure_is_reported(self):
        result = filled_surface(Automation(FilledDocument(select_succeeds=False)), "Sketch3")
        self.assertFalse(result["success"])
