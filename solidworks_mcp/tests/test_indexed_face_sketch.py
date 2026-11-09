import unittest
from unittest.mock import patch
from types import SimpleNamespace
from solidworks_mcp.tools.reference_geometry import create_sketch_on_planar_face

class Automation:
    def __init__(self,doc):self.doc=doc
    def get_active_doc(self):return self.doc,None
    def _result(self,success,message,error_code=0,data=None):return {'success':success,'message':message,'data':data or {}}

class Document:
    def __init__(self):
        self.sketch=None;self.created=0;self.SketchManager=SimpleNamespace(AddToDB=False)
    def GetType(self):return 1
    def GetActiveSketch2(self):return self.sketch
    def ClearSelection2(self,*a):pass
    def InsertSketch2(self,*a):
        self.created+=1
        self.sketch=SimpleNamespace(ModelToSketchTransform=SimpleNamespace(ArrayData=[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0]))

class Face:
    def __init__(self,selected=True):self.selected=selected
    def Select4(self,*a):return self.selected
    def GetSurface(self):return SimpleNamespace(PlaneParams=[0,0,1,0,0,0])

class IndexedFaceSketchTests(unittest.TestCase):
    def test_rejects_boolean_index(self):
        self.assertFalse(create_sketch_on_planar_face(Automation(Document()),True)['success'])
    def test_preserves_existing_active_sketch(self):
        doc=Document();doc.sketch=object()
        self.assertFalse(create_sketch_on_planar_face(Automation(doc),0)['success']);self.assertEqual(doc.created,0)
    def test_failed_selection_never_inserts_sketch(self):
        doc=Document()
        with patch('solidworks_mcp.tools.export._get_planar_face_by_index',return_value=Face(False)):
            self.assertFalse(create_sketch_on_planar_face(Automation(doc),0)['success'])
        self.assertEqual(doc.created,0)
    def test_void_insert_requires_observable_sketch_and_plane(self):
        doc=Document()
        with patch('solidworks_mcp.tools.export._get_planar_face_by_index',return_value=Face()):
            result=create_sketch_on_planar_face(Automation(doc),0,True)
        self.assertTrue(result['success']);self.assertEqual(result['data']['plane_residual_m'],0);self.assertTrue(doc.SketchManager.AddToDB)
