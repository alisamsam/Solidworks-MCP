import unittest

from solidworks_mcp.core.contracts import (
    DocumentRef,
    OperationError,
    OperationResult,
    OperationStatus,
    QuantityValidationError,
    validate_quantity,
)
from solidworks_mcp.core.evidence import JournalState, OperationJournal


class QuantityValidationTests(unittest.TestCase):
    def test_accepts_finite_length_in_allowed_unit(self):
        quantity = validate_quantity(25.4, "mm", {"mm", "inch"})

        self.assertEqual(25.4, quantity.value)
        self.assertEqual("mm", quantity.unit)

    def test_rejects_non_finite_quantity(self):
        with self.assertRaises(QuantityValidationError):
            validate_quantity(float("nan"), "mm", {"mm"})

    def test_rejects_unit_outside_allowed_set(self):
        with self.assertRaises(QuantityValidationError):
            validate_quantity(10, "m", {"mm", "inch"})

    def test_rejects_negative_length_when_minimum_is_zero(self):
        with self.assertRaises(QuantityValidationError):
            validate_quantity(-0.1, "mm", {"mm"}, minimum=0)


class OperationResultTests(unittest.TestCase):
    def test_serialization_preserves_legacy_result_fields(self):
        target = DocumentRef("doc-1", "C:/scratch/frame.SLDPRT", "part", "Default", "r1")
        result = OperationResult.completed(
            "op-1", target, {"width_mm": 1300}, warnings=["Rebuilt document"]
        )

        payload = result.to_dict(legacy={"success": True, "message": "Saved", "error_code": 0, "data": {}})

        self.assertEqual(True, payload["success"])
        self.assertEqual("Saved", payload["message"])
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("completed", payload["status"])
        self.assertEqual("r1", payload["target_after"]["revision_token"])
        self.assertEqual(["Rebuilt document"], payload["warnings"])

    def test_unknown_result_cannot_be_marked_retryable(self):
        result = OperationResult.unknown("op-2", None, "Timed out after COM call")

        self.assertEqual(OperationStatus.UNKNOWN, result.status)
        self.assertFalse(result.errors[0].retryable)


class OperationJournalTests(unittest.TestCase):
    def test_completed_operation_is_returned_without_second_execution(self):
        journal = OperationJournal()
        calls = []

        first = journal.run("op-3", lambda: calls.append("ran") or OperationResult.completed("op-3", None, {}))
        replay = journal.run("op-3", lambda: calls.append("again") or OperationResult.completed("op-3", None, {}))

        self.assertEqual(["ran"], calls)
        self.assertIs(first, replay)

    def test_unknown_operation_is_not_automatically_retried(self):
        journal = OperationJournal()
        first = OperationResult.unknown("op-4", None, "Connection lost")
        journal.record(first)
        calls = []

        replay = journal.run("op-4", lambda: calls.append("again") or OperationResult.completed("op-4", None, {}))

        self.assertEqual([], calls)
        self.assertIs(first, replay)

    def test_inflight_duplicate_returns_unknown_without_reexecuting(self):
        journal = OperationJournal()
        self.assertIsNone(journal.reserve("op-5"))
        journal.mark_running("op-5")

        replay = journal.reserve("op-5")

        self.assertEqual(OperationStatus.UNKNOWN, replay.status)
        self.assertEqual(JournalState.RUNNING, journal.get_state("op-5"))
        self.assertEqual("OPERATION_OUTCOME_UNKNOWN", replay.errors[0].code)

    def test_callback_exception_is_recorded_as_failed_and_not_retried(self):
        journal = OperationJournal()
        calls = []

        first = journal.run("op-6", lambda: calls.append("ran") or (_ for _ in ()).throw(RuntimeError("boom")))
        replay = journal.run(
            "op-6", lambda: calls.append("again") or OperationResult.completed("op-6", None, {})
        )

        self.assertEqual(["ran"], calls)
        self.assertEqual(OperationStatus.FAILED, first.status)
        self.assertEqual(JournalState.FAILED, journal.get_state("op-6"))
        self.assertIs(first, replay)


if __name__ == "__main__":
    unittest.main()
