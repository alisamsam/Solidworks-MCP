import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.drawing_annotations import auto_balloon, insert_marked_dimensions


class Annotation:
    def __init__(self, next_annotation=None):
        self.next_annotation = next_annotation

    def GetNext3(self):
        return self.next_annotation


class BalloonOptions:
    def __init__(self):
        self.Layout = None
        self.IgnoreMultiple = None


class View:
    def __init__(self, name, dimension_count=0, annotations=0, next_view=None):
        self.Name = name
        self.dimension_count = dimension_count
        self.annotations = annotations
        self.next_view = next_view

    def GetName2(self):
        return self.Name

    def GetDimensionCount2(self):
        return self.dimension_count

    def GetFirstAnnotation2(self):
        if not self.annotations:
            return None
        chain = None
        for _ in range(self.annotations):
            chain = Annotation(chain)
        return chain

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
    def __init__(self, doc_type=3, select_ok=True, inserted=True, balloons=True,
                 import_dimensions=1, balloons_created=2):
        self.doc_type = doc_type
        self.import_dimensions = import_dimensions
        self.balloons_created = balloons_created
        self.inserted = inserted
        self.balloons = balloons
        self.target = View("Drawing View1")
        self.sheet = View("Sheet1", next_view=self.target)
        self.FirstView = self.sheet
        self.Extension = Extension(select_ok)
        self.insert_calls = []
        self.balloon_calls = []
        self.clear_calls = []

    def GetType(self):
        return self.doc_type

    def GetFirstView(self):
        return self.FirstView

    def ClearSelection2(self, clear_all):
        self.clear_calls.append(clear_all)
        return True

    def InsertModelAnnotations4(self, option, types, all_views, duplicate_dims,
                                hidden_dims, use_placement, all_annotations,
                                all_reference_geometry):
        self.insert_calls.append((option, types, all_views, duplicate_dims,
                                  hidden_dims, use_placement, all_annotations,
                                  all_reference_geometry))
        if self.inserted and self.import_dimensions:
            self.target.dimension_count += self.import_dimensions
        return ["annotation"] * self.import_dimensions if self.inserted else []

    def CreateAutoBalloonOptions(self):
        return BalloonOptions()

    def AutoBalloon5(self, options):
        self.balloon_calls.append(options)
        if self.balloons and self.balloons_created:
            self.target.annotations += self.balloons_created
        return self.balloons


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


class DrawingAnnotationRegistrationTests(unittest.TestCase):
    def test_tools_are_registered_as_mutations(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("insert_marked_dimensions", tools)
        self.assertIn("auto_balloon", tools)
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("insert_marked_dimensions"))
        self.assertIs(OperationClass.MUTATE, operation_class_for("auto_balloon"))
        self.assertEqual(["view_name"],
                         tools["insert_marked_dimensions"].inputSchema["required"])


class InsertMarkedDimensionsTests(unittest.TestCase):
    def test_selects_view_and_uses_marked_for_drawing_option(self):
        automation = Automation()

        result = insert_marked_dimensions(automation, "Drawing View1")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            [("Drawing View1", "DRAWINGVIEW", False)],
            automation.document.Extension.select_calls,
        )
        # InsertModelAnnotations4(Option, Types, ...) with Types = 32768
        # (swInsertDimensionsMarkedForDrawing); the old InsertModelDimensions
        # took only 0..3 and could not filter.
        self.assertEqual(
            [(0, 32768, False, True, False, False, False, False)],
            automation.document.insert_calls,
        )
        self.assertEqual(1, result["data"]["inserted_annotations"])
        self.assertEqual(1, result["data"]["imported"])

    def test_unknown_view_is_rejected(self):
        automation = Automation()

        result = insert_marked_dimensions(automation, "Drawing View9")

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.insert_calls)

    def test_non_drawing_document_is_rejected(self):
        automation = Automation(Document(doc_type=1))

        result = insert_marked_dimensions(automation, "Drawing View1")

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.insert_calls)

    def test_empty_view_name_is_rejected_before_com(self):
        automation = Automation()

        result = insert_marked_dimensions(automation, "   ")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_nothing_imported_is_reported_when_api_returns_false(self):
        automation = Automation(Document(inserted=False, import_dimensions=0))

        result = insert_marked_dimensions(automation, "Drawing View1")

        self.assertFalse(result["success"])
        self.assertEqual("NO_MARKED_DIMENSIONS", result["data"]["code"])


class AutoBalloonTests(unittest.TestCase):
    def test_selects_view_sets_layout_and_calls_auto_balloon(self):
        automation = Automation()

        result = auto_balloon(automation, "Drawing View1", layout=2,
                              ignore_multiple=True)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            [("Drawing View1", "DRAWINGVIEW", False)],
            automation.document.Extension.select_calls,
        )
        options = automation.document.balloon_calls[0]
        self.assertEqual(2, options.Layout)
        self.assertTrue(options.IgnoreMultiple)
        self.assertEqual(2, result["data"]["balloons_added"])

    def test_unknown_view_is_rejected(self):
        automation = Automation()

        result = auto_balloon(automation, "Drawing View9")

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.balloon_calls)

    def test_no_balloons_added_is_reported(self):
        automation = Automation(Document(balloons=False, balloons_created=0))

        result = auto_balloon(automation, "Drawing View1")

        self.assertFalse(result["success"])
        self.assertEqual("NO_BALLOONS_ADDED", result["data"]["code"])

    def test_non_integer_layout_is_rejected_before_com(self):
        automation = Automation()

        result = auto_balloon(automation, "Drawing View1", layout="wide")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)


if __name__ == "__main__":
    unittest.main()
