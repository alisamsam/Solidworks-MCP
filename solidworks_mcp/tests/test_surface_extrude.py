"""Extruded sheet from a named 2D sketch."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.surface_features import extrude_surface


class ExtrudedFeature(Feature):
    def __init__(self):
        super().__init__("Surface-Extrude1", "ExtruRefSurface")

    def GetErrorCode(self):
        return 0


class SketchFeature(Feature):
    def __init__(self):
        super().__init__("Sketch2", "ProfileFeature")
        self.calls = []

    def Select2(self, append, mark):
        self.calls.append((append, mark))
        return True


class ExtrudedDocument(Document):
    def __init__(self):
        super().__init__()
        self.sketch = SketchFeature()
        self.features.append(self.sketch)
        self.FeatureManager = self

    def FeatureExtruRefSurface3(self, *args):
        self.args = args
        self.features.append(ExtrudedFeature())


class SurfaceExtrudeTests(unittest.TestCase):
    def test_sketch_selection_and_blind_depth(self):
        doc = ExtrudedDocument()
        result = extrude_surface(Automation(doc), "Sketch2", 10)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 0)], doc.sketch.calls)
        self.assertEqual(22, len(doc.args))
        self.assertEqual((True, False, 0, 0.0, 0, 0), doc.args[:6])
        self.assertAlmostEqual(0.01, doc.args[6])

    def test_bad_depth_precedes_com(self):
        sw = Automation(ExtrudedDocument())
        self.assertFalse(extrude_surface(sw, "Sketch2", float("inf"))["success"])
        self.assertEqual(0, sw.active_doc_calls)
