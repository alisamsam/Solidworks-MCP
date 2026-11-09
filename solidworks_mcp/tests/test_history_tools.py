import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.history import redo, undo


class Document:
    def __init__(self):
        self.undo_steps = []
        self.redo_steps = []

    def EditUndo2(self, steps):
        self.undo_steps.append(steps)

    def EditRedo2(self, steps):
        self.redo_steps.append(steps)


class FailingDocument(Document):
    def EditUndo2(self, steps):
        raise RuntimeError("undo stack unavailable")


class Automation:
    def __init__(self, document=None):
        self.document = document or Document()
        self.active_doc_calls = 0

    def get_active_doc(self):
        self.active_doc_calls += 1
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {
            "success": success,
            "message": message,
            "error_code": int(error_code),
            "data": data or {},
        }


class HistoryToolRegistrationTests(unittest.TestCase):
    def test_undo_and_redo_are_bounded_mutation_tools(self):
        tools = {item.name: item for item in registered_tools()}

        for name in ("undo", "redo"):
            self.assertIn(name, tools)
            self.assertIs(OperationClass.MUTATE, operation_class_for(name))
            steps = tools[name].inputSchema["properties"]["steps"]
            self.assertEqual(1, steps["minimum"])
            self.assertEqual(20, steps["maximum"])
            self.assertEqual(1, steps["default"])


class HistoryToolBehaviorTests(unittest.TestCase):
    def test_undo_issues_exact_number_of_steps_without_claiming_stack_details(self):
        automation = Automation()

        result = undo(automation, 3)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([3], automation.document.undo_steps)
        self.assertEqual("command_issued", result["data"]["status"])
        self.assertEqual("IModelDoc2.EditUndo2", result["data"]["api"])
        self.assertNotIn("feature", result["data"])

    def test_redo_issues_exact_number_of_steps(self):
        automation = Automation()

        result = redo(automation, 2)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([2], automation.document.redo_steps)
        self.assertEqual("command_issued", result["data"]["status"])

    def test_invalid_steps_are_rejected_before_active_document_access(self):
        for invalid in (0, 21, True, 1.5):
            with self.subTest(steps=invalid):
                automation = Automation()

                result = undo(automation, invalid)

                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)
                self.assertEqual([], automation.document.undo_steps)

    def test_com_failure_is_returned_as_a_tool_error(self):
        result = undo(Automation(FailingDocument()), 1)

        self.assertFalse(result["success"])
        self.assertIn("undo stack unavailable", result["message"])


if __name__ == "__main__":
    unittest.main()
