"""D1: the marked-for-drawing filter really filters, both ways.

A 40 x 20 mm rectangle carries two sketch dimensions. ``D1`` is marked
"Mark for Drawing" and ``D2`` is left unmarked. One drawing proves the marked
tool imports only ``D1``; a second drawing proves the not-marked option imports
only ``D2``. Because the two dimensions measure different lengths (40 mm vs
20 mm), the imported dimension is identified by name *and* by value.
"""

import os
import unittest
from pathlib import Path
from uuid import uuid4

import pythoncom
import win32com.client

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com, set_com
from solidworks_mcp.tools.drawing_annotations import insert_marked_dimensions
from solidworks_mcp.tools.drawings import add_standard_3_view
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.sketch_edit import add_sketch_dimension
from solidworks_mcp.tests.live._scratch import (close_new_documents,
                                                open_document_titles)

# swInsertAnnotation_e (swconst.tlb): the counterpart option that proves the
# two sets are disjoint.
SW_INSERT_DIMENSIONS_NOT_MARKED_FOR_DRAWING = 524288

# swImportModelItemsSource_e.swImportModelItemsFromEntireModel.
SW_IMPORT_MODEL_ITEMS_FROM_ENTIRE_MODEL = 0

WIDTH_MM = 40.0
HEIGHT_MM = 20.0


@unittest.skipUnless(os.environ.get("SW_MCP_LIVE_TESTS") == "1",
                     "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.")
class LiveMarkedDimensionTests(unittest.TestCase):
    def setUp(self):
        self.automation = SolidWorksAutomation()
        result = self.automation.connect()
        if not result["success"]:
            self.skipTest(result["message"])
        self.token = uuid4().hex
        self.extra_titles = []
        self.output_root = Path(self.automation._path_policy.output_roots[0])
        self.baseline_titles = open_document_titles(self.automation)

    def tearDown(self):
        for title in list(self.extra_titles):
            try:
                self.automation.app.CloseDoc(title)
            except Exception:
                pass
        documents = self.automation.list_open_documents()
        if documents["success"]:
            for item in documents["data"]["documents"]:
                if self.token in item["title"]:
                    try:
                        self.automation.app.CloseDoc(item["title"])
                    except Exception:
                        pass
        close_new_documents(self.automation, self.baseline_titles)
        self.automation.disconnect()

    # -- helpers -----------------------------------------------------------
    def _own_documents(self):
        documents = self.automation.list_open_documents()
        self.assertTrue(documents["success"], documents["message"])
        return [item["title"] for item in documents["data"]["documents"]
                if self.token in item["title"]]

    def _sketch_feature(self, part, name):
        retained = []
        feature = com(part, "FirstFeature")
        while feature is not None:
            retained.append(feature)
            if (com(feature, "GetTypeName2") == "ProfileFeature"
                    and str(com(feature, "Name")) == name):
                return feature
            feature = com(feature, "GetNextFeature")
        return None

    def _display_dimensions(self, feature):
        retained = []
        dimensions = []
        display = com(feature, "GetFirstDisplayDimension")
        while display is not None:
            retained.append(display)
            dimensions.append(display)
            display = com(feature, "GetNextDisplayDimension", display)
        return dimensions

    def _model_views(self, document):
        retained = []
        views = []
        view = com(document, "GetFirstView")
        while view is not None:
            retained.append(view)
            views.append(view)
            view = com(view, "GetNextView")
        return [view for view in views
                if com(view, "ReferencedDocument") is not None]

    def _view_dimensions(self, view):
        """Imported dimensions in a view as (full_name, system_value)."""
        retained = []
        entries = []
        for display in com(view, "GetDisplayDimensions") or []:
            retained.append(display)
            dimension = com(display, "GetDimension")
            if dimension is None:
                continue
            retained.append(dimension)
            entries.append((str(com(dimension, "FullName")),
                            float(com(dimension, "SystemValue"))))
        return entries

    def _view_dimensions_by_name(self, document, view_name):
        for view in self._model_views(document):
            if com(view, "GetName2") == view_name:
                return self._view_dimensions(view)
        self.fail(f"view not found: {view_name}")

    def _new_drawing_with_view(self, part_title):
        created = self.automation.create_new_drawing("A4")
        self.assertTrue(created["success"], created["message"])
        # Track the unsaved name too: a failure before SaveAs would otherwise
        # leak a "DrawN" window that the token sweep cannot see.
        self.extra_titles.append(created["data"]["name"])
        views = add_standard_3_view(self.automation, part_title)
        self.assertTrue(views["success"], views["message"])
        drawing, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        model_views = self._model_views(drawing)
        self.assertGreaterEqual(len(model_views), 1)
        return drawing, com(model_views[0], "GetName2")

    def _select_view(self, drawing, view_name):
        empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        com(drawing, "ClearSelection2", True)
        self.assertTrue(com(com(drawing, "Extension"), "SelectByID2",
                            view_name, "DRAWINGVIEW", 0.0, 0.0, 0.0,
                            False, 0, empty, 0), f"could not select {view_name}")

    # -- the live proof ----------------------------------------------------
    def test_marked_dimension_filter_both_ways(self):
        saved_dir = self.output_root / "saved"
        saved_dir.mkdir(parents=True, exist_ok=True)
        part_path = saved_dir / f"mcp_live_marked_part_{self.token}.SLDPRT"

        # 40 x 20 mm rectangle: D1 is the 40 mm side, D2 the 20 mm side.
        created = self.automation.create_new_part()
        self.assertTrue(created["success"], created["message"])
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        sketch_name = None
        feature = com(part, "FirstFeature")
        while feature is not None:
            if com(feature, "GetTypeName2") == "ProfileFeature":
                sketch_name = str(com(feature, "Name"))
            feature = com(feature, "GetNextFeature")
        self.assertIsNotNone(sketch_name)

        drawn = self.automation.draw_rectangle(
            -WIDTH_MM / 2, -HEIGHT_MM / 2, WIDTH_MM / 2, HEIGHT_MM / 2, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        exited = self.automation.exit_sketch()
        self.assertTrue(exited["success"], exited["message"])
        for entity, x, y in (("Line1", 0, -HEIGHT_MM), ("Line2", WIDTH_MM, 0)):
            dimension = add_sketch_dimension(self.automation, sketch_name,
                                             [entity], x, y)
            self.assertTrue(dimension["success"], dimension["message"])

        dimensions = self._display_dimensions(
            self._sketch_feature(part, sketch_name))
        self.assertEqual(2, len(dimensions))
        set_com(dimensions[0], "MarkedForDrawing", True)
        set_com(dimensions[1], "MarkedForDrawing", False)
        self.assertTrue(bool(com(dimensions[0], "MarkedForDrawing")))
        self.assertFalse(bool(com(dimensions[1], "MarkedForDrawing")))

        saved_part = save_document(self.automation, path=str(part_path))
        self.assertTrue(saved_part["success"], saved_part["message"])
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        part_title = str(com(part, "GetTitle"))

        # Drawing 1: the tool imports only the dimension marked for drawing.
        drawing_one, view_one = self._new_drawing_with_view(part_title)
        marked = insert_marked_dimensions(self.automation, view_one)
        self.assertTrue(marked["success"], marked["message"])
        self.assertEqual(1, marked["data"]["inserted_annotations"])
        self.assertEqual(1, marked["data"]["imported"])
        marked_dims = self._view_dimensions_by_name(drawing_one, view_one)
        self.assertEqual(1, len(marked_dims))
        self.assertTrue(marked_dims[0][0].startswith("D1@"), marked_dims[0])
        self.assertAlmostEqual(WIDTH_MM / 1000.0, marked_dims[0][1], places=6)
        drawing_one_path = saved_dir / f"mcp_live_marked_one_{self.token}.SLDDRW"
        self.assertTrue(save_document(
            self.automation, path=str(drawing_one_path))["success"])
        self.automation.app.CloseDoc(str(com(drawing_one, "GetTitle")))

        # Drawing 2: the opposite option imports only the unmarked dimension.
        drawing_two, view_two = self._new_drawing_with_view(part_title)
        self._select_view(drawing_two, view_two)
        com(drawing_two, "InsertModelAnnotations4",
            SW_IMPORT_MODEL_ITEMS_FROM_ENTIRE_MODEL,
            SW_INSERT_DIMENSIONS_NOT_MARKED_FOR_DRAWING,
            False, False, False, False, False, False)
        com(drawing_two, "ClearSelection2", True)
        unmarked_dims = self._view_dimensions_by_name(drawing_two, view_two)
        self.assertEqual(1, len(unmarked_dims))
        self.assertTrue(unmarked_dims[0][0].startswith("D2@"), unmarked_dims[0])
        self.assertAlmostEqual(HEIGHT_MM / 1000.0, unmarked_dims[0][1], places=6)
        drawing_two_path = saved_dir / f"mcp_live_marked_two_{self.token}.SLDDRW"
        self.assertTrue(save_document(
            self.automation, path=str(drawing_two_path))["success"])
        self.automation.app.CloseDoc(str(com(drawing_two, "GetTitle")))

        self.assertGreater(drawing_one_path.stat().st_size, 0)
        self.assertGreater(drawing_two_path.stat().st_size, 0)

        for title in self._own_documents():
            self.automation.app.CloseDoc(title)
        self.assertEqual([], self._own_documents())


if __name__ == "__main__":
    unittest.main()
