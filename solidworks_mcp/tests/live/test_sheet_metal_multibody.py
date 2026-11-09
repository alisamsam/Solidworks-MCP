"""Independent per-body thickness/radius without changing older sheet bodies."""
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

import pythoncom
from win32com.client import VARIANT
from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.sheetmetal import create_sheet_metal_base_flange
from solidworks_mcp.tools.sheetmetal_multibody import _snapshot,_unchanged


@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS')=='1','Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveSheetMetalMultibodyTests(unittest.TestCase):
    def test_three_independent_thicknesses_preserve_all_previous_geometry(self):
        root=Path(__file__).resolve().parents[3]/'output/sheet-metal-multibody-20261018-R01'/('live-'+uuid4().hex[:8])
        root.mkdir(parents=True);path=root/'MULTIBODY.SLDPRT'
        sw=SolidWorksAutomation();self.assertTrue(sw.connect()['success']);sw._path_policy=PathPolicy([root])
        app=sw.app;previous=com(app,'ActiveDoc');previous_path=com(previous,'GetPathName') if previous is not None else ''
        doc=None;rows=[]
        try:
            self.assertTrue(sw.create_new_part()['success']);doc=com(app,'ActiveDoc')
            cases=[(0,0,100,50,1,1),(160,0,80,40,2,2),(0,100,60,30,3,4)]
            for i,(x,y,w,h,thickness,radius) in enumerate(cases):
                before=[_snapshot(b) for b in com(doc,'GetBodies2',0,False) or []]
                self.assertTrue(sw.create_sketch('Front',exact_geometry=True)['success'])
                self.assertTrue(sw.draw_rectangle(x,y,x+w,y+h,'mm')['success'])
                if i:
                    rejected=create_sheet_metal_base_flange(sw,thickness,bend_radius_mm=radius)
                    self.assertFalse(rejected['success']);self.assertEqual('ALREADY_SHEET_METAL',rejected['data']['code'])
                r=create_sheet_metal_base_flange(sw,thickness,bend_radius_mm=radius,new_body=bool(i))
                self.assertTrue(r['success'],r)
                bodies=com(doc,'GetBodies2',0,False);self.assertEqual(i+1,len(bodies))
                after=[_snapshot(b) for b in bodies]
                for old in before:self.assertTrue(any(_unchanged(old,new) for new in after))
                if i:
                    self.assertAlmostEqual(w*h*thickness,r['data']['new_body_volume_mm3'],delta=1e-5)
                    self.assertTrue(r['data']['independent_bend_parameters'])
                self.assertTrue(sw.save_document(str(path))['success']);rows.append(r['data'])
            self.assertEqual([5000,5400,6400],sorted(round(com(b,'GetMassProperties',0.)[3]*1e9) for b in com(doc,'GetBodies2',0,False)))
            app.CloseDoc(com(doc,'GetTitle'));doc=None
            self.assertTrue(sw.open_document(str(path))['success']);doc=com(app,'ActiveDoc')
            bodies=com(doc,'GetBodies2',0,False);self.assertEqual(3,len(bodies))
            self.assertEqual([5000,5400,6400],sorted(round(com(b,'GetMassProperties',0.)[3]*1e9) for b in bodies))
            self.assertTrue(all(com(b,'IsSheetMetal') for b in bodies))
            features=com(com(doc,'FeatureManager'),'GetFeatures',False)
            definitions=[com(f,'GetDefinition') for f in features if com(f,'GetTypeName2')=='SheetMetal']
            self.assertEqual([1,2,3],sorted(round(com(d,'Thickness')*1000) for d in definitions))
            self.assertEqual([1,2,4],sorted(round(com(d,'BendRadius')*1000) for d in definitions))
            for row in rows[1:]:
                feature=com(doc,'FeatureByName',row['feature']);warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
                self.assertEqual(0,com(feature,'GetErrorCode2',warning));self.assertFalse(warning.value)
            (root/'measurements.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
        finally:
            if doc is not None:app.CloseDoc(com(doc,'GetTitle'))
            if previous_path and com(app,'GetOpenDocumentByName',previous_path) is not None:
                error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0);app.ActivateDoc3(com(previous,'GetTitle'),False,0,error)

if __name__=='__main__':unittest.main()
