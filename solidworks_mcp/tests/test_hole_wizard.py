"""Hole Wizard modes must prove native dimensions, selection and removed material."""
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from solidworks_mcp.core.policy import OperationClass, PathPolicy
from solidworks_mcp.registry import operation_class_for
from solidworks_mcp.tests.test_advanced_features import Automation, Document
from solidworks_mcp.tools.advanced_features import hole_wizard

class HoleFeature:
    Name='Hole1'
    def __init__(self,doc):self.doc=doc
    def GetErrorCode2(self,warning):return self.doc.native_error
    def GetTypeName2(self):return 'HoleWzd'
    def GetDefinition(self):return self.doc.definition
    def ModifyDefinition(self,definition,doc,component):
        if self.doc.modify_fails:return False
        self.doc.modified_end=definition.EndCondition
        return True

class Definition:
    def __init__(self,args):
        self.Diameter=0.;self.Depth=0.;self.EndCondition=args[4]
        self.HoleDiameter=args[5] if args[4]==0 else 0.
        self.ThruHoleDiameter=args[5] if args[4]==1 else 0.
        self.HoleDepth=args[6] if args[4]==0 else 0.
        self.CounterBoreDiameter=args[8];self.CounterBoreDepth=args[9]
        self.CounterSinkDiameter=args[8];self.CounterSinkAngle=args[9]
        self.Standard2=args[1];self.FastenerType2=args[2]
        self.FastenerSize=args[3]
    def AccessSelections(self,doc,component):return True
    def ReleaseSelectionAccess(self):pass

class HoleManager:
    def __init__(self,doc):self.doc=doc;self.args=None
    def HoleWizard5(self,*args):
        self.args=args;self.doc.definition=Definition(args)
        if self.doc.wrong_diameter:self.doc.definition.HoleDiameter=.001;self.doc.definition.ThruHoleDiameter=.001
        if self.doc.wrong_size:self.doc.definition.FastenerSize='WRONG'
        return self.doc.feature

class HoleExtension:
    def __init__(self,doc):self.doc=doc;self.ray=None
    def SelectByRay(self,*args):self.ray=args;return True

class Selection:
    def __init__(self,doc):self.doc=doc
    def GetSelectedObject6(self,index,mark):return self.doc.face

class HoleDocument(Document):
    def __init__(self):
        super().__init__();self.face=HoleFace();self.feature=HoleFeature(self);self.FeatureManager=HoleManager(self)
        self.Extension=HoleExtension(self);self.SelectionManager=Selection(self)
        self.native_error=0;self.rebuild=True;self.wrong_diameter=False;self.modify_fails=False;self.wrong_size=False
    def GetPathName(self):return ''
    def FeatureByName(self,name):return self.feature
    def EditRebuild3(self):return self.rebuild

class HoleFace:
    Normal=(0,0,1)
    bad_closest=False
    def GetClosestPointOn(self,x,y,z):
        if self.bad_closest:return (float('nan'),y,z,0,0)
        return (min(max(x,0),.1),min(max(y,0),.1),.01,0,0)

class Equality:
    def __init__(self):self.same=True
    def IsSame(self,a,b):return 1 if self.same else 0

class HoleWizardTests(unittest.TestCase):
    def setUp(self):
        self.doc=HoleDocument();self.sw=Automation(self.doc);self.sw.app=Equality()
        self.face_patch=patch('solidworks_mcp.tools.advanced_features._get_planar_face_by_index',return_value=self.doc.face)
        self.face_patch.start();self.addCleanup(self.face_patch.stop)
    def run_hole(self,**kwargs):
        args=dict(face_index=0,point_mm=[5,6,10],diameter_mm=6,depth_mm=8)|kwargs
        with patch('solidworks_mcp.tools.advanced_features._solid_volume_mm3',side_effect=[10000,9700]):
            return hole_wizard(self.sw,**args)
    def test_straight_hole_selects_location_and_converts_dimensions(self):
        result=self.run_hole();self.assertTrue(result['success'],result)
        self.assertEqual(OperationClass.MUTATE,operation_class_for('hole_wizard'))
        expected=(.005,.006,.011,0,0,-1,.0001,2,False,0,0)
        for actual,wanted in zip(self.doc.Extension.ray,expected):self.assertAlmostEqual(wanted,actual)
        args=self.doc.FeatureManager.args;self.assertEqual(27,len(args));self.assertEqual((2,1,39,'Ø6.0',0),args[:5])
        self.assertEqual((-1.,)*12,args[8:20]);self.assertAlmostEqual(.006,args[5]);self.assertAlmostEqual(.008,args[6])
    def test_through_all_has_no_blind_depth(self):
        r=self.run_hole(depth_mm=None,end_condition='through_all');self.assertTrue(r['success'],r)
        self.assertEqual(0,self.doc.FeatureManager.args[4]);self.assertEqual(.012,self.doc.FeatureManager.args[6])
        self.assertEqual(1,self.doc.modified_end)
    def test_counterbore_converts_head_dimensions(self):
        r=self.run_hole(hole_type='counterbore',catalog_size='M6',head_diameter_mm=11,head_depth_mm=4)
        self.assertTrue(r['success'],r);args=self.doc.FeatureManager.args
        self.assertEqual((0,1,33,'M6',0),args[:5]);self.assertEqual((.011,.004,0.),args[8:11])
    def test_countersink_converts_included_angle(self):
        r=self.run_hole(hole_type='countersink',catalog_size='M6',head_diameter_mm=12,head_angle_deg=90)
        self.assertTrue(r['success'],r);args=self.doc.FeatureManager.args
        self.assertEqual((1,1,35,'M6',0),args[:5]);self.assertEqual((.012,math.pi/2,0.),args[8:11])
    def test_invalid_input_does_not_touch_com(self):
        for args in [dict(point_mm=[1,2]),dict(diameter_mm=0),dict(depth_mm=float('nan')),dict(diameter_mm=5.25),dict(end_condition='up_to_next'),dict(end_condition='through_all'),dict(hole_type='unknown'),dict(hole_type='counterbore'),dict(head_diameter_mm=12),dict(hole_type='counterbore',catalog_size='M6',head_diameter_mm=5,head_depth_mm=4),dict(hole_type='counterbore',catalog_size='M6',head_diameter_mm=12,head_depth_mm=9),dict(hole_type='countersink',catalog_size='M6',head_diameter_mm=12,head_angle_deg=180)]:
            with self.subTest(args=args):
                self.sw.active_doc_calls=0;self.assertFalse(self.run_hole(**args)['success']);self.assertEqual(0,self.sw.active_doc_calls)
    def test_point_outside_face_rejected_before_feature_call(self):
        self.assertFalse(self.run_hole(point_mm=[500,5,10])['success']);self.assertIsNone(self.doc.FeatureManager.args)
    def test_point_off_plane_rejected_before_feature_call(self):
        self.assertFalse(self.run_hole(point_mm=[5,5,12])['success']);self.assertIsNone(self.doc.FeatureManager.args)
    def test_ray_must_hit_the_requested_native_face(self):
        self.sw.app.same=False;self.assertFalse(self.run_hole()['success']);self.assertIsNone(self.doc.FeatureManager.args)
    def test_protected_source_is_not_modified(self):
        self.doc.GetPathName=PathName(str(Path('protected/reference.SLDPRT').resolve())).GetPathName
        self.sw._path_policy=PathPolicy([Path('output/hole-wizard-20261018-R01')])
        self.assertFalse(self.run_hole()['success']);self.assertIsNone(self.doc.FeatureManager.args)
    def test_failed_rebuild_is_not_success(self):
        self.doc.rebuild=False;r=self.run_hole();self.assertFalse(r['success']);self.assertTrue(r['data']['document_may_be_modified'])
    def test_native_error_is_not_success(self):
        self.doc.native_error=1;self.assertFalse(self.run_hole()['success'])
    def test_readback_diameter_must_match_request(self):
        self.doc.wrong_diameter=True;self.assertFalse(self.run_hole()['success'])
    def test_missing_persisted_feature_is_not_success(self):
        self.doc.feature=None;self.assertFalse(self.run_hole()['success'])
    def test_no_material_removed_is_failure(self):
        with patch('solidworks_mcp.tools.advanced_features._solid_volume_mm3',side_effect=[10000,10000]):
            r=hole_wizard(self.sw,0,[5,6,10],6,8)
        self.assertFalse(r['success'])
    def test_invalid_native_closest_point_is_rejected_before_creation(self):
        self.doc.face.bad_closest=True
        self.assertFalse(self.run_hole()['success'])
        self.assertIsNone(self.doc.FeatureManager.args)
    def test_failed_through_modification_does_not_claim_success(self):
        self.doc.modify_fails=True
        r=self.run_hole(depth_mm=None,end_condition='through_all')
        self.assertFalse(r['success']);self.assertTrue(r['data']['document_may_be_modified'])
    def test_acute_countersink_seed_is_deeper_than_its_recess(self):
        r=self.run_hole(depth_mm=None,end_condition='through_all',hole_type='countersink',
                        catalog_size='M6',head_diameter_mm=12,head_angle_deg=10)
        self.assertTrue(r['success'],r)
        recess_depth_m=.003/math.tan(math.radians(5))
        self.assertGreater(self.doc.FeatureManager.args[6],recess_depth_m)
    def test_din_and_iso_use_their_verified_native_ids(self):
        for standard,index,fastener in [('din',4,67),('iso',8,139)]:
            with self.subTest(standard=standard):
                r=self.run_hole(standard=standard,hole_type='counterbore',catalog_size='M6',head_diameter_mm=11,head_depth_mm=4)
                self.assertTrue(r['success'],r)
                self.assertEqual((0,index,fastener,'M6',0),self.doc.FeatureManager.args[:5])
                self.assertEqual(index,r['data']['native_dimensions_si']['Standard2'])
    def test_invalid_standard_rejected_before_com(self):
        self.assertFalse(self.run_hole(standard='unknown')['success'])
        self.assertEqual(0,self.sw.active_doc_calls)
    def test_native_catalog_size_must_match_request(self):
        self.doc.wrong_size=True
        self.assertFalse(self.run_hole()['success'])

class PathName:
    def __init__(self,path):self.path=path
    def GetPathName(self):return self.path

if __name__=='__main__':unittest.main()
