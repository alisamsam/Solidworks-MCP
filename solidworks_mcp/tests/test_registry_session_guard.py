import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.core.session import TargetMismatchError
from solidworks_mcp.registry import _TOOLS, dispatch, tool


class GuardedAutomation:
    def __init__(self, mismatch=False):
        self.mismatch = mismatch
        self.bound = False
        self.handler_calls = 0

    def bind_active_document(self):
        self.bound = True
        return "before"

    def has_bound_document(self):
        return self.bound

    def require_bound_active_document(self):
        if self.mismatch:
            raise TargetMismatchError("WRONG_DOCUMENT", "focus changed")
        return "before"

    def mark_active_document_mutated(self, before):
        return "after"

    def _result(self, success, message, error_code=0, data=None):
        return {
            "success": success,
            "message": message,
            "error_code": int(error_code),
            "error_name": "test",
            "data": data or {},
        }


class RegistrySessionGuardTests(unittest.TestCase):
    tool_name = "_test_guarded_mutation"

    def tearDown(self):
        _TOOLS.pop(self.tool_name, None)

    def _register(self):
        @tool(
            name=self.tool_name,
            description="test",
            schema={"type": "object", "properties": {}, "required": []},
            operation_class=OperationClass.MUTATE,
        )
        def handler(sw):
            sw.handler_calls += 1
            return sw._result(True, "changed")

    def test_tool_registration_requires_explicit_operation_class(self):
        with self.assertRaises(TypeError):
            tool(
                name="_test_missing_operation_class",
                description="test",
                schema={"type": "object", "properties": {}, "required": []},
            )

    def test_first_legacy_mutation_binds_active_document(self):
        self._register()
        automation = GuardedAutomation()

        result = dispatch(self.tool_name, automation, {})

        self.assertTrue(result["success"])
        self.assertTrue(automation.bound)
        self.assertEqual(1, automation.handler_calls)

    def test_focus_mismatch_rejects_mutation_before_handler(self):
        self._register()
        automation = GuardedAutomation(mismatch=True)
        automation.bound = True

        result = dispatch(self.tool_name, automation, {})

        self.assertFalse(result["success"])
        self.assertEqual("WRONG_DOCUMENT", result["data"]["code"])
        self.assertEqual(0, automation.handler_calls)


if __name__ == "__main__":
    unittest.main()
