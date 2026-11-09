import unittest

from solidworks_mcp.core.contracts import DocumentRef, OperationStatus
from solidworks_mcp.core.session import (
    DocumentSession,
    SessionState,
    SessionTarget,
    TargetMismatchError,
    require_target,
    with_operation_metadata,
)


def reference(document_id="doc-1", configuration="Default", revision="r1"):
    return DocumentRef(document_id, "C:/output/frame.SLDPRT", "part", configuration, revision)


class SessionTargetTests(unittest.TestCase):
    def test_binds_document_configuration_and_revision_snapshot(self):
        state = SessionState()
        target = state.bind(reference())

        self.assertEqual("doc-1", target.document_id)
        self.assertEqual("Default", target.configuration)

    def test_rejects_mismatched_document_before_operation(self):
        state = SessionState()
        target = state.bind(reference())

        with self.assertRaises(TargetMismatchError):
            require_target(target, reference(document_id="doc-2"))

    def test_rejects_stale_revision_before_operation(self):
        state = SessionState()
        target = state.bind(reference())

        with self.assertRaises(TargetMismatchError):
            require_target(target, reference(revision="r2"))

    def test_metadata_adapter_preserves_legacy_fields(self):
        result = with_operation_metadata(
            {"success": True, "message": "Saved", "error_code": 0, "data": {"legacy": 1}},
            operation_id="op-5",
            target_before=reference(),
            target_after=reference(revision="r2"),
            status=OperationStatus.COMPLETED,
        )

        self.assertTrue(result["success"])
        self.assertEqual("Saved", result["message"])
        self.assertEqual("completed", result["status"])
        self.assertEqual("r2", result["target_after"]["revision_token"])


class DocumentSessionTests(unittest.TestCase):
    def test_unsaved_document_keeps_session_identity_between_snapshots(self):
        session = DocumentSession(id_factory=lambda: "session-doc-1")

        first = session.capture(
            title="Part1", path=None, document_type="part", configuration="Default"
        )
        second = session.capture(
            title="Part1", path=None, document_type="part", configuration="Default"
        )

        self.assertEqual("session-doc-1", first.document_id)
        self.assertEqual(first, second)
        self.assertIsNone(first.path)
        self.assertEqual("mcp:0", first.revision_token)

    def test_focus_change_is_rejected_against_bound_document(self):
        identifiers = iter(("session-doc-1", "session-doc-2"))
        session = DocumentSession(id_factory=lambda: next(identifiers))
        bound = session.bind(
            title="Part1", path=None, document_type="part", configuration="Default"
        )
        other = session.capture(
            title="Part2", path=None, document_type="part", configuration="Default"
        )

        with self.assertRaises(TargetMismatchError) as raised:
            session.require_bound(other)

        self.assertEqual("WRONG_DOCUMENT", raised.exception.operation_error.code)
        self.assertEqual("session-doc-1", bound.document_id)

    def test_successful_mutation_advances_revision_and_invalidates_old_target(self):
        session = DocumentSession(id_factory=lambda: "session-doc-1")
        before = session.bind(
            title="Part1", path=None, document_type="part", configuration="Default"
        )

        after = session.mark_mutated(before)

        self.assertEqual("mcp:1", after.revision_token)
        with self.assertRaises(TargetMismatchError) as raised:
            require_target(SessionTarget.from_document(before), after)
        self.assertEqual("STALE_REFERENCE", raised.exception.operation_error.code)

    def test_configuration_change_is_rejected_for_same_document(self):
        session = DocumentSession(id_factory=lambda: "session-doc-1")
        session.bind(
            title="Part1", path="C:/scratch/Part1.SLDPRT",
            document_type="part", configuration="Default",
        )
        alternate = session.capture(
            title="Part1", path="c:\\scratch\\Part1.SLDPRT",
            document_type="part", configuration="Alternate",
        )

        with self.assertRaises(TargetMismatchError) as raised:
            session.require_bound(alternate)

        self.assertEqual("WRONG_DOCUMENT", raised.exception.operation_error.code)


if __name__ == "__main__":
    unittest.main()
