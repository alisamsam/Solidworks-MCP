import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from solidworks_mcp import catalog
from solidworks_mcp.tests.test_routing_status import _SwStub
from solidworks_mcp.tools import routing_articles as ra


class ArticleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "articles.json"
        self.payload = {"unit": "mm", "revision": "R01", "articles": [
            {"id": "PIPE_A", "dimensions": {"d": "110", "s": "3,2", "unknown": None},
             "routing_status": "unbuilt_not_validated_native_geometry"}]}
        self.gate = patch.object(catalog, "routing_enabled", return_value=True)
        self.gate.start()
        self.addCleanup(self.gate.stop)

    def run_tool(self, id="PIPE_A"):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        return ra.get_routing_library_article(_SwStub(), str(self.path), id)

    def test_preserves_raw_dimensions_status_and_hash(self):
        result = self.run_tool()
        self.assertTrue(result["success"], result)
        self.assertEqual(self.payload["articles"][0], result["data"]["article"])
        self.assertEqual(64, len(result["data"]["catalog_sha256"]))
        self.assertFalse(result["data"]["cad_inspected"])

    def test_exact_id_only(self):
        result = self.run_tool("pipe_a")
        self.assertEqual("ARTICLE_NOT_FOUND", result["data"]["code"])

    def test_duplicate_and_wrong_array_rejected(self):
        self.payload["articles"] *= 2
        self.assertFalse(self.run_tool()["success"])
        self.payload["articles"] = {}
        self.assertFalse(self.run_tool()["success"])

    def test_wrong_units_and_dimensions_rejected(self):
        self.payload["unit"] = "inch"
        self.assertFalse(self.run_tool()["success"])
        self.payload["unit"] = "mm"
        self.payload["articles"][0]["dimensions"] = None
        self.assertFalse(self.run_tool()["success"])

    def test_limits(self):
        with patch.object(ra, "MAX_CATALOG_BYTES", 4):
            self.assertFalse(self.run_tool()["success"])
        with patch.object(ra, "MAX_ARTICLES", 0):
            self.assertFalse(self.run_tool()["success"])

    def test_gate_before_filesystem(self):
        with patch.object(catalog, "routing_enabled", return_value=False), \
                patch.object(ra.Path, "is_file", side_effect=AssertionError("must not read")):
            result = ra.get_routing_library_article(_SwStub(), str(self.path), "PIPE_A")
        self.assertEqual("ROUTING_DISABLED", result["data"]["code"])

    def test_no_relative_path_or_invalid_json(self):
        result = ra.get_routing_library_article(_SwStub(), "relative.json", "A")
        self.assertFalse(result["success"])
        self.path.write_text("{invalid")
        self.assertFalse(ra.get_routing_library_article(_SwStub(), str(self.path), "A")["success"])

    def test_json_exponent_overflow_is_rejected(self):
        self.path.write_text('{"unit":"mm","articles":[{"id":"A","dimensions":{"x":1e400}}]}')
        result = ra.get_routing_library_article(_SwStub(), str(self.path), "A")
        self.assertFalse(result["success"])
        json.dumps(result, allow_nan=False)
