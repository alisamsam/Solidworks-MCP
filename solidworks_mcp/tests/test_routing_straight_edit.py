import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from solidworks_mcp.tools import routing_active_edit as rp
from solidworks_mcp.tests.test_routing_active_edit import NS, SW

class StraightEditTests(unittest.TestCase):
    def setup_model(self):
        start=NS(X=0.,Y=0.,Z=0.)
        end=NS(X=-.22,Y=0.,Z=0.)
        def move(x,y,z): end.X=x;end.Y=y;end.Z=z;return True
        end.SetCoords=NS(move=move).move
        line=NS(GetType=lambda:0,ConstructionGeometry=False,GetLength=lambda:abs(end.X),
                GetStartPoint2=lambda:start,GetEndPoint2=lambda:end)
        sketch=NS(Is3D=lambda:True,GetSketchSegments=lambda:[line])
        target=NS(GetTitle=lambda:'route',GetPathName=lambda:'C:/out/route.sldasm',
                  GetType=lambda:2,IsRouteAssembly=lambda:True)
        doc=NS(GetTitle=lambda:'top',GetPathName=lambda:'C:/out/top.sldasm',GetType=lambda:2,
               GetEditTarget=lambda:target,GetActiveSketch2=lambda:sketch)
        sw=SW(doc);sw._path_policy=Mock()
        return sw,end
    def call(self,sw,**kw):
        with patch.object(rp,'_routing_allowed',return_value=True), \
             patch.object(rp,'_running_command',return_value={'active':False,'title':''}):
            return rp.resize_active_routing_line(sw,'C:/out/top.sldasm',
                    'C:/out/route.sldasm',220.,500.,**kw)
    def test_extends_existing_line_and_verifies(self):
        sw,end=self.setup_model();r=self.call(sw)
        self.assertTrue(r['success'],r);self.assertAlmostEqual(-.5,end.X)
        self.assertEqual(2,sw._path_policy.require_write.call_count)
        self.assertEqual(500.,r['data']['after']['length_mm'])
    def test_policy_denied_before_mutation(self):
        sw,end=self.setup_model();sw._path_policy.require_write.side_effect=PermissionError('protected')
        self.assertFalse(self.call(sw)['success']);self.assertEqual(-.22,end.X)
    def test_target_mismatch_before_mutation(self):
        sw,end=self.setup_model();sw.app.ActiveDoc.GetEditTarget=lambda:None
        self.assertFalse(self.call(sw)['success']);self.assertEqual(-.22,end.X)
    def test_stale_length_before_mutation(self):
        sw,end=self.setup_model();end.X=-.3
        self.assertFalse(self.call(sw)['success']);self.assertEqual(-.3,end.X)
    def test_nonfinite_input_before_com(self):
        with patch.object(rp,'_routing_allowed',return_value=True):
            r=rp.resize_active_routing_line(SW(None),'a','b',220.,float('nan'))
        self.assertFalse(r['success'])
    def test_native_no_effect_not_success(self):
        sw,end=self.setup_model();end.SetCoords=NS(move=lambda *a:True).move
        self.assertFalse(self.call(sw)['success']);self.assertEqual(-.22,end.X)

    def test_exit_checks_postcondition_not_void_return(self):
        sw,_=self.setup_model()
        def leave(manager,name):
            self.assertEqual('ExitRoute',name)
        def assembly():
            sw.app.ActiveDoc.GetActiveSketch2=NS(read=lambda:None).read
            sw.app.ActiveDoc.GetEditTarget=NS(read=lambda:sw.app.ActiveDoc).read
        sw.app.ActiveDoc.EditAssembly=NS(leave=assembly).leave
        with patch.object(rp,'_routing_allowed',return_value=True), \
             patch.object(rp,'_running_command',return_value={'active':False}), \
             patch.object(rp,'_read_route_manager',return_value=object()), \
             patch.object(rp,'_route_manager_call',side_effect=leave):
            r=rp.exit_active_routing_edit(sw,'C:/out/top.sldasm','C:/out/route.sldasm')
        self.assertTrue(r['success'],r)

    def test_exit_no_effect_fails(self):
        sw,_=self.setup_model()
        sw.app.ActiveDoc.EditAssembly=NS(leave=lambda:None).leave
        with patch.object(rp,'_routing_allowed',return_value=True), \
             patch.object(rp,'_running_command',return_value={'active':False}), \
             patch.object(rp,'_read_route_manager',return_value=object()), \
             patch.object(rp,'_route_manager_call',return_value=None):
            r=rp.exit_active_routing_edit(sw,'C:/out/top.sldasm','C:/out/route.sldasm')
        self.assertFalse(r['success'],r)

    def test_exit_closed_sketch_but_still_in_component_is_failure(self):
        sw,_=self.setup_model();doc=sw.app.ActiveDoc
        doc.EditAssembly=NS(leave=lambda:None).leave
        def close_only(raw,name):doc.GetActiveSketch2=NS(read=lambda:None).read
        with patch.object(rp,'_routing_allowed',return_value=True), \
             patch.object(rp,'_running_command',return_value={'active':False}), \
             patch.object(rp,'_read_route_manager',return_value=object()), \
             patch.object(rp,'_route_manager_call',side_effect=close_only):
            r=rp.exit_active_routing_edit(sw,'C:/out/top.sldasm','C:/out/route.sldasm')
        self.assertFalse(r['success'],r)

    def test_enter_selects_verified_route_component_in_container(self):
        sw,_=self.setup_model();doc=sw.app.ActiveDoc;target=doc.GetEditTarget()
        doc.GetActiveSketch2=NS(read=lambda:None).read
        feature=NS(Select2=lambda *a:True)
        component=NS(GetPathName=lambda:'C:/out/route.sldasm',GetModelDoc2=lambda:target)
        doc.GetComponentByName=NS(read=lambda n:component).read
        doc.FeatureByName=NS(read=lambda n:feature).read
        doc.ClearSelection2=NS(clear=lambda *a:None).clear
        def enter(raw,name):
            self.assertEqual('EditRoute',name)
            doc.GetActiveSketch2=NS(read=lambda:NS(Is3D=lambda:True)).read
        with patch.object(rp,'_routing_allowed',return_value=True), \
             patch.object(rp,'_running_command',return_value={'active':False}), \
             patch.object(rp,'_read_route_manager',return_value=object()), \
             patch.object(rp,'_route_manager_call',side_effect=enter):
            r=rp.enter_routing_edit(sw,'C:/out/top.sldasm','C:/out/route.sldasm','route-1')
        self.assertTrue(r['success'],r)

if __name__=='__main__':unittest.main()
