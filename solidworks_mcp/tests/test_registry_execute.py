import unittest

from solidworks_mcp.core.contracts import DocumentRef
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.core.session import TargetMismatchError
from solidworks_mcp.registry import _TOOLS, dispatch, execute, tool

REF = DocumentRef("doc-1", None, "part", "Default", "mcp:0")
SAVED = DocumentRef("doc-2", "C:\\out\\part.SLDPRT", "part", "Default", "mcp:0")


class Automation:
    def __init__(self, saved_ref=None, mismatch=False):
        self.bound = None
        self.saved_ref = saved_ref
        self.mismatch = mismatch
        self.calls = 0

    def has_bound_document(self):
        return self.bound is not None

    def bind_active_document(self):
        self.bound = self.saved_ref or REF
        return self.bound

    def require_bound_active_document(self):
        if self.mismatch:
            raise TargetMismatchError("WRONG_DOCUMENT", "focus changed")
        return self.bound

    def mark_active_document_mutated(self, before):
        return DocumentRef(before.document_id, before.path, before.document_type,
                           before.configuration, "mcp:1")

    def capture_active_document_ref(self):
        return (self.saved_ref or self.bound), None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "error_name": "test", "data": data or {}}


class ExecuteTests(unittest.TestCase):
    NAME = "_test_execute"

    def tearDown(self):
        _TOOLS.pop(self.NAME, None)

    def _register(self, operation_class, postflight=None, succeed=True):
        @tool(name=self.NAME, description="test", schema={"type": "object", "properties": {}},
              operation_class=operation_class, postflight=postflight)
        def handler(sw):
            sw.calls += 1
            return sw._result(succeed, "done")

    def test_unknown_tool_is_an_error_result(self):
        execution = execute("_test_missing_tool", Automation(), {})
        self.assertFalse(execution.result["success"])
        self.assertIn("Unknown tool", execution.result["message"])

    def test_mutation_binds_then_reports_new_revision(self):
        self._register(OperationClass.MUTATE)
        execution = execute(self.NAME, Automation(), {})
        self.assertEqual("mcp:0", execution.target_before.revision_token)
        self.assertEqual("mcp:1", execution.target_after.revision_token)

    def test_focus_mismatch_stops_before_handler(self):
        self._register(OperationClass.MUTATE)
        sw = Automation(mismatch=True)
        sw.bound = REF
        execution = execute(self.NAME, sw, {})
        self.assertEqual("WRONG_DOCUMENT", execution.result["data"]["code"])
        self.assertEqual(0, sw.calls)

    def test_failed_mutation_keeps_target(self):
        self._register(OperationClass.MUTATE, succeed=False)
        execution = execute(self.NAME, Automation(), {})
        self.assertIs(execution.target_before, execution.target_after)

    def test_postflight_none_keeps_revision(self):
        self._register(OperationClass.MUTATE, postflight="none")
        execution = execute(self.NAME, Automation(), {})
        self.assertIs(execution.target_before, execution.target_after)

    def test_postflight_bind_binds_the_new_document(self):
        self._register(OperationClass.SESSION, postflight="bind")
        execution = execute(self.NAME, Automation(), {})
        self.assertIsNone(execution.target_before)
        self.assertEqual(REF, execution.target_after)

    def test_postflight_bound_reports_the_bound_document(self):
        self._register(OperationClass.SESSION, postflight="bound")
        sw = Automation()
        sw.bound = REF
        self.assertEqual(REF, execute(self.NAME, sw, {}).target_after)

    def test_postflight_save_rebinds_when_identity_changes(self):
        self._register(OperationClass.MUTATE, postflight="save")
        sw = Automation()
        sw.bound = REF
        sw.saved_ref = SAVED
        self.assertEqual("doc-2", execute(self.NAME, sw, {}).target_after.document_id)

    def test_postflight_save_marks_mutation_when_identity_is_unchanged(self):
        self._register(OperationClass.MUTATE, postflight="save")
        execution = execute(self.NAME, Automation(), {})
        self.assertEqual("mcp:1", execution.target_after.revision_token)

    def test_read_tool_has_no_target(self):
        self._register(OperationClass.READ)
        execution = execute(self.NAME, Automation(), {})
        self.assertIsNone(execution.target_before)
        self.assertIsNone(execution.target_after)

    def test_unknown_postflight_is_rejected_at_registration(self):
        with self.assertRaises(ValueError):
            self._register(OperationClass.MUTATE, postflight="later")

    def test_dispatch_returns_only_the_result(self):
        self._register(OperationClass.READ)
        self.assertTrue(dispatch(self.NAME, Automation(), {})["success"])
        self.assertIsNone(dispatch("_test_missing_tool", Automation(), {}))


if __name__ == "__main__":
    unittest.main()
