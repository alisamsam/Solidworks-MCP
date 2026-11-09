import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.core.policy import OperationClass, PathPolicy
from solidworks_mcp.registry import _TOOLS, operation_class_for, registered_tools
from solidworks_mcp.tools.saving import save_document


class Document:
    def __init__(self, doc_type=3, title="Drawing1 - Sheet1"):
        self.doc_type = doc_type
        self.title = title

    def GetType(self):
        return self.doc_type

    def GetTitle(self):
        return self.title


class Automation:
    def __init__(self, output_root, document=None, write_file=True,
                 only_one=None):
        self._path_policy = PathPolicy(
            output_roots=[Path(output_root)],
            protected_roots=[Path(output_root) / "protected"],
        )
        self.document = document or Document()
        self.write_file = write_file
        self.only_one = only_one or Document(1, "OnlyPart")
        self.save_calls = []
        self.active_doc_calls = 0

    def get_active_doc(self):
        self.active_doc_calls += 1
        return self.document, None

    def save_document(self, filepath):
        self.save_calls.append(filepath)
        if self.write_file:
            Path(filepath).write_bytes(b"native")
        return {"success": True, "message": f"Saved: {filepath}", "data": {}}

    def _result(self, success, message, error_code=0, data=None):
        return {
            "success": success,
            "message": message,
            "error_code": int(error_code),
            "data": data or {},
        }


class SaveDocumentRegistrationTests(unittest.TestCase):
    def test_registered_as_mutation(self):
        names = {item.name for item in registered_tools()}

        self.assertIn("save_document", names)
        self.assertIs(OperationClass.MUTATE, operation_class_for("save_document"))


class SaveDocumentTests(unittest.TestCase):
    def test_auto_path_goes_to_output_root_with_drawing_extension(self):
        with tempfile.TemporaryDirectory() as root:
            automation = Automation(root)

            result = save_document(automation)

            self.assertTrue(result["success"], result["message"])
            expected = Path(root) / "saved" / "Drawing1 - Sheet1.SLDDRW"
            self.assertEqual(str(expected), result["data"]["path"])
            self.assertEqual([str(expected)], automation.save_calls)
            self.assertEqual(len(b"native"), result["data"]["size_bytes"])
            self.assertEqual("drawing", result["data"]["document_type"])

    def test_part_and_assembly_get_native_extensions(self):
        for doc_type, extension in ((1, ".SLDPRT"), (2, ".SLDASM")):
            with self.subTest(doc_type=doc_type), tempfile.TemporaryDirectory() as root:
                automation = Automation(root, Document(doc_type, "Model"))

                result = save_document(automation)

                self.assertTrue(result["success"], result["message"])
                self.assertTrue(result["data"]["path"].endswith(extension))

    def test_invalid_title_characters_are_sanitized(self):
        with tempfile.TemporaryDirectory() as root:
            automation = Automation(root, Document(3, "Sheet1: A/B*?"))

            result = save_document(automation)

            self.assertTrue(result["success"], result["message"])
            self.assertEqual("Sheet1_ A_B__.SLDDRW",
                             Path(result["data"]["path"]).name)

    def test_explicit_path_without_matching_suffix_is_corrected(self):
        with tempfile.TemporaryDirectory() as root:
            automation = Automation(root)

            result = save_document(automation, path=str(Path(root) / "review"))

            self.assertTrue(result["success"], result["message"])
            self.assertTrue(result["data"]["path"].endswith("review.SLDDRW"))

    def test_explicit_sldlfp_path_is_kept_for_a_part(self):
        for suffix in (".SLDLFP", ".sldlfp"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as root:
                automation = Automation(root, Document(1, "Kvadratna 12x12"))

                result = save_document(
                    automation, path=str(Path(root) / f"Kvadratna 12x12{suffix}")
                )

                self.assertTrue(result["success"], result["message"])
                self.assertEqual(
                    Path(root) / f"Kvadratna 12x12{suffix}", Path(result["data"]["path"])
                )
                self.assertEqual([result["data"]["path"]], automation.save_calls)

    def test_sldlfp_suffix_is_still_corrected_for_other_document_types(self):
        for doc_type, extension in ((2, ".SLDASM"), (3, ".SLDDRW")):
            with self.subTest(doc_type=doc_type), tempfile.TemporaryDirectory() as root:
                automation = Automation(root, Document(doc_type, "Model"))

                result = save_document(
                    automation, path=str(Path(root) / "profile.SLDLFP")
                )

                self.assertTrue(result["success"], result["message"])
                self.assertTrue(result["data"]["path"].endswith(extension))

    def test_other_extension_on_a_part_is_still_corrected(self):
        with tempfile.TemporaryDirectory() as root:
            automation = Automation(root, Document(1, "Model"))

            result = save_document(
                automation, path=str(Path(root) / "model.STP")
            )

            self.assertTrue(result["success"], result["message"])
            self.assertEqual(Path(root) / "model.SLDPRT", Path(result["data"]["path"]))

    def test_write_outside_output_root_is_denied_before_saving(self):
        with tempfile.TemporaryDirectory() as root:
            automation = Automation(root)

            result = save_document(automation, path=r"C:\Windows\Temp\escape.SLDDRW")

            self.assertFalse(result["success"])
            self.assertIn("denied", result["message"].lower())
            self.assertEqual([], automation.save_calls)

    def test_write_into_protected_root_is_denied(self):
        with tempfile.TemporaryDirectory() as root:
            automation = Automation(root)
            protected = Path(root) / "protected" / "x.SLDDRW"

            result = save_document(automation, path=str(protected))

            self.assertFalse(result["success"])
            self.assertEqual([], automation.save_calls)

    def test_existing_file_is_reported_when_overwrite_is_false(self):
        with tempfile.TemporaryDirectory() as root:
            automation = Automation(root)
            existing = Path(root) / "saved" / "Drawing1 - Sheet1.SLDDRW"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"old")

            result = save_document(automation, overwrite=False)

            self.assertFalse(result["success"])
            self.assertEqual("OUTPUT_EXISTS", result["data"]["code"])
            self.assertEqual([], automation.save_calls)

    def test_missing_file_after_save_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            automation = Automation(root, write_file=False)

            result = save_document(automation)

            self.assertFalse(result["success"])
            self.assertEqual(1, len(automation.save_calls))

    def test_unsupported_document_type_is_rejected_before_com(self):
        with tempfile.TemporaryDirectory() as root:
            automation = Automation(root, Document(9, "Weird"))

            result = save_document(automation)

            self.assertFalse(result["success"])
            self.assertEqual("VALIDATION_FAILED", result["data"]["code"])
            self.assertEqual([], automation.save_calls)

    def test_missing_output_root_requires_an_explicit_path(self):
        automation = Automation.__new__(Automation)
        automation.document = Document()
        automation.save_calls = []
        automation.get_active_doc = lambda: (automation.document, None)
        automation.save_document = lambda path: automation.save_calls.append(path)

        result = save_document(automation)

        self.assertFalse(result["success"])
        self.assertEqual("NO_OUTPUT_ROOT", result["data"]["code"])
        self.assertEqual([], automation.save_calls)


    def test_registered_save_document_rebinds_after_save_as(self):
        registered_tools()
        self.assertEqual("save", _TOOLS["save_document"]["postflight"])

if __name__ == "__main__":
    unittest.main()
