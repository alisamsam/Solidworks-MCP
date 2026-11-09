import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.tools.export import export_step, export_stl


class Extension:
    def __init__(self, succeeds=True, error_code=0, warning_code=0):
        self.succeeds = succeeds
        self.error_code = error_code
        self.warning_code = warning_code
        self.calls = []

    def SaveAs(self, path, version, options, export_data, errors, warnings):
        self.calls.append((path, version, options, export_data))
        errors.value = self.error_code
        warnings.value = self.warning_code
        if self.succeeds:
            Path(path).write_bytes(b"export")
        return self.succeeds


class Document:
    def __init__(self, extension):
        self.Extension = extension


class Automation:
    _path_policy = None

    def __init__(self, extension):
        self.document = Document(extension)

    def get_active_doc(self):
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "data": data or {}}


class ModelExportTests(unittest.TestCase):
    def test_step_export_writes_and_reports_verified_artifact(self):
        extension = Extension(warning_code=2)
        automation = Automation(extension)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.step"

            result = export_step(automation, str(path))

            self.assertTrue(result["success"], result["message"])
            self.assertEqual(str(path.resolve()), result["data"]["path"])
            self.assertEqual(2, result["data"]["save_warning_code"])
            self.assertEqual("sha256", result["data"]["verification"]["method"])
            self.assertTrue(path.is_file())

    def test_stl_uses_current_solidworks_tessellation_settings(self):
        automation = Automation(Extension())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.stl"

            result = export_stl(automation, str(path))

            self.assertTrue(result["success"], result["message"])
            self.assertEqual(
                "SolidWorks user preferences", result["data"]["settings_source"]
            )

    def test_export_rejects_wrong_extension_before_com(self):
        extension = Extension()
        result = export_step(Automation(extension), "part.stl")

        self.assertFalse(result["success"])
        self.assertEqual([], extension.calls)

    def test_export_failure_includes_native_error_code_and_no_artifact(self):
        extension = Extension(succeeds=False, error_code=256)
        automation = Automation(extension)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.step"

            result = export_step(automation, str(path))

            self.assertFalse(result["success"])
            self.assertEqual(256, result["data"]["save_error_code"])
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
