import unittest

from jsonschema import Draft7Validator

from solidworks_mcp.validation import ArgumentError, validate_arguments

SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string"},
        "depth": {"type": "number", "minimum": 0},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"]},
        "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
    },
    "required": ["file_path"],
}
OPEN_SCHEMA = dict(SCHEMA, additionalProperties=True)


def check(arguments, schema=SCHEMA):
    return validate_arguments(schema, Draft7Validator(schema), arguments)


class ValidateArgumentsTests(unittest.TestCase):
    def test_valid_arguments_pass_unchanged(self):
        self.assertEqual({"file_path": "a", "depth": 2}, check({"file_path": "a", "depth": 2}))

    def test_top_level_none_values_are_dropped(self):
        self.assertEqual({"file_path": "a"}, check({"file_path": "a", "unit": None}))

    def test_unknown_key_suggests_the_closest_name(self):
        with self.assertRaises(ArgumentError) as caught:
            check({"filepath": "a"})
        self.assertEqual("filepath", caught.exception.argument)
        self.assertIn("Did you mean 'file_path'?", str(caught.exception))

    def test_unknown_key_without_close_match_lists_valid_names(self):
        with self.assertRaises(ArgumentError) as caught:
            check({"file_path": "a", "zzz": 1})
        self.assertIn("Valid arguments: depth, file_path, points, unit", str(caught.exception))

    def test_unknown_key_is_rejected_even_when_schema_allows_extra(self):
        with self.assertRaises(ArgumentError):
            check({"file_path": "a", "dpeth": 1}, OPEN_SCHEMA)

    def test_missing_required_argument(self):
        with self.assertRaises(ArgumentError) as caught:
            check({"depth": 1})
        self.assertEqual("file_path", caught.exception.argument)
        self.assertIn("'file_path' is a required property", str(caught.exception))

    def test_wrong_type_names_the_path(self):
        with self.assertRaises(ArgumentError) as caught:
            check({"file_path": "a", "points": [[0, 0], [1, "x"]]})
        self.assertEqual("points[1][1]", caught.exception.argument)
        self.assertTrue(str(caught.exception).startswith("Invalid argument 'points[1][1]':"))

    def test_any_of_reports_the_most_relevant_branch(self):
        schema = {"type": "object", "properties": {
            "size": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "string", "enum": ["auto"]}]}}}
        with self.assertRaises(ArgumentError) as caught:
            check({"size": 0}, schema)
        self.assertEqual("size", caught.exception.argument)
        self.assertNotIn("is not valid under any of the given schemas", str(caught.exception))

    def test_enum_suggests_the_closest_value(self):
        with self.assertRaises(ArgumentError) as caught:
            check({"file_path": "a", "unit": "inches"})
        self.assertIn("Did you mean 'inch'?", str(caught.exception))

    def test_constraint_violation(self):
        with self.assertRaises(ArgumentError) as caught:
            check({"file_path": "a", "depth": -1})
        self.assertEqual("depth", caught.exception.argument)

    def test_schema_without_properties_accepts_anything(self):
        schema = {"type": "object"}
        self.assertEqual({"x": 1}, validate_arguments(schema, Draft7Validator(schema), {"x": 1}))


from solidworks_mcp.core.contracts import DocumentRef
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, execute, registered_tools, tool


class Automation:
    def __init__(self):
        self.binds = 0
        self.calls = []

    def has_bound_document(self):
        return False

    def bind_active_document(self):
        self.binds += 1
        return DocumentRef("doc-1", None, "part", "Default", "mcp:0")

    def mark_active_document_mutated(self, before):
        return before

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "error_name": "test", "data": data or {}}


class ExecuteValidationTests(unittest.TestCase):
    NAME = "_test_validation"

    def setUp(self):
        @tool(name=self.NAME, description="test", schema=SCHEMA,
              operation_class=OperationClass.MUTATE)
        def handler(sw, file_path, depth=10, unit=None, points=None):
            sw.calls.append((file_path, depth, unit))
            return sw._result(True, "done")

    def tearDown(self):
        _TOOLS.pop(self.NAME, None)

    def test_invalid_call_stops_before_binding_and_handler(self):
        sw = Automation()
        result = execute(self.NAME, sw, {"filepath": "a"}).result
        self.assertFalse(result["success"])
        self.assertEqual(107, result["error_code"])
        self.assertEqual({"code": "VALIDATION_FAILED", "argument": "filepath"}, result["data"])
        self.assertIn("Did you mean 'file_path'?", result["message"])
        self.assertEqual(0, sw.binds)
        self.assertEqual([], sw.calls)

    def test_none_values_fall_back_to_handler_defaults(self):
        sw = Automation()
        self.assertTrue(execute(self.NAME, sw, {"file_path": "a", "depth": None}).result["success"])
        self.assertEqual([("a", 10, None)], sw.calls)

    def test_validator_is_built_once(self):
        execute(self.NAME, Automation(), {"file_path": "a"})
        validator = _TOOLS[self.NAME]["validator"]
        execute(self.NAME, Automation(), {"file_path": "b"})
        self.assertIs(validator, _TOOLS[self.NAME]["validator"])


class AdvertisedSchemaTests(unittest.TestCase):
    def test_every_schema_is_valid_draft7(self):
        for item in registered_tools():
            with self.subTest(tool=item.name):
                Draft7Validator.check_schema(item.inputSchema)


if __name__ == "__main__":
    unittest.main()
