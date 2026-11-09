import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solidworks_mcp.tools import assembly


def _sw():
    return SimpleNamespace(_result=lambda ok, msg, error=None, data=None: {'success': ok, 'msg': msg, 'data': data})


class CheckPatternArgsTests(unittest.TestCase):
    ref = {'component': 'a-1', 'face_index': 0}

    def check(self, **kw):
        args = dict(pattern_type='linear', seed_component='a-1', reference=self.ref, count=3,
                    spacing_mm=250, angle_deg=None, equal_spacing=True, reverse=False)
        args.update(kw)
        return assembly._check_pattern_args(**args)

    def test_units_are_converted(self):
        self.assertEqual(self.check(), (108, 3, 0.25))
        kind, count, angle = self.check(pattern_type='circular', spacing_mm=None, angle_deg=90, count=4)
        self.assertEqual((kind, count), (109, 4))
        self.assertAlmostEqual(angle, math.pi / 2)

    def test_bad_arguments_are_rejected(self):
        bad_cases = [
            {'pattern_type': 'mirror'}, {'count': 1}, {'count': True}, {'count': 2.0}, {'count': 1001},
            {'spacing_mm': None}, {'spacing_mm': 0}, {'spacing_mm': -5}, {'spacing_mm': float('nan')},
            {'angle_deg': 30},  # angle is not valid for linear
            {'pattern_type': 'circular', 'spacing_mm': None, 'angle_deg': None},
            {'pattern_type': 'circular', 'spacing_mm': 10, 'angle_deg': 90},
            {'pattern_type': 'circular', 'spacing_mm': None, 'angle_deg': 0},
            {'pattern_type': 'circular', 'spacing_mm': None, 'angle_deg': 400},
            {'reference': {'component': 'a-1'}},
            {'reference': {'component': 'a-1', 'face_index': 0, 'axis': 'Axis1'}},
            {'seed_component': ''}, {'reverse': 1}, {'equal_spacing': 'yes'},
        ]
        for bad in bad_cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.check(**bad)


class CreateComponentPatternTests(unittest.TestCase):
    def case(self, feature_ok=True, selectable=True, seed_count=1, readback_count=None, added=None):
        calls = {'select': [], 'created': None, 'defs': []}

        class Data:
            D1TotalInstances = 0
            D1Spacing = 0.0
            D1ReverseDirection = False
            TotalInstances = 0
            Spacing = 0.0
            EqualSpacing = False
            ReverseDirection = False
            SeedComponentArray = None

            def GetSeedComponentCount(self): return seed_count

        data = Data()

        class Feature:
            Name = 'LocalLPattern1'

            def GetTypeName2(self): return 'LocalLPattern'

            def GetDefinition(self):
                if readback_count is not None:
                    data.D1TotalInstances = readback_count
                    data.TotalInstances = readback_count
                return data

        class FM:
            def CreateDefinition(self, kind):
                calls['defs'].append(kind)
                return data

            def CreateFeature(self, d):
                calls['created'] = d
                if not feature_ok:
                    return None
                names.extend(added if added is not None else [f'a-{i}' for i in range(2, d.D1TotalInstances + d.TotalInstances + 1)])
                return Feature()

        names = ['a-1']

        class Ext:
            def SelectByID2(self, name, kind, x, y, z, append, mark, callout, option):
                calls['select'].append((name, kind, append, mark))
                return selectable

        class Assembly:
            Extension = Ext()
            FeatureManager = FM()

            def ClearSelection2(self, *a): pass

            def GetTitle(self): return 'Assem1.SLDASM'

            def GetComponents(self, top_only):
                return [SimpleNamespace(Name2=n) for n in names]

        return calls, Assembly(), _sw()

    def run_tool(self, asm, sw, **kw):
        args = dict(pattern_type='linear', seed_component='a-1',
                    reference={'component': 'a-1', 'face_index': 2}, count=3, spacing_mm=250)
        args.update(kw)
        with patch.object(assembly, '_require_assembly', return_value=(asm, None)), \
                patch.object(assembly, '_exact_top_level', side_effect=lambda a, n: SimpleNamespace(Name2=n)), \
                patch.object(assembly, '_typed', side_effect=lambda obj, name: obj), \
                patch.object(assembly, '_select_component_face', return_value=True) as face:
            result = assembly.create_component_pattern(sw, **args)
        self.face = face
        return result

    def test_linear_pattern_is_created_and_verified(self):
        calls, asm, sw = self.case()
        r = self.run_tool(asm, sw)
        self.assertTrue(r['success'], r)
        self.assertEqual(calls['defs'], [108])
        data = calls['created']
        self.assertEqual((data.D1TotalInstances, data.D1Spacing, data.D1ReverseDirection), (3, 0.25, False))
        self.assertEqual(r['data']['feature_name'], 'LocalLPattern1')
        self.assertEqual(r['data']['new_components'], ['a-2', 'a-3'])
        self.assertFalse(r['data']['saved'])

    def test_direction_reference_uses_mark_2_and_seed_mark_1(self):
        calls, asm, sw = self.case()
        self.run_tool(asm, sw)
        args = self.face.call_args[0]
        self.assertEqual(args[3:], (False, 2))  # append False, mark 2
        self.assertEqual(calls['select'], [('a-1@Assem1', 'COMPONENT', True, 1)])

    def test_named_plane_reference_is_selected_with_mark_2(self):
        calls, asm, sw = self.case()
        self.run_tool(asm, sw, reference={'component': 'b-1', 'plane': 'Front Plane'})
        self.assertEqual(calls['select'][0], ('Front Plane@b-1@Assem1', 'PLANE', False, 2))

    def test_circular_pattern_uses_circular_definition(self):
        calls, asm, sw = self.case()
        r = self.run_tool(asm, sw, pattern_type='circular', spacing_mm=None, angle_deg=90, count=4)
        self.assertTrue(r['success'], r)
        self.assertEqual(calls['defs'], [109])
        data = calls['created']
        self.assertEqual(data.TotalInstances, 4)
        self.assertAlmostEqual(data.Spacing, math.pi / 2)
        self.assertTrue(data.EqualSpacing)

    def test_failures_are_reported_and_say_whether_the_document_changed(self):
        cases = [({'feature_ok': False}, {}, True), ({'selectable': False}, {}, False),
                 ({'readback_count': 2}, {}, True), ({'seed_count': 0}, {}, True),
                 ({'added': ['a-2']}, {}, True), ({}, {'count': 1}, False)]
        for case_kwargs, tool_kwargs, modified in cases:
            with self.subTest(case=case_kwargs, tool=tool_kwargs):
                calls, asm, sw = self.case(**case_kwargs)
                r = self.run_tool(asm, sw, **tool_kwargs)
                self.assertFalse(r['success'], r)
                self.assertEqual(r['data']['document_may_be_modified'], modified)
                self.assertFalse(r['data']['saved'])

    def test_face_selection_failure_never_creates_a_feature(self):
        calls, asm, sw = self.case()
        with patch.object(assembly, '_require_assembly', return_value=(asm, None)), \
                patch.object(assembly, '_exact_top_level', side_effect=lambda a, n: SimpleNamespace(Name2=n)), \
                patch.object(assembly, '_typed', side_effect=lambda obj, name: obj), \
                patch.object(assembly, '_select_component_face', return_value=False):
            r = assembly.create_component_pattern(sw, 'linear', 'a-1', {'component': 'a-1', 'face_index': 9}, 3,
                                                  spacing_mm=100)
        self.assertFalse(r['success'])
        self.assertIsNone(calls['created'])


if __name__ == '__main__':
    unittest.main()
