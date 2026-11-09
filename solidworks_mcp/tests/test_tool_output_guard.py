import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.assembly import pack_and_go
from solidworks_mcp.tools.export import export_face_to_dxf
from solidworks_mcp.tools.sheetmetal import export_flat_pattern
from solidworks_mcp.tools.sheetmetal import flatten_sheet_metal, get_flat_pattern_info


class ProtectedOutputProbe:
    def __init__(self, policy):
        self._path_policy = policy
        self.com_touched = False

    def get_active_doc(self):
        self.com_touched = True
        raise AssertionError("output policy must run before document COM access")

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class ToolOutputGuardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        output = root / "output"
        output.mkdir()
        self.references = root / "references"
        self.references.mkdir()
        self.policy = PathPolicy([output], [self.references])

    def tearDown(self):
        self.tempdir.cleanup()

    def test_face_export_rejects_protected_destination_before_com(self):
        probe = ProtectedOutputProbe(self.policy)

        result = export_face_to_dxf(probe, 1, str(self.references / "face.dxf"))

        self.assertFalse(result["success"])
        self.assertFalse(probe.com_touched)

    def test_flat_pattern_export_rejects_protected_destination_before_com(self):
        probe = ProtectedOutputProbe(self.policy)

        result = export_flat_pattern(probe, str(self.references / "flat.dxf"))

        self.assertFalse(result["success"])
        self.assertFalse(probe.com_touched)

    def test_pack_and_go_rejects_protected_destination_before_com(self):
        probe = ProtectedOutputProbe(self.policy)

        result = pack_and_go(probe, str(self.references / "package"))

        self.assertFalse(result["success"])
        self.assertFalse(probe.com_touched)

    def test_flatten_rejects_protected_active_document_before_feature_access(self):
        class DocumentProbe:
            GetPathName = str(self.references / "original.SLDPRT")

            @property
            def FirstFeature(self):
                raise AssertionError("feature access must be blocked")

        probe = ProtectedOutputProbe(self.policy)
        probe.get_active_doc = lambda: (DocumentProbe(), None)

        result = flatten_sheet_metal(probe, True)

        self.assertFalse(result["success"])

    def test_flat_pattern_info_rejects_protected_active_document_before_feature_access(self):
        class DocumentProbe:
            GetPathName = str(self.references / "original.SLDPRT")

            @property
            def FirstFeature(self):
                raise AssertionError("feature access must be blocked")

        probe = ProtectedOutputProbe(self.policy)
        probe.get_active_doc = lambda: (DocumentProbe(), None)

        result = get_flat_pattern_info(probe)

        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
