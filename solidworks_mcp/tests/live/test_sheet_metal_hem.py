"""Real native hems: two lengths/gaps, both directions, folded/flat/reopened."""
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
from solidworks_mcp.tools.inspection import list_body_edges
from solidworks_mcp.tools.sheetmetal import create_sheet_metal_base_flange, flatten_sheet_metal
from solidworks_mcp.tools.sheetmetal_hem import create_sheet_metal_hem


@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS')=='1','Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveHemTests(unittest.TestCase):
    def test_open_closed_fold_flat_and_reopen(self):
        root=Path(__file__).resolve().parents[3]/'output/sheet-metal-hem-20261018-R01'/('live-'+uuid4().hex[:8])
        root.mkdir(parents=True)
        sw=SolidWorksAutomation();self.assertTrue(sw.connect()['success']);sw._path_policy=PathPolicy([root])
        app=sw.app;previous=com(app,'ActiveDoc');previous_path=com(previous,'GetPathName') if previous is not None else ''
        rows=[];doc=None
        try:
            for kind,length,gap,reverse in [('open',10,1,False),('open',15,2,True),('closed',10,None,False),('closed',15,None,True)]:
                path=root/f'{kind}_{length}.SLDPRT'
                self.assertTrue(sw.create_new_part()['success']);doc=com(app,'ActiveDoc')
                self.assertTrue(sw.create_sketch('Front',exact_geometry=True)['success'])
                self.assertTrue(sw.draw_rectangle(0,0,100,50,'mm')['success'])
                self.assertTrue(create_sheet_metal_base_flange(sw,1,bend_radius_mm=1)['success'])
                self.assertTrue(sw.save_document(str(path))['success'])
                def geometry():
                    bodies=com(doc,'GetBodies2',0,False);self.assertEqual(1,len(bodies))
                    b=bodies[0];box=com(b,'GetBodyBox')
                    return dict(volume_mm3=com(b,'GetMassProperties',0.)[3]*1e9,
                                extents_mm=[(box[i+3]-box[i])*1000 for i in range(3)],faces=len(com(b,'GetFaces')))
                base=geometry();self.assertAlmostEqual(5000.,base['volume_mm3'],delta=1e-5)
                listed=list_body_edges(sw);self.assertTrue(listed['success'])
                edge=max(listed['data']['edges'],key=lambda r:r['length_mm'] or 0)['index']
                result=create_sheet_metal_hem(sw,edge,length,hem_type=kind,gap_mm=gap,reverse=reverse)
                self.assertTrue(result['success'],result);folded=geometry()
                # Hem wraps 180 deg: its total thickness-direction extent is 2t+gap.
                native_gap=result['data']['native_gap_mm']
                if kind=='closed':self.assertAlmostEqual(.1,native_gap,delta=1e-6)
                self.assertAlmostEqual(2+native_gap,folded['extents_mm'][0],delta=.001)
                self.assertAlmostEqual(100.,folded['extents_mm'][1],delta=.001)
                self.assertEqual(14,folded['faces'])
                # Verify real cylindrical bend radii, not just the feature label.
                radii=[]
                for face in com(com(doc,'GetBodies2',0,False)[0],'GetFaces'):
                    surface=com(face,'GetSurface')
                    if com(surface,'IsCylinder'):radii.append(com(surface,'CylinderParams')[6]*1000)
                for radius in (native_gap/2,native_gap/2+1):
                    self.assertTrue(any(abs(r-radius)<1e-6 for r in radii),(radius,radii))
                # 1-mm sheet, 180-degree turn, neutral radius g/2+t/2;
                # inside-position length is measured from the original sheet edge.
                developed=50.+length+math.pi*(native_gap+1)/2-(native_gap/2+1)
                self.assertAlmostEqual(100*developed,folded['volume_mm3'],delta=.001)
                self.assertTrue(flatten_sheet_metal(sw,True)['success']);flat=geometry()
                self.assertAlmostEqual(1.,min(flat['extents_mm']),delta=.001)
                self.assertAlmostEqual(100.,flat['extents_mm'][1],delta=.001)
                self.assertAlmostEqual(developed,flat['extents_mm'][2],delta=.001)
                self.assertAlmostEqual(100*developed,flat['volume_mm3'],delta=.001)
                self.assertEqual(6,flat['faces'])
                self.assertTrue(flatten_sheet_metal(sw,False)['success']);restored=geometry()
                self.assertAlmostEqual(folded['volume_mm3'],restored['volume_mm3'],delta=1e-5)
                for a,b in zip(folded['extents_mm'],restored['extents_mm']):self.assertAlmostEqual(a,b,delta=.001)
                self.assertTrue(sw.save_document(str(path))['success']);app.CloseDoc(com(doc,'GetTitle'));doc=None
                self.assertTrue(sw.open_document(str(path))['success']);doc=com(app,'ActiveDoc')
                self.assertAlmostEqual(folded['volume_mm3'],geometry()['volume_mm3'],delta=1e-5)
                feature=com(doc,'FeatureByName',result['data']['feature']);definition=com(feature,'GetDefinition')
                self.assertEqual(0 if kind=='open' else 1,com(definition,'Type'))
                self.assertEqual(1,com(definition,'BendPosition'));self.assertEqual(reverse,com(definition,'ReverseDirection'))
                self.assertAlmostEqual(length,com(definition,'Length')*1000,delta=1e-6)
                if gap is not None:self.assertAlmostEqual(gap,com(definition,'GapDistance')*1000,delta=1e-6)
                warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
                self.assertEqual(0,com(feature,'GetErrorCode2',warning));self.assertFalse(warning.value)
                rows.append(dict(kind=kind,length_mm=length,gap_mm=gap,reverse=reverse,folded=folded,flat=flat,result=result['data']))
                (root/'measurements.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
                app.CloseDoc(com(doc,'GetTitle'));doc=None
        finally:
            if doc is not None:app.CloseDoc(com(doc,'GetTitle'))
            if previous_path and com(app,'GetOpenDocumentByName',previous_path) is not None:
                error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0);app.ActivateDoc3(com(previous,'GetTitle'),False,0,error)

if __name__=='__main__':unittest.main()
