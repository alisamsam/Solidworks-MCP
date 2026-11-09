"""One scratch multibody part: native Save Bodies and persisted references."""
import hashlib
import os
from pathlib import Path
import unittest
from uuid import uuid4

import pythoncom
from win32com.client import VARIANT

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.save_bodies import save_bodies

@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS')=='1','Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveSaveBodiesTests(unittest.TestCase):
    def test_selected_subset_persists_without_consuming_source(self):
        root=Path(__file__).resolve().parents[3]/'output/save-bodies-20261018-R01'/('live-'+uuid4().hex[:8])
        root.mkdir(parents=True);source=root/'SOURCE.SLDPRT'
        sw=SolidWorksAutomation();self.assertTrue(sw.connect()['success']);sw._path_policy=PathPolicy([root])
        app=sw.app;previous=com(app,'ActiveDoc');previous_path=com(previous,'GetPathName') if previous is not None else ''
        doc=None
        try:
            self.assertTrue(sw.create_new_part()['success']);doc=com(app,'ActiveDoc')
            for x1,y1,x2,y2 in [(0,0,100,50),(150,0,190,30),(230,0,250,20)]:
                self.assertTrue(sw.create_sketch('Top',exact_geometry=True)['success'])
                self.assertTrue(sw.draw_rectangle(x1,y1,x2,y2,'mm')['success'])
                self.assertTrue(sw.extrude_sketch(10,unit='mm')['success'])
            self.assertTrue(sw.save_document(str(source))['success'])
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            solids=com(doc,'GetBodies2',0,True)
            expected=[com(b,'GetMassProperties',0)[3]*1e9 for b in solids]
            self.assertEqual([4000,12000,50000],sorted(round(x) for x in expected))
            paths=[str(root/'BODY_B.SLDPRT'),str(root/'BODY_A.SLDPRT')]
            result=save_bodies(sw,[2,0],paths,str(root/'ASSEMBLY.SLDASM'))
            self.assertTrue(result['success'],result)
            self.assertEqual([round(expected[2]),round(expected[0])],[round(p['volume_mm3']) for p in result['data']['parts']])
            self.assertEqual(before!=hashlib.sha256(source.read_bytes()).hexdigest(),result['data']['source_file_changed'])
            self.assertTrue(sw.save_document(str(source))['success'])
            app.CloseDoc(com(doc,'GetTitle'));doc=None
            self.assertTrue(sw.open_document(str(source))['success']);doc=com(app,'ActiveDoc')
            self.assertEqual(3,len(com(doc,'GetBodies2',0,False)))
            self.assertIsNotNone(com(doc,'FeatureByName',result['data']['feature_name']))
            self.assertTrue(com(doc,'EditRebuild3'))
            disk_hashes={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
            dirty=com(doc,'GetSaveFlag')
            rejected=save_bodies(sw,[1,0],paths,str(root/'ASSEMBLY.SLDASM'))
            self.assertFalse(rejected['success'])
            self.assertEqual(dirty,com(doc,'GetSaveFlag'))
            self.assertEqual(disk_hashes,{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths})
        finally:
            if doc is not None and Path(com(doc,'GetPathName')).resolve()==source:
                app.CloseDoc(com(doc,'GetTitle'))
            if previous_path:
                existing=com(app,'GetOpenDocumentByName',previous_path)
                if existing is not None:
                    error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
                    app.ActivateDoc3(com(existing,'GetTitle'),False,0,error)
                    self.assertEqual(0,error.value)

if __name__=='__main__':unittest.main()
