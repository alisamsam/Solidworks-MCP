"""Insert Part: a saved part's solid is imported into a fresh part."""

import os
import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools.body_features import insert_part
from solidworks_mcp.tools.saving import save_document


@unittest.skipUnless(os.environ.get("SW_MCP_LIVE_TESTS") == "1",
                     "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.")
class LiveInsertPartTests(unittest.TestCase):
    def setUp(self):
        self.automation = SolidWorksAutomation()
        result = self.automation.connect()
        if not result["success"]:
            self.skipTest(result["message"])
        self.open_titles = []
        self.output_root = Path(self.automation._path_policy.output_roots[0])

    def tearDown(self):
        for title in reversed(self.open_titles):
            try:
                self.automation.app.CloseDoc(title)
            except Exception:
                pass
        self.automation.disconnect()

    def _new_part(self):
        created = self.automation.create_new_part()
        self.assertTrue(created["success"], created["message"])
        self.open_titles.append(created["data"]["name"])

    def _document(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        return document

    def _bodies(self):
        return com(self._document(), "GetBodies2", 0, True) or []

    def _volume(self):
        return sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                   for body in self._bodies())

    def _feature_types(self):
        types = []
        feature = com(self._document(), "FirstFeature")
        while feature is not None:
            types.append(str(com(feature, "GetTypeName2")))
            feature = com(feature, "GetNextFeature")
        return types

    def _save_and_close(self, path):
        saved = save_document(self.automation, path=str(path))
        self.assertTrue(saved["success"], saved["message"])
        # SaveAs renames the document to the file stem.
        self.open_titles[-1] = path.stem
        self.automation.app.CloseDoc(path.stem)
        self.open_titles.pop()

    def test_insert_part_imports_source_solid_saves_and_closes(self):
        # Source part: 40 x 40 x 20 mm block saved into the approved output root.
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-20, -20, 20, 20, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extruded = self.automation.extrude_sketch(20, False, "mm")
        self.assertTrue(extruded["success"], extruded["message"])
        source_volume = self._volume()
        self.assertAlmostEqual(32000, source_volume, delta=1)
        source_path = self.output_root / "saved" / f"mcp_live_insert_source_{uuid4().hex}.SLDPRT"
        self._save_and_close(source_path)

        # Target part starts empty; Insert Part adds the source solid.
        self._new_part()
        self.assertEqual([], self._bodies())
        result = insert_part(self.automation, part_path=str(source_path))
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("Stock", result["data"]["feature_type"])
        self.assertEqual(1, result["data"]["bodies_after"])
        self.assertEqual(1, len(self._bodies()))
        self.assertAlmostEqual(source_volume, self._volume(), delta=1)
        self.assertIn("Stock", self._feature_types())

        # Save and close the target part; nothing of ours stays open.
        target_path = self.output_root / "saved" / f"mcp_live_insert_target_{uuid4().hex}.SLDPRT"
        self._save_and_close(target_path)
        self.assertGreater(target_path.stat().st_size, 0)
        documents = self.automation.list_open_documents()
        self.assertTrue(documents["success"], documents["message"])
        self.assertNotIn(target_path.stem,
                         [item["title"] for item in documents["data"]["documents"]])


if __name__ == "__main__":
    unittest.main()
