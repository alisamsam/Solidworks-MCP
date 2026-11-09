import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.tools import assembly

IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0.01, 0.02, 0.03, 2.0, 0, 0, 0]


def _sw():
    class Utility:
        def CreateTransform(self, variant):
            return FakeTransform([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0])  # real COM ignores the array

    class App:
        def GetMathUtility(self): return Utility()
    return SimpleNamespace(app=App(),
                           _result=lambda ok, msg, error=None, data=None: {'success': ok, 'msg': msg, 'data': data})


class FakeTransform:
    def __init__(self, data): self.ArrayData = data

    def __setattr__(self, key, value):
        object.__setattr__(self, key, list(getattr(value, 'value', value)))


class Component:
    Name2 = 'a-1'

    def __init__(self, data=None, fixed=False, accept=True):
        self.Transform2 = FakeTransform(list(data or IDENTITY))
        self.fixed, self.accept = fixed, accept

    def IsFixed(self): return self.fixed

    def __setattr__(self, key, value):
        if key == 'Transform2' and hasattr(self, 'Transform2') and not self.accept:
            return
        object.__setattr__(self, key, value)


def moved(point, rotation_deg):
    """Where the repo's own local-to-global maps a local point (identity translation, scale 1)."""
    tf = assembly._euler_to_matrix(rotation_deg) + [0, 0, 0, 1, 0, 0, 0]
    return assembly._local_to_global(point, tf)


class EulerTests(unittest.TestCase):
    def assertPoint(self, got, want):
        for a, b in zip(got, want):
            self.assertAlmostEqual(a, b)

    def test_positive_angles_are_right_handed(self):
        self.assertPoint(moved((1, 0, 0), [0, 0, 90]), (0, 1, 0))
        self.assertPoint(moved((0, 1, 0), [90, 0, 0]), (0, 0, 1))
        self.assertPoint(moved((0, 0, 1), [0, 90, 0]), (1, 0, 0))

    def test_composition_is_x_first_then_y_then_z(self):
        self.assertPoint(moved((0, 1, 0), [90, 0, 90]), (0, 0, 1))
        self.assertPoint(moved((1, 0, 0), [90, 0, 90]), (0, 1, 0))
        self.assertPoint(moved((0, 1, 0), [90, 90, 0]), (1, 0, 0))

    def test_matrix_to_euler_round_trips(self):
        for angles in ([0, 0, 0], [10, 20, 30], [-170, 45, 120], [90, 0, 0], [0, -60, 179]):
            with self.subTest(angles=angles):
                back = assembly._matrix_to_euler(assembly._euler_to_matrix(angles))
                self.assertPoint(assembly._euler_to_matrix(back), assembly._euler_to_matrix(angles))
                self.assertPoint(back, angles)

    def test_gimbal_lock_still_reproduces_the_matrix(self):
        m = assembly._euler_to_matrix([30, 90, 50])
        self.assertPoint(assembly._euler_to_matrix(assembly._matrix_to_euler(m)), m)

    def test_zero_is_identity(self):
        self.assertEqual(assembly._euler_to_matrix([0, 0, 0]), [1, 0, 0, 0, 1, 0, 0, 0, 1])


class RotationToolTests(unittest.TestCase):
    def run_tool(self, comp, rot=(0, 0, 90), expected=(0, 0, 0), name='a-1'):
        with patch.object(assembly, '_require_assembly', return_value=(object(), None)), \
                patch.object(assembly, '_find_component', return_value=comp):
            return assembly.set_component_rotation(_sw(), name, list(rot), list(expected))

    def test_rotates_and_keeps_translation_and_scale(self):
        c = Component()
        r = self.run_tool(c)
        self.assertTrue(r['success'], r)
        d = c.Transform2.ArrayData
        self.assertAlmostEqual(d[1], 1)  # local X now points along +Y
        self.assertEqual(d[9:], IDENTITY[9:])
        self.assertFalse(r['data']['saved'])

    def test_guards(self):
        self.assertFalse(self.run_tool(Component(fixed=True))['success'])
        self.assertFalse(self.run_tool(Component(), expected=(0, 0, 45))['success'])
        self.assertFalse(self.run_tool(Component(), name='s/a-1')['success'])
        self.assertFalse(self.run_tool(Component(), rot=(0, 0))['success'])
        self.assertFalse(self.run_tool(Component(), rot=(0, float('nan'), 0))['success'])

    def test_fails_when_native_placement_not_applied(self):
        c = Component(accept=False)
        r = self.run_tool(c)
        self.assertFalse(r['success'])
        self.assertTrue(r['data']['document_may_be_modified'])


if __name__ == '__main__':
    unittest.main()
