import hashlib
import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.workspace.delivery import (
    ArtifactCollisionError,
    build_delivery_manifest,
)


class DeliveryManifestTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.first = self.root / "frame.pdf"
        self.first.write_bytes(b"pdf-content")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_manifest_records_hash_size_and_revision(self):
        manifest = build_delivery_manifest(
            [{"artifact_id": "drawing", "path": self.first, "format": "pdf"}],
            source_revision="r2", configuration="Default", check_ids=["pdf-pages"],
        )

        artifact = manifest["artifacts"][0]
        self.assertEqual(hashlib.sha256(b"pdf-content").hexdigest(), artifact["sha256"])
        self.assertEqual(len(b"pdf-content"), artifact["byte_size"])
        self.assertEqual("r2", artifact["source_revision"])

    def test_duplicate_publish_name_is_rejected_before_finalization(self):
        second = self.root / "second.pdf"
        second.write_bytes(b"different")

        with self.assertRaises(ArtifactCollisionError):
            build_delivery_manifest(
                [
                    {"artifact_id": "one", "path": self.first, "format": "pdf", "publish_name": "frame.pdf"},
                    {"artifact_id": "two", "path": second, "format": "pdf", "publish_name": "frame.pdf"},
                ],
                source_revision="r2", configuration="Default", check_ids=[],
            )

    def test_empty_package_is_rejected(self):
        with self.assertRaises(ValueError):
            build_delivery_manifest(
                [], source_revision="r2", configuration="Default", check_ids=[],
            )

    def test_publish_name_is_case_insensitive_on_windows(self):
        second = self.root / "second.pdf"
        second.write_bytes(b"different")

        with self.assertRaises(ArtifactCollisionError):
            build_delivery_manifest(
                [
                    {"artifact_id": "one", "path": self.first, "format": "pdf", "publish_name": "FRAME.pdf"},
                    {"artifact_id": "two", "path": second, "format": "pdf", "publish_name": "frame.PDF"},
                ],
                source_revision="r2", configuration="Default", check_ids=[],
            )

    def test_publish_name_cannot_escape_final_package(self):
        with self.assertRaises(ValueError):
            build_delivery_manifest(
                [{"artifact_id": "drawing", "path": self.first, "format": "pdf", "publish_name": "../frame.pdf"}],
                source_revision="r2", configuration="Default", check_ids=[],
            )


if __name__ == "__main__":
    unittest.main()
