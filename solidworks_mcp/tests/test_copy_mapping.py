import unittest

from solidworks_mcp.core.contracts import DocumentRef
from solidworks_mcp.core.snapshot import ProjectSnapshot, SnapshotCoverage
from solidworks_mcp.workspace.copy_plan import CopyPlanError, plan_project_copy


class CopyMappingTests(unittest.TestCase):
    def snapshot(self, documents, edges=()):
        return ProjectSnapshot(
            snapshot_id="source-snapshot",
            documents=tuple(documents), instances=(),
            dependency_edges=tuple(edges), coverage=SnapshotCoverage(True, 0),
        )

    def test_same_basename_documents_receive_distinct_deterministic_destinations(self):
        snapshot = self.snapshot([
            DocumentRef("doc-a", "C:/reference/a/base.SLDPRT", "part", "Default", "r1"),
            DocumentRef("doc-b", "C:/reference/b/base.SLDPRT", "part", "Default", "r1"),
        ])

        manifest = plan_project_copy(snapshot, "C:/output/variant", library_policy="copy")

        destinations = [entry["destination"] for entry in manifest["documents"]]
        self.assertEqual(2, len(set(destinations)))
        self.assertTrue(all(path.startswith("C:/output/variant") for path in destinations))

    def test_unresolved_mutable_dependency_blocks_copy_plan(self):
        snapshot = self.snapshot(
            [DocumentRef("doc-a", "C:/reference/a/base.SLDPRT", "part", "Default", "r1")],
            [{"source": "doc-a", "target": "missing", "kind": "mutable", "state": "unresolved"}],
        )

        with self.assertRaises(CopyPlanError):
            plan_project_copy(snapshot, "C:/output/variant", library_policy="copy")


if __name__ == "__main__":
    unittest.main()
