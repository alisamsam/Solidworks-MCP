"""A positive sheet offset selects its source and verifies a new feature."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.surface_features import offset_surface


class SelectableSurface(Feature):
    def __init__(self):
        super().__init__("Surface-Plane1", "PlanarSurface")
        self.selections = []

    def Select2(self, append, mark):
        self.selections.append((append, mark))
        return True


class OffsetFeature(Feature):
    def __init__(self):
        super().__init__("Surface-Offset1", "OffsetRefSurface")

    def GetErrorCode(self):
        return 0


class OffsetDocument(Document):
    def __init__(self):
        super().__init__()
        self.surface = SelectableSurface()
        self.features.append(self.surface)

    def InsertOffsetSurface(self, distance, reverse):
        self.args = (distance, reverse)
        self.features.append(OffsetFeature())


class OffsetTests(unittest.TestCase):
    def test_creates_offset_with_converted_distance(self):
        doc = OffsetDocument()
        result = offset_surface(Automation(doc), "Surface-Plane1", 3,
                                reverse=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 0)], doc.surface.selections)
        self.assertEqual((0.003, True), doc.args)

    def test_rejects_non_finite_distance_before_com(self):
        sw = Automation(OffsetDocument())
        self.assertFalse(offset_surface(sw, "Surface-Plane1", float("inf"))["success"])
        self.assertEqual(0, sw.active_doc_calls)
