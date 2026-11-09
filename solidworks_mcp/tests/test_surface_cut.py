"""Surface cut must produce a measurable solid-volume reduction."""

import unittest
from unittest.mock import patch

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.surface_features import cut_with_surface


class Surface(Feature):
    def __init__(self):
        super().__init__("Surface-Plane1", "PlanarSurface")
        self.selected = []

    def Select2(self, append, mark):
        self.selected.append((append, mark))
        return True


class Cut(Feature):
    def __init__(self):
        super().__init__("SurfaceCut1", "SurfCut")

    def GetErrorCode(self):
        return 0


class CutDocument(Document):
    def __init__(self):
        super().__init__()
        self.surface = Surface()
        self.features.append(self.surface)

    def InsertCutSurface(self, flip, keep_piece):
        self.args = (flip, keep_piece)
        self.features.append(Cut())


class CutSurfaceTests(unittest.TestCase):
    @patch("solidworks_mcp.tools.surface_features._solid_volume_mm3", side_effect=[16000, 8000])
    def test_surface_selection_and_volume_decrease(self, volume):
        doc = CutDocument()
        result = cut_with_surface(Automation(doc), "Surface-Plane1", flip=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 0)], doc.surface.selected)
        self.assertEqual((True, -1), doc.args)
        self.assertEqual(8000, result["data"]["volume_after_mm3"])

    @patch("solidworks_mcp.tools.surface_features._solid_volume_mm3", side_effect=[16000, 16000])
    def test_unchanged_volume_fails(self, volume):
        result = cut_with_surface(Automation(CutDocument()), "Surface-Plane1")
        self.assertFalse(result["success"])

    def test_invalid_name_precedes_com(self):
        sw = Automation(CutDocument())
        self.assertFalse(cut_with_surface(sw, " ")["success"])
        self.assertEqual(0, sw.active_doc_calls)
