"""Unit tests for the edge flange tool (S2).

The mock records every COM call the tool makes, so the tests check the call
sequence and argument values as well as the geometry proof: an edge flange is
only reported as created when the sheet gains volume and faces.
"""

import math
import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.sheetmetal import create_edge_flange

LENGTH_M = 0.020


class Vertex:
    def __init__(self, point):
        self.point = point

    def GetPoint(self):
        return self.point


class Curve:
    def IsLine(self):
        return True


class Edge:
    def __init__(self, start, end, adjacent=()):
        self.start = start
        self.end = end
        self.adjacent = list(adjacent)
        self.selected = []

    def GetStartVertex(self):
        return Vertex(self.start)

    def GetEndVertex(self):
        return Vertex(self.end)

    def GetCurve(self):
        return Curve()

    def GetTwoAdjacentFaces2(self):
        return self.adjacent

    def Select4(self, append, callout):
        self.selected.append(append)
        return True


class Face:
    def __init__(self, edges=None):
        self.edges = edges or []

    def GetEdges(self):
        return self.edges


class Body:
    def __init__(self, name, faces, volume_m3, face_count=None):
        self.Name = name
        self.faces = faces
        self.volume_m3 = volume_m3
        self.face_count = face_count if face_count is not None else len(faces)

    def GetFaces(self):
        return self.faces + [Face()] * (self.face_count - len(self.faces))

    def GetMassProperties(self, density):
        return [0.0, 0.0, 0.0, self.volume_m3, 0.0, 0.0]


class Point:
    def __init__(self, x, y):
        self.X = x
        self.Y = y


class SketchLine:
    def __init__(self, start, end):
        self.start = start
        self.end = end

    def GetStartPoint2(self):
        return Point(*self.start)

    def GetEndPoint2(self):
        return Point(*self.end)


class Sketch:
    def __init__(self, lines):
        self.lines = list(lines)

    def GetSketchSegments(self):
        return self.lines


class SketchManager:
    def __init__(self):
        self.used = 0

    def SketchUseEdge(self, chain):
        self.used += 1
        return True


class SheetMetalDefinition:
    def __init__(self, bend_radius_m=0.01):
        self.BendRadius = bend_radius_m


class Feature:
    def __init__(self, name, type_name, definition=None, sketch=None):
        self.Name = name
        self._type_name = type_name
        self.definition = definition
        self.sketch = sketch
        self.next = None
        self.selects = 0

    def GetTypeName2(self):
        return self._type_name

    def GetNextFeature(self):
        return self.next

    def GetSpecificFeature2(self):
        return self.sketch

    def GetDefinition(self):
        return self.definition

    def Select2(self, append, mark):
        self.selects += 1
        return True


class FeatureManager:
    def __init__(self, document):
        self.document = document
        self.calls = []

    def InsertSheetMetalEdgeFlange2(self, edges, sketches, options, angle,
                                    radius, position, length, relief, ratio,
                                    width, depth, sharp, allowance):
        self.calls.append({
            "edges": list(edges.value),
            "sketches": list(sketches.value),
            "options": options,
            "angle": angle,
            "radius": radius,
            "position": position,
            "length": length,
            "relief": relief,
            "ratio": ratio,
            "width": width,
            "depth": depth,
            "sharp": sharp,
            "allowance": allowance,
        })
        self.document.apply_flange()
        return self.document.returned_feature


class Document:
    def __init__(self, bodies, returned_feature="default", gained_mm3=2135.619,
                 gained_faces=8, persist=True, use_default_radius=True,
                 sheet_metal=True, sketch_failure=False):
        self.bodies = bodies
        self.gained_mm3 = gained_mm3
        self.gained_faces = gained_faces
        self.persist = persist
        self.sketch_failure = sketch_failure
        self.applied = False
        self.created = None
        self.profile_sketch = Sketch([SketchLine((-0.1, 0.0), (0.0, 0.0))])
        self.sketch_manager = SketchManager()
        self.line_calls = []
        self.add_to_db = []
        self.display_when_added = []
        self.sketch_exits = 0
        self.clears = 0
        self.rebuilt = 0
        self.sketch_feature = Feature("Sketch9", "ProfileFeature",
                                      sketch=self.profile_sketch)
        self.sheet_metal = Feature("Sheet-Metal1", "SheetMetal",
                                   definition=SheetMetalDefinition())
        self.head = self.sheet_metal if sheet_metal else None
        self.sheet_metal.next = None
        self.returned_feature = (Feature("Edge-Flange1", "EdgeFlange")
                                 if returned_feature == "default"
                                 else returned_feature)
        self.feature_manager = FeatureManager(self)
        # FeatureManager is read through com(), which returns the attribute.
        self.FeatureManager = self.feature_manager
        self.SketchManager = self.sketch_manager

    def apply_flange(self):
        if self.applied:
            return
        self.applied = True
        self.bodies[0].volume_m3 += self.gained_mm3 * 1e-9
        self.bodies[0].face_count += self.gained_faces
        self.created = self.returned_feature
        if self.returned_feature is None:
            return
        self.returned_feature.next = None
        self.sheet_metal.next = self.returned_feature

    def FirstFeature(self):
        return self.head if self.persist else None

    def GetType(self):
        return 1

    def GetBodies2(self, body_type, visible_only):
        return self.bodies

    def ClearSelection2(self, clear_all):
        self.clears += 1

    def InsertSketchForEdgeFlange(self, edge, angle, flip):
        return None if self.sketch_failure else self.sketch_feature

    def EditSketch(self):
        return True

    def GetActiveSketch2(self):
        return self.profile_sketch

    def SetAddToDB(self, value):
        self.add_to_db.append(value)

    def SetDisplayWhenAdded(self, value):
        self.display_when_added.append(value)

    def CreateLine2(self, x1, y1, z1, x2, y2, z2):
        self.line_calls.append((x1, y1, z1, x2, y2, z2))
        return SketchLine((x1, y1), (x2, y2))

    def InsertSketch2(self, commit):
        self.sketch_exits += 1
        return True

    def ForceRebuild3(self, top_only):
        self.rebuilt += 1
        return True


class Automation:
    def __init__(self, doc):
        self.doc = doc

    def get_active_doc(self):
        return self.doc, None

    @staticmethod
    def _result(success, message, error=None, data=None):
        return {"success": success, "message": message, "error": error,
                "data": data}


def fixture(**kwargs):
    edge = Edge([0.0, 0.0, 0.0], [0.0, 0.1, 0.0])
    body = Body("Sheet", [Face(edges=[edge])], 5.0e-6, face_count=6)
    return Document([body], **kwargs), edge


class EdgeFlangeUnitTests(unittest.TestCase):
    def test_success_builds_the_profile_and_proves_geometry_change(self):
        doc, edge = fixture()
        result = create_edge_flange(Automation(doc), 0, 20.0)

        self.assertTrue(result["success"], result)
        self.assertEqual(1, len(doc.feature_manager.calls))
        call = doc.feature_manager.calls[0]
        self.assertEqual([edge], call["edges"])
        self.assertIs(doc.profile_sketch, call["sketches"][0])
        # Bend-outside is the only position that builds through the API.
        self.assertEqual(3, call["position"])
        self.assertEqual(4, call["relief"])
        self.assertEqual(2, call["sharp"])
        self.assertAlmostEqual(math.radians(90.0), call["angle"])
        self.assertAlmostEqual(LENGTH_M, call["length"])
        self.assertAlmostEqual(0.0, call["radius"])
        # Default radius and default relief.
        self.assertEqual(1 + 128, call["options"])

        # The profile is the bend line closed by three lines into a rectangle.
        self.assertEqual(
            [(-0.1, 0.0, 0.0, -0.1, 0.02, 0.0),
             (-0.1, 0.02, 0.0, 0.0, 0.02, 0.0),
             (0.0, 0.02, 0.0, 0.0, 0.0, 0.0)],
            [(round(a, 6), round(b, 6), round(c, 6), round(d, 6),
              round(f, 6), round(g, 6))
             for a, b, c, d, f, g in doc.line_calls])
        self.assertEqual(1, doc.sketch_manager.used)
        self.assertEqual(1, doc.sketch_exits)
        self.assertEqual([True, False], doc.add_to_db)
        self.assertEqual([False, True], doc.display_when_added)
        self.assertEqual(1, doc.sketch_feature.selects)

        self.assertEqual("Edge-Flange1", result["data"]["feature"])
        self.assertEqual("EdgeFlange", result["data"]["feature_type"])
        self.assertEqual("Sheet", result["data"]["edge_body"])
        self.assertAlmostEqual(2135.619, result["data"]["gained_mm3"], places=3)
        self.assertAlmostEqual(5000.0, result["data"]["volume_before_mm3"],
                               places=3)
        self.assertAlmostEqual(7135.619, result["data"]["volume_after_mm3"],
                               places=3)
        self.assertEqual(6, result["data"]["faces_before"])
        self.assertEqual(14, result["data"]["faces_after"])
        self.assertEqual(1, result["data"]["bodies_after"])
        self.assertTrue(result["data"]["uses_default_bend_radius"])
        self.assertAlmostEqual(10.0, result["data"]["bend_radius_mm"], places=3)
        self.assertEqual(1, doc.rebuilt)

    def test_explicit_radius_switches_off_the_default_radius_option(self):
        doc, _edge = fixture()
        result = create_edge_flange(Automation(doc), 0, 20.0, angle_deg=45.0,
                                    bend_radius_mm=5.0)
        self.assertTrue(result["success"], result)
        call = doc.feature_manager.calls[0]
        self.assertAlmostEqual(math.radians(45.0), call["angle"])
        self.assertAlmostEqual(0.005, call["radius"])
        self.assertEqual(128, call["options"])
        self.assertFalse(result["data"]["uses_default_bend_radius"])
        self.assertAlmostEqual(5.0, result["data"]["bend_radius_mm"], places=3)

    def test_validation_failures_never_call_the_feature_manager(self):
        cases = [
            ("negative edge", dict(edge_index=-1, length_mm=20.0)),
            ("float edge", dict(edge_index=1.5, length_mm=20.0)),
            ("bool edge", dict(edge_index=True, length_mm=20.0)),
            ("zero length", dict(edge_index=0, length_mm=0.0)),
            ("negative length", dict(edge_index=0, length_mm=-5.0)),
            ("zero angle", dict(edge_index=0, length_mm=20.0, angle_deg=0.0)),
            ("angle over 180", dict(edge_index=0, length_mm=20.0,
                                    angle_deg=180.0)),
            ("zero radius", dict(edge_index=0, length_mm=20.0,
                                 bend_radius_mm=0.0)),
        ]
        for label, kwargs in cases:
            with self.subTest(label=label):
                doc, _edge = fixture()
                result = create_edge_flange(Automation(doc), **kwargs)
                self.assertFalse(result["success"], label)
                self.assertFalse(doc.feature_manager.calls, label)
                self.assertFalse(doc.line_calls, label)

    def test_rejected_problems_after_validation(self):
        cases = [
            ("edge index out of range", dict(edge_index=4, length_mm=20.0),
             fixture()),
            ("no sheet metal", dict(edge_index=0, length_mm=20.0),
             fixture(sheet_metal=False)),
        ]
        for label, kwargs, (doc, _edge) in cases:
            with self.subTest(label=label):
                result = create_edge_flange(Automation(doc), **kwargs)
                self.assertFalse(result["success"], label)
                self.assertFalse(doc.feature_manager.calls, label)

        non_part, _edge = fixture()
        non_part.GetType = lambda: 2
        self.assertFalse(
            create_edge_flange(Automation(non_part), 0, 20.0)["success"])
        self.assertFalse(non_part.feature_manager.calls)

        no_sketch, _edge = fixture(sketch_failure=True)
        result = create_edge_flange(Automation(no_sketch), 0, 20.0)
        self.assertFalse(result["success"])
        self.assertFalse(no_sketch.feature_manager.calls)

        empty, _edge = fixture()
        empty.profile_sketch.lines = []
        result = create_edge_flange(Automation(empty), 0, 20.0)
        self.assertFalse(result["success"])
        self.assertIn("bend line", result["message"])
        self.assertFalse(empty.feature_manager.calls)
        # The sketch is still closed again, so the part is not left in edit mode.
        self.assertEqual(1, empty.sketch_exits)

    def test_created_but_unproven_feature_is_not_success(self):
        cases = [
            ("no feature", dict(returned_feature=None, gained_mm3=0.0,
                                gained_faces=0)),
            ("wrong type", dict(
                returned_feature=Feature("Boss-Extrude1", "Extrusion"))),
            ("did not persist", dict(persist=False)),
            ("no volume gain", dict(gained_mm3=0.0, gained_faces=8)),
            ("no new faces", dict(gained_mm3=100.0, gained_faces=0)),
        ]
        for label, kwargs in cases:
            with self.subTest(label=label):
                doc, _edge = fixture(**kwargs)
                result = create_edge_flange(Automation(doc), 0, 20.0)
                self.assertFalse(result["success"], label)

    def test_tool_is_registered_as_mutating(self):
        self.assertIn("create_edge_flange",
                      [tool.name for tool in registered_tools()])
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("create_edge_flange"))


if __name__ == "__main__":
    unittest.main()
