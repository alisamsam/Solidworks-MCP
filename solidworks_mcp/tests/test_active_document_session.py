import unittest

from solidworks_mcp.automation.base import SolidWorksAutomation
from solidworks_mcp.core.session import DocumentSession, TargetMismatchError


class FakeConfiguration:
    Name = "Default"


class FakeConfigurationManager:
    ActiveConfiguration = FakeConfiguration()


class FakeDocument:
    ConfigurationManager = FakeConfigurationManager()

    def __init__(self, title, path="", document_type=1):
        self.GetTitle = title
        self.GetPathName = path
        self.GetType = document_type


def automation_with_active(document):
    automation = SolidWorksAutomation.__new__(SolidWorksAutomation)
    identifiers = iter(("id-1", "id-2", "id-3"))
    automation._document_session = DocumentSession(id_factory=lambda: next(identifiers))
    automation.get_active_doc = lambda: (document, None)
    return automation


class ActiveDocumentSessionTests(unittest.TestCase):
    def test_bind_returns_serializable_active_document_snapshot(self):
        automation = automation_with_active(FakeDocument("Part1"))

        target = automation.bind_active_document()

        self.assertEqual("id-1", target.document_id)
        self.assertEqual("part", target.document_type)
        self.assertEqual("Default", target.configuration)
        self.assertIsNone(target.path)

    def test_focus_change_is_rejected_before_registered_handler_can_run(self):
        first = FakeDocument("Part1")
        automation = automation_with_active(first)
        automation.bind_active_document()
        automation.get_active_doc = lambda: (FakeDocument("Part2"), None)

        with self.assertRaises(TargetMismatchError) as raised:
            automation.require_bound_active_document()

        self.assertEqual("WRONG_DOCUMENT", raised.exception.operation_error.code)


if __name__ == "__main__":
    unittest.main()
