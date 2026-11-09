"""Per-body sheet parameters come from native body feature membership, never names/order."""
import json
from types import SimpleNamespace
import unittest
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for,registered_tools
from solidworks_mcp.tools.sheetmetal_bodies import list_sheet_metal_bodies


class Feature:
    def __init__(self,key,kind='SheetMetal',thickness=1):
        self.key=key;self.Name=key;self.kind=kind;self.suppressed=kind=='FlatPattern';self.error=0
        self.definition=SimpleNamespace(Thickness=thickness/1000,BendRadius=.002,KFactor=.5,BendAllowanceType=2)
    def GetTypeName2(self):return self.kind
    def GetDefinition(self):return self.definition
    def IsSuppressed(self):return self.suppressed
    def GetErrorCode2(self,w):w.value=False;return self.error

class Body:
    def __init__(self,key,thickness):
        self.key=key;self.Name=key;self.sheet=True;self.fail=False
        self.features=[Feature('Sheet-'+key,thickness=thickness),Feature('Flat-'+key,'FlatPattern')]
    def IsSheetMetal(self):return self.sheet
    def GetFeatures(self):
        if self.fail:raise RuntimeError('read failed')
        return self.features

class Doc:
    def __init__(self):
        self.solids=[Body('C',3),Body('A',1),Body('B',2)];self.visible=list(self.solids);self.stamp=7;self.stamps=None;self.document_type=1
        self.ConfigurationManager=SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name='Default'))
    def GetType(self):return self.document_type
    def GetBodies2(self,kind,visible):return self.visible if visible else self.solids
    def GetUpdateStamp(self):return self.stamps.pop(0) if self.stamps is not None else self.stamp
    def GetPathName(self):return 'C:/own/sheets.SLDPRT'

class App:
    result=None
    def IsSame(self,a,b):return self.result if self.result is not None else (1 if a.key==b.key else 0)

class Automation:
    def __init__(self):self.doc=Doc();self.app=App()
    def get_active_doc(self):return self.doc,None
    def _result(self,success,message,error_code=None,data=None):return dict(success=success,message=message,data=data,error_code=error_code)


class SheetBodyInfoTests(unittest.TestCase):
    def setUp(self):self.sw=Automation();self.doc=self.sw.doc
    def call(self):return list_sheet_metal_bodies(self.sw)
    def test_three_independent_definitions_in_native_body_order(self):
        r=self.call();self.assertTrue(r['success'],r);d=r['data'];self.assertTrue(d['complete'],d)
        self.assertEqual([3,1,2],[b['parameters']['thickness_mm'] for b in d['bodies']])
        self.assertEqual(['Sheet-C','Sheet-A','Sheet-B'],[b['sheet_metal_feature'] for b in d['bodies']])
        self.assertEqual([0,1,2],[b['body_index'] for b in d['bodies']])
        self.assertTrue(all(b['flattened'] is False for b in d['bodies']))
    def test_hidden_body_keeps_parameters_without_export_index(self):
        self.doc.visible=[self.doc.solids[2],self.doc.solids[0]];d=self.call()['data']
        self.assertTrue(d['complete']);self.assertEqual([1,None,0],[b['body_index'] for b in d['bodies']])
        self.assertEqual([0,1,2],[b['solid_body_index'] for b in d['bodies']])
        self.assertFalse(d['bodies'][1]['visible']);self.assertEqual(1,d['bodies'][1]['parameters']['thickness_mm'])
    def test_unrelated_same_names_do_not_pick_first_definition(self):
        for body in self.doc.solids:
            body.Name='same';body.features[0].Name='same'
        d=self.call()['data'];self.assertTrue(d['complete']);self.assertEqual([3,1,2],[b['parameters']['thickness_mm'] for b in d['bodies']])
    def test_duplicate_native_feature_occurrence_is_deduplicated(self):
        self.doc.solids[0].features.append(self.doc.solids[0].features[0]);self.assertTrue(self.call()['data']['complete'])
    def test_two_distinct_sheet_definitions_are_ambiguous(self):
        self.doc.solids[0].features.append(Feature('Other',thickness=9));d=self.call()['data']
        self.assertFalse(d['complete']);self.assertIsNone(d['bodies'][0]['parameters'])
    def test_missing_definition_not_guessed(self):
        self.doc.solids[0].features=[self.doc.solids[0].features[1]]
        d=self.call()['data'];self.assertFalse(d['complete']);self.assertIsNone(d['bodies'][0]['parameters'])
    def test_ordinary_solid_is_reported_separately(self):
        self.doc.solids[0].sheet=False;d=self.call()['data'];self.assertTrue(d['complete'])
        self.assertEqual(2,d['sheet_body_count']);self.assertEqual(1,len(d['non_sheet_bodies']))
    def test_no_sheet_bodies_is_valid_empty_read(self):
        for b in self.doc.solids:b.sheet=False
        d=self.call()['data'];self.assertTrue(d['complete']);self.assertEqual([],d['bodies'])
    def test_partial_parameter_failure_never_fabricates_zero_or_nan(self):
        for bad in [float('nan'),float('inf'),0,-1]:
            self.doc.solids[0].features[0].definition.Thickness=bad
            d=self.call()['data'];self.assertFalse(d['complete']);self.assertIsNone(d['bodies'][0]['parameters']);json.dumps(d,allow_nan=False)
    def test_all_installed_native_bend_types_and_inactive_k_factor(self):
        definition=self.doc.solids[0].features[0].definition
        for kind in (1,2,3,4,5):
            with self.subTest(kind=kind):
                definition.BendAllowanceType=kind;definition.KFactor=.5 if kind==2 else float('nan')
                d=self.call()['data'];self.assertTrue(d['complete'],d)
                p=d['bodies'][0]['parameters'];self.assertEqual(kind,p['bend_allowance_type'])
                self.assertEqual(kind==2,p['k_factor_is_active'])
                self.assertEqual(.5 if kind==2 else None,p['k_factor']);json.dumps(d,allow_nan=False)
    def test_unknown_native_bend_type_is_partial(self):
        self.doc.solids[0].features[0].definition.BendAllowanceType=0
        self.assertFalse(self.call()['data']['complete'])
    def test_flat_state_is_native_suppression_read(self):
        self.doc.solids[1].features[1].suppressed=False
        self.assertTrue(self.call()['data']['bodies'][1]['flattened'])
    def test_native_flat_pattern_error_is_not_a_complete_read(self):
        self.doc.solids[0].features[1].error=5
        self.assertFalse(self.call()['data']['complete'])
    def test_missing_or_multiple_flat_features_are_partial(self):
        self.doc.solids[0].features.pop();d=self.call()['data'];self.assertFalse(d['complete']);self.assertIsNone(d['bodies'][0]['flattened'])
    def test_body_feature_read_failure_is_partial(self):
        self.doc.solids[0].fail=True;self.assertFalse(self.call()['data']['complete'])
    def test_visible_native_set_mismatch_is_partial(self):
        self.doc.visible.append(Body('foreign',9));self.assertFalse(self.call()['data']['complete'])
    def test_identity_read_failure_is_partial(self):
        self.sw.app.result=-1;self.assertFalse(self.call()['data']['complete'])
    def test_nonpart_rejected(self):
        self.doc.document_type=2;self.assertFalse(self.call()['success'])
    def test_document_change_during_read_is_partial(self):
        self.doc.stamps=[7,8]
        self.assertFalse(self.call()['data']['complete'])
    def test_registered_read_only(self):
        self.assertIn('list_sheet_metal_bodies',{t.name for t in registered_tools()})
        self.assertEqual(OperationClass.READ,operation_class_for('list_sheet_metal_bodies'))

if __name__=='__main__':unittest.main()
