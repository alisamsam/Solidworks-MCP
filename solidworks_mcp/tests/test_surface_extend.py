"""Linear sheet-edge extension selects a concrete edge and verifies feature."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document, Feature
from solidworks_mcp.tools.surface_features import extend_surface


class Edge:
    def __init__(self):
        self.selected = []

    def Select4(self, append, data):
        self.selected.append((append, data.Mark))
        return True


class Body:
    def __init__(self):
        self.edge = Edge()

    def GetEdges(self):
        return [self.edge]


class SelectionManager:
    def CreateSelectData(self):
        return type("SelectData", (), {"Mark": 0})()


class ExtendedFeature(Feature):
    def __init__(self):
        super().__init__("Surface-Extend1", "ExtendRefSurface")

    def GetErrorCode(self):
        return 0


class ExtendedDocument(Document):
    def __init__(self):
        super().__init__()
        self.sheet = Body()
        self.SelectionManager = SelectionManager()

    def GetBodies2(self, kind, visible):
        return [self.sheet]

    def InsertExtendSurface(self, *args):
        self.args = args
        self.features.append(ExtendedFeature())


class ExtendSurfaceTests(unittest.TestCase):
    def test_selects_sheet_edge_and_creates_extension(self):
        document = ExtendedDocument()
        result = extend_surface(Automation(document), 0, 0, 5)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 0)], document.sheet.edge.selected)
        self.assertEqual((True, 0, 0.005), document.args)

    def test_invalid_distance_precedes_com(self):
        sw = Automation(ExtendedDocument())
        self.assertFalse(extend_surface(sw, 0, 0, 0)["success"])
        self.assertEqual(0, sw.active_doc_calls)
