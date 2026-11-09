"""Unit tests for the indexed body-edge listing (list_body_edges)."""

import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.inspection import list_body_edges, part_edges


class Vertex:
    def __init__(self, point):
        self.point = point

    def GetPoint(self):
        return self.point


class Curve:
    def __init__(self, is_line):
        self.is_line = is_line

    def IsLine(self):
        return self.is_line


class Edge:
    def __init__(self, start, end, is_line=True):
        self.start = start
        self.end = end
        self.is_line = is_line

    def GetStartVertex(self):
        return Vertex(self.start)

    def GetEndVertex(self):
        return Vertex(self.end)

    def GetCurve(self):
        return Curve(self.is_line)


class Face:
    def __init__(self, edges):
        self.edges = edges

    def GetEdges(self):
        return self.edges


class Body:
    def __init__(self, name, faces):
        self.Name = name
        self.faces = faces

    def GetFaces(self):
        return self.faces


class Document:
    def __init__(self, bodies):
        self.bodies = bodies

    def GetType(self):
        return 1

    def GetBodies2(self, body_type, visible_only):
        return self.bodies


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


def fixture():
    shared = Edge([0.0, 0.0, 0.0], [mm(50), 0.0, 0.0])
    arc = Edge([0.0, 0.0, 0.0], [0.0, mm(10), 0.0], is_line=False)
    body_a = Body("Member A", [Face([shared, arc]), Face([shared])])
    body_b = Body("Member B", [Face([Edge([0.0, 0.0, 0.0],
                                           [0.0, 0.0, mm(80)])])])
    return Document([body_a, body_b])


class BodyEdgeTests(unittest.TestCase):
    def test_edges_are_deduplicated_kept_in_order_and_measured(self):
        edges = part_edges(fixture())
        self.assertEqual(3, len(edges))
        self.assertEqual([0, 1, 2], [edge["index"] for edge in edges])
        self.assertEqual("Member A", edges[0]["body"])
        self.assertEqual(50.0, edges[0]["length_mm"])
        self.assertTrue(edges[0]["is_line"])
        self.assertEqual([0.0, 0.0, 0.0], edges[0]["start_mm"])
        self.assertEqual([50.0, 0.0, 0.0], edges[0]["end_mm"])
        # The arc shares its start point but not its endpoint, and is reported
        # without a length because only straight edges get one.
        self.assertFalse(edges[1]["is_line"])
        self.assertIsNone(edges[1]["length_mm"])
        self.assertEqual("Member B", edges[2]["body"])
        self.assertEqual(80.0, edges[2]["length_mm"])

    def test_tool_reports_indices_and_filters_by_length(self):
        doc = fixture()
        result = list_body_edges(Automation(doc))
        self.assertTrue(result["success"], result)
        self.assertEqual(3, result["data"]["count"])
        self.assertEqual(3, result["data"]["total_edges"])
        self.assertEqual([0, 1, 2], [edge["index"]
                                     for edge in result["data"]["edges"]])

        filtered = list_body_edges(Automation(doc), min_length_mm=60.0)
        self.assertTrue(filtered["success"], filtered)
        self.assertEqual(1, filtered["data"]["count"])
        # Filtering must not renumber: the arc and the 80 mm edge keep indexes.
        self.assertEqual([2], [edge["index"] for edge in filtered["data"]["edges"]])

    def test_invalid_inputs_and_non_parts_are_rejected(self):
        doc = fixture()
        for value in (-1.0, True, "long"):
            with self.subTest(value=value):
                result = list_body_edges(Automation(doc), min_length_mm=value)
                self.assertFalse(result["success"])
        non_part = Document([])
        non_part.GetType = lambda: 2
        self.assertFalse(list_body_edges(Automation(non_part))["success"])

    def test_tool_is_registered_as_read_only(self):
        self.assertIn("list_body_edges",
                      [tool.name for tool in registered_tools()])
        self.assertIs(OperationClass.READ,
                      operation_class_for("list_body_edges"))


if __name__ == "__main__":
    unittest.main()
