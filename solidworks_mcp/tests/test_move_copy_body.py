"""Translate/duplicate solid bodies using the selected body and mark 1."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Feature
from solidworks_mcp.tests.test_delete_body import Body, BodyDocument
from solidworks_mcp.tools.body_features import move_copy_body


class MovedBody(Body):
    def __init__(self, volume, x=0):
        super().__init__(volume)
        self.x = x

    def GetBodyBox(self):
        return (self.x, 0, 0, self.x + 0.01, 0.01, 0.01)


class MoveDocument(BodyDocument):
    def __init__(self):
        super().__init__()
        self.bodies = [MovedBody(100)]
        self.SelectionManager = type("SelectionManager", (), {
            "CreateSelectData": lambda self: type("Data", (), {"Mark": 0})(),
        })()

    def InsertMoveCopyBody2(self, *args):
        self.args = args
        selected = next(body for body in self.bodies if body.selected)
        shifted = MovedBody(selected.volume, selected.x + args[0])
        if args[-2]:
            self.bodies.append(shifted)
        else:
            self.bodies = [shifted]
        return Feature("MoveCopyBody1", "MoveCopyBody")


class MoveCopyTests(unittest.TestCase):
    def test_move_changes_box_and_retains_volume(self):
        doc = MoveDocument()
        result = move_copy_body(Automation(doc), 0, 20, 0, 0)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual((0.02, 0.0, 0.0, 0.0), doc.args[:4])
        self.assertEqual((False, 1), doc.args[-2:])
        self.assertEqual(1, result["data"]["bodies_after"])
        self.assertAlmostEqual(100, result["data"]["volume_after_mm3"])

    def test_copy_adds_second_body_and_doubles_volume(self):
        doc = MoveDocument()
        result = move_copy_body(Automation(doc), 0, 20, 0, 0, copy=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual((True, 1), doc.args[-2:])
        self.assertEqual(2, result["data"]["bodies_after"])
        self.assertAlmostEqual(200, result["data"]["volume_after_mm3"])

    def test_zero_vector_is_rejected_before_com(self):
        sw = Automation(MoveDocument())
        self.assertFalse(move_copy_body(sw, 0, 0, 0, 0)["success"])
        self.assertEqual(0, sw.active_doc_calls)
