"""Planar surface from a closed sketch's boundary segments."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature, SelectionManager
from solidworks_mcp.tools.surface_features import planar_surface


class Segment:
    def __init__(self):
        self.marks = []

    def Select4(self, append, data):
        self.marks.append((append, data.Mark))
        return True


class SketchFeature(Feature):
    def __init__(self, segments):
        super().__init__("Sketch2", "ProfileFeature")
        self.segments = segments

    def GetSpecificFeature2(self):
        return self

    def GetSketchSegments(self):
        return self.segments


class SurfaceFeature(Feature):
    def __init__(self):
        super().__init__("Surface-Plane1", "PlanarSurface")

    def GetErrorCode(self):
        return 0


class PlanarDocument(Document):
    def __init__(self, created=True):
        super().__init__()
        self.segments = [Segment() for _ in range(4)]
        self.features.append(SketchFeature(self.segments))
        self.created = created
        self.SelectionManager = SelectionManager()

    def InsertPlanarRefSurface(self):
        if self.created:
            self.features.append(SurfaceFeature())
        return self.created


class PlanarSurfaceTests(unittest.TestCase):
    def test_selects_all_boundary_segments_with_mark_one(self):
        document = PlanarDocument()
        result = planar_surface(Automation(document), "Sketch2")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("Surface-Plane1", result["data"]["feature_name"])
        self.assertEqual([[(i > 0, 1)] for i in range(4)],
                         [segment.marks for segment in document.segments])

    def test_invalid_input_and_creation_failure(self):
        automation = Automation(PlanarDocument())
        self.assertFalse(planar_surface(automation, " ")["success"])
        self.assertEqual(0, automation.active_doc_calls)
        result = planar_surface(Automation(PlanarDocument(created=False)), "Sketch2")
        self.assertFalse(result["success"])
