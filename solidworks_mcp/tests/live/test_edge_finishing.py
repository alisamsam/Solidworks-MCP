"""One scratch part: three independent corner operations and saved readback."""
import math
import os
from pathlib import Path
import unittest
from uuid import uuid4

import pythoncom
import win32com.client
from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.inspection import part_edges


@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS')=='1','Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveEdgeFinishingTests(unittest.TestCase):
    def test_corner_operations_and_saved_geometry(self):
        root=Path(__file__).resolve().parents[3]/'output/edge-finishing-20261018-R01'
        root.mkdir(parents=True,exist_ok=True)
        target=root/f'LIVE_EDGE_{uuid4().hex[:8]}.SLDPRT'
        sw=SolidWorksAutomation()
        self.assertTrue(sw.connect()['success'])
        sw._path_policy=PathPolicy([root])
        app=win32com.client.dynamic.Dispatch(sw.app)
        previous=com(app,'ActiveDoc')
        previous_path=com(previous,'GetPathName') if previous is not None else None
        doc=None
        try:
            self.assertTrue(sw.create_new_part()['success'])
            doc=com(app,'ActiveDoc')
            self.assertTrue(sw.create_sketch('Top',exact_geometry=True)['success'])
            self.assertTrue(sw.draw_rectangle(0,0,100,50,'mm')['success'])
            self.assertTrue(sw.extrude_sketch(40,unit='mm')['success'])
            def volume():return com(com(com(doc,'Extension'),'CreateMassProperty'),'Volume')*1e9
            def key(row):return tuple(sorted((tuple(row['start_mm']),tuple(row['end_mm']))))
            corners=[key(e) for e in part_edges(doc) if e['is_line'] and abs(e['length_mm']-40)<1e-6]
            self.assertEqual(4,len(corners))
            def index(corner):return next(e['index'] for e in part_edges(doc) if key(e)==corner)
            self.assertAlmostEqual(200000.,volume(),places=5)
            result=sw.chamfer_edges(3,unit='mm',chamfer_type='distance_distance',distance2=5,
                edge_indices=[index(corners[0])],tangent_propagation=False,flip_direction=True)
            self.assertTrue(result['success'],result)
            self.assertAlmostEqual(199700.,volume(),places=5)
            # Product alone is insufficient: read the two actual setbacks.
            point=corners[0][0]
            distances={round(math.dist(point,p),4) for e in part_edges(doc)
                       for p in (e['start_mm'],e['end_mm'])}
            self.assertIn(3.,distances);self.assertIn(5.,distances)
            result=sw.chamfer_edges(2,45,'mm',edge_indices=[index(corners[1])])
            self.assertTrue(result['success'],result)
            self.assertAlmostEqual(199620.,volume(),places=5)
            result=sw.fillet_edges(2,'mm',edge_indices=[index(corners[2])],tangent_propagation=False)
            self.assertTrue(result['success'],result)
            expected=199620.-(4.-math.pi)*40.
            self.assertAlmostEqual(expected,volume(),places=5)
            self.assertTrue(sw.save_document(str(target))['success'])
            app.CloseDoc(com(doc,'GetTitle'))
            doc=None
            self.assertTrue(sw.open_document(str(target))['success'])
            doc=com(app,'ActiveDoc')
            self.assertEqual(target.resolve(),Path(com(doc,'GetPathName')).resolve())
            self.assertAlmostEqual(expected,volume(),places=5)
            for name in ('Chamfer1','Chamfer2','Fillet1'):
                self.assertIsNotNone(com(doc,'FeatureByName',name),name)
        finally:
            # Only the specific document created by this test is closed.
            if doc is not None:
                path=com(doc,'GetPathName')
                if not path or Path(path).resolve()==target.resolve():
                    app.CloseDoc(com(doc,'GetTitle'))
            if previous is not None and previous_path:
                existing=app.GetOpenDocumentByName(previous_path)
                if existing is not None:
                    error=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
                    app.ActivateDoc3(com(existing,'GetTitle'),False,0,error)
                    self.assertEqual(0,error.value)


if __name__=='__main__':unittest.main()
