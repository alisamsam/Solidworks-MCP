"""add_drawing_dimension: a model view gains dimensions, then the drawing closes."""

import os
import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools.drawings import add_drawing_dimension, add_standard_3_view
from solidworks_mcp.tools.saving import save_document


@unittest.skipUnless(os.environ.get("SW_MCP_LIVE_TESTS") == "1",
                     "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.")
class LiveDrawingDimensionTests(unittest.TestCase):
    def setUp(self):
        self.automation = SolidWorksAutomation()
        result = self.automation.connect()
        if not result["success"]:
            self.skipTest(result["message"])
        # Unique token lets tear-down close exactly this test's documents,
        # including drawing windows whose title carries a "- Sheet1" suffix.
        self.token = uuid4().hex
        self.output_root = Path(self.automation._path_policy.output_roots[0])

    def tearDown(self):
        documents = self.automation.list_open_documents()
        if documents["success"]:
            for item in documents["data"]["documents"]:
                if self.token in item["title"]:
                    try:
                        self.automation.app.CloseDoc(item["title"])
                    except Exception:
                        pass
        self.automation.disconnect()

    def _own_documents(self):
        documents = self.automation.list_open_documents()
        self.assertTrue(documents["success"], documents["message"])
        return [item["title"] for item in documents["data"]["documents"]
                if self.token in item["title"]]

    def _model_view_name(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        retained = []
        view = com(document, "GetFirstView")
        while view is not None:
            retained.append(view)
            view = com(view, "GetNextView")
        for view in retained:
            if com(view, "ReferencedDocument") is not None:
                return com(view, "GetName2")
        return None

    def test_auto_dimension_model_view_saves_and_closes(self):
        saved_dir = self.output_root / "saved"
        saved_dir.mkdir(parents=True, exist_ok=True)
        part_path = saved_dir / f"mcp_live_dimension_part_{self.token}.SLDPRT"
        drawing_path = part_path.with_suffix(".SLDDRW")

        # Source part: 40 x 40 x 20 mm block.
        created = self.automation.create_new_part()
        self.assertTrue(created["success"], created["message"])
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-20, -20, 20, 20, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extruded = self.automation.extrude_sketch(20, False, "mm")
        self.assertTrue(extruded["success"], extruded["message"])
        saved_part = save_document(self.automation, path=str(part_path))
        self.assertTrue(saved_part["success"], saved_part["message"])
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        part_title = str(com(part, "GetTitle"))

        # Active drawing with the standard views of the saved part.
        drawing_created = self.automation.create_new_drawing("A4")
        self.assertTrue(drawing_created["success"], drawing_created["message"])
        views = add_standard_3_view(self.automation, part_title)
        self.assertTrue(views["success"], views["message"])
        view_name = self._model_view_name()
        self.assertIsNotNone(view_name, "No model view was created on the drawing.")

        # The real check: the named view gains drawing dimensions.
        result = add_drawing_dimension(self.automation, view_name)
        self.assertTrue(result["success"], result["message"])
        self.assertGreater(result["data"]["dimensions_after"],
                           result["data"]["dimensions_before"])
        self.assertGreater(result["data"]["dimensions_added"], 0)

        # An unknown view must fail without touching the drawing.
        unknown = add_drawing_dimension(self.automation, "Drawing View 999")
        self.assertFalse(unknown["success"])

        saved_drawing = save_document(self.automation, path=str(drawing_path))
        self.assertTrue(saved_drawing["success"], saved_drawing["message"])
        self.assertGreater(drawing_path.stat().st_size, 0)

        # Close this test's own documents and prove nothing of ours stays open.
        for title in self._own_documents():
            self.automation.app.CloseDoc(title)
        self.assertEqual([], self._own_documents())


if __name__ == "__main__":
    unittest.main()
