"""Save/close decisions with native-shaped bool/BYREF fakes; no SolidWorks."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from solidworks_mcp.automation.documents import DocumentOperations
from solidworks_mcp.automation.base import SolidWorksAutomation
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.core.session import DocumentSession, TargetMismatchError


class Document:
    def __init__(self, path='', kind=1):
        self.path, self.kind = str(path), kind
        self.stamp, self.dirty = 1, True
        self.result, self.errors, self.warnings = True, 0, 0
        self.calls = []
        self.Extension = self

    def GetPathName(self): return self.path
    def GetTitle(self): return Path(self.path).name if self.path else 'Part1'
    def GetType(self): return self.kind
    def GetUpdateStamp(self): return self.stamp
    def GetSaveFlag(self): return self.dirty

    def Save3(self, options, errors, warnings):
        self.calls.append(('Save3', options))
        errors.value, warnings.value = self.errors, self.warnings
        if self.result and not self.errors:
            Path(self.path).write_bytes(b'new saved state')
            self.dirty = False
        return self.result

    def SaveAs(self, path, version, options, export, errors, warnings):
        self.calls.append(('SaveAs', options))
        if self.result and not self.errors: self.path = path
        return self.Save3(options, errors, warnings)


class App:
    def __init__(self, doc): self.docs, self.closed = [doc], []
    def GetDocuments(self): return tuple(self.docs)
    def OpenDoc6(self, path, kind, options, configuration, errors, warnings):
        self.ActiveDoc=self.new_document;self.docs.append(self.new_document)
        return self.new_document
    def ActivateDoc3(self, *args): return self.ActiveDoc
    def GetOpenDocumentByName(self, path):
        return next((d for d in self.docs if d.path == path), None)
    def CloseDoc(self, name):
        self.closed.append(name)
        self.docs = [d for d in self.docs if name not in (d.path, d.GetTitle())]


class Automation(DocumentOperations):
    def __init__(self, root, doc):
        self._path_policy = PathPolicy([Path(root)])
        self.document = doc
        self._sw_app = App(doc)
    def get_active_doc(self): return self.document, None
    def _get_doc_path(self, doc): return doc.GetPathName()
    def _get_doc_title(self, doc): return doc.GetTitle()
    def _result(self, success, message, error_code=0, data=None):
        return dict(success=success, message=message, error_code=int(error_code), data=data or {})


class BoundAutomation(Automation, SolidWorksAutomation):
    def __init__(self, root, doc):
        Automation.__init__(self, root, doc)
        self._document_session = DocumentSession()


class DocumentSaveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.doc = Document(self.root/'part.SLDPRT')
        Path(self.doc.path).write_bytes(b'last saved state')
        self.sw = Automation(self.root, self.doc)
        self.dispatch = patch('solidworks_mcp.automation.documents.win32com.client.dynamic.Dispatch', side_effect=lambda x:x)
        self.dispatch.start()

    def tearDown(self):
        self.dispatch.stop()
        self.temp.cleanup()

    def own(self): self.sw._register_managed_document(self.doc)

    def test_user_document_inside_output_root_is_not_saved(self):
        r = self.sw.save_document(self.doc.path)
        self.assertFalse(r['success'])
        self.assertEqual('USER_DOCUMENT_PROTECTED', r['data']['code'])
        self.assertEqual([], self.doc.calls)

    def test_user_document_is_not_saved_as_a_copy_either(self):
        r = self.sw.save_document(str(self.root/'copy.SLDPRT'))
        self.assertFalse(r['success'])
        self.assertEqual([], self.doc.calls)

    def test_user_document_is_not_closed_even_with_recovery_script(self):
        script = self.root/'rebuild.py';script.write_text('print(1)')
        r = self.sw.close_document(save=False, recovery_script=str(script))
        self.assertFalse(r['success'])
        self.assertEqual([], self.sw._sw_app.closed)

    def test_same_path_uses_save3_and_returns_true_success(self):
        self.own();r=self.sw.save_document(self.doc.path)
        self.assertTrue(r['success'], r)
        self.assertEqual([('Save3', 1)], self.doc.calls)
        self.assertEqual('Save3', r['data']['method'])

    def test_internal_no_path_save_uses_save3(self):
        self.own();self.assertTrue(self.sw.save_document()['success'])
        self.assertEqual([('Save3', 1)], self.doc.calls)

    def test_false_with_zero_error_is_not_success(self):
        self.own();self.doc.result=False
        self.assertFalse(self.sw.save_document()['success'])

    def test_true_with_native_error_is_not_success(self):
        self.own();self.doc.errors=4
        r=self.sw.save_document();self.assertFalse(r['success'])
        self.assertEqual(4,r['data']['save_errors'])

    def test_warning_is_retained_without_losing_success(self):
        self.own();self.doc.warnings=2
        r=self.sw.save_document();self.assertTrue(r['success'],r)
        self.assertEqual(2,r['data']['save_warnings'])

    def test_new_path_uses_saveas_with_no_save_referenced_flag(self):
        self.own();target=self.root/'copy.SLDPRT'
        r=self.sw.save_document(str(target));self.assertTrue(r['success'],r)
        self.assertEqual(('SaveAs',1),self.doc.calls[0])
        self.assertEqual(str(target),r['data']['path'])

    def test_manual_edit_of_owned_output_blocks_save_and_discard(self):
        self.own();self.doc.stamp+=1
        self.assertFalse(self.sw.save_document()['success'])
        self.assertFalse(self.sw.close_document(save=False)['success'])
        self.assertEqual([],self.doc.calls);self.assertEqual([],self.sw._sw_app.closed)

    def test_failed_save_does_not_implicitly_close(self):
        self.own();self.doc.result=False
        self.assertFalse(self.sw.close_document(save=True)['success'])
        self.assertEqual([],self.sw._sw_app.closed)

    def test_owned_saved_output_can_be_discarded_after_error(self):
        self.own();self.doc.result=False
        self.sw.save_document()
        r=self.sw.close_document(save=False);self.assertTrue(r['success'],r)
        self.assertEqual([self.doc.path],self.sw._sw_app.closed)
        self.assertEqual(b'last saved state',Path(self.doc.path).read_bytes())

    def test_owned_unsaved_output_without_recovery_is_kept(self):
        self.doc.path='';self.own()
        r=self.sw.close_document(save=False);self.assertFalse(r['success'])
        self.assertEqual([],self.sw._sw_app.closed)

    def test_owned_unsaved_output_with_readable_script_can_be_discarded(self):
        self.doc.path='';self.own()
        script=self.root/'rebuild.py';script.write_text('print(1)')
        r=self.sw.close_document(save=False,recovery_script=str(script))
        self.assertTrue(r['success'],r);self.assertEqual(['Part1'],self.sw._sw_app.closed)

    def test_missing_script_does_not_authorize_discard(self):
        self.doc.path='';self.own()
        self.assertFalse(self.sw.close_document(recovery_script=str(self.root/'missing.py'))['success'])

    def test_dirty_user_reference_prevents_assembly_save_or_close(self):
        self.doc.kind=2;self.own()
        self.sw._sw_app.docs.append(Document(self.root/'user.SLDPRT'))
        self.assertFalse(self.sw.save_document()['success'])
        self.assertFalse(self.sw.close_document()['success'])
        self.assertEqual([],self.doc.calls);self.assertEqual([],self.sw._sw_app.closed)

    def test_rebind_cannot_bless_manual_edits(self):
        sw=BoundAutomation(self.root,self.doc);sw._register_managed_document(self.doc)
        sw.bind_active_document();self.doc.stamp+=1
        with self.assertRaises(TargetMismatchError):sw.bind_active_document()
        self.assertFalse(sw.save_document()['success'])

    def test_successful_guarded_mutation_updates_expected_snapshot(self):
        sw=BoundAutomation(self.root,self.doc);sw._register_managed_document(self.doc)
        before=sw.bind_active_document();sw.require_bound_active_document()
        self.doc.stamp+=1;sw.mark_active_document_mutated(before)
        self.assertTrue(sw.save_document()['success'])

    def test_known_failed_operation_can_discard_but_not_save_its_partial_output(self):
        self.own();token=self.sw._begin_managed_operation()
        self.doc.stamp+=1
        self.sw._end_failed_managed_operation(token)
        self.assertFalse(self.sw.save_document()['success'])
        self.assertTrue(self.sw.close_document()['success'])

    def test_script_argument_must_be_a_script_not_an_arbitrary_file(self):
        self.doc.path='';self.own();not_script=self.root/'notes.txt'
        not_script.write_text('not a rebuild script')
        self.assertFalse(self.sw.close_document(recovery_script=str(not_script))['success'])

    def test_registered_failed_mutation_tracks_partial_changes_for_recovery(self):
        from solidworks_mcp import registry
        from solidworks_mcp.core.policy import OperationClass
        registry.registered_tools()
        sw=BoundAutomation(self.root,self.doc);sw._register_managed_document(self.doc)
        def fail(_sw):
            self.doc.stamp+=1
            return {'success':False,'message':'native operation failed','data':{}}
        entry={'tool':SimpleNamespace(inputSchema={'type':'object','properties':{}}),
               'handler':fail,'operation_class':OperationClass.MUTATE,'postflight':None}
        with patch.dict(registry._TOOLS,{'safety_test_mutation':entry}):
            self.assertFalse(registry.execute('safety_test_mutation',sw,{}).result['success'])
        self.assertFalse(sw.save_document()['success'])
        self.assertTrue(sw.close_document()['success'])

    def test_preexisting_loaded_output_is_not_adopted_on_open(self):
        self.sw._adopt_newly_opened_output(self.doc, was_loaded=True)
        self.assertFalse(self.sw.save_document()['success'])

    def test_only_new_clean_output_can_be_adopted(self):
        self.sw._remember_managed_output(self.doc.path)  # Created/saved or copied by this session.
        self.sw._adopt_newly_opened_output(self.doc, was_loaded=False)
        self.assertIsNone(self.sw._managed_record(self.doc))  # dirty
        self.doc.dirty=False
        self.sw._adopt_newly_opened_output(self.doc, was_loaded=False)
        self.assertIsNotNone(self.sw._managed_record(self.doc))

    def test_cleanup_keeps_clean_preexisting_user_output(self):
        from solidworks_mcp.tools.session import _restart_blockers
        self.doc.dirty=False
        rows=[{'path':self.doc.path,'title':self.doc.GetTitle(),'unsaved_changes':False}]
        blockers=_restart_blockers(self.sw,rows)
        self.assertEqual(1,len(blockers))
        self.own();self.assertEqual([],_restart_blockers(self.sw,rows))

    def test_project_batch_registers_only_new_clean_output_before_editing(self):
        from solidworks_mcp.tools.parameter_batch import open_exact
        self.doc.dirty=False;app=self.sw._sw_app
        app.docs=[];app.ActiveDoc=None;app.new_document=self.doc
        self.sw.app=app;self.sw.is_connected=True
        self.sw._remember_managed_output(self.doc.path)
        with open_exact(self.sw,self.doc.path):
            self.assertIsNotNone(self.sw._managed_record(self.doc))

    def test_closed_user_file_in_output_root_is_not_adopted(self):
        self.doc.dirty=False
        self.sw._adopt_newly_opened_output(self.doc, was_loaded=False)
        self.assertIsNone(self.sw._managed_record(self.doc))
        self.assertFalse(self.sw.save_document()['success'])

    def test_externally_changed_known_file_is_not_adopted(self):
        self.doc.dirty=False;self.sw._remember_managed_output(self.doc.path)
        Path(self.doc.path).write_bytes(b'user edited saved file')
        self.sw._adopt_newly_opened_output(self.doc, was_loaded=False)
        self.assertIsNone(self.sw._managed_record(self.doc))

    def test_saveas_cannot_overwrite_an_unowned_user_file(self):
        self.own();target=self.root/'user.SLDPRT';target.write_bytes(b'user work')
        self.assertFalse(self.sw.save_document(str(target))['success'])
        self.assertEqual(b'user work',target.read_bytes());self.assertEqual([],self.doc.calls)

    def test_external_saved_edit_to_managed_file_blocks_overwrite(self):
        self.own();self.sw._remember_managed_output(self.doc.path)
        Path(self.doc.path).write_bytes(b'external user save')
        self.assertFalse(self.sw.save_document()['success'])
        self.assertFalse(self.sw.close_document()['success'])
        self.assertEqual([],self.doc.calls)

    def test_project_scope_attributes_failed_target_for_recovery(self):
        from solidworks_mcp.automation.document_safety import managed_operation
        self.own()
        with self.assertRaises(ValueError):
            with managed_operation(self.sw):
                self.doc.stamp+=1
                raise ValueError('failed project rebuild')
        self.assertTrue(self.sw.close_document()['success'])


if __name__=='__main__': unittest.main()
