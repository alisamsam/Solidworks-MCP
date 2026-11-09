import unittest

from solidworks_mcp.core.contracts import DocumentRef
from solidworks_mcp.core.snapshot import InstanceRef, ProjectSnapshot, SnapshotCoverage


class ProjectSnapshotTests(unittest.TestCase):
    def test_repeated_document_instances_are_preserved_in_snapshot(self):
        document = DocumentRef("doc-frame", "C:/output/frame.SLDPRT", "part", "Default", "r1")
        snapshot = ProjectSnapshot(
            snapshot_id="snapshot-1",
            documents=(document,),
            instances=(
                InstanceRef("root/frame-1", None, "doc-frame", "Default"),
                InstanceRef("root/frame-2", None, "doc-frame", "Default"),
            ),
            coverage=SnapshotCoverage(complete=True, visited_count=2),
        )

        payload = snapshot.to_dict()

        self.assertEqual(1, len(payload["documents"]))
        self.assertEqual(2, len(payload["instances"]))
        self.assertEqual(["root/frame-1", "root/frame-2"],
                         [instance["instance_path"] for instance in payload["instances"]])

    def test_incomplete_coverage_retains_unresolved_edges(self):
        snapshot = ProjectSnapshot(
            snapshot_id="snapshot-2",
            documents=(),
            instances=(),
            coverage=SnapshotCoverage(
                complete=False, visited_count=0,
                unresolved=("external-reference:missing.SLDPRT",), truncated=False,
            ),
        )

        self.assertFalse(snapshot.to_dict()["coverage"]["complete"])
        self.assertEqual(["external-reference:missing.SLDPRT"],
                         snapshot.to_dict()["coverage"]["unresolved"])


if __name__ == "__main__":
    unittest.main()
