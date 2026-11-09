import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.imports import (
    SW_MULTICAD_ENABLE_3D_INTERCONNECT, import_neutral_file,
)


class Document:
    def __init__(self, title):
        self.title = title

    def GetTitle(self):
        return self.title


class App:
    """Stands in for the SolidWorks application (no _oleobj_, so no wrapping)."""

    def __init__(self, interconnect=True, document="bearing"):
        self.interconnect = interconnect
        self.document = document
        self.toggle_calls = []
        self.open_calls = []

    def GetUserPreferenceToggle(self, toggle_id):
        assert toggle_id == SW_MULTICAD_ENABLE_3D_INTERCONNECT
        return self.interconnect

    def SetUserPreferenceToggle(self, toggle_id, value):
        self.toggle_calls.append((toggle_id, value))
        self.interconnect = value
        return True

    def OpenDoc6(self, path, doc_type, options, configuration, errors, warnings):
        self.open_calls.append((path, doc_type, options, configuration))
        if self.document is None:
            errors.value = 2097152
            return None
        return Document(self.document)


class Automation:
    def __init__(self, app=None):
        self.app = app or App()

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message,
                "error_code": int(error_code), "data": data or {}}


class ImportRegistrationTests(unittest.TestCase):
    def test_registered_as_mutation(self):
        names = {item.name for item in registered_tools()}

        self.assertIn("import_neutral_file", names)
        self.assertIs(OperationClass.MUTATE, operation_class_for("import_neutral_file"))


class ImportNeutralFileTests(unittest.TestCase):
    def _step_file(self, directory, name="bearing_608zz.step"):
        path = Path(directory) / name
        path.write_bytes(b"ISO-10303-21;\n")
        return path

    def test_disables_3d_interconnect_then_restores_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._step_file(directory)
            app = App(interconnect=True)
            automation = Automation(app)

            result = import_neutral_file(automation, str(path))

            self.assertTrue(result["success"], result["message"])
            self.assertEqual(
                [(SW_MULTICAD_ENABLE_3D_INTERCONNECT, False),
                 (SW_MULTICAD_ENABLE_3D_INTERCONNECT, True)],
                app.toggle_calls,
            )
            self.assertTrue(app.interconnect, "the user setting must come back")
            self.assertTrue(result["data"]["three_d_interconnect_disabled"])
            self.assertEqual(1, len(app.open_calls))
            self.assertEqual(str(path), app.open_calls[0][0])
            self.assertEqual(1, app.open_calls[0][1], "STEP imports as a part")

    def test_leaves_the_toggle_alone_when_it_was_already_off(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._step_file(directory)
            app = App(interconnect=False)

            result = import_neutral_file(Automation(app), str(path))

            self.assertTrue(result["success"], result["message"])
            self.assertEqual([], app.toggle_calls)
            self.assertFalse(result["data"]["three_d_interconnect_disabled"])

    def test_failed_import_reports_the_load_error_and_restores_the_toggle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._step_file(directory)
            app = App(document=None)

            result = import_neutral_file(Automation(app), str(path))

            self.assertFalse(result["success"])
            self.assertEqual("IMPORT_NEEDS_REPAIR", result["data"]["code"])
            self.assertEqual(2097152, result["data"]["load_error_code"])
            self.assertTrue(app.interconnect, "the toggle must be restored too")

    def test_unsupported_extension_is_rejected_before_com(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._step_file(directory, "notes.txt")
            app = App()

            result = import_neutral_file(Automation(app), str(path))

            self.assertFalse(result["success"])
            self.assertEqual("VALIDATION_FAILED", result["data"]["code"])
            self.assertEqual([], app.open_calls)
            self.assertEqual([], app.toggle_calls)

    def test_missing_file_is_rejected(self):
        app = App()

        result = import_neutral_file(Automation(app), r"C:\nope\missing.step")

        self.assertFalse(result["success"])
        self.assertEqual("FILE_NOT_FOUND", result["data"]["code"])
        self.assertEqual([], app.open_calls)

    def test_native_assembly_imports_as_an_assembly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.sldasm"
            path.write_bytes(b"native")
            app = App(document="model")

            result = import_neutral_file(Automation(app), str(path))

            self.assertTrue(result["success"], result["message"])
            self.assertEqual(2, app.open_calls[0][1])


if __name__ == "__main__":
    unittest.main()
