"""Read invariants and per-body parameters in an own mixed multibody part."""
import hashlib
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
from solidworks_mcp.tools.sheetmetal_bodies import list_sheet_metal_bodies


@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS')=='1','Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveSheetBodyInfoTests(unittest.TestCase):
    def test_independent_parameters_hidden_and_ordinary_body_read_invariants(self):
        root=Path(__file__).resolve().parents[3]/'output/sheet-metal-body-info-20261018-R01'/('live-'+uuid4().hex[:8])
        root.mkdir(parents=True);path=root/'MIXED.SLDPRT'
        sw=SolidWorksAutomation();self.assertTrue(sw.connect()['success']);sw._path_policy=PathPolicy([root])
        app=sw.app;previous=com(app,'ActiveDoc');previous_path=com(previous,'GetPathName') if previous is not None else ''
        doc=None;records={}
        try:
            self.assertTrue(sw.create_new_part()['success']);doc=com(app,'ActiveDoc')
            for i,(x,y,w,h,t,radius) in enumerate([(0,0,100,50,1,1),(160,0,80,40,2,2),(0,100,60,30,3,4)]):
                self.assertTrue(sw.create_sketch('Front',exact_geometry=True)['success'])
                self.assertTrue(sw.draw_rectangle(x,y,x+w,y+h,'mm')['success'])
                result=create_sheet_metal_base_flange(sw,t,bend_radius_mm=radius,new_body=bool(i))
                self.assertTrue(result['success'],result)
                self.assertTrue(sw.save_document(str(path))['success'])
            self.assertTrue(sw.create_sketch('Front',exact_geometry=True)['success'])
            self.assertTrue(sw.draw_rectangle(300,200,340,220,'mm')['success'])
            self.assertTrue(sw.extrude_sketch(6,unit='mm')['success'])
            self.assertTrue(sw.save_document(str(path))['success'])
            def state():
                return dict(stamp=com(doc,'GetUpdateStamp'),dirty=com(doc,'GetSaveFlag'),
                    configuration=com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name'),
                    selected=com(com(doc,'SelectionManager'),'GetSelectedObjectCount2',-1),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    volumes_mm3=sorted(round(com(b,'GetMassProperties',0)[3]*1e9,6) for b in com(doc,'GetBodies2',0,False)))
            before=state();r=list_sheet_metal_bodies(sw);self.assertTrue(r['success'],r);d=r['data']
            self.assertEqual(before,state());self.assertTrue(d['complete'],d)
            self.assertEqual((4,3,1),(d['solid_body_count'],d['sheet_body_count'],len(d['non_sheet_bodies'])))
            self.assertEqual([1,2,3],sorted(b['parameters']['thickness_mm'] for b in d['bodies']))
            self.assertEqual([1,2,4],sorted(b['parameters']['bend_radius_mm'] for b in d['bodies']))
            self.assertTrue(all(b['parameters']['k_factor']==.5 and not b['flattened'] for b in d['bodies']))
            records['normal']=d
            solids=com(doc,'GetBodies2',0,False)
            chosen=d['bodies'][0];hidden=solids[chosen['solid_body_index']]
            com(hidden,'HideBody',True);before=state()
            r=list_sheet_metal_bodies(sw);self.assertTrue(r['data']['complete'],r);self.assertEqual(before,state())
            hidden_row=next(b for b in r['data']['bodies'] if b['name']==chosen['name'])
            self.assertFalse(hidden_row['visible']);self.assertIsNone(hidden_row['body_index'])
            self.assertEqual(chosen['parameters'],hidden_row['parameters']);records['hidden']=r['data']
            com(hidden,'HideBody',False);self.assertTrue(sw.save_document(str(path))['success'])
            app.CloseDoc(com(doc,'GetTitle'));doc=None
            self.assertTrue(sw.open_document(str(path))['success']);doc=com(app,'ActiveDoc')
            before=state();r=list_sheet_metal_bodies(sw);self.assertTrue(r['data']['complete'],r);self.assertEqual(before,state())
            self.assertEqual([1,2,3],sorted(b['parameters']['thickness_mm'] for b in r['data']['bodies']))
            records['reopened']=r['data'];records['read_invariants']=before
            (root/'measurements.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        finally:
            if doc is not None:app.CloseDoc(com(doc,'GetTitle'))
            if previous_path and com(app,'GetOpenDocumentByName',previous_path) is not None:
                error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0);app.ActivateDoc3(com(previous,'GetTitle'),False,0,error)

if __name__=='__main__':unittest.main()
