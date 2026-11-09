import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.tools import assembly


class Transform:
    def __init__(self, values): self._data = list(values)
    @property
    def ArrayData(self): return self._data
    @ArrayData.setter
    def ArrayData(self, values): self._data = list(getattr(values, 'value', values))


class Math:
    def CreateTransform(self, values):
        # Reproduce the real COM issue: CreateTransform ignores supplied array.
        return Transform([1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0])


class ComponentTranslationTests(unittest.TestCase):
    def setup_case(self):
        values = [0,1,0,-1,0,0,0,0,1,.001,.002,.003,1,0,0,0]
        component = SimpleNamespace(Name2='beam-1', Transform2=Transform(values), IsFixed=False)
        app = SimpleNamespace(GetMathUtility=Math())
        sw = SimpleNamespace(app=app, _result=lambda ok,msg,error=None,data=None: {'success':ok,'data':data})
        return component,sw,values

    def test_verified_translation_preserves_rotation_and_scale(self):
        component,sw,before = self.setup_case()
        with patch.object(assembly,'_require_assembly',return_value=(object(),None)), patch.object(assembly,'_find_component',return_value=component):
            result = assembly.set_component_translation(sw,'beam-1',[0,0,0],[1,2,3])
        self.assertTrue(result['success'])
        self.assertEqual(component.Transform2.ArrayData[:9],before[:9])
        self.assertEqual(component.Transform2.ArrayData[9:12],[0,0,0])
        self.assertEqual(component.Transform2.ArrayData[12:],before[12:])

    def test_stale_position_and_fixed_component_are_rejected_without_mutation(self):
        for expected,fixed in [([1,2,4],False),([1,2,3],True)]:
            component,sw,before = self.setup_case(); component.IsFixed=fixed
            with patch.object(assembly,'_require_assembly',return_value=(object(),None)), patch.object(assembly,'_find_component',return_value=component):
                result = assembly.set_component_translation(sw,'beam-1',[0,0,0],expected)
            self.assertFalse(result['success'])
            self.assertEqual(component.Transform2.ArrayData,before)

    def test_nested_suffix_and_invalid_numbers_are_rejected_without_moving(self):
        cases = [('sub-1/beam-1',[0,0,0]), ('beam-1',[float('nan'),0,0]), ('beam-1',[True,0,0])]
        for name,translation in cases:
            component,sw,before = self.setup_case(); component.Name2=name
            with patch.object(assembly,'_require_assembly',return_value=(object(),None)), patch.object(assembly,'_find_component',return_value=component):
                result = assembly.set_component_translation(sw,'beam-1',translation,[1,2,3])
            self.assertFalse(result['success'])
            self.assertEqual(component.Transform2.ArrayData,before)


if __name__ == '__main__': unittest.main()
