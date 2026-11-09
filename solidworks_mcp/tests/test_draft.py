"""Draft on planar faces (M2.2); live evidence in api-findings §33."""

import math
import unittest
from unittest.mock import patch

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tests.test_advanced_features import Automation, Document, Face
from solidworks_mcp.tools.advanced_features import draft_faces

FACE_LOOKUP = "solidworks_mcp.tools.advanced_features._get_planar_face_by_index"


class DraftFeature:
    def __init__(self, error_code=0):
        self.Name = "Draft1"
        self.error_code = error_code

    def GetErrorCode(self):
        return self.error_code

    def Select2(self, append, mark):
        return True


class DraftFeatureManager:
    def __init__(self, created, error_code):
        self.created = created
        self.error_code = error_code
        self.draft_args = None

    def InsertMultiFaceDraft(self, *args):
        self.draft_args = args
        return DraftFeature(self.error_code) if self.created else None


class DraftDocument(Document):
    def __init__(self, created=True, error_code=0):
        super().__init__()
        self.FeatureManager = DraftFeatureManager(created, error_code)
        self.edit_delete_calls = 0

    def EditDelete(self):
        self.edit_delete_calls += 1
        return True


class DraftTests(unittest.TestCase):
    def test_draft_is_registered_as_a_mutation(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIs(OperationClass.MUTATE, operation_class_for("draft_faces"))
        self.assertEqual(["angle", "neutral_face_index", "draft_face_indices"],
                         tools["draft_faces"].inputSchema["required"])

    @patch(FACE_LOOKUP)
    def test_neutral_face_gets_mark_one_and_drafted_faces_mark_two(self, get_face):
        neutral, first, second = Face(), Face(), Face()
        get_face.side_effect = [neutral, first, second]
        automation = Automation(DraftDocument())

        result = draft_faces(automation, 5, 5, [0, 2])

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 1)], neutral.select_calls)
        self.assertEqual([(True, 2)], first.select_calls)
        self.assertEqual([(True, 2)], second.select_calls)
        args = automation.document.FeatureManager.draft_args
        self.assertAlmostEqual(math.radians(5), args[0], places=12)
        self.assertEqual((False, False, 0, False, False), args[1:])
        self.assertEqual("Draft1", result["data"]["feature_name"])

    @patch(FACE_LOOKUP)
    def test_flip_is_passed_through(self, get_face):
        get_face.side_effect = [Face(), Face()]
        automation = Automation(DraftDocument())

        draft_faces(automation, 3, 5, [0], flip=True)

        self.assertIs(True, automation.document.FeatureManager.draft_args[1])

    def test_bad_input_is_rejected_before_com(self):
        for call in (
            {"angle": 0, "neutral_face_index": 5, "draft_face_indices": [0]},
            {"angle": 90, "neutral_face_index": 5, "draft_face_indices": [0]},
            {"angle": 5, "neutral_face_index": 5, "draft_face_indices": []},
            {"angle": 5, "neutral_face_index": 5, "draft_face_indices": [5]},
            {"angle": 5, "neutral_face_index": -1, "draft_face_indices": [0]},
            {"angle": 5, "neutral_face_index": 5, "draft_face_indices": [0, 0]},
        ):
            with self.subTest(call=call):
                automation = Automation(DraftDocument())
                self.assertFalse(draft_faces(automation, **call)["success"])
                self.assertEqual(0, automation.active_doc_calls)

    @patch(FACE_LOOKUP)
    def test_a_missing_face_is_reported(self, get_face):
        get_face.side_effect = [Face(), None]

        result = draft_faces(Automation(DraftDocument()), 5, 5, [9])

        self.assertFalse(result["success"])
        self.assertIn("9", result["message"])

    @patch(FACE_LOOKUP)
    def test_a_broken_draft_is_removed(self, get_face):
        get_face.side_effect = [Face(), Face()]
        automation = Automation(DraftDocument(error_code=5))

        result = draft_faces(automation, 5, 5, [0])

        self.assertFalse(result["success"])
        self.assertEqual(1, automation.document.edit_delete_calls)
