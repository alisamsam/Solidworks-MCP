import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.tools import assembly


def _sw():
    return SimpleNamespace(_result=lambda ok, msg, error=None, data=None: {'success': ok, 'msg': msg, 'data': data})


class RemoveComponentTests(unittest.TestCase):
    def case(self, noop=False, deleted_ok=True, selectable=True):
        class Post:
            Name2 = 'post-1'
            GetPathName = 'C:/p/post.SLDPRT'

            def Select4(self, *a): return selectable

        post = Post()
        other = SimpleNamespace(Name2='rail-1', GetPathName='C:/p/rail.SLDPRT')
        comps = [post, other]

        class FakeExtension:
            def DeleteSelection2(self, options):
                if not noop:
                    comps.remove(post)
                return deleted_ok

        class Document:
            SelectionManager = SimpleNamespace(CreateSelectData=object())
            Extension = FakeExtension()

            def ClearSelection2(self, *a): pass

            def GetComponents(self, top_only): return list(comps)

        return post, comps, Document(), _sw()

    def run_tool(self, doc, sw, comp, name='post-1', path='C:/p/post.SLDPRT'):
        with patch.object(assembly, '_require_assembly', return_value=(doc, None)), \
                patch.object(assembly, '_find_component', return_value=comp):
            return assembly.remove_component(sw, name, path)

    def test_removes_only_the_named_component_and_verifies(self):
        post, comps, doc, sw = self.case()
        r = self.run_tool(doc, sw, post)
        self.assertTrue(r['success'], r)
        self.assertEqual([c.Name2 for c in comps], ['rail-1'])
        self.assertEqual(r['data']['remaining_components'], 1)

    def test_fails_when_component_still_present_after_delete(self):
        post, comps, doc, sw = self.case(noop=True)
        r = self.run_tool(doc, sw, post)
        self.assertFalse(r['success'])

    def test_selection_failure_deletes_nothing(self):
        post, comps, doc, sw = self.case(selectable=False)
        r = self.run_tool(doc, sw, post)
        self.assertFalse(r['success'])
        self.assertEqual(len(comps), 2)
        self.assertFalse(r['data']['document_may_be_modified'])

    def test_rejects_nested_name_and_wrong_expected_path(self):
        for name, path in [('sub-1/post-1', 'C:/p/post.SLDPRT'), ('post-1', 'C:/p/other.SLDPRT')]:
            post, comps, doc, sw = self.case()
            r = self.run_tool(doc, sw, post, name, path)
            self.assertFalse(r['success'])
            self.assertEqual(len(comps), 2)


class SuppressComponentTests(unittest.TestCase):
    def case(self, noop=False):
        class Component:
            Name2 = 'post-1'
            state = 2

            def GetSuppression2(self):
                return self.state

            def SetSuppression2(self, state):
                if not noop:
                    self.state = state
                return 1
        return Component(), _sw()

    def run_tool(self, sw, comp, name, suppressed):
        with patch.object(assembly, '_require_assembly', return_value=(object(), None)), \
                patch.object(assembly, '_find_component', return_value=comp):
            return assembly.suppress_component(sw, name, suppressed)

    def test_suppress_and_unsuppress_are_verified_by_readback(self):
        c, sw = self.case()
        self.assertTrue(self.run_tool(sw, c, 'post-1', True)['success'])
        self.assertEqual(c.state, 0)
        self.assertTrue(self.run_tool(sw, c, 'post-1', False)['success'])
        self.assertEqual(c.state, 2)

    def test_fails_when_native_state_does_not_change(self):
        c, sw = self.case(noop=True)
        self.assertFalse(self.run_tool(sw, c, 'post-1', True)['success'])

    def test_exact_top_level_name_and_real_boolean_required(self):
        for name, flag in [('sub-1/post-1', True), ('post', True), ('post-1', 1)]:
            c, sw = self.case()
            self.assertFalse(self.run_tool(sw, c, name, flag)['success'])
            self.assertEqual(c.state, 2)


if __name__ == '__main__':
    unittest.main()
