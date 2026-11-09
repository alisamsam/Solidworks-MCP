"""add_drawing_dimension must prove the view's dimension count grew."""

import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.drawings import add_drawing_dimension

AUTODIM_ARGS = (0, 1, 1, 1, 1)  # BasedOnPreselect, Baseline, Above, Baseline, Right


class View:
    def __init__(self, name, dimension_count=0, next_view=None):
        self.Name = name
        self.dimension_count = dimension_count
        self.next_view = next_view

    def GetName2(self):
        return self.Name

    def GetDimensionCount2(self):
        return self.dimension_count

    def GetNextView(self):
        return self.next_view


class Extension:
    def __init__(self, select_ok=True):
        self.select_ok = select_ok
        self.select_calls = []

    def SelectByID2(self, name, type_name, x, y, z, append, mark, callout, options):
        self.select_calls.append((name, type_name, append))
        return self.select_ok


class Document:
    def __init__(self, doc_type=3, select_ok=True, status=0, added=3):
        self.doc_type = doc_type
        self.status = status
        self.added = added
        self.target = View("Drawing View1")
        self.sheet = View("Sheet1", next_view=self.target)
        self.Extension = Extension(select_ok)
        self.autodim_calls = []
        self.clear_calls = []

    def GetType(self):
        return self.doc_type

    def GetFirstView(self):
        return self.sheet

    def ClearSelection2(self, clear_all):
        self.clear_calls.append(clear_all)
        return True

    def AutoDimension(self, *args):
        self.autodim_calls.append(args)
        if self.added:
            self.target.dimension_count += self.added
        return self.status


class Automation:
    def __init__(self, document=None):
        self.document = document or Document()
        self.active_doc_calls = 0

    def get_active_doc(self):
        self.active_doc_calls += 1
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message,
                "error_code": int(error_code), "data": data or {}}


class DrawingDimensionRegistrationTests(unittest.TestCase):
    def test_tool_is_registered_as_mutation(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("add_drawing_dimension", tools)
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("add_drawing_dimension"))
        self.assertEqual(["view_name"],
                         tools["add_drawing_dimension"].inputSchema["required"])


class AddDrawingDimensionTests(unittest.TestCase):
    def test_auto_dimensions_view_and_reports_growth(self):
        automation = Automation()

        result = add_drawing_dimension(automation, "Drawing View1")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([("Drawing View1", "DRAWINGVIEW", False)],
                         automation.document.Extension.select_calls)
        self.assertEqual([AUTODIM_ARGS], automation.document.autodim_calls)
        self.assertEqual(3, result["data"]["dimensions_added"])
        self.assertEqual((0, 3), (result["data"]["dimensions_before"],
                                  result["data"]["dimensions_after"]))
        self.assertEqual([True, True], automation.document.clear_calls)

    def test_growth_wins_over_a_non_zero_return_code(self):
        # SW 2025 rev 33.1.1 returns 1 from AutoDimension even when it adds
        # dimensions, so a growing count must still be reported as success.
        automation = Automation(Document(status=1, added=2))

        result = add_drawing_dimension(automation, "Drawing View1")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(2, result["data"]["dimensions_added"])
        self.assertEqual(1, result["data"]["autodim_status"])

    def test_no_growth_is_reported_as_failure(self):
        automation = Automation(Document(added=0))

        result = add_drawing_dimension(automation, "Drawing View1")

        self.assertFalse(result["success"])
        self.assertEqual("NO_DIMENSIONS_ADDED", result["data"]["code"])

    def test_unknown_view_is_rejected_before_autodimension(self):
        automation = Automation()

        result = add_drawing_dimension(automation, "Drawing View9")

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.autodim_calls)

    def test_unselectable_view_is_rejected_before_autodimension(self):
        automation = Automation(Document(select_ok=False))

        result = add_drawing_dimension(automation, "Drawing View1")

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.autodim_calls)

    def test_non_drawing_document_is_rejected(self):
        automation = Automation(Document(doc_type=1))

        result = add_drawing_dimension(automation, "Drawing View1")

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.autodim_calls)

    def test_empty_view_name_is_rejected_before_com(self):
        automation = Automation()

        result = add_drawing_dimension(automation, "   ")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)


if __name__ == "__main__":
    unittest.main()
