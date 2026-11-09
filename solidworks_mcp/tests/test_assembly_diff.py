import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.tools import assembly


def _sw():
    return SimpleNamespace(_result=lambda ok, msg, error=None, data=None: {'success': ok, 'msg': msg, 'data': data})


def comp(name, tx=0.0, path=None, suppressed=False, fixed=False):
    transform = [1, 0, 0, 0, 1, 0, 0, 0, 1, tx / 1000, 0, 0, 1, 0, 0, 0]
    return {'name': name, 'path': path or f'C:/p/{name}.SLDPRT', 'transform': transform,
            'suppressed': suppressed, 'is_fixed': fixed}


class DiffTests(unittest.TestCase):
    def diff(self, actual, expected, tol=0.1, ignore_extra=False):
        return assembly._diff(actual, expected, tol, ignore_extra)

    def test_matching_components_are_complete(self):
        r = self.diff([comp('a-1', 10)], [{'name': 'a-1', 'translation_mm': [10, 0, 0]}])
        self.assertTrue(r['complete'])
        self.assertEqual(r['matching'], ['a-1'])

    def test_missing_and_extra(self):
        r = self.diff([comp('a-1'), comp('x-1')], [{'name': 'a-1'}, {'name': 'b-1'}])
        self.assertEqual(r['missing'], ['b-1'])
        self.assertEqual([e['name'] for e in r['extra']], ['x-1'])
        self.assertFalse(r['complete'])

    def test_ignore_extra(self):
        r = self.diff([comp('a-1'), comp('x-1')], [{'name': 'a-1'}], ignore_extra=True)
        self.assertEqual(r['extra'], [])
        self.assertTrue(r['complete'])

    def test_moved_beyond_tolerance_reports_delta(self):
        r = self.diff([comp('a-1', 10.5)], [{'name': 'a-1', 'translation_mm': [10, 0, 0]}])
        self.assertEqual(len(r['moved']), 1)
        self.assertAlmostEqual(r['moved'][0]['delta_mm'], 0.5)
        self.assertEqual(r['matching'], [])
        within = self.diff([comp('a-1', 10.05)], [{'name': 'a-1', 'translation_mm': [10, 0, 0]}])
        self.assertEqual(within['moved'], [])

    def test_state_changes_and_unset_fields_are_ignored(self):
        r = self.diff([comp('a-1', suppressed=True, fixed=False)],
                      [{'name': 'a-1', 'suppressed': False, 'fixed': True}])
        self.assertEqual({(s['field'], s['expected'], s['actual']) for s in r['state_changed']},
                         {('suppressed', False, True), ('fixed', True, False)})
        self.assertTrue(self.diff([comp('a-1', suppressed=True)], [{'name': 'a-1'}])['complete'])

    def test_path_compared_case_and_slash_insensitively(self):
        ok = self.diff([comp('a-1', path='C:\\P\\a-1.SLDPRT')], [{'name': 'a-1', 'path': 'c:/p/a-1.sldprt'}])
        self.assertTrue(ok['complete'])
        bad = self.diff([comp('a-1')], [{'name': 'a-1', 'path': 'C:/p/other.SLDPRT'}])
        self.assertEqual(bad['state_changed'][0]['field'], 'path')

    def test_unreadable_transform_is_reported_not_matched(self):
        c = comp('a-1')
        c['transform'] = None
        r = self.diff([c], [{'name': 'a-1', 'translation_mm': [0, 0, 0]}])
        self.assertEqual(r['state_changed'][0]['field'], 'translation')
        self.assertFalse(r['complete'])

    def test_invalid_input_raises(self):
        for expected, tol in [([{'name': 'a-1'}, {'name': 'a-1'}], 0.1), ([{'name': ''}], 0.1),
                              ([{'name': 'a/b'}], 0.1), ([{'name': 'a', 'translation_mm': [1, 2]}], 0.1),
                              ([{'name': 'a', 'suppressed': 'no'}], 0.1), ([{'name': 'a'}], -1),
                              ([{'name': 'a'}], float('nan')), ('x', 0.1),
                              ([{'name': 'a', 'path': 5}], 0.1), ([{'name': 'a', 'translation': [0, 0, 0]}], 0.1)]:
            with self.subTest(expected=expected, tol=tol), self.assertRaises(ValueError):
                self.diff([], expected, tol)


class AssemblyDiffToolTests(unittest.TestCase):
    def test_reads_top_level_components_and_reports(self):
        sw = _sw()
        listing = {'success': True, 'data': {'components': [comp('a-1', 5)], 'coverage': {'complete': True}}}
        with patch.object(assembly, 'list_components', return_value=listing) as lc:
            r = assembly.assembly_diff(sw, [{'name': 'a-1', 'translation_mm': [0, 0, 0]}])
        lc.assert_called_once_with(sw, depth=1, mode='detailed')
        self.assertTrue(r['success'])
        self.assertEqual(len(r['data']['moved']), 1)
        self.assertFalse(r['data']['complete'])

    def test_listing_failure_and_bad_input_are_failures(self):
        sw = _sw()
        with patch.object(assembly, 'list_components', return_value={'success': False, 'msg': 'no asm'}):
            self.assertFalse(assembly.assembly_diff(sw, [{'name': 'a-1'}])['success'])
        self.assertFalse(assembly.assembly_diff(sw, [{'name': ''}])['success'])

    def test_ignore_extra_must_be_a_real_boolean(self):
        self.assertFalse(assembly.assembly_diff(_sw(), [{'name': 'a-1'}], ignore_extra='false')['success'])

    def test_incomplete_coverage_blocks_complete_flag(self):
        sw = _sw()
        listing = {'success': True, 'data': {'components': [comp('a-1')],
                                             'coverage': {'complete': False, 'unresolved': ['a-1: x']}}}
        with patch.object(assembly, 'list_components', return_value=listing):
            r = assembly.assembly_diff(sw, [{'name': 'a-1'}])
        self.assertFalse(r['data']['complete'])


if __name__ == '__main__':
    unittest.main()
