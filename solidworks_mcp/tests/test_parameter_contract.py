import unittest

from solidworks_mcp.workspace.parameters import ParameterChange, StaleParameterError, validate_parameter_changes


class ParameterContractTests(unittest.TestCase):
    def test_accepts_change_when_revision_and_old_value_match(self):
        changes = [ParameterChange("D1@Sketch1", expected_old_value=100.0, new_value=130.0)]

        accepted = validate_parameter_changes(
            changes, expected_revision="r1", actual_revision="r1",
            current_values={"D1@Sketch1": 100.0},
        )

        self.assertEqual(changes, accepted)

    def test_rejects_change_when_revision_is_stale(self):
        with self.assertRaises(StaleParameterError):
            validate_parameter_changes(
                [ParameterChange("D1@Sketch1", 100.0, 130.0)],
                expected_revision="r1", actual_revision="r2",
                current_values={"D1@Sketch1": 100.0},
            )

    def test_rejects_change_when_driving_value_changed_externally(self):
        with self.assertRaises(StaleParameterError):
            validate_parameter_changes(
                [ParameterChange("D1@Sketch1", 100.0, 130.0)],
                expected_revision="r1", actual_revision="r1",
                current_values={"D1@Sketch1": 110.0},
            )


if __name__ == "__main__":
    unittest.main()
