"""Explicit additional-body mode must preserve all existing solid geometry."""
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.sheetmetal import create_sheet_metal_base_flange


class Body:
    def __init__(self,key,volume=5e-6,box=None):self.key=key;self.Name=key;self.volume=volume;self.box=box or [0,0,0,.1,.05,.001]
    def GetMassProperties(self,density):return [0.,0.,0.,self.volume,.01]
    def GetFaceCount(self):return 6
    def GetBodyBox(self):return self.box
    def IsSheetMetal(self):return True

class Feature:
    Name='Base-Flange2'
    def __init__(self):self.definition=SimpleNamespace(Thickness=.002,BendRadius=.001);self.error=0;self.warning=False
    def GetTypeName2(self):return 'SMBaseFlange'
    def GetDefinition(self):return self.definition
    def GetFaces(self):
        class Face:
            def GetBody(inner):return Body('new')
        return [Face()]
    def GetErrorCode2(self,w):w.value=self.warning;return self.error

class SheetDefinition:
    def __init__(self):self.Thickness=.001;self.BendRadius=.001;self.override_code=0;self.releases=0
    def AccessSelections(self,doc,component):return True
    def SetOverrideDefaultParameter2(self,kind,value):return self.override_code
    def ReleaseSelectionAccess(self):self.releases+=1

class SheetFeature:
    def __init__(self,name):self.Name=name;self.definition=SheetDefinition();self.modified=True
    def GetTypeName2(self):return 'SheetMetal'
    def GetDefinition(self):return self.definition
    def ModifyDefinition(self,data,doc,component):return self.modified
    def GetErrorCode2(self,w):w.value=False;return 0

class Manager:
    def __init__(self,doc):self.doc=doc;self.calls=[]
    def InsertSheetMetalBaseFlange(self,*args):
        self.calls.append(args);self.doc.called=True
        return self.doc.feature if self.doc.created else None
    def GetFeatures(self,top):return [self.doc.old_sm]+([self.doc.new_sm] if self.doc.called else [])

class Doc:
    def __init__(self):
        self.feature=Feature();self.before=[Body('old')];self.after=self.before+[Body('new',8e-6,[.2,0,0,.28,.05,.002])]
        self.called=False;self.created=True;self.persist=True;self.rebuilt=True;self.clears=0
        self.FeatureManager=Manager(self)
        self.old_sm=SheetFeature('Sheet-Metal1');self.new_sm=SheetFeature('Sheet-Metal2')
    def GetType(self):return 1
    def GetPathName(self):return str(Path('output/new-body-unit.SLDPRT').resolve())
    def GetBodies2(self,kind,visible):return self.after if self.called else self.before
    def FeatureByName(self,name):
        if not self.persist:return None
        return self.new_sm if name==self.new_sm.Name else self.feature
    def EditRebuild3(self):return self.rebuilt
    def ClearSelection2(self,clear):self.clears+=1

class App:
    def IsSame(self,a,b):return 1 if a.key==b.key else 0

class Automation:
    def __init__(self):self.doc=Doc();self.app=App()
    def get_active_doc(self):return self.doc,None
    def _close_and_select_sketch(self,doc):return True,'Sketch2',''
    def _result(self,success,message,error_code=None,data=None):return dict(success=success,message=message,data=data)


class NewBodyTests(unittest.TestCase):
    def setUp(self):
        self.sw=Automation();self.doc=self.sw.doc
        self.sm_patch=patch('solidworks_mcp.tools.sheetmetal._find_sheet_metal_feature',return_value=self.doc.old_sm)
        self.sm_patch.start();self.addCleanup(self.sm_patch.stop)
    def call(self,**kw):return create_sheet_metal_base_flange(self.sw,2.,bend_radius_mm=1.,new_body=True,**kw)
    def test_additional_body_has_verified_dimensions_and_preserves_old(self):
        r=self.call();self.assertTrue(r['success'],r)
        self.assertEqual((1,2),(r['data']['bodies_before'],r['data']['bodies_after']))
        self.assertEqual('new',r['data']['new_body_name']);self.assertTrue(r['data']['existing_geometry_unchanged'])
        self.assertAlmostEqual(8000.,r['data']['new_body_volume_mm3']);self.assertEqual(2.,r['data']['thickness_mm'])
    def test_old_default_still_rejects_accidental_second_body(self):
        self.assertFalse(create_sheet_metal_base_flange(self.sw,2.)['success']);self.assertFalse(self.doc.called)
    def test_bad_numbers_and_boolean_rejected_before_mutation(self):
        for args in [dict(thickness_mm=math.inf),dict(thickness_mm=math.nan),dict(width_mm=math.inf),dict(bend_radius_mm=math.nan),dict(new_body=1)]:
            k=dict(thickness_mm=2.,new_body=True);k.update(args)
            self.assertFalse(create_sheet_metal_base_flange(self.sw,**k)['success'])
        self.assertFalse(self.doc.called)
    def test_new_body_policy_guard_precedes_sketch_mutation(self):
        self.sw._path_policy=PathPolicy([Path('output/elsewhere')]);self.assertFalse(self.call()['success']);self.assertFalse(self.doc.called)
    def test_nonpart_rejected(self):
        with patch.object(self.doc,'GetType',return_value=2):self.assertFalse(self.call()['success'])
        self.assertFalse(self.doc.called)
    def test_requires_an_existing_sheet_metal_body(self):
        self.doc.before=[];self.assertFalse(self.call()['success']);self.assertFalse(self.doc.called)
    def test_null_native_and_missing_persistent_feature_rejected(self):
        self.doc.created=False;self.assertFalse(self.call()['success']);self.doc.created=True
        self.doc.persist=False;self.assertFalse(self.call()['success'])
    def test_failed_rebuild_native_error_or_warning_not_success(self):
        self.doc.rebuilt=False;self.assertFalse(self.call()['success']);self.doc.rebuilt=True
        self.doc.feature.error=1;self.assertFalse(self.call()['success']);self.doc.feature.error=0
        self.doc.feature.warning=True;self.assertFalse(self.call()['success'])
    def test_merge_no_new_body_is_failure(self):
        self.doc.after=self.doc.before;r=self.call();self.assertFalse(r['success']);self.assertTrue(r['data']['document_may_be_modified'])
    def test_old_body_change_or_disappearance_not_success(self):
        self.doc.after[0]=Body('old',6e-6);self.assertFalse(self.call()['success'])
        self.doc.after=[Body('replacement',3e-6),Body('new',8e-6)];self.assertFalse(self.call()['success'])
    def test_native_regeneration_of_unchanged_old_body_is_accepted(self):
        self.doc.after[0]=Body('regenerated')
        self.assertTrue(self.call()['success'])
    def test_feature_not_geometry_identifies_new_body(self):
        # Coincident identical geometry can never choose which body is new.
        self.doc.after=[Body('new'),Body('regenerated')]
        r=self.call();self.assertTrue(r['success'],r);self.assertEqual('new',r['data']['new_body_name'])
    def test_native_parameter_mismatch_not_success(self):
        class WrongDefinition(SheetDefinition):
            @property
            def Thickness(self):return .001
            @Thickness.setter
            def Thickness(self,value):pass
        self.doc.new_sm.definition=WrongDefinition();self.assertFalse(self.call()['success'])
    def test_shared_defaults_not_changed_by_creation_call(self):
        r=self.call();self.assertTrue(r['success'],r)
        self.assertEqual(.001,self.doc.FeatureManager.calls[0][0])
        self.assertEqual(.002,self.doc.new_sm.definition.Thickness)
        self.assertEqual(1,self.doc.new_sm.definition.releases)
    def test_failed_override_or_modify_is_failure(self):
        self.doc.new_sm.definition.override_code=1;self.assertFalse(self.call()['success'])
        self.doc.new_sm.definition.override_code=0;self.doc.new_sm.modified=False;self.assertFalse(self.call()['success'])
    def test_hidden_body_is_counted_and_preserved(self):
        hidden=Body('hidden',2e-6);self.doc.before.append(hidden);self.doc.after.append(hidden)
        r=self.call();self.assertTrue(r['success'],r)
        self.assertEqual(2,r['data']['bodies_before']);self.assertEqual(3,r['data']['bodies_after'])

if __name__=='__main__':unittest.main()
