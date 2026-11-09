"""Tangent ruled surface must add measurable sheet area."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.surface_features import ruled_surface


class Edge:
    def __init__(self):
        self.marks = []

    def Select4(self, append, data):
        self.marks.append(data.Mark)
        return True


class Face:
    def __init__(self, area):
        self.area = area

    def GetArea(self):
        return self.area


class Sheet:
    def __init__(self, area):
        self.faces = [Face(area)]
        self.edges = [Edge()]

    def GetFaces(self):
        return self.faces

    def GetEdges(self):
        return self.edges


class SelectionManager:
    def CreateSelectData(self):
        return type("SelectData", (), {"Mark": 0})()


class RuledDocument(Document):
    def __init__(self):
        super().__init__()
        self.sheets = [Sheet(1600 / 1e6)]
        self.SelectionManager = SelectionManager()
        self.FeatureManager = self

    def GetBodies2(self, kind, visible):
        return self.sheets

    def InsertRuledSurfaceFromEdge2(self, *args):
        self.args = args
        self.sheets.append(Sheet(200 / 1e6))
        return Feature("RuledSurface1", "RuledSurface")


class RuledSurfaceTests(unittest.TestCase):
    def test_tangent_surface_selects_edge_and_increases_area(self):
        doc = RuledDocument()
        result = ruled_surface(Automation(doc), 0, 0, 5)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([4], doc.sheets[0].edges[0].marks)
        self.assertEqual((0, 0.005, False, False, False, 0.0, False,
                          0.0, 0.0, 0.0, False), doc.args)
        self.assertAlmostEqual(1800, result["data"]["area_after_mm2"])

    def test_bad_length_precedes_com(self):
        sw = Automation(RuledDocument())
        self.assertFalse(ruled_surface(sw, 0, 0, 0)["success"])
        self.assertEqual(0, sw.active_doc_calls)
