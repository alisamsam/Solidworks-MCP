import json
import unittest

from solidworks_mcp.server import format_result

REF = {"document_id": "doc-1", "path": None, "document_type": "part",
       "configuration": "Default", "revision_token": "mcp:0"}


def _payload(target_after=REF, warnings=(), errors=()):
    return {
        "success": True, "message": "Found 12 features", "error_code": 0, "error_name": "swSuccess",
        "data": {"features": [{"name": f"Boss-Extrude{i}", "type": "Extrusion", "suppressed": False}
                              for i in range(12)], "count": 12},
        "schema_version": 1, "operation_id": "op-1", "status": "completed",
        "target_before": REF, "target_after": target_after,
        "warnings": list(warnings), "errors": list(errors),
    }


def _previous_format(r):
    """format_result before the compact format, kept here as the size baseline."""
    lines = [f"[{'SUCCESS' if r['success'] else 'ERROR'}] {r['message']}"]
    if r.get("data"):
        lines.append("Details: " + json.dumps(r["data"], indent=2))
    lines.append("Operation: " + json.dumps({
        "schema_version": r["schema_version"], "operation_id": r["operation_id"],
        "status": r["status"], "target_before": r.get("target_before"),
        "target_after": r.get("target_after"), "warnings": r.get("warnings", []),
        "errors": r.get("errors", [])}, indent=2))
    return "\n".join(lines)


def _details(text):
    return json.JSONDecoder().raw_decode(text.split("Details: ", 1)[1])[0]


class ResultFormatTests(unittest.TestCase):
    def test_compact_text_is_at_least_30_percent_shorter(self):
        payload = _payload()
        self.assertLessEqual(len(format_result(payload)), 0.70 * len(_previous_format(payload)))

    def test_external_parse_response_contract_holds(self):
        text = format_result(_payload())
        self.assertTrue(text.startswith("[SUCCESS]"))
        self.assertEqual(12, _details(text)["count"])
        self.assertIn('"document_id": "doc-1"', text)

    def test_operation_block_omits_empty_and_unchanged_fields(self):
        operation = json.loads(format_result(_payload()).split("Operation: ", 1)[1])
        self.assertEqual({"operation_id": "op-1", "status": "completed", "target_before": REF}, operation)

    def test_operation_block_keeps_changes_warnings_and_errors(self):
        after = dict(REF, revision_token="mcp:1")
        text = format_result(_payload(after, warnings=["Rebuilt"], errors=[{"code": "X"}]))
        operation = json.loads(text.split("Operation: ", 1)[1])
        self.assertEqual("mcp:1", operation["target_after"]["revision_token"])
        self.assertEqual(["Rebuilt"], operation["warnings"])
        self.assertEqual([{"code": "X"}], operation["errors"])

    def test_non_ascii_text_is_kept_readable(self):
        payload = _payload()
        payload["data"] = {"note": "Skupni register – čžš"}
        self.assertIn("čžš", format_result(payload))


if __name__ == "__main__":
    unittest.main()
