import asyncio
import inspect
import unittest

from solidworks_mcp import server
from solidworks_mcp.core.contracts import DocumentRef
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.core.session import TargetMismatchError
from solidworks_mcp.registry import _TOOLS, tool


class FakeAutomation:
    def __init__(self, mismatch=False):
        self.mismatch = mismatch
        self.draw_calls = 0

    def has_bound_document(self):
        return True

    def require_bound_active_document(self):
        if self.mismatch:
            raise TargetMismatchError("WRONG_DOCUMENT", "focus changed")
        return DocumentRef("doc-1", None, "part", "Default", "mcp:0")

    def bind_active_document(self):
        return DocumentRef("doc-1", None, "part", "Default", "mcp:0")

    def mark_active_document_mutated(self, before):
        return DocumentRef(
            before.document_id, before.path, before.document_type,
            before.configuration, "mcp:1",
        )

    def draw_line(self, *args):
        self.draw_calls += 1
        return self._result(True, "line")

    def _result(self, success, message, error_code=0, data=None):
        return {
            "success": success,
            "message": message,
            "error_code": int(error_code),
            "error_name": "test",
            "data": data or {},
        }


class ServerSessionGuardTests(unittest.TestCase):
    def setUp(self):
        self.original_automation = server.sw_automation

    def tearDown(self):
        server.sw_automation = self.original_automation
        _TOOLS.pop("_test_server_registered_mutation", None)

    def test_bind_active_document_is_advertised_and_returns_reference(self):
        server.sw_automation = FakeAutomation()

        names = [tool.name for tool in asyncio.run(server.list_tools())]
        response = asyncio.run(server.call_tool("bind_active_document", {}))

        self.assertIn("bind_active_document", names)
        self.assertIn('"document_id": "doc-1"', response[0].text)

    def test_schemas_omit_operation_id_and_instructions_explain_it(self):
        advertised = asyncio.run(server.list_tools())

        for advertised_tool in advertised:
            with self.subTest(tool=advertised_tool.name):
                self.assertNotIn("operation_id", advertised_tool.inputSchema.get("properties", {}))
        self.assertIn("operation_id", server.modeling_guidance.server_instructions())

    def test_legacy_mutation_rejects_focus_change_before_handler(self):
        automation = FakeAutomation(mismatch=True)
        server.sw_automation = automation

        response = asyncio.run(server.call_tool("draw_line", {}))

        self.assertIn("WRONG_DOCUMENT", response[0].text)
        self.assertEqual(0, automation.draw_calls)

    def test_duplicate_operation_id_replays_without_second_mutation(self):
        automation = FakeAutomation()
        server.sw_automation = automation
        operation = {"operation_id": "repeat-draw-1"}

        first = asyncio.run(server.call_tool("draw_line", operation))
        replay = asyncio.run(server.call_tool("draw_line", operation))

        self.assertEqual(1, automation.draw_calls)
        self.assertIn("repeat-draw-1", first[0].text)
        self.assertEqual(first[0].text, replay[0].text)

    def test_registered_mutation_reports_before_and_after_revisions(self):
        @tool(
            name="_test_server_registered_mutation",
            description="test",
            schema={"type": "object", "properties": {}, "required": []},
            operation_class=OperationClass.MUTATE,
        )
        def registered_mutation(sw):
            return sw._result(True, "changed")

        server.sw_automation = FakeAutomation()

        response = asyncio.run(server.call_tool(
            "_test_server_registered_mutation", {"operation_id": "registered-op-1"}
        ))

        self.assertIn('"revision_token": "mcp:0"', response[0].text)
        self.assertIn('"revision_token": "mcp:1"', response[0].text)

    def test_save_as_rebinds_document_when_unsaved_identity_becomes_path(self):
        class SavedAutomation(FakeAutomation):
            def __init__(self):
                super().__init__()
                self.saved = False

            def bind_active_document(self):
                if self.saved:
                    return DocumentRef("doc-saved", "C:\\scratch\\part.SLDPRT", "part", "Default", "mcp:0")
                return super().bind_active_document()

            def capture_active_document_ref(self):
                return self.bind_active_document(), None

        @tool(
            name="_test_save_as_rebind",
            description="test",
            schema={"type": "object", "properties": {}, "required": []},
            operation_class=OperationClass.MUTATE,
            postflight="save",
        )
        def save(sw):
            sw.saved = True
            return sw._result(True, "saved")

        try:
            server.sw_automation = SavedAutomation()
            result = asyncio.run(server.call_tool("_test_save_as_rebind",
                                                  {"operation_id": "save-as-rebind-test"}))
            self.assertIn('"document_id": "doc-saved"', result[0].text)
        finally:
            _TOOLS.pop("_test_save_as_rebind", None)

    def test_call_tool_stays_small(self):
        lines = inspect.getsource(server.call_tool).splitlines()
        self.assertLess(len(lines), 60)


if __name__ == "__main__":
    unittest.main()
