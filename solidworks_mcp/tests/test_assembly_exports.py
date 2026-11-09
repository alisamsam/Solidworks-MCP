import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from .test_manufacturing_package import SW
from solidworks_mcp.tools.assembly_exports import export_assembly_manufacturing_package, _validate_options, _process_part, _run_parts, request_manufacturing_package_stop


class ExportBatchTests(unittest.TestCase):
    def test_report_publication_keeps_stop_readable_until_atomic_replace(self):
        import json
        import os
        from solidworks_mcp.tools.assembly_exports import _publish_report
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'00_Pregled').mkdir();output=folder/'00_Pregled/exports.json'
            original={'schema_version':1,'status':'running','items':[]}
            output.write_text(json.dumps(original));sw=SW(tmp,folder/'root.sldasm')
            replace=os.replace;observed=[]
            def before_replace(source,target):
                observed.append(request_manufacturing_package_stop(sw,str(folder)))
                replace(source,target)
            with patch('solidworks_mcp.tools.assembly_exports.os.replace',side_effect=before_replace):
                _publish_report(output,dict(original,items=[{'plan_id':'K0001'}]))
            self.assertTrue(observed[0]['success'],observed)
            self.assertEqual(1,len(json.loads(output.read_text())['items']))
            self.assertEqual([],list(output.parent.glob('*.tmp')))
    def test_copy_must_match_planned_full_dependency_snapshot(self):
        from solidworks_mcp.tools.assembly_exports import _verify_plan_copy
        root=str(Path('root.sldasm').resolve());master=str(Path('master.sldprt').resolve())
        plan={'source_snapshot':[{'path':root,'sha256':'a'*64},{'path':master,'sha256':'b'*64}]}
        good={'files':[{'source':root,'source_sha256':'a'*64},{'source':master,'source_sha256':'b'*64}]}
        _verify_plan_copy(plan,good)
        bad={'files':[dict(row) for row in good['files']]};bad['files'][1]['source_sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'changed'):_verify_plan_copy(plan,bad)
        with self.assertRaises(ValueError):_verify_plan_copy(plan,{'files':good['files'][:1]})
        with self.assertRaises(ValueError):_verify_plan_copy({},good)
    def test_cooperative_stop_finishes_current_item_and_skips_remaining(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'00_Pregled').mkdir();report={'items':[],'status':'running'}
            parts=[{'plan_id':'K0001','document_path':str(folder/'p.sldprt')}, {'plan_id':'K0002','document_path':str(folder/'q.sldprt')}]
            def first(*args):
                (folder/'00_Pregled/STOP.request').write_text('stop')
                return {'plan_id':'K0001','status':'exported_needs_review','artifacts':[],'errors':[]}
            with patch('solidworks_mcp.tools.assembly_exports._process_part',side_effect=first) as process:
                _run_parts(None,parts,{Path(p['document_path']):Path(p['document_path']) for p in parts},folder,['step'],None,'first_angle',report)
            process.assert_called_once();self.assertEqual('stopped',report['status']);self.assertEqual(['K0002'],report['not_processed'])
    def test_stop_tool_is_com_free_and_policy_guarded(self):
        import json
        from solidworks_mcp.registry import needs_com_thread
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'00_Pregled').mkdir()
            (folder/'00_Pregled/exports.json').write_text(json.dumps({'schema_version':1,'status':'running','items':[]}))
            sw=SW(tmp,folder/'p.sldasm');sw.get_active_doc=Mock()
            result=request_manufacturing_package_stop(sw,str(folder))
            self.assertTrue(result['success'],result);self.assertFalse(needs_com_thread('request_manufacturing_package_stop'))
            sw.get_active_doc.assert_not_called();self.assertTrue((folder/'00_Pregled/STOP.request').exists())
    def test_subset_requires_fresh_plan_fingerprint_before_com(self):
        with tempfile.TemporaryDirectory() as tmp:
            sw=SW(tmp,Path(tmp)/'a.sldasm')
            with patch('solidworks_mcp.tools.assembly_exports.plan_assembly_documentation') as plan:
                result=export_assembly_manufacturing_package(sw,'a','Default',str(Path(tmp)/'new'),item_ids=['K0001'])
            self.assertFalse(result['success']);plan.assert_not_called()
    def test_stale_plan_fingerprint_prevents_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            sw=SW(tmp,Path(tmp)/'a.sldasm')
            with patch('solidworks_mcp.tools.assembly_exports.plan_assembly_documentation',return_value={
                'success':True,'data':{'items':[],'inventory_complete':True,'plan_fingerprint':'a'*64}}), \
                 patch('solidworks_mcp.tools.assembly_exports.copy_project') as copied:
                result=export_assembly_manufacturing_package(sw,'a','Default',str(Path(tmp)/'new'),item_ids=['K0001'],expected_plan_fingerprint='b'*64)
            self.assertFalse(result['success']);copied.assert_not_called()
    def test_incomplete_geometry_read_fails_item_without_export(self):
        from types import MethodType,SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'copy.sldprt';path.write_bytes(b'part');sw=SW(tmp,path)
            sw.doc.ForceRebuild3=MethodType(lambda doc,top:True,sw.doc)
            sw.doc.ClearSelection2=MethodType(lambda doc,all:None,sw.doc)
            sw.doc.GetTitle=MethodType(lambda doc:'copy',sw.doc)
            class App:
                closed=False
                def OpenDoc6(self,*args):return sw.doc
                def CloseDoc(self,title):self.closed=True
            sw.app=App()
            item={'plan_id':'K0001','source_key':'key','document_path':str(path),'configuration':'Default','quantity':1}
            with patch('solidworks_mcp.tools.assembly_exports._activate_source'), \
                 patch('solidworks_mcp.tools.assembly_exports.inspect_part_manufacturing',return_value={
                    'success':True,'data':{'bodies':[{}],'body_read_complete':False}}), \
                 patch('solidworks_mcp.tools.assembly_exports.export_step') as exported:
                row=_process_part(sw,path,item,Path(tmp),['step'])
            self.assertEqual('failed',row['status']);exported.assert_not_called();self.assertTrue(sw.app.closed)
    def test_formats_are_explicit_unique_supported(self):
        for value in [[],['stl'],['step','step'],'step']:
            with self.assertRaises(ValueError):_validate_options(value,None)
        self.assertEqual(['step','plate_dxf'],_validate_options(None,None))
    def test_requested_ids_cannot_be_duplicate_or_empty(self):
        for value in [[],['K0001','K0001'],[1],['../escape']]:
            with self.assertRaises(ValueError):_validate_options(['step'],value)
    def test_batch_can_request_drawing_drafts_explicitly(self):
        self.assertEqual(['drawing_pdf'],_validate_options(['drawing_pdf'],None))
    def test_existing_output_fails_before_com(self):
        with tempfile.TemporaryDirectory() as tmp:
            sw=SW(tmp,Path(tmp)/'a.sldasm'); sw.get_active_doc=Mock()
            result=export_assembly_manufacturing_package(sw,'a','Default',tmp)
            self.assertFalse(result['success']);sw.get_active_doc.assert_not_called()
    def test_invalid_options_fails_before_plan_and_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            sw=SW(tmp,Path(tmp)/'a.sldasm')
            with patch('solidworks_mcp.tools.assembly_exports.plan_assembly_documentation') as plan:
                result=export_assembly_manufacturing_package(sw,'a','Default',str(Path(tmp)/'new'),formats=['stl'])
            self.assertFalse(result['success']);plan.assert_not_called()
    def test_unknown_selected_ids_fail_before_native_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            sw=SW(tmp,Path(tmp)/'a.sldasm')
            with patch('solidworks_mcp.tools.assembly_exports.plan_assembly_documentation',return_value={'success':True,'data':{'items':[],'inventory_complete':True}}), \
                 patch('solidworks_mcp.tools.assembly_exports.copy_project') as copied:
                result=export_assembly_manufacturing_package(sw,'a','Default',str(Path(tmp)/'new'),item_ids=['K9999'])
            self.assertFalse(result['success']);copied.assert_not_called()


if __name__=='__main__':unittest.main()
