import unittest
from unittest.mock import patch
from types import SimpleNamespace
from solidworks_mcp.tools.assembly import list_component_faces

class FaceGeometryTests(unittest.TestCase):
 def test_plane_point_and_oriented_normal_are_transformed_to_assembly(self):
  surface=SimpleNamespace(PlaneParams=[0,0,1,0,0,.005])
  face=SimpleNamespace(GetSurface=surface,GetArea=.03,
    GetBox=[0,0,.005,.3,.1,.005],Normal=[0,0,-1])
  # Local Z maps to assembly Y, local Y to negative assembly Z.
  tf=[1,0,0,0,0,-1,0,1,0,1,2,3,1,0,0,0]
  comp=SimpleNamespace(Transform2=SimpleNamespace(ArrayData=tf))
  sw=SimpleNamespace(_result=lambda ok,msg,error=None,data=None:{'success':ok,'data':data})
  with patch('solidworks_mcp.tools.assembly._require_assembly',return_value=(object(),None)),patch('solidworks_mcp.tools.assembly._find_component',return_value=comp),patch('solidworks_mcp.tools.assembly._component_faces',return_value=[(face,'planar')]):
   r=list_component_faces(sw,'plate-1')['data']
  self.assertTrue(r['complete'])
  f=r['faces'][0]
  self.assertEqual([1000,2005,3000],f['plane_point_assembly_mm'])
  self.assertEqual([0,-1,0],f['normal_assembly'])
  self.assertEqual([1150,2005,2950],f['box_center_assembly_mm'])
  self.assertEqual(0,f['index'])
 def test_missing_geometry_retains_index_and_reports_incomplete(self):
  face=SimpleNamespace(GetSurface=object(),GetArea=.01)
  sw=SimpleNamespace(_result=lambda ok,msg,error=None,data=None:{'success':ok,'data':data})
  with patch('solidworks_mcp.tools.assembly._require_assembly',return_value=(object(),None)),patch('solidworks_mcp.tools.assembly._find_component',return_value=object()),patch('solidworks_mcp.tools.assembly._component_faces',return_value=[(face,'planar')]):
   r=list_component_faces(sw,'plate-1')['data']
  self.assertFalse(r['complete']);self.assertTrue(r['unresolved'])
  self.assertEqual(0,r['faces'][0]['index'])
