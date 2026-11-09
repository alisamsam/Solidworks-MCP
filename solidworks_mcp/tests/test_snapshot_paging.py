import unittest

from solidworks_mcp.core.contracts import DocumentRef
from solidworks_mcp.core.snapshot import InstanceRef, ProjectSnapshot, SnapshotCoverage
from solidworks_mcp.inspection.snapshots import SnapshotCursorError, SnapshotStore


def target(revision="r1"):
    return DocumentRef("assembly-1", "C:/scratch/top.SLDASM", "assembly", "Default", revision)


def snapshot():
    return ProjectSnapshot(
        snapshot_id="snapshot-1",
        documents=(target(),),
        instances=tuple(
            InstanceRef(f"Top/Part-{index}", "Top", f"part-{index}", "Default")
            for index in range(3)
        ),
        coverage=SnapshotCoverage(complete=True, visited_count=3),
    )


class SnapshotPagingTests(unittest.TestCase):
    def test_page_cursor_resumes_without_losing_repeated_instances(self):
        store = SnapshotStore()

        first = store.add(snapshot(), target(), page_size=2)
        second = store.resume(first.coverage.next_cursor, target(), page_size=2)

        self.assertEqual(["Top/Part-0", "Top/Part-1"],
                         [item.instance_path for item in first.instances])
        self.assertEqual(["Top/Part-2"], [item.instance_path for item in second.instances])
        self.assertTrue(first.coverage.truncated)
        self.assertIsNone(second.coverage.next_cursor)

    def test_cursor_is_stale_after_document_revision_changes(self):
        store = SnapshotStore()
        first = store.add(snapshot(), target(), page_size=1)

        with self.assertRaises(SnapshotCursorError) as raised:
            store.resume(first.coverage.next_cursor, target("r2"), page_size=1)

        self.assertEqual("STALE_REFERENCE", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
