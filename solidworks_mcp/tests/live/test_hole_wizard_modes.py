"""One scratch plate: six native Hole Wizard modes and persisted geometry."""
import json
import math
import os
from pathlib import Path
import unittest
from uuid import uuid4

import pythoncom
from win32com.client import VARIANT
from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.advanced_features import hole_wizard
from solidworks_mcp.tools.export import list_planar_faces

@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS')=='1','Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveHoleWizardModesTests(unittest.TestCase):
    def test_six_modes_have_requested_geometry_and_persist(self):
        root=Path(__file__).resolve().parents[3]/'output/hole-wizard-20261018-R01'/('live-'+uuid4().hex[:8])
        root.mkdir(parents=True);target=root/'HOLES.SLDPRT'
        sw=SolidWorksAutomation();self.assertTrue(sw.connect()['success']);sw._path_policy=PathPolicy([root])
        app=sw.app;previous=com(app,'ActiveDoc');previous_path=com(previous,'GetPathName') if previous is not None else ''
        doc=None;rows=[]
        try:
            self.assertTrue(sw.create_new_part()['success']);doc=com(app,'ActiveDoc')
            self.assertTrue(sw.create_sketch('Top',exact_geometry=True)['success'])
            self.assertTrue(sw.draw_rectangle(0,0,160,80,'mm')['success'])
            self.assertTrue(sw.extrude_sketch(20,unit='mm')['success'])
            def volume():return com(com(com(doc,'Extension'),'CreateMassProperty'),'Volume')*1e9
            self.assertAlmostEqual(256000.,volume(),places=5)
            total=0.
            for end,x in [('blind',-20),('through_all',-60)]:
                for kind,y in [('drill',25),('counterbore',65),('countersink',105)]:
                    faces=list_planar_faces(sw);self.assertTrue(faces['success'],faces)
                    cap=max((f for f in faces['data']['faces'] if f['normal'][2]>.99),key=lambda f:f['area_mm2'])
                    diameter=6 if kind=='drill' else 6.6;r=diameter/2
                    kwargs=dict(face_index=cap['index'],point_mm=[x,y,20],diameter_mm=diameter,hole_type=kind,end_condition=end)
                    depth=8 if kind=='drill' else 10
                    if end=='blind':kwargs['depth_mm']=depth
                    if kind!='drill':kwargs.update(catalog_size='M6',head_diameter_mm=11 if kind=='counterbore' else 12)
                    if kind=='counterbore':kwargs['head_depth_mm']=4
                    if kind=='countersink':kwargs['head_angle_deg']=90
                    before=volume();result=hole_wizard(sw,**kwargs);self.assertTrue(result['success'],result)
                    expected=math.pi*r*r*(depth if end=='blind' else 20)
                    if end=='blind':expected+=math.pi*r*r*(r/math.tan(math.radians(59)))/3
                    if kind=='counterbore':expected+=math.pi*(5.5**2-r*r)*4
                    if kind=='countersink':
                        h=6-r;expected+=math.pi*h*(36+6*r+r*r)/3-math.pi*r*r*h
                    self.assertAlmostEqual(expected,before-volume(),delta=.001)
                    # Read actual cylindrical faces: the bore axis is at the requested point.
                    found=False
                    for body in com(doc,'GetBodies2',0,False):
                        for face in com(body,'GetFaces'):
                            surface=com(face,'GetSurface')
                            if com(surface,'IsCylinder'):
                                p=com(surface,'CylinderParams')
                                if abs(p[0]*1000-x)<1e-5 and abs(p[1]*1000-y)<1e-5 and abs(p[6]*1000-r)<1e-5:found=True
                    self.assertTrue(found,(kind,end,'bore axis/radius not found'))
                    total+=expected;rows.append(dict(kind=kind,end=end,expected_removed_mm3=expected,data=result['data']))
            self.assertAlmostEqual(256000-total,volume(),delta=.001)
            self.assertTrue(sw.save_document(str(target))['success'])
            app.CloseDoc(com(doc,'GetTitle'));doc=None
            self.assertTrue(sw.open_document(str(target))['success']);doc=com(app,'ActiveDoc')
            self.assertAlmostEqual(256000-total,volume(),delta=.001)
            for row in rows:
                feature=com(doc,'FeatureByName',row['data']['feature_name']);self.assertIsNotNone(feature)
                definition=com(feature,'GetDefinition')
                self.assertEqual(0 if row['end']=='blind' else 1,com(definition,'EndCondition'))
                warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
                self.assertEqual(0,com(feature,'GetErrorCode2',warning));self.assertFalse(warning.value)
            (root/'measurements.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf-8')
        finally:
            if doc is not None:
                path=com(doc,'GetPathName')
                if not path or Path(path).resolve()==target.resolve():app.CloseDoc(com(doc,'GetTitle'))
            if previous_path:
                opened=com(app,'GetOpenDocumentByName',previous_path)
                if opened is not None:
                    error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
                    app.ActivateDoc3(com(opened,'GetTitle'),False,0,error)
                    self.assertEqual(0,error.value)

if __name__=='__main__':unittest.main()
