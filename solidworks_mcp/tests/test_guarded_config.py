import unittest

from solidworks_mcp.config import SolidWorksConfig
from solidworks_mcp.core.policy import PathPolicy


class GuardedConfigurationTests(unittest.TestCase):
    def test_disabled_guarded_mode_has_no_write_policy(self):
        config = SolidWorksConfig(guarded_mode=False)

        self.assertIsNone(config.create_path_policy())

    def test_enabled_guarded_mode_builds_policy_from_trusted_roots(self):
        config = SolidWorksConfig(
            guarded_mode=True,
            output_roots=["C:/scratch/output"],
            protected_roots=["C:/references"],
        )

        self.assertIsInstance(config.create_path_policy(), PathPolicy)

    def test_enabled_guarded_mode_requires_output_root(self):
        config = SolidWorksConfig(guarded_mode=True)

        with self.assertRaises(ValueError):
            config.create_path_policy()


if __name__ == "__main__":
    unittest.main()
