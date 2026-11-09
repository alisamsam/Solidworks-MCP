import json
import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.core.contracts import DocumentRef, OperationResult
from solidworks_mcp.core.evidence import EvidenceWriter, EvidenceValidationError


class EvidenceWriterTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.output = Path(self.tempdir.name) / "evidence.jsonl"
        self.protected = Path("C:/Users/Jan/Documents/GrabCAD")

    def tearDown(self):
        self.tempdir.cleanup()

    def result(self):
        return OperationResult.completed(
            "op-evidence",
            DocumentRef("doc-1", str(self.protected / "frame.SLDPRT"), "part", "Default", "r1"),
            {"artifact_path": str(self.protected / "frame.pdf")},
        )

    def test_writes_deterministic_schema_versioned_jsonl_record(self):
        writer = EvidenceWriter(self.output, protected_roots=[self.protected])
        record = writer.append(self.result(), commit="abc123", verification_status="static_only")

        line = self.output.read_text(encoding="utf-8").strip()
        self.assertEqual(record, json.loads(line))
        self.assertEqual(1, record["schema_version"])
        self.assertEqual("static_only", record["verification_status"])
        self.assertEqual("abc123", record["commit"])

    def test_requires_known_verification_status(self):
        writer = EvidenceWriter(self.output)

        with self.assertRaises(EvidenceValidationError):
            writer.append(self.result(), commit="abc123", verification_status="probably_ok")

    def test_redacts_protected_root_paths_from_record(self):
        writer = EvidenceWriter(self.output, protected_roots=[self.protected])
        record = writer.append(self.result(), commit="abc123", verification_status="not_run")

        serialized = json.dumps(record)
        self.assertNotIn("GrabCAD", serialized)
        self.assertIn("<protected-root>", serialized)


if __name__ == "__main__":
    unittest.main()
