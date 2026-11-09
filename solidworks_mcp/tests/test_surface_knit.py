"""Knit requires two distinct named surfaces and a new feature."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.surface_features import knit_surface


class SheetFeature(Feature):
    def __init__(self, name):
        super().__init__(name, "PlanarSurface")
        self.marks = []

    def Select2(self, append, mark):
        self.marks.append((append, mark))
        return True


class KnitFeature(Feature):
    def __init__(self):
        super().__init__("Surface-Knit1", "SewRefSurface")

    def GetErrorCode(self):
        return 0


class KnitDocument(Document):
    def __init__(self):
        super().__init__()
        self.sources = [SheetFeature("Surface-Plane1"), SheetFeature("Surface-Plane2")]
        self.features.extend(self.sources)
        self.FeatureManager = self

    def InsertSewRefSurface(self, *args):
        self.args = args
        feature = KnitFeature()
        self.features.append(feature)
        return feature


class KnitTests(unittest.TestCase):
    def test_selects_sources_with_mark_one_and_creates_knit(self):
        doc = KnitDocument()
        result = knit_surface(Automation(doc), ["Surface-Plane1", "Surface-Plane2"])
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([[(False, 1)], [(True, 1)]], [sheet.marks for sheet in doc.sources])
        self.assertEqual((False, False, True, 0.00001, 0.0), doc.args)

    def test_duplicate_names_rejected_before_com(self):
        automation = Automation(KnitDocument())
        self.assertFalse(knit_surface(automation, ["Surface-Plane1"] * 2)["success"])
        self.assertEqual(0, automation.active_doc_calls)
