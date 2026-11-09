"""6.3: bounded traversal stops at the requested depth and pages results.

A saved part gives the feature-tree depth bound. A nested assembly
(assembly B contains assembly A which contains the part) gives both the
component depth bound and something to page over, because the flat instance
list then has two entries.
"""

import os
import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools.assembly import insert_component, list_components
from solidworks_mcp.tools.inspection import inspect_document
from solidworks_mcp.tools.saving import save_document

DEPTH_LIMIT_MARKER = "feature depth limit reached"


@unittest.skipUnless(os.environ.get("SW_MCP_LIVE_TESTS") == "1",
                     "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.")
class LiveBoundedTraversalTests(unittest.TestCase):
    def setUp(self):
        self.automation = SolidWorksAutomation()
        result = self.automation.connect()
        if not result["success"]:
            self.skipTest(result["message"])
        self.token = uuid4().hex
        self.titles = []
        self.saved_dir = Path(self.automation._path_policy.output_roots[0]) / "saved"

    def tearDown(self):
        for title in reversed(self.titles):
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
        self.automation.disconnect()

    def _track(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        title = str(com(document, "GetTitle"))
        self.titles.append(title)
        return document, title

    def _depth_limit_hits(self, result):
        coverage = result["data"]["snapshot"]["coverage"]
        return [item for item in coverage["unresolved"]
                if DEPTH_LIMIT_MARKER in item]

    def test_depth_bounds_and_paging(self):
        self.saved_dir.mkdir(parents=True, exist_ok=True)

        # Part: 40 x 40 x 20 mm block, saved so an assembly can reference it.
        created = self.automation.create_new_part()
        self.assertTrue(created["success"], created["message"])
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(-20, -20, 20, 20, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        extruded = self.automation.extrude_sketch(20, False, "mm")
        self.assertTrue(extruded["success"], extruded["message"])
        part_path = self.saved_dir / f"mcp_live_bounded_part_{self.token}.SLDPRT"
        self.assertTrue(save_document(
            self.automation, path=str(part_path))["success"])
        self._track()

        # Feature-tree depth: depth 1 stops early, depth 8 does not.
        shallow = inspect_document(self.automation, sections=["features"], depth=1)
        self.assertTrue(shallow["success"], shallow["message"])
        deep = inspect_document(self.automation, sections=["features"], depth=8)
        self.assertTrue(deep["success"], deep["message"])
        self.assertGreaterEqual(len(self._depth_limit_hits(shallow)), 1)
        self.assertEqual(0, len(self._depth_limit_hits(deep)),
                         "depth 8 should not hit the feature depth limit")

        # Assembly A holds the part; assembly B holds A and the part.
        assembly_a = self.automation.create_new_assembly()
        self.assertTrue(assembly_a["success"], assembly_a["message"])
        self.titles.append(assembly_a["data"]["name"])
        inserted = insert_component(self.automation, str(part_path), 0.0, 0.0, 0.0)
        self.assertTrue(inserted["success"], inserted["message"])
        a_path = self.saved_dir / f"mcp_live_bounded_a_{self.token}.SLDASM"
        self.assertTrue(save_document(self.automation, path=str(a_path))["success"])
        self._track()

        assembly_b = self.automation.create_new_assembly()
        self.assertTrue(assembly_b["success"], assembly_b["message"])
        self.titles.append(assembly_b["data"]["name"])
        for path, offset in ((a_path, 0.0), (part_path, 0.05)):
            inserted = insert_component(self.automation, str(path), offset, 0.0, 0.0)
            self.assertTrue(inserted["success"], inserted["message"])
        b_path = self.saved_dir / f"mcp_live_bounded_b_{self.token}.SLDASM"
        self.assertTrue(save_document(self.automation, path=str(b_path))["success"])
        self._track()

        # Component depth: depth 1 truncates the nested sub-assembly, depth 32
        # visits every instance (A, the part inside A, the part in B).
        flat = list_components(self.automation, depth=1)
        self.assertTrue(flat["success"], flat["message"])
        self.assertTrue(flat["data"]["coverage"]["truncated"])
        self.assertFalse(flat["data"]["coverage"]["complete"])
        complete = list_components(self.automation, depth=32)
        self.assertTrue(complete["success"], complete["message"])
        self.assertFalse(complete["data"]["coverage"]["truncated"])
        self.assertEqual(3, complete["data"]["coverage"]["visited_count"])

        # Paging: page_size 1 walks all three instances one page at a time.
        first = inspect_document(self.automation, sections=["assembly"],
                                 depth=32, page_size=1)
        self.assertTrue(first["success"], first["message"])
        coverage = first["data"]["snapshot"]["coverage"]
        self.assertEqual(1, coverage["visited_count"])
        cursor = coverage["next_cursor"]
        self.assertIsNotNone(cursor, "page_size 1 should leave a next cursor")

        visited = coverage["visited_count"]
        pages = 1
        while cursor is not None:
            page = inspect_document(self.automation, sections=["assembly"],
                                    depth=32, cursor=cursor, page_size=1)
            self.assertTrue(page["success"], page["message"])
            coverage = page["data"]["snapshot"]["coverage"]
            visited += coverage["visited_count"]
            cursor = coverage["next_cursor"]
            pages += 1
            self.assertLessEqual(pages, 5, "paging did not terminate")
        self.assertEqual(3, pages)
        self.assertEqual(3, visited)

        for path in (part_path, a_path, b_path):
            self.assertTrue(path.is_file(), f"missing artifact {path}")
            self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
