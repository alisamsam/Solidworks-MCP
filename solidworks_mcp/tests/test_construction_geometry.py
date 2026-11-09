import unittest
from types import SimpleNamespace
from solidworks_mcp.tools.construction_geometry import inspect_construction_geometry

class Point:
    def __init__(self,x,y): self.X=x; self.Y=y; self.Z=0
class Segment:
    ConstructionGeometry=False
    def __init__(self,a,b): self.a=Point(*a);self.b=Point(*b)
    def GetType(self): return 0
    def GetStartPoint2(self):return self.a
    def GetEndPoint2(self):return self.b
class Feature:
    def __init__(self,segments):self.segments=segments
    def GetTypeName2(self):return 'ProfileFeature'
    def GetSpecificFeature2(self):return self
    def GetSketchSegments(self):return self.segments
    def ModelToSketchTransform(self):return SimpleNamespace(ArrayData=[1]*16)
class Doc:
    def __init__(self,f):self.f=f
    def FeatureByName(self,name):return self.f
    def GetPathName(self):return 'copy.SLDPRT'
class SW:
    def __init__(self,f):self.doc=Doc(f)
    def get_active_doc(self):return self.doc,None
    def _result(self,success,message,error_code=0,data=None):return {'success':success,'data':data or {},'message':message}
class GeometryTests(unittest.TestCase):
    def test_offset_outline_reports_midpoint_and_centering_translation(self):
        f=Feature([Segment((0,0),(.15,0)),Segment((.15,0),(.15,.1)),Segment((.15,.1),(0,.1)),Segment((0,.1),(0,0))])
        r=inspect_construction_geometry(SW(f),'Sketch1')
        self.assertTrue(r['success'])
        self.assertEqual([75,50,0],r['data']['endpoint_center_mm'])
        self.assertEqual([-75,-50,0],r['data']['centering_translation_mm'])
        self.assertFalse(r['data']['origin_at_endpoint_center'])
    def test_unknown_segment_keeps_coverage_incomplete(self):
        class Unknown(Segment):
            def GetType(self):return 3
        r=inspect_construction_geometry(SW(Feature([Unknown((0,0),(1,1))])),'Sketch1')
        self.assertFalse(r['data']['complete'])
        self.assertIsNone(r['data']['endpoint_center_mm'])
    def test_arc_preserves_center_radius_and_direction(self):
        class Arc(Segment):
            def GetType(self):return 1
            def GetCenterPoint2(self):return Point(0,0)
            def GetRadius(self):return .002
            def GetRotationDir(self):return -1
        r=inspect_construction_geometry(SW(Feature([Arc((.002,0),(0,.002))])),'Sketch1')
        arc=r['data']['segments'][0]
        self.assertEqual([0,0,0],arc['center_mm'])
        self.assertEqual(2,arc['radius_mm'])
        self.assertEqual(-1,arc['rotation_direction'])

    def test_missing_feature_fails(self):
        self.assertFalse(inspect_construction_geometry(SW(None),'absent')['success'])
