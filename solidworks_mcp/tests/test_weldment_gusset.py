"""Unit tests for the weldment gusset tool (W4)."""

import math
import unittest
from unittest.mock import patch

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.weldments import (
    GUSSET_DIRECTIONS, GUSSET_LOCATIONS, create_weldment_gusset,
)


class Surface:
    def __init__(self, planar=True):
        self.IsPlane = planar


class Face:
    def __init__(self, normal, planar=True):
        self.Normal = normal
        self._surface = Surface(planar)
        self.selections = []

    def GetSurface(self):
        return self._surface

    def Select4(self, append, select_data):
        self.selections.append((append, getattr(select_data, "Mark", None)))
        return True


class SelectData:
    Mark = 0


class SelectionManager:
    def CreateSelectData(self):
        return SelectData()


class Body:
    def __init__(self, name, faces, volume_m3=1.0e-6):
        self.Name = name
        self.faces = faces
        self.volume_m3 = volume_m3

    def GetFaces(self):
        return self.faces

    def GetMassProperties(self, density):
        return [0.0, 0.0, 0.0, self.volume_m3, 0.0, 0.0]


class Feature:
    def __init__(self, name="Gusset1", type_name="Gusset"):
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

    def InsertGussetFeature3(self, *args):
        self.calls.append(args)
        if self.document.feature is None:
            return None
        if self.document.in_tree and self.document.adds_material:
            self.document.bodies.append(Body("Gusset1", [], 1.5e-6))
        return self.document.feature


def two_bodies():
    # Global planar-face indices: A:0(+Z), A:1(+Y), A:2(non-planar),
    # B:3(-Y), B:4(+Z).
    a = Body("Member A", [Face([0.0, 0.0, 1.0]), Face([0.0, 1.0, 0.0]),
                          Face([0.0, 0.0, 1.0], planar=False)])
    b = Body("Member B", [Face([0.0, -1.0, 0.0]), Face([0.0, 0.0, 1.0])])
    return [a, b]


class Document:
    Name = "Weldment"

    def __init__(self, weldment=True, bodies=None):
        self.bodies = bodies if bodies is not None else two_bodies()
        self.feature = Feature()
        self.in_tree = True
        self.adds_material = True
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
        assert body_type == 0
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


class WeldmentGussetTests(unittest.TestCase):
    def setUp(self):
        self.variant_patch = patch(
            "solidworks_mcp.tools.weldments.win32com.client.VARIANT",
            side_effect=lambda kind, values: (kind, list(values)))
        self.variant = self.variant_patch.start()
        self.addCleanup(self.variant_patch.stop)

    def test_defaults_map_to_the_official_example_arguments(self):
        doc = Document()
        result = create_weldment_gusset(Automation(doc), 0, 3)

        self.assertTrue(result["success"], result)
        self.assertEqual(1, len(doc.FeatureManager.calls))
        args = doc.FeatureManager.calls[0]
        self.assertEqual(20, len(args))
        self.assertAlmostEqual(0.005, args[0])
        self.assertEqual(GUSSET_DIRECTIONS["both"], args[1])
        self.assertEqual(GUSSET_LOCATIONS["center"], args[2])
        self.assertIs(False, args[3])  # triangle, BIsProfile false
        self.assertAlmostEqual(0.025, args[4])
        self.assertAlmostEqual(0.025, args[5])
        self.assertAlmostEqual(0.015, args[6])
        self.assertAlmostEqual(math.radians(45), args[7])
        self.assertAlmostEqual(0.015, args[8])
        self.assertIs(False, args[9])
        self.assertAlmostEqual(0.005, args[10])
        self.assertEqual(0, args[11])
        self.assertIs(False, args[12])
        self.assertIs(False, args[13])
        self.assertIs(False, args[14])
        self.assertAlmostEqual(0.0125, args[15])
        self.assertAlmostEqual(0.0125, args[16])
        self.assertAlmostEqual(math.radians(45), args[17])
        self.assertIs(True, args[18])
        self.assertIs(False, args[19])
        # Supporting faces selected with mark 1, in order.
        self.assertEqual([(False, 1)], doc.bodies[0].faces[0].selections)
        self.assertEqual([(True, 1)], doc.bodies[1].faces[0].selections)
        self.assertEqual([True, True], doc.clears)
        self.assertEqual("Gusset", result["data"]["feature_type"])
        self.assertEqual(["Gusset1"], result["data"]["gusset_bodies"])
        self.assertAlmostEqual(1500.0, result["data"]["added_mm3"])

    def test_custom_modes_convert_units_and_enum_names(self):
        doc = Document()
        result = create_weldment_gusset(
            Automation(doc), 0, 3, depth_mm=6.0, direction="outer",
            location="end", profile="polygon", leg1_mm=30.0, leg2_mm=20.0,
            leg3_mm=10.0, angle_deg=30.0, use_length_dim=True, leg4_mm=12.0,
            offset=True, offset_mm=3.0, reverse_dir=True, reverse_face=True,
            crv_index=2, chamfer=True, chamfer1_mm=4.0, chamfer2_mm=5.0,
            chamfer_angle_deg=60.0, use_length_dim_for_chamfer=False)
        self.assertTrue(result["success"], result)
        args = doc.FeatureManager.calls[0]
        self.assertAlmostEqual(0.006, args[0])
        self.assertEqual(GUSSET_DIRECTIONS["outer"], args[1])
        self.assertEqual(GUSSET_LOCATIONS["end"], args[2])
        self.assertIs(True, args[3])  # polygon
        self.assertAlmostEqual(0.030, args[4])
        self.assertAlmostEqual(0.010, args[6])
        self.assertAlmostEqual(math.radians(30), args[7])
        self.assertAlmostEqual(0.012, args[8])
        self.assertIs(True, args[9])
        self.assertAlmostEqual(0.003, args[10])
        self.assertEqual(2, args[11])
        self.assertIs(True, args[12])
        self.assertIs(True, args[13])
        self.assertIs(True, args[14])
        self.assertIs(True, args[19])
        self.assertAlmostEqual(math.radians(60), args[17])
        self.assertIs(False, args[18])

    def test_invalid_pairs_are_rejected_without_mutation(self):
        cases = [
            ("same index", dict(face_a_index=0, face_b_index=0)),
            ("same body", dict(face_a_index=0, face_b_index=1)),
            ("parallel faces", dict(face_a_index=0, face_b_index=4)),
            ("non-planar", dict(face_a_index=2, face_b_index=3)),
            ("out of range", dict(face_a_index=0, face_b_index=99)),
            ("bad direction", dict(face_a_index=0, face_b_index=3,
                                   direction="sideways")),
            ("bad profile", dict(face_a_index=0, face_b_index=3,
                                 profile="circle")),
            ("negative depth", dict(face_a_index=0, face_b_index=3,
                                    depth_mm=-1)),
            ("angle out of range", dict(face_a_index=0, face_b_index=3,
                                        angle_deg=200)),
            ("bool as number", dict(face_a_index=0, face_b_index=3,
                                    leg1_mm=True)),
        ]
        for label, kwargs in cases:
            with self.subTest(label=label):
                doc = Document()
                result = create_weldment_gusset(Automation(doc), **kwargs)
                self.assertFalse(result["success"], label)
                self.assertFalse(doc.FeatureManager.calls, label)

    def test_feature_missing_from_tree_or_adding_nothing_is_not_success(self):
        no_tree = Document()
        no_tree.in_tree = False
        result = create_weldment_gusset(Automation(no_tree), 0, 3)
        self.assertFalse(result["success"])

        no_material = Document()
        no_material.adds_material = False
        result = create_weldment_gusset(Automation(no_material), 0, 3)
        self.assertFalse(result["success"])
        self.assertEqual(0.0, result["data"]["added_mm3"])

    def test_non_weldment_part_is_rejected(self):
        doc = Document(weldment=False)
        result = create_weldment_gusset(Automation(doc), 0, 3)
        self.assertFalse(result["success"])
        self.assertFalse(doc.FeatureManager.calls)

    def test_tool_is_registered_as_mutating(self):
        self.assertIn("create_weldment_gusset",
                      [tool.name for tool in registered_tools()])
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("create_weldment_gusset"))


if __name__ == "__main__":
    unittest.main()
