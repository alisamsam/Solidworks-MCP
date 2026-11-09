"""Current native body identity, visible Save Bodies indices and honest partial reads."""
from types import SimpleNamespace
import json
import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for,registered_tools
from solidworks_mcp.tools.cutlist_bodies import get_cut_list_body_map


class Body:
    def __init__(self,key,name=None,volume=1e-6):self.key=key;self.Name=name or key;self.volume=volume
    def GetMassProperties(self,density):return [0.,0.,0.,self.volume]
    def GetBodyBox(self):return [0.,0.,0.,.01,.01,.01]

class Properties:
    def __init__(self):self.calls=[];self.resolved=True
    def GetNames(self):return ['LENGTH','QUANTITY']
    def Get5(self,name,cached,raw,value,resolved):
        self.calls.append(cached);raw.value='"SW-Length"' if name=='LENGTH' else '2'
        value.value='250,00' if name=='LENGTH' else '2';resolved.value=self.resolved;return 2

class Folder:
    def __init__(self,members):self.members=members;self.count=len(members)
    def GetBodyCount(self):return self.count
    def GetBodies(self):return self.members
    def UpdateCutList(self):raise AssertionError('read must not update cut list')

class Feature:
    def __init__(self,name,members,key=None):
        self.Name=name;self.key=key or name;self.folder=Folder(members);self.CustomPropertyManager=Properties()
    def GetTypeName2(self):return 'CutListFolder'
    def GetSpecificFeature2(self):return self.folder

class Manager:
    def __init__(self,features):self.features=features
    def GetFeatures(self,top_only):
        if top_only:raise AssertionError('must include nested cut-list features')
        return self.features

class Doc:
    def __init__(self):
        self.solids=[Body('long'),Body('equal2'),Body('equal1')]
        self.visible=list(self.solids)
        self.features=[Feature('Pair',[Body('equal1'),Body('equal2')]),Feature('Long',[Body('long')])]
        self.FeatureManager=Manager(self.features);self.stamp=10
        self.ConfigurationManager=SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name='As Welded'))
    def GetType(self):return 1
    def GetPathName(self):return 'C:/approved/own.SLDPRT'
    def GetBodies2(self,kind,visible):return self.visible if visible else self.solids
    def GetUnits(self):return (0,1,8,2,0)
    def GetUpdateStamp(self):return self.stamp

class App:
    def IsSame(self,a,b):return 1 if a.key==b.key else 0

class Automation:
    def __init__(self):self.doc=Doc();self.app=App()
    def get_active_doc(self):return self.doc,None
    def _result(self,success,message,error_code=None,data=None):return dict(success=success,message=message,data=data,error_code=error_code)


class BodyMapTests(unittest.TestCase):
    def setUp(self):self.sw=Automation();self.doc=self.sw.doc
    def call(self,**kw):return get_cut_list_body_map(self.sw,**kw)
    def test_maps_actual_identity_with_different_wrapper_and_native_order(self):
        r=self.call();self.assertTrue(r['success'],r);d=r['data'];self.assertTrue(d['mapping_complete'])
        pair=next(x for x in d['items'] if x['folder']=='Pair')
        self.assertEqual(2,pair['body_count']);self.assertEqual([2,1],[b['body_index'] for b in pair['bodies']])
        self.assertEqual([1000.,1000.],[b['volume_mm3'] for b in pair['bodies']])
        self.assertFalse(d['unassigned_bodies']);self.assertEqual('As Welded',d['configuration'])
    def test_hidden_body_has_no_visible_save_bodies_index(self):
        self.doc.visible=[self.doc.solids[2],self.doc.solids[0]]
        d=self.call()['data'];pair=next(x for x in d['items'] if x['folder']=='Pair')
        self.assertTrue(d['mapping_complete']);self.assertEqual([0,None],[b['body_index'] for b in pair['bodies']])
        self.assertEqual([2,1],[b['solid_body_index'] for b in pair['bodies']])
        self.assertEqual([True,False],[b['visible'] for b in pair['bodies']])
    def test_same_name_is_not_same_body(self):
        self.doc.features[0].folder.members[0]=Body('foreign',name='equal1')
        d=self.call()['data'];self.assertFalse(d['mapping_complete']);self.assertTrue(d['unassigned_bodies'])
        self.assertIsNone(d['items'][0]['bodies'][0]['body_index'])
    def test_same_name_native_bodies_disambiguated_by_identity(self):
        for b in self.doc.solids:b.Name='same'
        for f in self.doc.features:
            for b in f.folder.members:b.Name='same'
        self.assertTrue(self.call()['data']['mapping_complete'])
    def test_unmatched_visible_entry_makes_snapshot_incomplete(self):
        self.doc.visible.append(Body('foreign'))
        d=self.call()['data'];self.assertFalse(d['mapping_complete'])
        self.assertTrue(any(w['code']=='VISIBLE_BODY_SET_MISMATCH' for w in d['warnings']))
    def test_names_only_order_candidates_identity_can_match_other_name(self):
        # Native wrappers can expose names different from the earlier snapshot.
        self.doc.visible=[Body('long'),Body('equal2',name='equal1'),Body('equal1',name='equal2')]
        d=self.call()['data'];self.assertTrue(d['mapping_complete'],d)
        pair=next(f for f in d['items'] if f['folder']=='Pair')
        self.assertEqual([2,1],[b['body_index'] for b in pair['bodies']])
        self.assertTrue(all(b['visible'] for b in pair['bodies']))
    def test_properties_cached_raw_and_evaluated_without_assuming_mm_or_locale(self):
        d=self.call()['data'];p=d['items'][0]['properties']['LENGTH']
        self.assertEqual('250,00',p['evaluated']);self.assertEqual('"SW-Length"',p['raw'])
        self.assertTrue(p['was_resolved']);self.assertEqual('not_verified',d['properties_freshness'])
        self.assertNotIn('length_mm',d['items'][0]);self.assertEqual(0,d['document_length_unit_code'])
        self.assertTrue(all(self.doc.features[0].CustomPropertyManager.calls))
    def test_properties_can_be_omitted(self):
        d=self.call(include_properties=False)['data'];self.assertNotIn('properties',d['items'][0])
        self.assertFalse(self.doc.features[0].CustomPropertyManager.calls)
    def test_bad_boolean_and_nonpart_rejected(self):
        self.assertFalse(self.call(include_properties=1)['success'])
        self.doc.GetType=lambda:2;self.assertFalse(self.call()['success'])
    def test_empty_cut_list_reports_unassigned_without_refresh(self):
        self.doc.features.clear();d=self.call()['data'];self.assertFalse(d['mapping_complete']);self.assertEqual(3,len(d['unassigned_bodies']))
    def test_empty_folder_does_not_create_a_phantom_item(self):
        self.doc.features.append(Feature('Empty',[]));self.assertEqual(2,len(self.call()['data']['items']))
    def test_duplicate_tree_occurrence_not_duplicate_quantity(self):
        self.doc.features.append(self.doc.features[0]);d=self.call()['data']
        self.assertEqual(2,len(d['items']));self.assertTrue(d['mapping_complete'])
    def test_two_distinct_folders_claiming_same_body_are_partial(self):
        self.doc.features.append(Feature('Other',[Body('long')]))
        d=self.call()['data'];self.assertFalse(d['mapping_complete']);self.assertTrue(any(x['code']=='DUPLICATE_MEMBERSHIP' for x in d['warnings']))
    def test_native_count_mismatch_is_partial(self):
        self.doc.features[0].folder.count=3;self.assertFalse(self.call()['data']['mapping_complete'])
    def test_identity_failure_never_guesses(self):
        self.sw.app.IsSame=lambda a,b:-1
        d=self.call()['data'];self.assertFalse(d['mapping_complete'])
        self.assertTrue(all(b['body_index'] is None for f in d['items'] for b in f['bodies']))
    def test_folder_read_failure_not_silently_omitted(self):
        def broken():raise RuntimeError('native read error')
        self.doc.features[0].folder.GetBodies=broken
        d=self.call()['data'];self.assertFalse(d['mapping_complete']);self.assertTrue(d['warnings'])
    def test_nonfinite_geometry_is_json_safe_and_reported(self):
        self.doc.solids[0].volume=float('nan');d=self.call()['data']
        self.assertFalse(d['mapping_complete']);json.dumps(d,allow_nan=False)
    def test_unresolved_property_not_labeled_fresh(self):
        self.doc.features[0].CustomPropertyManager.resolved=False
        d=self.call()['data'];self.assertFalse(d['items'][0]['properties']['LENGTH']['was_resolved'])
        self.assertEqual('not_verified',d['properties_freshness'])
    def test_registry_read_only(self):
        self.assertIn('get_cut_list_body_map',{t.name for t in registered_tools()})
        self.assertEqual(OperationClass.READ,operation_class_for('get_cut_list_body_map'))

if __name__=='__main__':unittest.main()
