import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.constants import SwMateTypes
from solidworks_mcp.tools import assembly


def _sw():
    return SimpleNamespace(_result=lambda ok, msg, error=None, data=None: {'success': ok, 'msg': msg, 'data': data})


class CheckMateArgsTests(unittest.TestCase):
    def ref(self, **kw):
        return {'component': 'a-1', **kw}

    def test_exactly_one_selector_per_reference(self):
        for bad in [self.ref(), self.ref(face_index=0, plane='Front Plane'),
                    self.ref(plane='Front Plane', axis='Axis1'), {'face_index': 0},
                    self.ref(face_index=-1), self.ref(face_index=True), self.ref(plane='')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                assembly._check_mate_args('coincident', bad, self.ref(face_index=1), None, None)

    def test_value_rules_per_mate_type(self):
        r1, r2 = self.ref(face_index=0), self.ref(face_index=1)
        with self.assertRaises(ValueError):
            assembly._check_mate_args('distance', r1, r2, None, None)
        with self.assertRaises(ValueError):
            assembly._check_mate_args('angle', r1, r2, None, None)
        with self.assertRaises(ValueError):
            assembly._check_mate_args('parallel', r1, r2, 5, None)
        with self.assertRaises(ValueError):
            assembly._check_mate_args('parallel', r1, r2, None, 5)
        with self.assertRaises(ValueError):
            assembly._check_mate_args('width', r1, r2, None, None)
        with self.assertRaises(ValueError):
            assembly._check_mate_args('distance', r1, r2, float('nan'), None)

    def test_units_are_converted_to_metres_and_radians(self):
        r1, r2 = self.ref(face_index=0), self.ref(face_index=1)
        self.assertEqual(assembly._check_mate_args('distance', r1, r2, 25, None),
                         (SwMateTypes.swMateDISTANCE, 0.025, 0.0))
        kind, dist, angle = assembly._check_mate_args('angle', r1, r2, None, 90)
        self.assertEqual(kind, SwMateTypes.swMateANGLE)
        self.assertAlmostEqual(angle, math.pi / 2)
        self.assertEqual(assembly._check_mate_args('lock', r1, r2, None, None)[0], SwMateTypes.swMateLOCK)


class AddMateTests(unittest.TestCase):
    def case(self, mate_ok=True, selectable=True, status=1):
        calls = {'select': [], 'mate': None}

        class FakeExtension:
            def SelectByID2(self, name, kind, x, y, z, append, mark, callout, option):
                calls['select'].append((name, kind, append, mark))
                return selectable

        class FakeMate:
            Name = 'Parallel1'

            def GetTypeName2(self): return 'MateParallel'

        mate = FakeMate()

        class Assembly:
            Extension = FakeExtension()

            def ClearSelection2(self, *a): pass

            def GetTitle(self): return 'Assem1.SLDASM'

            def AddMate5(self, *args):
                calls['mate'] = args
                args[-1].value = status
                return mate if mate_ok else None

            def FeatureByName(self, name): return mate if name == 'Parallel1' else None

        return calls, Assembly(), _sw()

    def run_tool(self, asm, sw, **kw):
        args = dict(mate_type='parallel', ref1={'component': 'a-1', 'plane': 'Front Plane'},
                    ref2={'component': 'b-1', 'axis': 'Axis1'})
        args.update(kw)
        with patch.object(assembly, '_require_assembly', return_value=(asm, None)), \
                patch.object(assembly, '_exact_top_level', side_effect=lambda a, n: SimpleNamespace(Name2=n)):
            return assembly.add_mate(sw, **args)

    def test_named_references_are_selected_with_assembly_context(self):
        calls, asm, sw = self.case()
        r = self.run_tool(asm, sw)
        self.assertTrue(r['success'], r)
        self.assertEqual(calls['select'], [('Front Plane@a-1@Assem1', 'PLANE', False, 1),
                                           ('Axis1@b-1@Assem1', 'AXIS', True, 1)])
        self.assertEqual(calls['mate'][0], int(SwMateTypes.swMatePARALLEL))
        self.assertEqual(r['data']['mate_name'], 'Parallel1')

    def test_angle_goes_to_native_call_in_radians(self):
        calls, asm, sw = self.case()
        self.run_tool(asm, sw, mate_type='angle', angle_deg=90)
        self.assertAlmostEqual(calls['mate'][8], math.pi / 2)

    def test_distance_flip_and_status_reach_the_result(self):
        calls, asm, sw = self.case(status=5)
        r = self.run_tool(asm, sw, mate_type='distance', distance_mm=25, flip=True)
        self.assertTrue(r['success'], r)
        self.assertTrue(calls['mate'][2])
        self.assertEqual(calls['mate'][3:6], (0.025, 0.025, 0.025))
        self.assertEqual(r['data']['add_mate_status'], 5)
        self.assertIn('warning', r['data'])
        _, asm, sw = self.case(status=1)
        self.assertNotIn('warning', self.run_tool(asm, sw)['data'])

    def test_nested_component_reference_is_rejected(self):
        _, asm, sw = self.case()
        with patch.object(assembly, '_require_assembly', return_value=(asm, None)),                 patch.object(assembly, '_exact_top_level', side_effect=ValueError('Exact top-level required.')):
            r = assembly.add_mate(sw, 'parallel', {'component': 'sub-1/a-1', 'plane': 'Front Plane'},
                                  {'component': 'b-1', 'axis': 'Axis1'})
        self.assertFalse(r['success'])

    def test_face_reference_uses_existing_face_selection(self):
        calls, asm, sw = self.case()
        with patch.object(assembly, '_select_component_face', return_value=True) as sel:
            r = self.run_tool(asm, sw, ref1={'component': 'a-1', 'face_index': 3},
                              ref2={'component': 'b-1', 'face_index': 0})
        self.assertTrue(r['success'], r)
        self.assertEqual(sel.call_count, 2)

    def test_failures_are_reported(self):
        for kwargs, case_kwargs in [({}, {'mate_ok': False}), ({}, {'selectable': False}),
                                    ({'mate_type': 'width'}, {})]:
            with self.subTest(kwargs=kwargs, case=case_kwargs):
                calls, asm, sw = self.case(**case_kwargs)
                r = self.run_tool(asm, sw, **kwargs)
                self.assertFalse(r['success'])
                if kwargs or case_kwargs.get('selectable') is False:
                    self.assertIsNone(calls['mate'])


if __name__ == '__main__':
    unittest.main()
