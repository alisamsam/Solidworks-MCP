"""Unit tests for capping hollow-profile weldment member ends (W3)."""

import unittest
from unittest.mock import patch

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.weldments import (
    END_CAP_DIRECTIONS, create_weldment_end_cap, _planar_end_faces,
)


class Surface:
    def __init__(self, planar=True):
        self.IsPlane = planar


class Face:
    def __init__(self, normal, box, planar=True):
        self.Normal = normal
        self._box = box
        self._surface = Surface(planar)
        self.selections = []

    def GetSurface(self):
        return self._surface

    def GetBox(self):
        return self._box

    def Select4(self, append, select_data):
        self.selections.append((append, getattr(select_data, "Mark", None)))
        return True


class SelectData:
    Mark = 0


class SelectionManager:
    def CreateSelectData(self):
        return SelectData()


class Body:
    def __init__(self, name="Member A", volume_m3=1.0e-6):
        self.Name = name
        self.volume_m3 = volume_m3
        # A 2 m long, 50 mm square tube along X: two X-normal end faces.
        self.faces = [
            Face([1.0, 0.0, 0.0], [2.0, -0.025, -0.025, 2.0, 0.025, 0.025]),
            Face([0.0, 1.0, 0.0], [0.0, 0.025, -0.025, 2.0, 0.025, 0.025]),
            Face([-1.0, 0.0, 0.0], [0.0, -0.025, -0.025, 0.0, 0.025, 0.025]),
        ]

    def GetBodyBox(self):
        return [0.0, -0.025, -0.025, 2.0, 0.025, 0.025]

    def GetFaces(self):
        return self.faces

    def GetMassProperties(self, density):
        return [0.0, 0.0, 0.0, self.volume_m3, 0.0, 0.0]


class Feature:
    def __init__(self, name="End cap1", type_name="EndCap"):
        self.Name = name
        self._type_name = type_name

    def GetTypeName2(self):
        return self._type_name

    def GetNextFeature(self):
        return None


class Manager:
    def __init__(self, document):
        self.document = document
        self.calls = []

    def InsertEndCapFeature3(self, *args):
        self.calls.append(args)
        if self.document.feature is None:
            return None
        if self.document.in_tree:
            # SolidWorks adds the caps as their own bodies.
            self.document.bodies.append(Body("End cap1[1]", 5.0e-7))
        return self.document.feature


class Document:
    Name = "Weldment"

    def __init__(self, weldment=True, bodies=None):
        self.body = Body()
        self.bodies = bodies if bodies is not None else [self.body]
        self.feature = Feature()
        self.in_tree = True
        self.weldment = weldment
        self.FeatureManager = Manager(self)
        self.SelectionManager = SelectionManager()
        self.clears = []

    def FirstFeature(self):
        return self if self.weldment else None

    def GetTypeName2(self):
        return "WeldmentFeature"

    def GetNextFeature(self):
        if self.weldment and self.in_tree:
            return self.feature
        return None

    def GetType(self):
        return 1

    def GetBodies2(self, body_type, visible_only):
        assert body_type == 0 and visible_only is False
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


class WeldmentEndCapTests(unittest.TestCase):
    def setUp(self):
        self.variant_patch = patch(
            "solidworks_mcp.tools.weldments.win32com.client.VARIANT",
            side_effect=lambda kind, values: (kind, list(values)))
        self.variant = self.variant_patch.start()
        self.addCleanup(self.variant_patch.stop)

    def test_auto_detected_ends_pass_exact_si_values_and_cap_both_faces(self):
        doc = Document()
        sw = Automation(doc)
        result = create_weldment_end_cap(
            sw, "Member A", depth_mm=4.0, direction="inset", inset_mm=1.5,
            chamfer=True, chamfer_mm=2.0, corner_treatment=True, reverse=True,
            given_offset=True, offset_value_mm=1.0, wall_thickness_ratio=0.4)

        self.assertTrue(result["success"], result)
        self.assertEqual(1, len(doc.FeatureManager.calls))
        (depth, given, chamfer, offset, ratio, chamfer_value, corners,
         inset, reverse, direction) = doc.FeatureManager.calls[0]
        self.assertAlmostEqual(0.004, depth)
        self.assertIs(True, given)
        self.assertIs(True, chamfer)
        self.assertAlmostEqual(0.001, offset)
        self.assertAlmostEqual(0.4, ratio)
        self.assertAlmostEqual(0.002, chamfer_value)
        self.assertIs(True, corners)
        self.assertAlmostEqual(0.0015, inset)
        self.assertIs(True, reverse)
        self.assertEqual(END_CAP_DIRECTIONS["inset"], direction)
        self.assertEqual([], doc.body.faces[1].selections)
        self.assertEqual([(True, 1)], doc.body.faces[0].selections)
        self.assertEqual([(False, 1)], doc.body.faces[2].selections)
        self.assertEqual([True, True], doc.clears)
        self.assertEqual(2, result["data"]["face_count"])
        self.assertTrue(result["data"]["auto_detected_faces"])
        self.assertEqual(["End cap1[1]"], result["data"]["cap_bodies"])
        self.assertAlmostEqual(500.0, result["data"]["added_mm3"])

    def test_direction_defaults_to_inward_not_the_protruding_side(self):
        doc = Document()
        result = create_weldment_end_cap(Automation(doc), "Member A")
        self.assertTrue(result["success"], result)
        self.assertEqual("inward", result["data"]["direction"])
        self.assertEqual(END_CAP_DIRECTIONS["inward"], doc.FeatureManager.calls[0][-1])

    def test_explicit_face_index_selects_only_that_face(self):
        doc = Document()
        result = create_weldment_end_cap(Automation(doc), "Member A",
                                         face_indices=[0], depth_mm=1.0)
        self.assertTrue(result["success"], result)
        selected = [position for position, face in enumerate(doc.body.faces)
                    if face.selections]
        self.assertEqual([0], selected)
        self.assertFalse(result["data"]["auto_detected_faces"])

    def test_auto_detect_returns_only_axis_normal_planar_faces(self):
        body = Body()
        ends = _planar_end_faces(body)
        self.assertEqual([body.faces[2], body.faces[0]], ends)

    def test_hollow_face_gap_or_missing_body_never_calls_feature_manager(self):
        no_faces = Document()
        no_faces.body.faces = [Face([0.0, 1.0, 0.0], [0, 0, 0, 1, 1, 1])]
        for label, doc, name in (
            ("no planar ends", no_faces, "Member A"),
            ("missing body", Document(), "Missing"),
        ):
            with self.subTest(label=label):
                result = create_weldment_end_cap(Automation(doc), name)
                self.assertFalse(result["success"])
                self.assertFalse(doc.FeatureManager.calls)

    def test_bad_inputs_are_rejected_without_mutation(self):
        doc = Document()
        calls = [
            dict(face_indices=[99]),
            dict(face_indices=[0, 0]),
            dict(face_indices=[]),
            dict(depth_mm=0),
            dict(direction="sideways"),
            dict(chamfer="yes"),
        ]
        for kwargs in calls:
            with self.subTest(kwargs=kwargs):
                result = create_weldment_end_cap(Automation(doc), "Member A",
                                                 **kwargs)
                self.assertFalse(result["success"])
        self.assertFalse(doc.FeatureManager.calls)

    def test_feature_missing_from_tree_is_not_reported_as_success(self):
        doc = Document()
        doc.in_tree = False
        result = create_weldment_end_cap(Automation(doc), "Member A")
        self.assertFalse(result["success"])
        self.assertEqual([True, True], doc.clears)

    def test_non_weldment_part_is_rejected(self):
        doc = Document(weldment=False)
        result = create_weldment_end_cap(Automation(doc), "Member A")
        self.assertFalse(result["success"])
        self.assertFalse(doc.FeatureManager.calls)

    def test_tool_is_registered_as_mutating(self):
        self.assertIn("create_weldment_end_cap",
                      [tool.name for tool in registered_tools()])
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("create_weldment_end_cap"))


if __name__ == "__main__":
    unittest.main()
