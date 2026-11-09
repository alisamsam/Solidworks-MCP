import unittest
from unittest.mock import Mock,patch
from solidworks_mcp.tools import routing_active_edit as ra
from solidworks_mcp.tests.test_routing_active_edit import SW,NS

class PropertiesCommandTests(unittest.TestCase):
    def setup_sw(self):
        feature=NS(GetTypeName2=lambda:'FabricatedRoute',Select2=lambda *a:True)
        doc=NS(GetType=lambda:2,GetPathName=lambda:'C:/out/route.sldasm',IsRouteAssembly=lambda:True,
               FeatureByName=lambda n:feature,ClearSelection2=lambda *a:None)
        doc.GetEditTarget=NS(read=lambda:doc).read
        sw=SW(doc);sw._path_policy=Mock();sw.app.RunCommand=Mock(return_value=True)
        return sw
    def call(self,sw,action,state):
        after={'active':True,'title':'Route Properties'} if action=='open' else {'active':False,'title':''}
        with patch.object(ra,'_routing_allowed',return_value=True), \
             patch.object(ra,'_running_command',side_effect=[state,after]):
            return ra.routing_properties_command(sw,'C:/out/route.sldasm',action,
                                                  expected_route_path='C:/out/route.sldasm')
    def test_open_uses_verified_native_command(self):
        sw=self.setup_sw();r=self.call(sw,'open',{'active':False,'title':''})
        self.assertTrue(r['success'],r);sw.app.RunCommand.assert_called_once_with(2257,'')
    def test_accept_only_exact_known_active_page(self):
        sw=self.setup_sw();r=self.call(sw,'accept',{'active':True,'title':'Route Properties'})
        self.assertTrue(r['success'],r);sw.app.RunCommand.assert_called_once_with(-2,'')
    def test_other_page_never_accepted(self):
        sw=self.setup_sw();r=self.call(sw,'accept',{'active':True,'title':'Delete'})
        self.assertFalse(r['success']);sw.app.RunCommand.assert_not_called()

    def test_native_true_without_observed_page_is_not_success(self):
        sw=self.setup_sw()
        with patch.object(ra,'_routing_allowed',return_value=True), \
             patch.object(ra,'_running_command',return_value={'active':False,'title':''}):
            r=ra.routing_properties_command(sw,'C:/out/route.sldasm','open',
                                             expected_route_path='C:/out/route.sldasm')
        self.assertFalse(r['success'],r)
    def test_denied_path_never_runs_command(self):
        sw=self.setup_sw();sw._path_policy.require_write.side_effect=PermissionError('protected')
        self.assertFalse(self.call(sw,'open',{'active':False,'title':''})['success'])
        sw.app.RunCommand.assert_not_called()

    def test_protected_edit_target_never_accepted(self):
        sw=self.setup_sw()
        protected=NS(GetPathName=lambda:'C:/protected/library.sldasm')
        sw.app.ActiveDoc.GetEditTarget=NS(read=lambda:protected).read
        def guard(path,operation):
            if 'protected' in str(path):raise PermissionError('protected target')
        sw._path_policy.require_write.side_effect=guard
        with patch.object(ra,'_routing_allowed',return_value=True), \
             patch.object(ra,'_running_command',return_value={'active':True,'title':'Route Properties'}):
            r=ra.routing_properties_command(sw,'C:/out/route.sldasm','accept',
                                             expected_route_path='C:/protected/library.sldasm')
        self.assertFalse(r['success']);sw.app.RunCommand.assert_not_called()

if __name__=='__main__':unittest.main()
