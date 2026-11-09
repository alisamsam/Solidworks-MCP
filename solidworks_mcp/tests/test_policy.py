import tempfile
import unittest
import os
from pathlib import Path

from solidworks_mcp.config import SolidWorksConfig
from solidworks_mcp.core.policy import OperationClass, PathPolicy, WriteDeniedError


class PathPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.output_root = self.root / "approved-output"
        self.output_root.mkdir()
        self.protected_root = self.root / "reference-projects"
        self.protected_root.mkdir()
        self.policy = PathPolicy(output_roots=[self.output_root], protected_roots=[self.protected_root])

    def tearDown(self):
        self.tempdir.cleanup()

    def test_allows_export_inside_approved_output_root(self):
        allowed = self.policy.require_write(self.output_root / "drawings" / "frame.pdf", OperationClass.EXPORT)

        self.assertEqual((self.output_root / "drawings" / "frame.pdf").resolve(), allowed)

    def test_denies_sibling_with_allowed_root_prefix(self):
        with self.assertRaises(WriteDeniedError):
            self.policy.require_write(self.root / "approved-output-backup" / "frame.pdf", OperationClass.EXPORT)

    def test_denies_parent_traversal_outside_approved_root(self):
        with self.assertRaises(WriteDeniedError):
            self.policy.require_write(self.output_root / ".." / "escaped.SLDPRT", OperationClass.MUTATE)

    def test_denies_symlink_escape_after_canonical_resolution(self):
        link = self.output_root / "reference-link"
        try:
            os.symlink(self.protected_root, link, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Symlink creation is unavailable in this Windows environment: {error}")

        with self.assertRaises(WriteDeniedError):
            self.policy.require_write(link / "original.SLDPRT", OperationClass.MUTATE)

    def test_denies_write_to_protected_reference_root(self):
        with self.assertRaises(WriteDeniedError):
            self.policy.require_write(self.protected_root / "original.SLDPRT", OperationClass.MUTATE)

    def test_denies_read_only_operation_class_for_write(self):
        with self.assertRaises(WriteDeniedError):
            self.policy.require_write(self.output_root / "frame.SLDPRT", OperationClass.READ)

    def test_allows_stateful_read_only_inside_approved_output_root(self):
        allowed = self.policy.require_write(
            self.output_root / "frame.SLDPRT", OperationClass.STATEFUL_READ)

        self.assertEqual((self.output_root / "frame.SLDPRT").resolve(), allowed)

    def test_config_allows_library_root_without_approving_repo(self):
        library = self.root / "repo" / "solidworks_mcp" / "standard_library"
        config = SolidWorksConfig(guarded_mode=True,
                                  output_roots=[str(self.output_root), str(library)])
        policy = config.create_path_policy()

        self.assertEqual((library / "sized" / "M10.SLDPRT").resolve(),
                         policy.require_write(library / "sized" / "M10.SLDPRT", OperationClass.MUTATE))
        with self.assertRaises(WriteDeniedError):
            policy.require_write(library.parent / "config.json", OperationClass.MUTATE)


if __name__ == "__main__":
    unittest.main()
