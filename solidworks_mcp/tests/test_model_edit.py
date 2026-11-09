"""Existing-model edits require an isolated target and observable postconditions."""
import unittest
from types import SimpleNamespace, MethodType
from unittest.mock import patch

from solidworks_mcp.tools.model_edit import set_model_dimension, update_model_equation, replace_component


class Dimension:
    def __init__(self):
        self.value = .1
        self.ReadOnly = False
        self.DrivenState = 2
        self.calls = []
        self.type = 0  # swDimensionParamTypeDoubleLinear, NOT swDimensionType_e
        self.write = True

    def GetType(self): return self.type
    def GetSystemValue3(self, scope, configs): return (self.value,)
    def SetSystemValue3(self, value, scope, configs):
        self.calls.append((value, scope, configs))
        if self.write: self.value = value
        return 0


class Equations:
    def __init__(self):
        self.items = ['"B" = 100mm']
        self.scope = []
    def GetCount(self): return len(self.items)
    def Equation(self, index): return self.items[index]
    def GlobalVariable(self, index): return True
    def Disabled(self, index): return False
    def Status(self, index): return 0
    def Value(self, index): return .1
    def EvaluateAll(self): return -1
    def SetEquationAndConfigurationOption(self, index, equation, scope, names):
        self.scope.append((scope, names)); self.items[index] = equation; return index


class Document:
    def __init__(self):
        self.dimension = Dimension()
        self.manager = Equations()
        self.rebuilds = 0
        self.rebuild_ok = True
        self.components = []
        self.selected = None
        self.ConfigurationManager = SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name='Default'))
        self.SelectionManager = SimpleNamespace(CreateSelectData=object())
        self.FirstFeature = None
    def GetPathName(self): return 'C:/copy/Part.SLDPRT'
    def GetType(self): return 1
    def Parameter(self, name): return self.dimension if name == 'D1@Sketch1' else None
    def GetEquationMgr(self): return self.manager
    def GetConfigurationNames(self): return ('Default', 'Other')
    def EditRebuild3(self): self.rebuilds += 1; return self.rebuild_ok
    def GetComponents(self, top): return self.components
    def ClearSelection2(self, all): self.selected = None
    def ReplaceComponents2(self, path, config, all_instances, choice, mates):
        for item in self.components:
            if all_instances or item is self.selected: item.path = path
        return True


class Automation:
    def __init__(self):
        self.document = Document()
        self.app = SimpleNamespace()
        self.app.GetConfigurationNames = MethodType(lambda self, path: ['Default'], self.app)
    def get_active_doc(self): return self.document, None
    def _result(self, success, message, error_code=0, data=None):
        return dict(success=success, message=message, data=data or {})


class ModelEditTests(unittest.TestCase):
    def setUp(self):
        self.sw = Automation()
        self.guard = patch('solidworks_mcp.tools.model_edit.require_editable_copy', return_value=None)
        self.guard.start(); self.addCleanup(self.guard.stop)

    def edit(self, **kwargs):
        return set_model_dimension(self.sw, 'D1@Sketch1', 150, 'mm', expected_value=100,
                                   configuration='Default', **kwargs)

    def test_dimension_changes_only_current_configuration_and_reads_back(self):
        result = self.edit()
        self.assertTrue(result['success'], result)
        self.assertEqual((.15, 1, None), self.sw.document.dimension.calls[0])
        self.assertAlmostEqual(150, result['data']['after'])
        self.assertEqual(1, self.sw.document.rebuilds)

    def test_dimension_does_not_mutate_driven_equation_controlled_stale_or_wrong_config(self):
        for condition in ['readonly', 'driven', 'equation', 'stale', 'config', 'unit']:
            with self.subTest(condition=condition):
                self.sw.document = Document()
                dim = self.sw.document.dimension
                kwargs = dict(expected_value=100, configuration='Default', unit='mm')
                if condition == 'readonly': dim.ReadOnly = True
                if condition == 'driven': dim.DrivenState = 1
                if condition == 'equation': self.sw.document.manager.items = ['"D1@Sketch1" = "B"']
                if condition == 'stale': kwargs['expected_value'] = 90
                if condition == 'config': kwargs['configuration'] = 'Other'
                if condition == 'unit': kwargs['unit'] = 'deg'
                result = set_model_dimension(self.sw, 'D1@Sketch1', 150, **kwargs)
                self.assertFalse(result['success'], result)
                self.assertFalse(dim.calls)

    def test_write_or_rebuild_without_matching_result_is_not_success(self):
        self.sw.document.dimension.write = False
        self.assertFalse(self.edit()['success'])
        self.sw.document.dimension.write = True
        self.sw.document.rebuild_ok = False
        self.assertFalse(self.edit()['success'])

    def test_feature_error_prevents_verified_success(self):
        self.sw.document.FirstFeature = SimpleNamespace(GetErrorCode=1)
        self.assertFalse(self.edit()['success'])

    def test_angular_units_use_dimension_parameter_enum(self):
        self.sw.document.dimension.type = 1
        self.sw.document.dimension.value = 3.141592653589793 / 2
        result = set_model_dimension(self.sw, 'D1@Sketch1', 45, 'deg', 90, 'Default')
        self.assertTrue(result['success'], result)
        self.assertAlmostEqual(45, result['data']['after'])

    def test_copy_guard_denies_before_dimension_write(self):
        with patch('solidworks_mcp.tools.model_edit.require_editable_copy',
                   return_value={'success':False, 'message':'not isolated'}):
            self.assertFalse(self.edit()['success'])
            self.assertFalse(self.sw.document.dimension.calls)

    def test_equation_update_retains_lhs_and_checks_original_expression(self):
        result = update_model_equation(self.sw, 0, '150mm', '"B" = 100mm', configuration='Default')
        self.assertTrue(result['success'], result)
        self.assertEqual('"B" = 150mm', self.sw.document.manager.items[0])
        self.assertEqual([(1, None)], self.sw.document.manager.scope)
        self.assertFalse(update_model_equation(self.sw, 0, '170mm', '"B" = 100mm', configuration='Default')['success'])

    def test_equation_rhs_cannot_inject_additional_assignment(self):
        for rhs in ['1\n"X" = 2', '1 = 2', '', 'NaN']:
            with self.subTest(rhs=rhs):
                self.assertFalse(update_model_equation(self.sw, 0, rhs, '"B" = 100mm', configuration='Default')['success'])
        self.assertEqual([], self.sw.document.manager.scope)

    def test_replace_only_selected_occurrence_and_does_not_change_other_instance(self):
        doc = self.sw.document
        doc.GetType = MethodType(lambda self: 2, doc)
        doc.GetPathName = MethodType(lambda self: 'C:/copy/Assembly.SLDASM', doc)
        for name in ['Part-1', 'Part-2']:
            item = SimpleNamespace(Name2=name, path='C:/copy/Part.SLDPRT', ReferencedConfiguration='Default')
            item.GetPathName = MethodType(lambda self: self.path, item)
            item.Select4 = MethodType(lambda self, append, data, popup: setattr(doc, 'selected', self) or True, item)
            doc.components.append(item)
        existing = SimpleNamespace(Name2='Other-1', path='C:/copy/Other.SLDPRT', ReferencedConfiguration='Other')
        existing.GetPathName = MethodType(lambda self: self.path, existing)
        doc.components.append(existing)
        with patch('solidworks_mcp.tools.model_edit.Path.is_file', return_value=True):
            result = replace_component(self.sw, 'Part-1', 'C:/copy/Other.SLDPRT',
                                       expected_path='C:/copy/Part.SLDPRT', configuration='Default')
        self.assertTrue(result['success'], result)
        self.assertTrue(doc.components[0].path.endswith('Other.SLDPRT'))
        self.assertEqual('C:/copy/Part.SLDPRT', doc.components[1].path)
        self.assertEqual('Other', doc.components[2].ReferencedConfiguration)


if __name__ == '__main__': unittest.main()
