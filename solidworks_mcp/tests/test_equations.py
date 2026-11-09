"""add_equation must add a named global variable and read it back."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document
from solidworks_mcp.tools.equations import add_equation


class EquationManager:
    def __init__(self):
        self.equations = []
        self.calls = []
        self.add3_result = None
        self.read_back_override = None
        self.read_back_missing = False
        self.global_variable_override = None

    def Add3(self, index, equation, solve, which_configurations, config_names):
        self.calls.append((index, equation, solve, which_configurations,
                           config_names))
        if self.add3_result is not None:
            return self.add3_result
        if index == -1:
            index = len(self.equations)
        self.equations.insert(index, (equation, True))
        return index

    def Add2(self, index, equation, solve):
        return self.Add3(index, equation, solve, None, None)

    def GetCount(self):
        return len(self.equations)

    def Equation(self, index):
        if self.read_back_missing:
            return None
        if self.read_back_override is not None:
            return self.read_back_override
        return self.equations[index][0]

    def GlobalVariable(self, index):
        if self.global_variable_override is not None:
            return self.global_variable_override
        return self.equations[index][1]


class EquationDocument(Document):
    def __init__(self, manager=None):
        super().__init__()
        self.equation_manager = manager or EquationManager()
        self.configurations = ["Default", "Alternative"]

    def GetEquationMgr(self):
        return self.equation_manager

    def GetConfigurationNames(self):
        return self.configurations


class AddEquationTests(unittest.TestCase):
    def setUp(self):
        self.document = EquationDocument()
        self.automation = Automation(self.document)

    def add(self, **kwargs):
        return add_equation(self.automation, **kwargs)

    def test_adds_numeric_global_variable_and_reads_it_back(self):
        result = self.add(name="B", value=2)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            [(-1, '"B" = 2', True, 2, None)],
            self.document.equation_manager.calls,
        )
        self.assertEqual(0, result["data"]["index"])
        self.assertEqual('"B" = 2', result["data"]["read_back"])
        self.assertTrue(result["data"]["is_global_variable"])
        self.assertEqual(1, result["data"]["equation_count"])
        self.assertEqual("verified", result["data"]["status"])

    def test_text_value_is_stored_as_a_quoted_expression(self):
        result = self.add(name="Label", value="bracket")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual('"Label" = "bracket"',
                         self.document.equation_manager.equations[0][0])
        self.assertEqual('"Label" = "bracket"', result["data"]["read_back"])

    def test_float_value_keeps_its_decimal_point(self):
        result = self.add(name="B", value=2.5)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual('"B" = 2.5', result["data"]["expression"])

    def test_single_configuration_uses_add2(self):
        self.document.configurations = ["Default"]
        result = self.add(name="B", value=2)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual((-1, '"B" = 2', True, None, None),
                         self.document.equation_manager.calls[0])

    def test_appends_after_existing_equations(self):
        self.document.equation_manager.equations.append(('"A" = 1', True))
        result = self.add(name="B", value=2)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, result["data"]["index"])
        self.assertEqual(2, result["data"]["equation_count"])

    def test_whitespace_differences_in_read_back_are_accepted(self):
        self.document.equation_manager.read_back_override = '"B"   =   2'
        result = self.add(name="B", value=2)
        self.assertTrue(result["success"], result["message"])

    def test_add_failure_is_not_reported_as_success(self):
        self.document.equation_manager.add3_result = -1
        result = self.add(name="B", value=2)
        self.assertFalse(result["success"])
        self.assertEqual("EQUATION_ADD_FAILED", result["data"]["code"])
        self.assertEqual([], self.document.equation_manager.equations)

    def test_read_back_mismatch_is_not_reported_as_success(self):
        self.document.equation_manager.read_back_override = '"B" = 3'
        result = self.add(name="B", value=2)
        self.assertFalse(result["success"])
        self.assertEqual("EQUATION_MISMATCH", result["data"]["code"])
        self.assertEqual('"B" = 3', result["data"]["read_back"])

    def test_equation_that_is_not_a_global_variable_is_rejected(self):
        self.document.equation_manager.global_variable_override = False
        result = self.add(name="B", value=2)
        self.assertFalse(result["success"])
        self.assertEqual("EQUATION_NOT_GLOBAL_VARIABLE", result["data"]["code"])

    def test_missing_equation_manager_is_reported(self):
        self.document.equation_manager = None
        result = self.add(name="B", value=2)
        self.assertFalse(result["success"])
        self.assertEqual("NO_EQUATION_MANAGER", result["data"]["code"])

    def test_missing_read_back_with_solve_is_reported(self):
        self.document.equation_manager.read_back_missing = True
        result = self.add(name="B", value=2)
        self.assertFalse(result["success"])
        self.assertEqual("EQUATION_NOT_READABLE", result["data"]["code"])

    def test_solve_false_defers_read_back_when_unavailable(self):
        self.document.equation_manager.read_back_missing = True
        result = self.add(name="B", value=2, solve=False)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("added_pending_solve", result["data"]["status"])
        self.assertEqual((-1, '"B" = 2', False, 2, None),
                         self.document.equation_manager.calls[0])

    def test_validation_rejects_bad_input_without_touching_solidworks(self):
        for kwargs in (
            {"name": "", "value": 2},
            {"name": "   ", "value": 2},
            {"name": 'B"C', "value": 2},
            {"name": "B", "value": True},
            {"name": "B", "value": None},
            {"name": "B", "value": float("nan")},
            {"name": "B", "value": object()},
            {"name": "B", "value": 'text"quote'},
            {"name": "B", "value": 2, "solve": 1},
            {"name": "B", "value": 2, "solve": "yes"},
        ):
            with self.subTest(kwargs=kwargs):
                result = self.add(**kwargs)
                self.assertFalse(result["success"])
                self.assertEqual("VALIDATION_FAILED", result["data"]["code"])
        self.assertEqual(0, self.automation.active_doc_calls)
        self.assertEqual([], self.document.equation_manager.calls)


if __name__ == "__main__":
    unittest.main()
