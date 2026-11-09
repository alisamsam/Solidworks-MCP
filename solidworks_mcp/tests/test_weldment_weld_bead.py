"""Unit tests for the cosmetic weld bead tool (W5)."""

import unittest
from unittest.mock import patch

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.weldments import create_cosmetic_weld_bead


class Vertex:
    def __init__(self, point):
        self.point = point

    def GetPoint(self):
        return self.point


class Curve:
    def IsLine(self):
        return True


class Edge:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.selections = []

    def GetStartVertex(self):
        return Vertex(self.start)

    def GetEndVertex(self):
        return Vertex(self.end)

    def GetCurve(self):
        return Curve()

    def Select4(self, append, select_data):
        self.selections.append((append, getattr(select_data, "Mark", None)))
        return True


class Face:
    def __init__(self, edges):
        self.edges = edges

    def GetEdges(self):
        return self.edges


class Body:
    def __init__(self, name, edges, volume_m3=1.0e-6):
        self.Name = name
        self.faces = [Face(edges)]
        self.volume_m3 = volume_m3

    def GetFaces(self):
        return self.faces

    def GetMassProperties(self, density):
        return [0.0, 0.0, 0.0, self.volume_m3, 0.0, 0.0]


class SelectData:
    Mark = None


class SelectionManager:
    def CreateSelectData(self):
        return SelectData()


class Folder:
    TotalLength = 120.0  # document units (millimetres)


class Definition:
    BeadSize = 0.004

    def GetWeldBeadFolder(self):
        return Folder()


class Feature:
    def __init__(self, name="Weld Bead1", type_name="CosmeticWeldBead"):
        self.Name = name
        self._type_name = type_name

    def GetTypeName2(self):
        return self._type_name

    def GetDefinition(self):
        return Definition()

    def GetFirstSubFeature(self):
        return None

    def GetNextSubFeature(self):
        return None


class FolderFeature(Feature):
    def __init__(self, name, type_name, child):
        super().__init__(name, type_name)
        self.child = child

    def GetFirstSubFeature(self):
        return self.child


class Manager:
    def __init__(self, document):
        self.document = document
        self.calls = []

    def InsertCosmeticWeldBead2(self, *args):
        self.calls.append(args)
        return self.document.returned


class Document:
    def __init__(self, edges, returned=None, in_tree=True):
        self.bodies = [Body("Member A", edges)]
        self.returned = [Feature()] if returned is None else returned
        self.in_tree = in_tree
        self.FeatureManager = Manager(self)
        self.SelectionManager = SelectionManager()
        self.clears = []

    def FirstFeature(self):
        child = None
        if self.in_tree and self.returned:
            first = self.returned[0]
            if "bead" in str(first.GetTypeName2()).casefold():
                child = first
        return FolderFeature("Weld Folder", "CosmeticWeldCutList", child)

    def GetType(self):
        return 1

    def GetBodies2(self, body_type, visible_only):
        return self.bodies

    def ForceRebuild3(self, top_only):
        return True

    def ClearSelection2(self, clear_all):
        self.clears.append(clear_all)


class Automation:
    def __init__(self, doc):
        self.doc = doc

    def get_active_doc(self):
        return self.doc, None

    @staticmethod
    def _result(success, message, error=None, data=None):
        return {"success": success, "message": message, "error": error,
                "data": data}


def mm(value):
    return value / 1000.0


def fixture(returned=None, in_tree=True):
    edges = [
        Edge([0.0, 0.0, 0.0], [0.0, 0.0, mm(40)]),
        Edge([0.0, 0.0, 0.0], [mm(30), 0.0, 0.0]),
        Edge([0.0, 0.0, 0.0], [0.0, mm(60), 0.0]),
    ]
    return Document(edges, returned=returned, in_tree=in_tree), edges


class CosmeticWeldBeadTests(unittest.TestCase):
    def setUp(self):
        self.variant_patch = patch(
            "solidworks_mcp.tools.weldments.win32com.client.VARIANT",
            side_effect=lambda kind, values: (kind, list(values)))
        self.variant = self.variant_patch.start()
        self.addCleanup(self.variant_patch.stop)

    def test_weld_path_mode_is_called_with_the_named_edges(self):
        doc, edges = fixture()
        result = create_cosmetic_weld_bead(Automation(doc), [0, 2], size_mm=4.0)

        self.assertTrue(result["success"], result)
        self.assertEqual(1, len(doc.FeatureManager.calls))
        mode, edge_array, weld_to, size = doc.FeatureManager.calls[0]
        self.assertEqual(1, mode)  # swCosmeticWeldBeadMode_WeldPath
        self.assertEqual([edges[0], edges[2]], edge_array[1])
        self.assertIsNone(weld_to)
        self.assertAlmostEqual(0.004, size)
        self.assertEqual([(False, 0)], edges[0].selections)
        self.assertEqual([(True, 0)], edges[2].selections)
        self.assertEqual([], edges[1].selections)
        self.assertEqual([True, True], doc.clears)
        self.assertEqual(["Weld Bead1"], result["data"]["features"])
        self.assertEqual("CosmeticWeldBead", result["data"]["feature_type"])
        self.assertEqual(4.0, result["data"]["bead_size_mm"])
        self.assertEqual(120.0, result["data"]["total_weld_length_mm"])
        self.assertEqual(0.0, result["data"]["added_mm3"])

    def test_invalid_inputs_never_call_the_feature_manager(self):
        cases = [
            ("empty", dict(edge_indices=[])),
            ("duplicate", dict(edge_indices=[0, 0])),
            ("negative", dict(edge_indices=[-1])),
            ("not integer", dict(edge_indices=["0"])),
            ("out of range", dict(edge_indices=[99])),
            ("zero size", dict(edge_indices=[0], size_mm=0)),
            ("bool size", dict(edge_indices=[0], size_mm=True)),
        ]
        for label, kwargs in cases:
            with self.subTest(label=label):
                doc, _edges = fixture()
                result = create_cosmetic_weld_bead(Automation(doc), **kwargs)
                self.assertFalse(result["success"], label)
                self.assertFalse(doc.FeatureManager.calls, label)

    def test_missing_or_unknown_or_unpersisted_features_are_not_success(self):
        empty, _ = fixture(returned=[])
        self.assertFalse(create_cosmetic_weld_bead(Automation(empty), [0])["success"])

        wrong_type, _ = fixture(returned=[Feature("Boss1", "Extrusion")])
        self.assertFalse(
            create_cosmetic_weld_bead(Automation(wrong_type), [0])["success"])

        unpersisted, _ = fixture(in_tree=False)
        self.assertFalse(
            create_cosmetic_weld_bead(Automation(unpersisted), [0])["success"])

    def test_non_part_is_rejected(self):
        doc, _ = fixture()
        doc.GetType = lambda: 2
        result = create_cosmetic_weld_bead(Automation(doc), [0])
        self.assertFalse(result["success"])
        self.assertFalse(doc.FeatureManager.calls)

    def test_tool_is_registered_as_mutating(self):
        self.assertIn("create_cosmetic_weld_bead",
                      [tool.name for tool in registered_tools()])
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("create_cosmetic_weld_bead"))


if __name__ == "__main__":
    unittest.main()
