"""Sweep chooses profile and path by different marks, producing sheet area."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tests.test_surface_loft import Profile
from solidworks_mcp.tests.test_surface_ruled import Sheet
from solidworks_mcp.tools.surface_features import sweep_surface


class SweepFeature(Feature):
    def __init__(self):
        super().__init__("Surface-Sweep1", "SweepRefSurface")

    def GetErrorCode(self):
        return 0


class SweepDocument(Document):
    def __init__(self):
        super().__init__()
        self.profiles = [Profile("Sketch1"), Profile("Sketch2")]
        self.features.extend(self.profiles)
        self.sheets = []

    def GetBodies2(self, kind, visible):
        return self.sheets[:]

    def InsertSweepRefSurface(self, *args):
        self.args = args
        self.sheets.append(Sheet(628.3 / 1e6))
        self.features.append(SweepFeature())


class SweepSurfaceTests(unittest.TestCase):
    def test_distinct_selection_marks_and_new_sheet(self):
        doc = SweepDocument()
        result = sweep_surface(Automation(doc), "Sketch1", "Sketch2")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 1)], doc.profiles[0].selection)
        self.assertEqual([(True, 4)], doc.profiles[1].selection)
        self.assertEqual((False, 0, False, False), doc.args)
        self.assertAlmostEqual(628.3, result["data"]["area_after_mm2"])

    def test_same_sketch_precedes_com(self):
        sw = Automation(SweepDocument())
        self.assertFalse(sweep_surface(sw, "Sketch1", "Sketch1")["success"])
        self.assertEqual(0, sw.active_doc_calls)
