"""Unit tests for the Tab and Slot tool (S22)."""

import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.sheetmetal import create_tab_and_slot


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

    def GetStartVertex(self):
        return Vertex(self.start)

    def GetEndVertex(self):
        return Vertex(self.end)

    def GetCurve(self):
        return Curve()

    def GetTwoAdjacentFaces2(self):
        return self.adjacent


class Surface:
    def __init__(self, planar):
        self.planar = planar

    def IsPlane(self):
        return self.planar


class Face:
    def __init__(self, planar=True, edges=None, body=None, normal=(0.0, 0.0, 1.0)):
        self.planar = planar
        self.edges = edges or []
        self.body = body
        self.normal = normal

    def GetSurface(self):
        return Surface(self.planar)

    def GetEdges(self):
        return self.edges

    def GetBody(self):
        return self.body

    def Normal(self):
        return self.normal


class Body:
    def __init__(self, name, faces, volume_m3):
        self.Name = name
        self.faces = faces
        self.volume_m3 = volume_m3
        for face in faces:
            if getattr(face, "body", None) is None:
                face.body = self

    def GetFaces(self):
        return self.faces

    def GetMassProperties(self, density):
        return [0.0, 0.0, 0.0, self.volume_m3, 0.0, 0.0]


class Group:
    """Records every property the tool sets, like a COM put."""

    def __init__(self):
        object.__setattr__(self, "properties", {})

    def __setattr__(self, name, value):
        self.properties[name] = value
        object.__setattr__(self, name, value)


class Definition:
    def __init__(self, group, access_error=None):
        self.group = group
        self.access_error = access_error
        self.access_calls = []
        self.release_calls = 0

    def SelectionAddNewGroup(self):
        return self.group

    def SelectionGetGroups(self):
        return [self.group]

    def AccessSelections(self, document, component):
        self.access_calls.append((document, component))
        if self.access_error is not None:
            raise RuntimeError(self.access_error)
        return True

    def ReleaseSelectionAccess(self):
        self.release_calls += 1


class Feature:
    def __init__(self, name="Tab and Slot-Tab1", type_name="TabAndSlotFeature",
                 definition=None):
        self.Name = name
        self._type_name = type_name
        self.definition = definition

    def GetTypeName2(self):
        return self._type_name

    def GetDefinition(self):
        return self.definition


class FeatureManager:
    def __init__(self, document):
        self.document = document
        self.creations = []

    def CreateDefinition(self, feature_id):
        self.document.feature_id = feature_id
        return self.document.definition

    def CreateFeature(self, definition):
        self.creations.append(definition)
        self.document.apply_geometry_change()
        return self.document.returned_feature


class Document:
    def __init__(self, bodies, returned_feature="default", gain_mm3=60.0,
                 loss_mm3=12.48, persist=True, access_error=None,
                 rename_bodies=True, flip_order=False):
        self.bodies = bodies
        self.gain_mm3 = gain_mm3
        self.loss_mm3 = loss_mm3
        self.persist = persist
        self.rename_bodies = rename_bodies
        self.flip_order = flip_order
        self.applied = False
        self.feature_id = None
        self.group = Group()
        self.definition = Definition(self.group, access_error=access_error)
        self.returned_feature = (Feature(definition=self.definition)
                                 if returned_feature == "default"
                                 else returned_feature)
        self.FeatureManager = FeatureManager(self)
        self.rebuilt = 0
        self.clears = 0

    def apply_geometry_change(self):
        if self.applied:
            return
        self.applied = True
        self.bodies[0].volume_m3 += self.gain_mm3 * 1e-9
        self.bodies[1].volume_m3 -= self.loss_mm3 * 1e-9
        if self.rename_bodies:
            self.bodies[0].Name = "Tab and Slot-Tab1"
            self.bodies[1].Name = "Tab and Slot-Slot1"
        if self.flip_order:
            # SolidWorks does not promise a stable GetBodies2 order.
            self.bodies.reverse()

    def FirstFeature(self):
        return self.returned_feature if self.persist else None

    def GetType(self):
        return 1

    def GetBodies2(self, body_type, visible_only):
        return self.bodies

    def ForceRebuild3(self, top_only):
        self.rebuilt += 1
        return True

    def ClearSelection2(self, clear_all):
        self.clears += 1


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


def fixture(**kwargs):
    """Two bodies; face index 2 of body B is the planar slot face.

    The tab edge has two adjacent faces, like a real rim edge: one coplanar with
    the slot face (normal (0,-1,0) against the slot's (0,1,0)) and one that is
    not, so the tool must pick the coplanar one.
    """
    coplanar = Face(planar=True, normal=(0.0, -1.0, 0.0))
    elsewhere = Face(planar=True, normal=(0.0, 0.0, 1.0))
    tab_edge = Edge([0.0, 0.0, 0.0], [0.0, 0.0, mm(50)],
                    adjacent=(elsewhere, coplanar))
    body_a = Body("Member A", [Face(edges=[tab_edge])], 5.0e-6)
    body_b = Body("Member B",
                  [Face(planar=False), Face(planar=True, normal=(0.0, 1.0, 0.0)),
                   Face(planar=False)],
                  1.0e-5)
    doc = Document([body_a, body_b], **kwargs)
    return doc, tab_edge


def single_body_document():
    edge = Edge([0.0, 0.0, 0.0], [0.0, 0.0, mm(50)])
    body = Body("Member A", [Face(edges=[edge])], 5.0e-6)
    return Document([body])


class TabAndSlotUnitTests(unittest.TestCase):
    def test_success_configures_the_group_and_proves_geometry_change(self):
        doc, tab_edge = fixture()
        result = create_tab_and_slot(Automation(doc), 0, 2)

        self.assertTrue(result["success"], result)
        self.assertEqual(88, doc.feature_id)  # swFmTabAndSlot
        self.assertEqual(1, len(doc.FeatureManager.creations))
        props = doc.group.properties
        self.assertIs(tab_edge, props["SelectionTabEdge"])
        self.assertIs(doc.bodies[1].faces[1], props["SelectionSlotFace"])
        self.assertAlmostEqual(0.010, props["TabLength"])
        self.assertAlmostEqual(0.0002, props["SlotClearance"])
        self.assertEqual(0, props["TabHeightType"])
        self.assertAlmostEqual(0.006, props["TabHeightValue"])
        self.assertEqual(0, props["TabEdgesType"])
        self.assertEqual(0, props["SpacingType"])
        self.assertEqual(1, props["SpacingNumberOfInstances"])
        # The coplanar adjacent face is chosen as the tab's reference face.
        self.assertIs(tab_edge.adjacent[1], props["TabFace"])
        self.assertNotIn("TabThickness", props)
        self.assertNotIn("Offset", props)

        self.assertEqual("Tab and Slot-Tab1", result["data"]["feature"])
        self.assertEqual("TabAndSlotFeature", result["data"]["feature_type"])
        self.assertEqual("Member A", result["data"]["tab_edge_body"])
        self.assertEqual("Member B", result["data"]["slot_face_body"])
        self.assertAlmostEqual(60.0, result["data"]["gained_mm3"], places=3)
        self.assertAlmostEqual(12.48, result["data"]["removed_mm3"], places=3)
        self.assertEqual("Member A", result["data"]["tab_body"]["name"])
        self.assertAlmostEqual(5000.0, result["data"]["tab_body"]["before_mm3"],
                               places=3)
        self.assertAlmostEqual(5060.0, result["data"]["tab_body"]["after_mm3"],
                               places=3)
        self.assertEqual("Member B", result["data"]["slot_body"]["name"])
        self.assertEqual([5000.0, 10000.0], result["data"]["bodies_before"])
        self.assertEqual(1, doc.rebuilt)
        # The definition is opened and released again for the readback.
        self.assertEqual(1, len(doc.definition.access_calls))
        self.assertEqual(1, doc.definition.release_calls)
        self.assertEqual(1, result["data"]["definition_readback"]["groups"])

    def test_modes_map_to_the_expected_group_values(self):
        cases = [
            ("equal spacing", {"spacing": "equal", "instances": 3},
             {"SpacingType": 0, "SpacingNumberOfInstances": 3}),
            ("length spacing", {"spacing": "length", "spacing_mm": 15.0},
             {"SpacingType": 1, "SpacingNumberOfInstances": 1}),
            ("fillet", {"edge_treatment": "fillet", "edge_treatment_mm": 2.0},
             {"TabEdgesType": 1, "TabFilletEdgeTreatmentValue": 0.002}),
            ("chamfer", {"edge_treatment": "chamfer", "edge_treatment_mm": 1.5},
             {"TabEdgesType": 2, "TabChamferEdgeTreatmentValue": 0.0015}),
            ("offset from edges",
             {"offset_from_edges": True, "start_offset_mm": 5.0,
              "end_offset_mm": 2.0},
             {"Offset": True, "D1OffsetFromStart": 0.005,
              "D2OffsetFromEnd": 0.002}),
            ("tab thickness", {"tab_thickness_mm": 1.5},
             {"TabThickness": 0.0015}),
        ]
        for label, kwargs, expected in cases:
            with self.subTest(label=label):
                doc, _edge = fixture()
                result = create_tab_and_slot(Automation(doc), 0, 2, **kwargs)
                self.assertTrue(result["success"], result)
                for key, value in expected.items():
                    self.assertEqual(value, doc.group.properties[key], key)
                if kwargs.get("spacing") != "length":
                    self.assertNotIn("Spacing", doc.group.properties)

    def test_validation_failures_never_call_the_feature_manager(self):
        cases = [
            ("negative edge", dict(tab_edge_index=-1, slot_face_index=2)),
            ("float edge", dict(tab_edge_index=1.5, slot_face_index=2)),
            ("bool edge", dict(tab_edge_index=True, slot_face_index=2)),
            ("negative face", dict(tab_edge_index=0, slot_face_index=-2)),
            ("zero length", dict(tab_edge_index=0, slot_face_index=2,
                                 tab_length_mm=0)),
            ("zero height", dict(tab_edge_index=0, slot_face_index=2,
                                 tab_height_mm=0)),
            ("negative clearance", dict(tab_edge_index=0, slot_face_index=2,
                                        slot_clearance_mm=-1)),
            ("bad spacing", dict(tab_edge_index=0, slot_face_index=2,
                                 spacing="grid")),
            ("bad instances", dict(tab_edge_index=0, slot_face_index=2,
                                   spacing="equal", instances=0)),
            ("length without spacing", dict(tab_edge_index=0, slot_face_index=2,
                                            spacing="length")),
            ("bad treatment", dict(tab_edge_index=0, slot_face_index=2,
                                   edge_treatment="round")),
            ("bad treatment size", dict(tab_edge_index=0, slot_face_index=2,
                                        edge_treatment="fillet",
                                        edge_treatment_mm=0)),
            ("bad thickness", dict(tab_edge_index=0, slot_face_index=2,
                                   tab_thickness_mm=-0.5)),
            ("bad offset flag", dict(tab_edge_index=0, slot_face_index=2,
                                     offset_from_edges="yes")),
            ("bad offsets", dict(tab_edge_index=0, slot_face_index=2,
                                 start_offset_mm=-1)),
        ]
        for label, kwargs in cases:
            with self.subTest(label=label):
                doc, _edge = fixture()
                result = create_tab_and_slot(Automation(doc), **kwargs)
                self.assertFalse(result["success"], label)
                self.assertFalse(doc.FeatureManager.creations, label)
                self.assertFalse(doc.group.properties, label)

    def test_rejected_problems_after_validation(self):
        cases = [
            ("edge index out of range", dict(tab_edge_index=5, slot_face_index=2),
             fixture()),
            ("face is not planar", dict(tab_edge_index=0, slot_face_index=1),
             fixture()),
            ("only one body", dict(tab_edge_index=0, slot_face_index=1),
             (single_body_document(), None)),
        ]
        for label, kwargs, (doc, _edge) in cases:
            with self.subTest(label=label):
                result = create_tab_and_slot(Automation(doc), **kwargs)
                self.assertFalse(result["success"], label)
                self.assertFalse(doc.FeatureManager.creations, label)

        non_part, _edge = fixture()
        non_part.GetType = lambda: 2
        self.assertFalse(create_tab_and_slot(Automation(non_part), 0, 2)["success"])
        self.assertFalse(non_part.FeatureManager.creations)

    def test_created_but_unproven_feature_is_not_success(self):
        cases = [
            ("no feature", dict(returned_feature=None, gain_mm3=0.0, loss_mm3=0.0)),
            ("wrong type", dict(returned_feature=Feature("Boss-Extrude1", "Extrusion"))),
            ("did not persist", dict(persist=False)),
            ("only a gain", dict(loss_mm3=0.0)),
            ("only a loss", dict(gain_mm3=0.0)),
        ]
        for label, kwargs in cases:
            with self.subTest(label=label):
                doc, _edge = fixture(**kwargs)
                result = create_tab_and_slot(Automation(doc), 0, 2)
                self.assertFalse(result["success"], label)

    def test_body_order_change_does_not_break_the_proof(self):
        doc, _edge = fixture(flip_order=True)
        result = create_tab_and_slot(Automation(doc), 0, 2)
        self.assertTrue(result["success"], result)
        self.assertAlmostEqual(60.0, result["data"]["gained_mm3"], places=3)
        self.assertAlmostEqual(12.48, result["data"]["removed_mm3"], places=3)
        self.assertEqual("Member A", result["data"]["tab_body"]["name"])
        self.assertEqual("Member B", result["data"]["slot_body"]["name"])

    def test_tab_face_selection_handles_missing_or_curved_neighbours(self):
        cases = [
            ("perpendicular only", [(True, (0.0, 0.0, 1.0)), (True, (1.0, 0.0, 0.0))],
             None),
            ("curved then coplanar", [(False, (0.0, 1.0, 0.0)),
                                      (True, (0.0, -1.0, 0.0))], 1),
            ("no neighbours", [], None),
        ]
        for label, neighbours, expected in cases:
            with self.subTest(label=label):
                doc, tab_edge = fixture()
                tab_edge.adjacent = [Face(planar=planar, normal=normal)
                                     for planar, normal in neighbours]
                result = create_tab_and_slot(Automation(doc), 0, 2)
                self.assertTrue(result["success"], result)
                if expected is None:
                    self.assertNotIn("TabFace", doc.group.properties)
                else:
                    self.assertIs(tab_edge.adjacent[expected],
                                  doc.group.properties["TabFace"])

    def test_readback_failure_still_reports_success(self):
        doc, _edge = fixture(access_error="rollback refused")
        result = create_tab_and_slot(Automation(doc), 0, 2)
        self.assertTrue(result["success"], result)
        self.assertIn("error", result["data"]["definition_readback"])

    def test_tool_is_registered_as_mutating(self):
        self.assertIn("create_tab_and_slot",
                      [tool.name for tool in registered_tools()])
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("create_tab_and_slot"))


if __name__ == "__main__":
    unittest.main()
