import unittest
from types import SimpleNamespace
from solidworks_mcp.tools.sketch_entities import draw_line_3d


class Units:
    def to_meters(self, value, unit):
        return value * {'mm': .001, 'm': 1}[unit]


class Manager:
    def __init__(self):
        self.calls = []

    def CreateLine(self, *args):
        self.calls.append(args)
        return object()


class SW:
    def __init__(self, is3d=True):
        self.manager = Manager()
        self.doc = SimpleNamespace(GetActiveSketch2=SimpleNamespace(Is3D=is3d), SketchManager=self.manager)
        self._units = Units()

    def get_active_doc(self):
        return self.doc, None

    def _result(self, success, message, code=None, data=None):
        return {'success': success, 'data': data, 'message': message}


class LineTests(unittest.TestCase):
    def test_preserves_z_and_converts_units(self):
        sw = SW()
        self.assertTrue(draw_line_3d(sw, 0, 200, -100, 825, 200, -100)['success'])
        self.assertEqual(len(sw.manager.calls), 1)
        for actual, expected in zip(sw.manager.calls[0], (0, .2, -.1, .825, .2, -.1)):
            self.assertAlmostEqual(actual, expected)

    def test_rejects_2d_and_zero_length_without_creation(self):
        for sw, args in [(SW(False), (0, 0, 0, 10, 0, 0)), (SW(), (1, 2, 3, 1, 2, 3))]:
            self.assertFalse(draw_line_3d(sw, *args)['success'])
            self.assertEqual(sw.manager.calls, [])


if __name__ == '__main__':
    unittest.main()
