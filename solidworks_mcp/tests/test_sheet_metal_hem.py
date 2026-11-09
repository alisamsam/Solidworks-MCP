"""Hem input, native readback, geometry and safe failure contracts."""
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from solidworks_mcp.core.policy import OperationClass, PathPolicy
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools import sheetmetal_hem as module


class Feature:
    Name='Hem1'
    def __init__(self):
        self.definition=SimpleNamespace(Type=0,BendPosition=1,ReverseDirection=False,
            Length=.01,GapDistance=.001,MiterGap=.001)
        self.error=0;self.warning=False
    def GetTypeName2(self):return 'Hem'
    def GetDefinition(self):return self.definition
    def GetErrorCode2(self,warning):warning.value=self.warning;return self.error

class Edge:
    def Select4(self,append,data):return True

class Manager:
    def __init__(self,doc):self.doc=doc;self.calls=[]
    def InsertSheetMetalHem2(self,*args):
        self.calls.append(args);self.doc.modified=True
        d=self.doc.feature.definition
        d.Type=args[0];d.ReverseDirection=args[2]
        d.Length=args[3];d.GapDistance=args[4] if args[0]==0 else .0001
        if self.doc.mismatch:d.Length=.5
        return self.doc.feature if self.doc.created else None

class Document:
    def __init__(self):
        self.feature=Feature();self.FeatureManager=Manager(self);self.modified=False
        self.created=True;self.persist=True;self.rebuilt=True;self.mismatch=False;self.clears=0
        self.all_bodies=[object()]
    def GetType(self):return 1
    def GetPathName(self):return str(Path('output/hem-unit.SLDPRT').resolve())
    def GetActiveSketch2(self):return None
    def GetBodies2(self,kind,visible_only):return self.all_bodies
    def ClearSelection2(self,value):self.clears+=1
    def EditRebuild3(self):return self.rebuilt
    def FeatureByName(self,name):return self.feature if self.persist else None

class Automation:
    def __init__(self,doc):self.doc=doc
    def get_active_doc(self):return self.doc,None
    def _result(self,success,message,error_code=None,data=None):
        return dict(success=success,message=message,data=data,error_code=error_code)


class HemTests(unittest.TestCase):
    def setUp(self):
        self.doc=Document();self.sw=Automation(self.doc)
        self.sheet=SimpleNamespace(Thickness=.001)
        class SM:
            def GetDefinition(inner):return self.sheet
        self.before=[dict(volume_mm3=5000.,faces=6)]
        self.after=[dict(volume_mm3=6164.159265,faces=14)]
        self.edges=[dict(edge=Edge(),is_line=True,body='Sheet',length_mm=100.)]
        for name,value in [('_find_sheet_metal_feature',SM()),('_find_flat_pattern_feature',None),
                           ('part_edges',self.edges)]:
            patcher=patch.object(module,name,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(module,'_body_volumes',side_effect=lambda doc:self.after if doc.modified else self.before)
        patcher.start();self.addCleanup(patcher.stop)
    def call(self,**kw):return module.create_sheet_metal_hem(self.sw,0,10.,**kw)
    def test_open_native_arguments_and_verified_parameters(self):
        r=self.call();self.assertTrue(r['success'],r)
        args=self.doc.FeatureManager.calls[0]
        self.assertEqual((0,1,False,.01,.001),args[:5]);self.assertEqual(16,len(args))
        self.assertTrue(args[9]);self.assertEqual(1.,r['data']['gap_mm'])
        self.assertAlmostEqual(1164.159265,r['data']['gained_mm3']);self.assertGreaterEqual(self.doc.clears,2)
    def test_closed_reports_native_gap_instead_of_claiming_zero(self):
        r=self.call(hem_type='closed',reverse=True)
        self.assertTrue(r['success'],r);self.assertEqual(.1,r['data']['native_gap_mm'])
        self.assertIsNone(r['data']['gap_mm']);self.assertTrue(r['data']['reverse'])
    def test_input_rejected_before_document_access(self):
        for options in [dict(length_mm=math.nan),dict(length_mm=math.inf),dict(length_mm=True),
                        dict(length_mm=0),dict(edge_index=True),dict(edge_index=-1),dict(edge_index=1.5),
                        dict(hem_type='rolled'),dict(gap_mm=0),dict(gap_mm=math.inf),dict(gap_mm=True),
                        dict(hem_type='closed',gap_mm=1),dict(reverse=1),dict(miter_gap_mm=-1),
                        dict(miter_gap_mm=math.nan)]:
            with self.subTest(options=options):
                args=dict(edge_index=0,length_mm=10);args.update(options)
                r=module.create_sheet_metal_hem(self.sw,**args);self.assertFalse(r['success'],r)
        self.assertFalse(self.doc.FeatureManager.calls)
    def test_protected_path_denied_before_native_creation(self):
        self.sw._path_policy=PathPolicy([Path('output/elsewhere')])
        self.assertFalse(self.call()['success']);self.assertFalse(self.doc.FeatureManager.calls)
    def test_missing_sheet_metal_rejected(self):
        with patch.object(module,'_find_sheet_metal_feature',return_value=None):self.assertFalse(self.call()['success'])
        self.assertFalse(self.doc.FeatureManager.calls)
    def test_active_sketch_rejected(self):
        with patch.object(self.doc,'GetActiveSketch2',return_value=object()):self.assertFalse(self.call()['success'])
        self.assertFalse(self.doc.FeatureManager.calls)
    def test_flattened_sheet_rejected(self):
        class Flat:
            def IsSuppressed(self):return False
        with patch.object(module,'_find_flat_pattern_feature',return_value=Flat()):self.assertFalse(self.call()['success'])
        self.assertFalse(self.doc.FeatureManager.calls)
    def test_nonpart_and_multibody_rejected(self):
        with patch.object(self.doc,'GetType',return_value=2):self.assertFalse(self.call()['success'])
        self.before*=2;self.assertFalse(self.call()['success']);self.assertFalse(self.doc.FeatureManager.calls)
    def test_bad_edge_rejected(self):
        self.assertFalse(module.create_sheet_metal_hem(self.sw,8,10)['success'])
        self.edges[0]['is_line']=False;self.assertFalse(self.call()['success'])
        self.assertFalse(self.doc.FeatureManager.calls)
    def test_hidden_second_solid_rejected(self):
        self.doc.all_bodies.append(object())
        self.assertFalse(self.call()['success']);self.assertFalse(self.doc.FeatureManager.calls)
    def test_null_native_result_not_success(self):
        self.doc.created=False;r=self.call();self.assertFalse(r['success']);self.assertTrue(r['data']['document_may_be_modified'])
    def test_missing_persistence_rebuild_and_feature_error_not_success(self):
        for attr,value in [('persist',False),('rebuilt',False)]:
            with self.subTest(attr=attr):
                setattr(self.doc,attr,value);r=self.call();self.assertFalse(r['success']);setattr(self.doc,attr,True)
        self.doc.feature.error=5;self.assertFalse(self.call()['success'])
        self.doc.feature.error=0;self.doc.feature.warning=True;self.assertFalse(self.call()['success'])
    def test_native_parameter_mismatch_not_success(self):
        self.doc.mismatch=True;r=self.call();self.assertFalse(r['success']);self.assertTrue(r['data']['document_may_be_modified'])
    def test_no_material_or_face_change_not_success(self):
        for value in [[dict(volume_mm3=5000.,faces=14)],[dict(volume_mm3=6000.,faces=6)],self.after*2]:
            self.after=value;self.assertFalse(self.call()['success'])
    def test_registry_is_mutating(self):
        self.assertIn('create_sheet_metal_hem',{t.name for t in registered_tools()})
        self.assertEqual(OperationClass.MUTATE,operation_class_for('create_sheet_metal_hem'))

if __name__=='__main__':unittest.main()
