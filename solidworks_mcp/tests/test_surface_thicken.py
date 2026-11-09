"""Surface thicken turns a sheet into a measurable solid."""

import unittest
from unittest.mock import patch

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.surface_features import thicken_surface


class SourceSurface(Feature):
    def __init__(self, name="Surface-Plane1", kind="PlanarSurface"):
        super().__init__(name, kind)
        self.marks = []

    def Select2(self, append, mark):
        self.marks.append((append, mark))
        return True


class ThickenedFeature(Feature):
    def __init__(self):
        super().__init__("Thicken1", "BossThicken")

    def GetErrorCode(self):
        return 0


class ThickeningManager:
    def __init__(self):
        self.args = None

    def FeatureBossThicken(self, *args):
        self.args = args
        return ThickenedFeature()


class ThickeningDocument(Document):
    def __init__(self, name="Surface-Plane1", kind="PlanarSurface"):
        super().__init__()
        self.surface = SourceSurface(name, kind)
        self.features.append(self.surface)
        self.FeatureManager = ThickeningManager()


class ThickenTests(unittest.TestCase):
    @patch("solidworks_mcp.tools.surface_features._solid_volume_mm3", side_effect=[0, 1600])
    def test_selects_surface_and_proves_volume(self, volume):
        document = ThickeningDocument()
        result = thicken_surface(Automation(document), "Surface-Plane1", 1, side="both")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 1)], document.surface.marks)
        self.assertEqual((0.001, 2, 0, False, False, False, True),
                         document.FeatureManager.args)
        self.assertEqual(1600, result["data"]["volume_after_mm3"])

    def test_bad_thickness_is_rejected_before_com(self):
        automation = Automation(ThickeningDocument())
        self.assertFalse(thicken_surface(automation, "Surface-Plane1", -1)["success"])
        self.assertEqual(0, automation.active_doc_calls)

    @patch("solidworks_mcp.tools.surface_features._solid_volume_mm3", side_effect=[0, 800])
    def test_extruded_sheet_is_supported(self, volume):
        document = ThickeningDocument("Surface-Extrude1", "ExtruRefSurface")
        result = thicken_surface(Automation(document), "Surface-Extrude1", 2)
        self.assertTrue(result["success"], result["message"])
