import unittest

from solidworks_mcp.workspace.acceptance import aggregate_checks


class AcceptanceCheckTests(unittest.TestCase):
    def test_passes_only_when_every_required_check_passes(self):
        result = aggregate_checks([
            {"check_id": "dimension", "required": True, "status": "passed"},
            {"check_id": "visual", "required": False, "status": "not_run"},
        ])

        self.assertEqual("passed", result["status"])

    def test_needs_review_cannot_be_promoted_to_passed(self):
        result = aggregate_checks([
            {"check_id": "dimension", "required": True, "status": "passed"},
            {"check_id": "conflict", "required": True, "status": "needs_review"},
        ])

        self.assertEqual("needs_review", result["status"])
        self.assertEqual(["conflict"], result["blocking_check_ids"])


if __name__ == "__main__":
    unittest.main()
