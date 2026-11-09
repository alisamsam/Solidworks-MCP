"""Revolved sheet from an open sketch with a construction axis."""

import math
import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.surface_features import revolve_surface


class RevolvedFeature(Feature):
    def __init__(self):
        super().__init__("Surface-Revolve1", "RevolvRefSurf")

    def GetErrorCode(self):
        return 0


class SketchFeature(Feature):
    def __init__(self):
        super().__init__("Sketch2", "ProfileFeature")
        self.marks = []

    def Select2(self, append, mark):
        self.marks.append((append, mark))
        return True


class RevolvedDocument(Document):
    def __init__(self):
        super().__init__()
        self.sketch = SketchFeature()
        self.features.append(self.sketch)
        self.FeatureManager = self

    def InsertRevolvedRefSurface(self, *args):
        self.args = args
        feature = RevolvedFeature()
        self.features.append(feature)
        return feature


class SurfaceRevolveTests(unittest.TestCase):
    def test_revolves_named_sketch_with_radian_angle(self):
        document = RevolvedDocument()
        result = revolve_surface(Automation(document), "Sketch2", 180)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 0)], document.sketch.marks)
        self.assertEqual((math.pi, False, 0.0, 0), document.args)

    def test_angle_validation_precedes_com(self):
        automation = Automation(RevolvedDocument())
        self.assertFalse(revolve_surface(automation, "Sketch2", float("nan"))["success"])
        self.assertEqual(0, automation.active_doc_calls)
