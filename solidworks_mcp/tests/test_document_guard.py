import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.automation.documents import DocumentOperations
from solidworks_mcp.core.policy import PathPolicy


class FakeDocument:
    def __init__(self):
        self.save_as_calls = []
        self.save3_calls = []

    def SaveAs(self, path):
        self.save_as_calls.append(path)
        return True

    def Save3(self, *args):
        self.save3_calls.append(args)
        return 0


class FakeApp:
    def __init__(self):
        self.closed = []

    def CloseDoc(self, title):
        self.closed.append(title)


class GuardedAutomation(DocumentOperations):
    def __init__(self, document_path, policy):
        self.document = FakeDocument()
        self.document_path = document_path
        self._path_policy = policy
        self._sw_app = FakeApp()

    def get_active_doc(self):
        return self.document, None

    def _get_doc_path(self, _doc):
        return str(self.document_path)

    def _get_doc_title(self, _doc):
        return "frame.SLDPRT"

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class DocumentGuardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.output = root / "output"
        self.output.mkdir()
        self.references = root / "references"
        self.references.mkdir()
        self.policy = PathPolicy([self.output], [self.references])

    def tearDown(self):
        self.tempdir.cleanup()

    def test_denies_save_as_to_protected_reference_before_com_call(self):
        automation = GuardedAutomation(self.output / "copy.SLDPRT", self.policy)

        result = automation.save_document(str(self.references / "original.SLDPRT"))

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.save_as_calls)

    def test_denies_in_place_save_of_protected_document_before_com_call(self):
        automation = GuardedAutomation(self.references / "original.SLDPRT", self.policy)

        result = automation.save_document()

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.save3_calls)

    def test_denies_close_save_of_protected_document_before_close(self):
        automation = GuardedAutomation(self.references / "original.SLDPRT", self.policy)

        result = automation.close_document(save=True)

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.save3_calls)
        self.assertEqual([], automation._sw_app.closed)


if __name__ == "__main__":
    unittest.main()
