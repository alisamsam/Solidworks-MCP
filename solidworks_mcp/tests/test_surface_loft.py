"""Two ordered section sketches produce a nonzero sheet body."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tests.test_surface_ruled import SelectionManager, Sheet
from solidworks_mcp.tools.surface_features import loft_surface


class Profile(Feature):
    def __init__(self, name):
        super().__init__(name, "ProfileFeature")
        self.selection = []

    def Select2(self, append, mark):
        self.selection.append((append, mark))
        return True


class LoftFeature(Feature):
    def __init__(self):
        super().__init__("Surface-Loft1", "BlendRefSurface")

    def GetErrorCode(self):
        return 0


class LoftDocument(Document):
    def __init__(self):
        super().__init__()
        self.profiles = [Profile("Sketch1"), Profile("Sketch2")]
        self.features.extend(self.profiles)
        self.SelectionManager = SelectionManager()
        self.sheets = []

    def GetBodies2(self, kind, visible):
        return self.sheets[:]

    def InsertLoftRefSurface(self, *args):
        self.args = args
        self.sheets.append(Sheet(1200 / 1e6))
        self.features.append(LoftFeature())


class LoftSurfaceTests(unittest.TestCase):
    def test_creates_sheet_from_ordered_profiles(self):
        doc = LoftDocument()
        result = loft_surface(Automation(doc), ["Sketch1", "Sketch2"])
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 1)], doc.profiles[0].selection)
        self.assertEqual([(True, 1)], doc.profiles[1].selection)
        self.assertEqual((False, False, False), doc.args)
        self.assertAlmostEqual(1200, result["data"]["area_after_mm2"])

    def test_duplicate_profile_rejected_before_com(self):
        sw = Automation(LoftDocument())
        self.assertFalse(loft_surface(sw, ["Sketch1", "Sketch1"])["success"])
        self.assertEqual(0, sw.active_doc_calls)
