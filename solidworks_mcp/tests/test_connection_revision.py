import unittest
from unittest.mock import patch

from solidworks_mcp.automation.base import ComThreadOwnershipError, SolidWorksAutomation


class MethodRevisionApplication:
    def __init__(self):
        self.revision_calls = 0
        self.Visible = False

    def RevisionNumber(self):
        self.revision_calls += 1
        return "33.1.1"


class ConnectionRevisionTests(unittest.TestCase):
    def test_connect_calls_method_style_revision_number(self):
        app = MethodRevisionApplication()
        automation = SolidWorksAutomation()

        with patch("solidworks_mcp.automation.base.win32com.client.GetObject", return_value=app):
            self.assertTrue(automation._try_connect_com())

        self.assertEqual(1, app.revision_calls)

    def test_successful_connection_records_current_com_owner_thread(self):
        app = MethodRevisionApplication()
        automation = SolidWorksAutomation()

        with patch("solidworks_mcp.automation.base.threading.get_ident", return_value=1234), \
             patch("solidworks_mcp.automation.base.win32com.client.GetObject", return_value=app):
            self.assertTrue(automation._try_connect_com())

        self.assertEqual(1234, automation._com_owner_thread_id)

    def test_active_document_is_rejected_before_com_access_on_wrong_thread(self):
        class AccessTrackingApplication:
            active_doc_reads = 0

            @property
            def ActiveDoc(self):
                self.active_doc_reads += 1
                return object()

        app = AccessTrackingApplication()
        automation = SolidWorksAutomation()
        automation._sw_app = app
        automation._connected = True
        automation._com_owner_thread_id = 1234

        with patch("solidworks_mcp.automation.base.threading.get_ident", return_value=5678):
            with self.assertRaises(ComThreadOwnershipError):
                automation.get_active_doc()

        self.assertEqual(0, app.active_doc_reads)


if __name__ == "__main__":
    unittest.main()
