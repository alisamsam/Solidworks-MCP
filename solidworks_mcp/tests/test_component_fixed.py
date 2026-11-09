import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.tools import assembly

class ComponentFixedTests(unittest.TestCase):
    def case(self,noop=False):
        c=SimpleNamespace(Name2='post-1',IsFixed=True,Select4=lambda *a:True)
        class Document:
            SelectionManager=SimpleNamespace(CreateSelectData=object())
            def ClearSelection2(self,*a):pass
            def UnfixComponent(self):
                if not noop:c.IsFixed=False
            def FixComponent(self):
                if not noop:c.IsFixed=True
        doc=Document()
        sw=SimpleNamespace(_result=lambda ok,msg,error=None,data=None:{'success':ok,'data':data})
        return c,doc,sw
    def test_void_native_method_needs_state_readback(self):
        for noop in (False,True):
            c,doc,sw=self.case(noop)
            with patch.object(assembly,'_require_assembly',return_value=(doc,None)),patch.object(assembly,'_find_component',return_value=c):
                r=assembly.set_component_fixed(sw,'post-1',False)
            self.assertEqual(r['success'],not noop)
    def test_exact_top_level_name_and_real_boolean_required(self):
        for name,fixed in [('post-1',0),('sub-1/post-1',False),('post',False)]:
            c,doc,sw=self.case()
            with patch.object(assembly,'_require_assembly',return_value=(doc,None)),patch.object(assembly,'_find_component',return_value=c):
                r=assembly.set_component_fixed(sw,name,fixed)
            self.assertFalse(r['success']);self.assertTrue(c.IsFixed)
