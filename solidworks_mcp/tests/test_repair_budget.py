import unittest

from solidworks_mcp.workspace.repair import RepairBudgetExceeded, RepairJournal


class RepairBudgetTests(unittest.TestCase):
    def test_only_two_repair_attempts_are_permitted_per_job(self):
        journal = RepairJournal(max_attempts=2)

        journal.record_attempt("fix view", "checkpoint-1")
        journal.record_attempt("refresh cut list", "checkpoint-2")

        with self.assertRaises(RepairBudgetExceeded):
            journal.record_attempt("change parameter", "checkpoint-3")

    def test_each_attempt_retains_reason_and_checkpoint(self):
        journal = RepairJournal(max_attempts=2)
        journal.record_attempt("fix view", "checkpoint-1")

        self.assertEqual(
            [{"attempt": 1, "reason": "fix view", "checkpoint": "checkpoint-1"}],
            journal.to_dict()["attempts"],
        )


if __name__ == "__main__":
    unittest.main()
