"""Isolated export orchestration must never flatten/save the source document."""
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace,MethodType
import unittest
from unittest.mock import patch,Mock

from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tests.test_sheet_metal_body_info import Automation
from solidworks_mcp.tools.sheetmetal_body_export import export_sheet_metal_body_dxf,_activate_source as native_activate


class NativeActivationTests(unittest.TestCase):
    def test_activation_never_prompts_or_rebuilds_source(self):
        class Document:
            def GetTitle(self):return 'SOURCE'
            def GetPathName(self):return str(Path('source.SLDPRT').resolve())
        class App:
            def __init__(self):self.ActiveDoc=Document();self.options=[]
            def ActivateDoc3(self,title,use_preferences,option,error):
                self.options.append(option);return self.ActiveDoc
        app=App();native_activate(app,app.ActiveDoc,Path('source.SLDPRT').resolve())
        self.assertEqual([1],app.options)


class SheetBodyDxfTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source/PART.SLDPRT'
        self.source.parent.mkdir();self.source.write_bytes(b'SOURCE')
        self.destination=self.root/'export';self.sw=Automation();self.doc=self.sw.doc
        self.doc.GetPathName=MethodType(lambda doc:str(self.source),self.doc)
        self.doc.GetSaveFlag=MethodType(lambda doc:False,self.doc)
        self.sw._path_policy=PathPolicy([self.root]);self.sw.app.ActiveDoc=self.doc
        self.state=dict(stamp=7,configuration='Default',dirty=False,path=str(self.source),sha='SOURCE',geometry=[])
        self.row=dict(body_index=0,solid_body_index=0,name='C',flat_pattern_feature='Flat-C',parameters={'thickness_mm':3})
        self.info={'success':True,'data':{'complete':True,'update_stamp':7,'bodies':[self.row]}}
        self.copy_data=None;self.copy_calls=0;self.export_calls=0
        def copy(sw,source_path,destination_folder,**kw):
            self.copy_calls+=1;folder=Path(destination_folder);folder.mkdir(parents=True)
            target=folder/'CLONE.SLDPRT';target.write_bytes(self.source.read_bytes())
            self.copy_data=dict(root_document=str(target),files=[dict(source=str(self.source),copy=str(target),source_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest())])
            return {'success':True,'data':self.copy_data}
        def export(sw,clone,target_row,source_geometry,out,configuration):
            self.export_calls+=1;Path(out).write_bytes(b'0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n')
            return dict(flat_pattern_feature='Flat-C',selected_body_verified=True)
        patches=[patch('solidworks_mcp.tools.sheetmetal_body_export._source_state',side_effect=lambda d:dict(self.state)),
                 patch('solidworks_mcp.tools.sheetmetal_body_export.list_sheet_metal_bodies',return_value=self.info),
                 patch('solidworks_mcp.tools.sheetmetal_body_export._snapshot',return_value={'v':1}),
                 patch('solidworks_mcp.tools.sheetmetal_body_export.copy_project',side_effect=copy),
                 patch('solidworks_mcp.tools.sheetmetal_body_export._read_saved',side_effect=lambda app,path,kind,reader:(reader(SimpleNamespace()),0)),
                 patch('solidworks_mcp.tools.sheetmetal_body_export._perform_export',side_effect=export),
                 patch('solidworks_mcp.tools.sheetmetal_body_export._activate_source'),
                 patch('solidworks_mcp.tools.sheetmetal_body_export._close_outputs'),
                 patch('solidworks_mcp.tools.sheetmetal_body_export._selections',return_value=[])]
        self.mocks=[p.start() for p in patches]
        for p in patches:self.addCleanup(p.stop)

    def call(self,**kw):return export_sheet_metal_body_dxf(self.sw,kw.get('body_index',0),kw.get('expected_update_stamp',7),str(self.destination))

    def test_success_uses_new_copy_not_source_and_records_provenance(self):
        r=self.call();self.assertTrue(r['success'],r)
        self.assertTrue(r['data']['source_unchanged']);self.assertEqual(1,self.copy_calls)
        self.assertEqual(b'SOURCE',self.source.read_bytes());self.assertTrue((self.destination/'export.json').is_file())
        self.assertTrue(r['data']['selected_body_verified']);self.assertEqual(1,self.export_calls)

    def test_stale_index_is_rejected_before_copy(self):
        self.assertFalse(self.call(expected_update_stamp=6)['success']);self.assertEqual(0,self.copy_calls)

    def test_change_after_inventory_is_rejected_before_copy(self):
        self.state['stamp']=8
        self.assertFalse(self.call()['success']);self.assertEqual(0,self.copy_calls)

    def test_nonexistent_or_hidden_body_index_is_rejected(self):
        self.assertFalse(self.call(body_index=9)['success']);self.assertEqual(0,self.copy_calls)

    def test_non_sheet_body_has_no_export_target(self):
        self.info['data']['bodies']=[];self.assertFalse(self.call()['success']);self.assertEqual(0,self.copy_calls)

    def test_incomplete_native_inventory_is_rejected(self):
        self.info['data']['complete']=False;self.assertFalse(self.call()['success']);self.assertEqual(0,self.copy_calls)

    def test_invalid_integer_values_rejected(self):
        for kw in [dict(body_index=True),dict(body_index=-1),dict(expected_update_stamp=True),dict(expected_update_stamp=-1)]:
            self.assertFalse(self.call(**kw)['success'])
        self.assertEqual(0,self.copy_calls)

    def test_existing_destination_never_overwritten(self):
        self.destination.mkdir();(self.destination/'KEEP').write_text('KEEP')
        self.assertFalse(self.call()['success']);self.assertEqual('KEEP',(self.destination/'KEEP').read_text())
        self.assertEqual(0,self.copy_calls)

    def test_destination_policy_precedes_cad(self):
        self.sw._path_policy=PathPolicy([self.root/'other'])
        self.sw.get_active_doc=Mock(return_value=(self.doc,None))
        self.assertFalse(self.call()['success'])
        self.sw.get_active_doc.assert_not_called()

    def test_missing_policy_precedes_cad(self):
        del self.sw._path_policy
        self.sw.get_active_doc=Mock(return_value=(self.doc,None))
        self.assertFalse(self.call()['success'])
        self.sw.get_active_doc.assert_not_called()

    def test_source_policy_precedes_copy(self):
        self.sw._path_policy=PathPolicy([self.destination])
        self.assertFalse(self.call()['success']);self.assertEqual(0,self.copy_calls)

    def test_dirty_source_requires_explicit_saved_state(self):
        self.doc.GetSaveFlag=MethodType(lambda doc:True,self.doc);self.assertFalse(self.call()['success']);self.assertEqual(0,self.copy_calls)

    def test_unknown_source_save_state_is_not_assumed_clean(self):
        self.doc.GetSaveFlag=MethodType(lambda doc:None,self.doc)
        self.assertFalse(self.call()['success']);self.assertEqual(0,self.copy_calls)

    def test_copy_failure_never_calls_export(self):
        self.mocks[3].side_effect=None;self.mocks[3].return_value={'success':False,'message':'Missing dependency'}
        self.assertFalse(self.call()['success']);self.assertEqual(0,self.export_calls)

    def test_unknown_copy_warning_never_reports_success(self):
        self.mocks[4].side_effect=lambda app,path,kind,reader:(reader(SimpleNamespace()),64)
        self.assertFalse(self.call()['success'])

    def test_clone_needs_regeneration_warning_requires_verified_rebuild(self):
        self.mocks[4].side_effect=lambda app,path,kind,reader:(reader(SimpleNamespace()),32)
        self.assertFalse(self.call()['success'])

    def test_readonly_warning_is_recorded_without_source_change(self):
        self.mocks[4].side_effect=lambda app,path,kind,reader:(reader(SimpleNamespace()),2)
        r=self.call();self.assertTrue(r['success'],r);self.assertEqual(2,r['data']['copy_load_warning'])

    def test_export_failure_closes_clone_and_restores_source(self):
        self.mocks[5].side_effect=ValueError('Native export failed')
        r=self.call();self.assertFalse(r['success']);self.assertTrue(r['data']['source_unchanged'])
        self.assertEqual(self.doc,self.mocks[6].call_args.args[1]);self.mocks[7].assert_called_once()

    def test_source_state_change_never_reports_success(self):
        self.mocks[0].side_effect=[dict(self.state),{**self.state,'stamp':8}]
        self.assertFalse(self.call()['success'])

    def test_missing_export_file_never_reports_success(self):
        self.mocks[5].side_effect=None;self.mocks[5].return_value={'selected_body_verified':True}
        self.assertFalse(self.call()['success'])

    def test_restore_failure_is_reported(self):
        self.mocks[6].side_effect=RuntimeError('Cannot activate source')
        r=self.call();self.assertFalse(r['success']);self.assertFalse(r['data']['source_restored'])

    def test_changed_source_bytes_never_report_success(self):
        def changed(*args):
            self.source.write_bytes(b'CHANGED');Path(args[4]).write_bytes(b'DXF');return {'selected_body_verified':True}
        self.mocks[5].side_effect=changed
        self.assertFalse(self.call()['success'])


if __name__=='__main__':unittest.main()
