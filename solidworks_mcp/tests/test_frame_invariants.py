import unittest

from solidworks_mcp.workspace.frame_changes import validate_frame_invariants


class FrameInvariantTests(unittest.TestCase):
    def test_preserved_properties_pass(self):
        before = {"profile": "40x40", "material": "S235", "height_mm": 500, "body_count": 4, "joints": 8}
        after = {**before, "width_mm": 1300}

        self.assertEqual([], validate_frame_invariants(before, after))

    def test_changed_profile_is_reported_as_failed_invariant(self):
        before = {"profile": "40x40", "material": "S235", "height_mm": 500, "body_count": 4, "joints": 8}
        after = {**before, "profile": "50x50"}

        self.assertEqual(["profile"], validate_frame_invariants(before, after))


if __name__ == "__main__":
    unittest.main()
