"""Own library-profile weldment: membership, hidden solids, read invariants and Save Bodies."""
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
from solidworks_mcp.tools.cutlist import get_cut_list
from solidworks_mcp.tools.cutlist_bodies import get_cut_list_body_map
from solidworks_mcp.tools.save_bodies import save_bodies
from solidworks_mcp.tools.weldments import create_structural_member,list_weldment_profiles


@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS')=='1','Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveCutListBodyMapTests(unittest.TestCase):
    def test_membership_hidden_body_read_invariants_reopen_and_save_bodies(self):
        root=Path(__file__).resolve().parents[3]/'output/cut-list-body-map-20261018-R01'/('live-'+uuid4().hex[:8])
        root.mkdir(parents=True);source=root/'SOURCE.SLDPRT'
        sw=SolidWorksAutomation();self.assertTrue(sw.connect()['success']);sw._path_policy=PathPolicy([root])
        app=sw.app;previous=com(app,'ActiveDoc');previous_path=com(previous,'GetPathName') if previous is not None else ''
        doc=None;records={}
        try:
            self.assertTrue(sw.create_new_part()['success']);doc=com(app,'ActiveDoc')
            profiles=list_weldment_profiles(sw,filter='50x50');self.assertTrue(profiles['success'],profiles)
            profile=next(p['path'] for p in profiles['data']['profiles'] if p['folder'].casefold().startswith('custom'))
            profile_hash=hashlib.sha256(Path(profile).read_bytes()).hexdigest()
            self.assertTrue(sw.create_sketch('Front',exact_geometry=True)['success'])
            for x,y,length in [(0,0,250),(0,150,250),(0,300,400)]:
                self.assertTrue(sw.draw_line(x,y,x+length,y,'mm')['success'])
            com(doc,'InsertSketch2',True)
            self.assertTrue(create_structural_member(sw,'Sketch1',profile,separate_groups=True)['success'])
            self.assertTrue(get_cut_list(sw)['success'])
            self.assertTrue(sw.save_document(str(source))['success'])
            def state():
                return dict(stamp=com(doc,'GetUpdateStamp'),dirty=com(doc,'GetSaveFlag'),
                    configuration=com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name'),
                    selection_count=com(com(doc,'SelectionManager'),'GetSelectedObjectCount2',-1),
                    sha=hashlib.sha256(source.read_bytes()).hexdigest(),
                    volumes_mm3=sorted(round(com(b,'GetMassProperties',0.)[3]*1e9,6) for b in com(doc,'GetBodies2',0,False)))
            before=state();r=get_cut_list_body_map(sw);self.assertTrue(r['success'],r);d=r['data']
            self.assertEqual(before,state());self.assertTrue(d['mapping_complete'],d)
            self.assertEqual([1,2],sorted(x['body_count'] for x in d['items']))
            pair=next(x for x in d['items'] if x['body_count']==2)
            long=next(x for x in d['items'] if x['body_count']==1)
            self.assertEqual('250',pair['properties']['LENGTH']['evaluated'])
            self.assertEqual('400',long['properties']['LENGTH']['evaluated'])
            solids=com(doc,'GetBodies2',0,True)
            for item in d['items']:
                for row in item['bodies']:
                    self.assertEqual(row['name'],com(solids[row['body_index']],'Name'))
                    self.assertAlmostEqual(row['volume_mm3'],com(solids[row['body_index']],'GetMassProperties',0.)[3]*1e9,delta=1e-5)
            records['normal']=d
            # Visibility changes the indices consumed by Save Bodies. Hidden
            # members remain in the cut-list map with a null visible index.
            hidden=com(doc,'GetBodies2',0,False)[1];hidden_name=com(hidden,'Name')
            com(hidden,'HideBody',True);hidden_before=state()
            h=get_cut_list_body_map(sw);self.assertTrue(h['success'],h);self.assertEqual(hidden_before,state())
            self.assertTrue(h['data']['mapping_complete'],h)
            row=next(b for f in h['data']['items'] for b in f['bodies'] if b['name']==hidden_name)
            self.assertFalse(row['visible']);self.assertIsNone(row['body_index']);self.assertIsNotNone(row['solid_body_index'])
            self.assertEqual(2,h['data']['visible_body_count']);records['hidden']=h['data']
            com(hidden,'HideBody',False);self.assertTrue(sw.save_document(str(source))['success'])
            app.CloseDoc(com(doc,'GetTitle'));doc=None
            self.assertTrue(sw.open_document(str(source))['success']);doc=com(app,'ActiveDoc')
            before=state();r=get_cut_list_body_map(sw);self.assertTrue(r['data']['mapping_complete'],r)
            self.assertEqual(before,state());records['reopened']=r['data']
            chosen=[next(f for f in r['data']['items'] if f['body_count']==n)['bodies'][0] for n in (1,2)]
            result=save_bodies(sw,[b['body_index'] for b in chosen],
                [str(root/'LONG.SLDPRT'),str(root/'SHORT.SLDPRT')],str(root/'SELECTED.SLDASM'))
            self.assertTrue(result['success'],result)
            self.assertEqual(2,len(result['data']['parts']))
            for body,part in zip(chosen,result['data']['parts']):self.assertAlmostEqual(body['volume_mm3'],part['volume_mm3'],delta=1e-5)
            self.assertEqual(3,len(com(doc,'GetBodies2',0,False)))
            after_export=get_cut_list_body_map(sw,include_properties=False)
            self.assertTrue(after_export['success'],after_export)
            self.assertTrue(after_export['data']['mapping_complete'],after_export)
            self.assertEqual([1,2],sorted(f['body_count'] for f in after_export['data']['items']))
            records['after_save_bodies']=after_export['data']
            self.assertEqual(profile_hash,hashlib.sha256(Path(profile).read_bytes()).hexdigest())
            records['save_bodies']=result['data'];records['read_invariants']=before
            (root/'measurements.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        finally:
            if doc is not None:app.CloseDoc(com(doc,'GetTitle'))
            if previous_path and com(app,'GetOpenDocumentByName',previous_path) is not None:
                error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0);app.ActivateDoc3(com(previous,'GetTitle'),False,0,error)

if __name__=='__main__':unittest.main()
