import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.tools import assembly


def _sw(toggle=False):
    class App:
        def GetUserPreferenceToggle(self, toggle_id):
            return toggle if toggle_id == 18 else False
    return SimpleNamespace(app=App(),
                           _result=lambda ok, msg, error=None, data=None: {'success': ok, 'msg': msg, 'data': data})


class Component:
    def __init__(self, name, path='C:/p/post.SLDPRT', accept=True):
        self.Name2 = name
        self.path = path
        self.accept = accept
        self.selected = False

    def GetPathName(self):
        return self.path

    def Select4(self, *a):
        self.selected = True
        return True

    def __setattr__(self, key, value):
        if key == 'Name2' and getattr(self, 'accept', True) is False and hasattr(self, 'Name2'):
            return  # native rename silently ignored
        object.__setattr__(self, key, value)


class FakeAssembly:
    def __init__(self, comps):
        self.comps = comps
        self.SelectionManager = SimpleNamespace(CreateSelectData=object())

    def ClearSelection2(self, *a): pass

    def GetComponents(self, top_only): return list(self.comps)


class RenameComponentTests(unittest.TestCase):
    def run_tool(self, sw, comp, others, new_name, name='post-1', path='C:/p/post.SLDPRT'):
        asm = FakeAssembly([comp] + others)
        with patch.object(assembly, '_require_assembly', return_value=(asm, None)), \
                patch.object(assembly, '_find_component', return_value=comp):
            return assembly.rename_component(sw, name, new_name, path)

    def test_renames_and_verifies_readback(self):
        c = Component('post-1')
        r = self.run_tool(_sw(), c, [Component('rail-1')], 'stopnica-3')
        self.assertTrue(r['success'], r)
        self.assertEqual(c.Name2, 'stopnica-3')
        self.assertEqual(r['data']['before'], 'post-1')

    def test_fails_when_native_name_did_not_change(self):
        c = Component('post-1', accept=False)
        r = self.run_tool(_sw(), c, [], 'stopnica-3')
        self.assertFalse(r['success'])
        self.assertEqual(c.Name2, 'post-1')

    def test_refuses_when_update_component_names_preference_is_on(self):
        c = Component('post-1')
        r = self.run_tool(_sw(toggle=True), c, [], 'stopnica-3')
        self.assertFalse(r['success'])
        self.assertIn('External References', r['msg'])
        self.assertEqual(c.Name2, 'post-1')
        self.assertFalse(r['data']['document_may_be_modified'])

    def test_rejects_bad_names_duplicates_nested_and_wrong_path(self):
        cases = [('', 'post-1', 'C:/p/post.SLDPRT'), ('a/b', 'post-1', 'C:/p/post.SLDPRT'),
                 ('rail-1', 'post-1', 'C:/p/post.SLDPRT'), ('stopnica-3', 'sub-1/post-1', 'C:/p/post.SLDPRT'),
                 ('stopnica-3', 'post-1', 'C:/p/other.SLDPRT'), ('a@b', 'post-1', 'C:/p/post.SLDPRT'),
                 ('a<1>', 'post-1', 'C:/p/post.SLDPRT'), ('post-1', 'post-1', 'C:/p/post.SLDPRT')]
        for new_name, name, path in cases:
            with self.subTest(new_name=new_name, name=name, path=path):
                c = Component('post-1')
                r = self.run_tool(_sw(), c, [Component('rail-1')], new_name, name, path)
                self.assertFalse(r['success'])
                self.assertEqual(c.Name2, 'post-1')


if __name__ == '__main__':
    unittest.main()
