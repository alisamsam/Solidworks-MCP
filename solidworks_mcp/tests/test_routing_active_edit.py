"""Read the actual in-context route sketch without activating its document."""
import unittest
from types import MethodType
from unittest.mock import patch
from solidworks_mcp.tools import routing_active_edit as rp

class NS:
    def __init__(self, **members):
        for key,value in members.items():
            setattr(self,key,MethodType(lambda self,*a,_f=value: _f(*a),self)
                    if callable(value) else value)


class SW:
    is_connected = True
    def __init__(self, doc): self.app = NS(ActiveDoc=doc)
    def _result(self, success, message, error_code=0, data=None):
        return dict(success=success, message=message, data=data)


class ActiveEditTests(unittest.TestCase):
    def call(self, doc):
        with patch.object(rp, '_routing_allowed', return_value=True), \
             patch.object(rp, '_running_command', return_value={'title':'', 'active':False}):
            return rp.inspect_routing_active_edit(SW(doc))

    def doc(self, target=None, sketch=None):
        return NS(GetType=lambda:2, GetTitle=lambda:'top', GetPathName=lambda:'C:/top.sldasm',
                  GetEditTarget=lambda:target, GetActiveSketch2=lambda:sketch)

    def test_route_in_context_reads_active_sketch_not_feature_by_name(self):
        route=NS(GetTitle=lambda:'route', GetPathName=lambda:'C:/route.sldasm',
                 GetType=lambda:2, IsRouteAssembly=lambda:True)
        line=NS(GetType=lambda:0, ConstructionGeometry=False, GetLength=lambda:.22,
                GetStartPoint2=lambda:NS(X=0,Y=0,Z=0),
                GetEndPoint2=lambda:NS(X=-.22,Y=0,Z=0))
        result=self.call(self.doc(route,NS(Is3D=lambda:True,GetSketchSegments=lambda:[line])))
        self.assertTrue(result['success'],result)
        self.assertEqual('C:/route.sldasm',result['data']['edit_target']['path'])
        self.assertEqual([-220.,0.,0.],result['data']['segments'][0]['end_mm'])
        self.assertFalse(result['data']['managed_route_membership_verified'])

    def test_no_sketch_is_observed_not_inferred_as_empty(self):
        result=self.call(self.doc())
        self.assertTrue(result['success'],result)
        self.assertIsNone(result['data']['segments'])
        self.assertFalse(result['data']['has_active_sketch'])

    def test_disabled_does_not_touch_sw(self):
        with patch.object(rp,'_routing_allowed',return_value=False):
            result=rp.inspect_routing_active_edit(SW(None))
        self.assertFalse(result['success'])

    def test_segment_limit_checked_before_reading_segments(self):
        result=self.call(self.doc(sketch=NS(Is3D=lambda:True,
            GetSketchSegments=lambda:[object()]*(rp._MAX_SEGMENTS+1))))
        self.assertFalse(result['success'])

    def test_native_failure_is_not_no_sketch(self):
        doc=self.doc()
        def broken(): raise RuntimeError('native unavailable')
        doc.GetActiveSketch2=MethodType(lambda self:broken(),doc)
        result=self.call(doc)
        self.assertFalse(result['success'])
        self.assertIn('native unavailable',str(result))

    def test_unreadable_segment_fails_complete_read(self):
        result=self.call(self.doc(sketch=NS(Is3D=lambda:True,GetSketchSegments=lambda:[object()])) )
        self.assertFalse(result['success'])


if __name__=='__main__': unittest.main()
