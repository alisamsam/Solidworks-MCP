import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from .test_manufacturing_package import SW
from solidworks_mcp.tools.documentation_drawing import _view_snapshot, _set_projection, create_documentation_drawing, _finish, _set_position, _layout


class View:
    ReferencedConfiguration='Default'
    def GetName2(self):return 'Front'
    def GetReferencedModelName(self):return str(self.path)
    def GetOutline(self):return [.02,.05,.12,.15]


class DrawingTests(unittest.TestCase):
    def test_layout_repositions_native_gaps_instead_of_only_scaling_geometry(self):
        path=Path('p.sldprt').resolve()
        class LayoutView(View):
            def __init__(self,pos,width,height):self.path=path;self.pos=pos;self.width=width;self.height=height
            @property
            def Position(self):return self.pos
            @Position.setter
            def Position(self,value):self.pos=list(value.value)
            def GetOutline(self):return [self.pos[0]-self.width/2,self.pos[1]-self.height/2,self.pos[0]+self.width/2,self.pos[1]+self.height/2]
        views=[LayoutView([.093,.156],.047,.0585),LayoutView([.093,.0694],.047,.0371),LayoutView([.191,.156],.0371,.0585)]
        class Sheet:
            def GetProperties2(self):return [0,0,1,31,True,.2794,.2159,False]
            def SetScale(self,*args):pass
        class Drawing:
            def GetCurrentSheet(self):return Sheet()
            def ForceRebuild3(self,top):return True
        result=_layout(Drawing(),views,path,'Default')
        self.assertFalse(result['layout_needs_review'],result)
    def test_small_template_views_are_enlarged_to_use_reserved_sheet(self):
        path=Path('p.sldprt').resolve();factor=[1.]
        class FitView(View):
            def __init__(self,pos,w,h):self.path=path;self.pos=pos;self.w=w;self.h=h
            @property
            def Position(self):return self.pos
            @Position.setter
            def Position(self,value):self.pos=list(value.value)
            def GetOutline(self):return [self.pos[0]-self.w*factor[0]/2,self.pos[1]-self.h*factor[0]/2,self.pos[0]+self.w*factor[0]/2,self.pos[1]+self.h*factor[0]/2]
        views=[FitView([.09,.15],.031,.026),FitView([.09,.06],.031,.001),FitView([.2,.15],.001,.026)]
        class Sheet:
            def GetProperties2(self):return [0,0,1,50,True,.2794,.2159,False]
            def SetScale(self,n,d,*args):factor[0]=(n/d)/.02
        class Drawing:
            def GetCurrentSheet(self):return Sheet()
            def ForceRebuild3(self,top):return True
        result=_layout(Drawing(),views,path,'Default')
        self.assertGreater(factor[0],2.);self.assertFalse(result['layout_needs_review'],result)
    def test_position_uses_native_double_array_not_variant_list(self):
        class NativeView:
            _position=[0.,0.]
            @property
            def Position(self):return self._position
            @Position.setter
            def Position(self,value):
                # Observed SW2025 behavior: raw list puts [0,x], typed doubles work.
                self._position=list(value.value) if hasattr(value,'varianttype') else [0.,value[0]]
        view=NativeView();_set_position(view,.10,.15)
        self.assertEqual([.10,.15],view.Position)
    def test_source_restoration_still_runs_after_copy_cleanup_failure(self):
        sw=NS(app=object());source=object();before=('before',)
        with patch('solidworks_mcp.tools.documentation_drawing._close_outputs',side_effect=ValueError('cleanup failed')), \
             patch('solidworks_mcp.tools.documentation_drawing._activate_source') as activate, \
             patch('solidworks_mcp.tools.documentation_drawing._state',return_value=before):
            errors=_finish(sw,[Path('copy')],source,before,Path('source').resolve(),{})
        activate.assert_called_once();self.assertTrue(errors)
    def test_wrong_model_reference_fails(self):
        v=View();v.path=Path('other.sldprt').resolve()
        with self.assertRaises(ValueError):_view_snapshot([v],Path('expected.sldprt').resolve(),'Default')
    def test_wrong_config_fails(self):
        v=View();v.path=Path('p.sldprt').resolve()
        with self.assertRaises(ValueError):_view_snapshot([v],v.path,'Other')
    def test_valid_outline_and_reference(self):
        v=View();v.path=Path('p.sldprt').resolve()
        self.assertEqual('Front',_view_snapshot([v],v.path,'Default')[0]['name'])
    def test_void_projection_setter_verified_by_readback(self):
        class Sheet:
            def GetProperties2(self):return [0,0,1,10,self.first,.297,.21,False]
            def SetProperties2(self,p,t,s1,s2,first,w,h,same):self.first=first
        sheet=Sheet();sheet.first=False
        _set_projection(sheet,'first_angle');self.assertTrue(sheet.first)
    def test_silent_noop_projection_rejected(self):
        class Sheet:
            def GetProperties2(self):return [0,0,1,10,False,.297,.21,False]
            def SetProperties2(self,*args):pass
        with self.assertRaises(ValueError):_set_projection(Sheet(),'first_angle')
    def test_existing_folder_fails_before_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            sw=SW(tmp,Path(tmp)/'p.sldprt');sw.get_active_doc=Mock()
            result=create_documentation_drawing(sw,str(Path(tmp)/'p.sldprt'),'Default',tmp)
            self.assertFalse(result['success']);sw.get_active_doc.assert_not_called()


if __name__=='__main__':unittest.main()
