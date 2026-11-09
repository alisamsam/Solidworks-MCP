"""Grouping independent sketch lines under one structural-member feature."""

import unittest
from unittest.mock import patch

from solidworks_mcp.tools.weldments import create_structural_member


class Sketch:
    def __init__(self):
        self.segments = [object(), object(), object()]

    def GetSketchSegments(self):
        return self.segments
class Feature:
    Name = "Sketch1"

    def __init__(self):
        self.sketch = Sketch()
        self.kind = 'ProfileFeature'

    def GetTypeName2(self):
        return self.kind

    def GetSpecificFeature2(self):
        return self.sketch

    def GetNextFeature(self):
        return None


class Manager:
    def __init__(self):
        self.groups = []
        self.inserted = None

    def InsertWeldmentFeature(self):
        return None

    def CreateStructuralMemberGroup(self):
        group = type("Group", (), {})()
        self.groups.append(group)
        return group

    def InsertStructuralWeldment5(self, *args):
        self.inserted = args
        return type("WeldMember", (), {"Name": "Rods (1)"})()


class Document:
    def __init__(self):
        self.feature = Feature()
        self.FeatureManager = Manager()

    def FirstFeature(self):
        return self.feature


class Automation:
    def __init__(self, doc):
        self.doc = doc

    def get_active_doc(self):
        return self.doc, None

    @staticmethod
    def _result(success, message, error=None, data=None):
        return {"success": success, "message": message, "data": data}


class SeparateGroupTests(unittest.TestCase):
    def test_accepts_3d_framework_sketch(self):
        doc = Document()
        doc.feature.kind = '3DProfileFeature'
        with patch('solidworks_mcp.tools.weldments.os.path.isfile', return_value=True), \
             patch('solidworks_mcp.tools.weldments.win32com.client.VARIANT', side_effect=lambda kind, items: items):
            result = create_structural_member(Automation(doc), 'Sketch1', 'C:/library/profile.SLDLFP')
        self.assertTrue(result['success'], result)
        self.assertIsNotNone(doc.FeatureManager.inserted)

    def test_disconnected_lines_share_one_profile_feature_but_have_distinct_groups(self):
        doc = Document()
        with patch("solidworks_mcp.tools.weldments.os.path.isfile", return_value=True), \
             patch("solidworks_mcp.tools.weldments.win32com.client.VARIANT",
                   side_effect=lambda kind, items: items):
            result = create_structural_member(
                Automation(doc), "Sketch1", "C:/library/8mm palica.SLDLFP",
                separate_groups=True)
        self.assertTrue(result["success"], result)
        self.assertEqual(3, len(doc.FeatureManager.groups))
        self.assertEqual([[segment] for segment in doc.feature.sketch.segments],
                         [group.Segments for group in doc.FeatureManager.groups])
        self.assertEqual(doc.FeatureManager.groups, doc.FeatureManager.inserted[3])

    def test_group_mode_all_groups_disconnected_lines_together_but_per_segment_does_not(self):
        for mode, expected in (("all", 1), ("per_segment", 3), ("auto", 1)):
            with self.subTest(mode=mode):
                doc = Document()
                with patch("solidworks_mcp.tools.weldments.os.path.isfile",
                           return_value=True), \
                     patch("solidworks_mcp.tools.weldments.win32com.client.VARIANT",
                           side_effect=lambda kind, items: items):
                    result = create_structural_member(
                        Automation(doc), "Sketch1", "C:/library/rod.SLDLFP",
                        group_mode=mode)
                self.assertTrue(result["success"], result)
                self.assertEqual(expected, len(doc.FeatureManager.groups))

    def test_segment_indices_profile_only_the_chosen_lines_of_a_shared_sketch(self):
        doc = Document()
        segments = doc.feature.sketch.segments
        with patch("solidworks_mcp.tools.weldments.os.path.isfile", return_value=True), \
             patch("solidworks_mcp.tools.weldments.win32com.client.VARIANT",
                   side_effect=lambda kind, items: items):
            result = create_structural_member(
                Automation(doc), "Sketch1", "C:/library/rod.SLDLFP",
                group_mode="per_segment", segment_indices=[0, 2])
        self.assertTrue(result["success"], result)
        self.assertEqual([[segments[0]], [segments[2]]],
                         [group.Segments for group in doc.FeatureManager.groups])

    def test_segment_indices_reject_bad_values_before_any_com_call(self):
        for indices in ([], [3], [0, 0], [-1], [True], "0"):
            with self.subTest(indices=indices):
                doc = Document()
                result = create_structural_member(
                    Automation(doc), "Sketch1", "C:/library/rod.SLDLFP",
                    segment_indices=indices)
                self.assertFalse(result["success"])
                self.assertFalse(doc.FeatureManager.groups)

    def test_connected_frame_explicitly_sets_miter_corner_treatment(self):
        doc = Document()
        with patch("solidworks_mcp.tools.weldments.os.path.isfile", return_value=True), \
             patch("solidworks_mcp.tools.weldments.win32com.client.VARIANT",
                   side_effect=lambda kind, items: items):
            result = create_structural_member(
                Automation(doc), "Sketch1", "C:/library/50x20.SLDLFP",
                corner_type="miter")
        self.assertTrue(result["success"], result)
        self.assertEqual(1, len(doc.FeatureManager.groups))
        self.assertTrue(doc.FeatureManager.groups[0].ApplyCornerTreatment)
        self.assertEqual(1, doc.FeatureManager.groups[0].CornerTreatmentType)


if __name__ == "__main__":
    unittest.main()
