import math
import unittest
from types import SimpleNamespace as NS
from types import MethodType
from unittest.mock import patch
from .test_sheet_metal_body_info import Automation
from solidworks_mcp.tools.manufacturing_bodies import _plate_candidate, inspect_part_manufacturing


class Face:
    def __init__(self, area, point, normal, planar=True):
        self.area=area; self.Normal=normal; self.surface=NS(IsPlane=planar, PlaneParams=[*normal,*point])
    def GetArea(self): return self.area
    def GetSurface(self): return self.surface


class PlateTests(unittest.TestCase):
    def setUp(self):
        self.faces=[Face(.005,[0,0,0],[0,0,-1]),Face(.005,[0,0,.002],[0,0,1])]
    def test_through_plate_candidate(self):
        result=_plate_candidate(self.faces, 10000, 17)
        self.assertEqual(17,result['face_index']); self.assertAlmostEqual(2,result['thickness_mm'])
        self.assertEqual('plate_candidate',result['kind'])
    def test_reject_non_parallel_blind_or_variable_section(self):
        for normal,area,volume in [([0,1,0],.005,10000),([0,0,1],.004,10000),([0,0,1],.005,9000)]:
            self.faces[1].Normal=normal; self.faces[1].area=area
            self.assertIsNone(_plate_candidate(self.faces,volume,0))
    def test_cube_not_plate(self):
        self.faces[1].surface.PlaneParams[-1]=.1
        self.assertIsNone(_plate_candidate(self.faces,500000,0))
    def test_nonfinite_geometry_rejected(self):
        self.assertIsNone(_plate_candidate(self.faces,math.nan,0))
    def test_global_index_counts_curved_faces(self):
        self.faces.insert(0,Face(1,[0,0,0],[0,0,1],False))
        self.assertEqual(11,_plate_candidate(self.faces,10000,10)['face_index'])


class InspectionTests(unittest.TestCase):
    def test_geometry_failure_is_explicit_not_empty_success(self):
        sw=Automation(); sw.doc.GetSaveFlag=False
        with patch('solidworks_mcp.tools.manufacturing_bodies.get_cut_list_body_map',return_value={'success':False,'message':'bad membership'}):
            r=inspect_part_manufacturing(sw)
        self.assertFalse(r['success'])
    def test_upstream_geometry_warning_prevents_complete_inspection(self):
        sw=Automation();sw.doc.GetSaveFlag=False
        sw.doc.GetBodies2=MethodType(lambda obj,kind,visible:[],sw.doc)
        sw.doc.GetMaterialPropertyName2=MethodType(lambda obj,cfg,db:'',sw.doc)
        mapping={'items':[],'unassigned_bodies':[],'warnings':[{'code':'GEOMETRY_READ_FAILED','body':'A'}],'mapping_complete':False}
        with patch('solidworks_mcp.tools.manufacturing_bodies.get_cut_list_body_map',return_value={'success':True,'data':mapping}):
            r=inspect_part_manufacturing(sw)
        self.assertTrue(r['success'],r)
        self.assertFalse(r['data']['inspection_complete'])
        self.assertFalse(r['data']['body_read_complete'])


if __name__=='__main__':unittest.main()
