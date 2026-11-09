import unittest

from solidworks_mcp.workspace.frame_changes import interpret_frame_request


class FrameChangeInterpretationTests(unittest.TestCase):
    def test_explicit_slovenian_delta_becomes_width_change_without_question(self):
        result = interpret_frame_request("Razširi okvir za 300 mm.")

        self.assertEqual("ready", result["status"])
        self.assertEqual("width", result["changes"][0]["parameter"])
        self.assertEqual(300.0, result["changes"][0]["delta_mm"])

    def test_ambiguous_wider_request_requires_review(self):
        result = interpret_frame_request("Naredi okvir širši.")

        self.assertEqual("needs_review", result["status"])

    def test_contradictory_width_constraints_require_review_before_mutation(self):
        result = interpret_frame_request("Ohrani zunanjo širino 1000 mm in jo povečaj na 1300 mm.")

        self.assertEqual("needs_review", result["status"])
        self.assertIn("contradiction", result["reasons"])


if __name__ == "__main__":
    unittest.main()
