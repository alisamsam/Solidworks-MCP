import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.tools import assembly


def _sw():
    return SimpleNamespace(_result=lambda ok, msg, error=None, data=None: {'success': ok, 'msg': msg, 'data': data})


def mate(name, *components, state='solved'):
    return {'name': name, 'mate_type_name': 'coincident', 'suppressed': False,
            'solver_status': {'state': state}, 'entities': [{'component': c} for c in components]}


class MatesTouchingTests(unittest.TestCase):
    def test_mate_appears_for_both_components(self):
        m = [mate('M1', 'a-1', 'b-1'), mate('M2', 'b-1', 'c-1')]
        self.assertEqual([x['name'] for x in assembly._mates_touching(m, 'a-1')], ['M1'])
        self.assertEqual([x['name'] for x in assembly._mates_touching(m, 'b-1')], ['M1', 'M2'])
        self.assertEqual(assembly._mates_touching(m, 'zzz'), [])

    def test_other_components_and_nested_entities(self):
        m = [mate('M1', 'sub-1/a-1', 'b-1')]
        r = assembly._mates_touching(m, 'sub-1')
        self.assertEqual(r[0]['other_components'], ['b-1'])
        self.assertEqual(assembly._mates_touching(m, 'sub'), [])

    def test_entity_without_component_is_ignored(self):
        m = [{'name': 'M', 'entities': [{'component': None}, {}]}]
        self.assertEqual(assembly._mates_touching(m, 'a-1'), [])


class Transform:
    ArrayData = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0.01, 0.02, 0.03, 1, 0, 0, 0]


class Component:
    Name2 = 'a-1'
    Transform2 = Transform()

    def GetPathName(self): return 'C:/p/a.SLDPRT'

    ReferencedConfiguration = 'Default'

    def GetSuppression(self): return 2

    def IsFixed(self): return True


class GetComponentTests(unittest.TestCase):
    def run_tool(self, found, mates=None, name='a-1'):
        mates = mates if mates is not None else {'success': True, 'data': {'mates': [mate('M1', 'a-1', 'b-1')]}}
        with patch.object(assembly, '_require_assembly', return_value=(object(), None)), \
                patch.object(assembly, '_find_component', return_value=found), \
                patch.object(assembly, 'list_mates', return_value=mates):
            return assembly.get_component(_sw(), name)

    def test_reports_state_and_mates(self):
        r = self.run_tool(Component())
        self.assertTrue(r['success'], r)
        d = r['data']
        self.assertEqual(d['translation_mm'], [10.0, 20.0, 30.0])
        self.assertEqual((d['path'], d['configuration'], d['fixed'], d['suppressed']),
                         ('C:/p/a.SLDPRT', 'Default', True, False))
        self.assertEqual([m['name'] for m in d['mates']], ['M1'])
        self.assertEqual(d['rotation_deg'], [0.0, 0.0, 0.0])
        self.assertTrue(d['mates_complete'])

    def test_incomplete_mate_listing_is_flagged(self):
        r = self.run_tool(Component(), mates={'success': True, 'data': {
            'mates': [], 'coverage': {'complete': False}}})
        self.assertFalse(r['data']['mates_complete'])

    def test_unreadable_transform_does_not_raise(self):
        class Broken(Component):
            @property
            def Transform2(self): raise RuntimeError('lightweight')
        r = self.run_tool(Broken())
        self.assertTrue(r['success'])
        self.assertIsNone(r['data']['translation_mm'])
        self.assertIsNone(r['data']['rotation_deg'])

    def test_unknown_or_nested_name_fails(self):
        self.assertFalse(self.run_tool(None)['success'])
        self.assertFalse(self.run_tool(Component(), name='sub-1/a-1')['success'])
        self.assertFalse(self.run_tool(Component(), name='')['success'])

    def test_mate_listing_failure_is_reported_without_losing_component(self):
        r = self.run_tool(Component(), mates={'success': False, 'msg': 'boom'})
        self.assertTrue(r['success'])
        self.assertIsNone(r['data']['mates'])
        self.assertIn('boom', r['data']['mates_error'])


class FindComponentTests(unittest.TestCase):
    def test_exact_top_level_name_wins_over_earlier_nested_suffix(self):
        class C:
            def __init__(self, name): self.Name2 = name

        nested, top = C('sub-1/a-1'), C('a-1')

        class Asm:
            def GetComponents(self, top_only): return [nested, top]

        self.assertIs(assembly._find_component(Asm(), 'a-1'), top)
        self.assertIs(assembly._find_component(Asm(), 'sub-1/a-1'), nested)


if __name__ == '__main__':
    unittest.main()
