"""Save Bodies must prove persisted geometry and preserve unrelated documents."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from solidworks_mcp.core.policy import PathPolicy, OperationClass
from solidworks_mcp.registry import operation_class_for
from solidworks_mcp.tools.save_bodies import save_bodies

class Body:
    def __init__(self,name,volume,offset=0):self.Name=name;self.volume=volume;self.offset=offset
    def GetMassProperties(self,density):return [0,0,0,self.volume]
    def GetBodyBox(self):return [self.offset,0,0,self.offset+.01,.02,.03]

class Feature:
    Name='Save Bodies1'
    def GetTypeName2(self):return 'CreateAssemFeat'
    def GetErrorCode2(self,warning):return 0
    def GetNextFeature(self):return None

class Component:
    def __init__(self,path):self.path=path
    def GetPathName(self):return self.path

class Doc:
    def __init__(self,path,bodies=None,kind=1):
        self.path=str(path);self.bodies=bodies or [];self.kind=kind;self.dirty=False
        self.FeatureManager=self;self.calls=[];self.feature=Feature();self.rebuild=True;self.created=False
    def GetPathName(self):return self.path
    def GetTitle(self):return Path(self.path).name
    def GetType(self):return self.kind
    def GetSaveFlag(self):return self.dirty
    def GetBodies2(self,kind,visible):return self.bodies
    def FeatureByName(self,name):return self.feature
    def FirstFeature(self):return self.feature if self.created else None
    def EditRebuild3(self):
        if self.app.require_active and self.app.ActiveDoc is not self:
            raise RuntimeError('Inactive source rebuild rejected')
        return self.rebuild
    def GetComponents(self,top):return self.components
    def CreateSaveBodyFeature(self,bodies,paths,assembly,consume,properties):
        self.calls.append((bodies.value,paths.value,assembly,consume,properties));self.dirty=True
        self.created=True
        if self.app.autosave_source:Path(self.path).write_bytes(b'natively saved source')
        if self.app.rename_source:
            self.bodies=[Body('Save Bodies1['+str(i)+']',b.volume,b.offset) for i,b in enumerate(reversed(self.bodies))]
        if self.app.missing_feature:return None
        if not self.app.skip_files:
            for body,path in zip(bodies.value,paths.value):
                Path(path).write_bytes(b'native child')
                child=Doc(path,[body] if not self.app.wrong_child else [Body('wrong',1)])
                self.app.saved[str(path)]=child;self.app.opened[str(path)]=child
            Path(assembly).write_bytes(b'native assembly')
            self.app.saved[assembly]=Doc(assembly,kind=2)
            self.app.saved[assembly].components=[Component(p) for p in paths.value]
            self.app.opened[assembly]=self.app.saved[assembly];self.app.ActiveDoc=self.app.saved[assembly]
        return self.feature

class App:
    def __init__(self,source):
        self.ActiveDoc=source;source.app=self;self.opened={source.path:source};self.saved={source.path:source}
        self.closed=[];self.reopened=[];self.missing_feature=False;self.skip_files=False;self.wrong_child=False;self.restore_fails=False;self.rename_source=False;self.require_active=False;self.autosave_source=False
    def GetDocuments(self):return list(self.opened.values())
    def GetOpenDocumentByName(self,path):return self.opened.get(path)
    def CloseDoc(self,title):
        self.closed.append(title)
        for path,doc in list(self.opened.items()):
            if doc.GetTitle()==title:del self.opened[path]
    def OpenDoc6(self,path,kind,options,config,error,warning):
        self.reopened.append((path,kind,options));doc=self.saved[path];self.opened[path]=doc;self.ActiveDoc=doc;return doc
    def ActivateDoc3(self,title,silent,rebuild,error):
        if self.restore_fails:return None
        self.ActiveDoc=next(d for d in self.opened.values() if d.GetTitle()==title);return self.ActiveDoc

class Sw:
    def __init__(self,root):
        source=root/'source.SLDPRT';source.write_bytes(b'original source')
        self.doc=Doc(source,[Body('small',12e-6),Body('large',50e-6,.1)])
        self.app=App(self.doc);self._path_policy=PathPolicy([root]);self.get_active_doc=Mock(return_value=(self.doc,None))
    def _result(self,success,message,error_code=None,data=None):return dict(success=success,message=message,data=data or {})

class SaveBodiesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.sw=Sw(self.root)
        self.args=dict(body_indices=[1,0],output_paths=[str(self.root/'large.SLDPRT'),str(self.root/'small.SLDPRT')],assembly_path=str(self.root/'parts.SLDASM'))
    def run_tool(self,**overrides):return save_bodies(self.sw,**(self.args|overrides))
    def test_native_feature_persisted_children_and_restored_source(self):
        result=self.run_tool();self.assertTrue(result['success'],result)
        bodies,paths,assembly,consume,properties=self.sw.doc.calls[0]
        self.assertEqual(['large','small'],[b.Name for b in bodies]);self.assertFalse(consume);self.assertFalse(properties)
        self.assertEqual(self.args['output_paths'],list(paths));self.assertEqual(self.sw.doc,self.sw.app.ActiveDoc)
        self.assertTrue(result['data']['source_save_required']);self.assertEqual(2,len(result['data']['parts']))
        self.assertEqual([50000.,12000.],[round(p['volume_mm3'],4) for p in result['data']['parts']])
        self.assertEqual(3,len(self.sw.app.reopened));self.assertEqual(b'original source',Path(self.sw.doc.path).read_bytes())
        self.assertNotIn('source.SLDPRT',self.sw.app.closed)
        self.assertEqual(OperationClass.MUTATE,operation_class_for('save_bodies'))
    def test_invalid_arguments_fail_before_com(self):
        for override in [dict(body_indices=[]),dict(body_indices=[True]),dict(body_indices=[-1]),dict(body_indices=[0,0]),dict(output_paths=['relative.SLDPRT','x.SLDPRT']),dict(output_paths=[str(self.root/'one.SLDPRT')]),dict(assembly_path=str(self.root/'bad.step'))]:
            with self.subTest(override=override):
                self.sw.get_active_doc.reset_mock();self.assertFalse(self.run_tool(**override)['success']);self.sw.get_active_doc.assert_not_called()
    def test_existing_output_preserved_and_com_not_read(self):
        p=Path(self.args['output_paths'][1]);p.write_bytes(b'KEEP')
        self.assertFalse(self.run_tool()['success']);self.assertEqual(b'KEEP',p.read_bytes());self.sw.get_active_doc.assert_not_called()
    def test_native_source_body_rename_and_reorder_preserve_geometry(self):
        self.sw.app.rename_source=True
        result=self.run_tool()
        self.assertTrue(result['success'],result)
        self.assertTrue(result['data']['source_geometry_unchanged'])
    def test_reactivate_source_before_rebuild_after_assembly_creation(self):
        self.sw.app.require_active=True
        result=self.run_tool()
        self.assertTrue(result['success'],result)
    def test_native_source_save_is_reported_on_approved_working_copy(self):
        self.sw.app.autosave_source=True
        result=self.run_tool()
        self.assertTrue(result['success'],result)
        self.assertTrue(result['data']['source_file_changed'])
    def test_existing_save_bodies_feature_refused_before_mutation(self):
        self.sw.doc.created=True
        result=self.run_tool()
        self.assertFalse(result['success'])
        self.assertEqual([],self.sw.doc.calls)
        self.assertFalse(result['data']['document_may_be_modified'])
    def test_protected_source_not_mutated(self):
        self.sw._path_policy=PathPolicy([self.root/'outputs'])
        self.args['output_paths']=[str(self.root/'outputs'/p) for p in ('one.SLDPRT','two.SLDPRT')];self.args['assembly_path']=str(self.root/'outputs/parts.SLDASM')
        self.assertFalse(self.run_tool()['success']);self.assertEqual([],self.sw.doc.calls)
    def test_unsaved_dirty_or_out_of_range_source_rejected(self):
        for field,value in [('path',''),('dirty',True),('kind',2)]:
            with self.subTest(field=field):
                old=getattr(self.sw.doc,field);setattr(self.sw.doc,field,value)
                self.assertFalse(self.run_tool()['success']);setattr(self.sw.doc,field,old)
        self.assertFalse(self.run_tool(body_indices=[1,8])['success']);self.assertEqual([],self.sw.doc.calls)
    def test_feature_proxy_without_files_is_failure(self):
        self.sw.app.skip_files=True;r=self.run_tool();self.assertFalse(r['success']);self.assertTrue(r['data']['document_may_be_modified'])
    def test_no_native_feature_is_failure(self):
        self.sw.app.missing_feature=True;self.assertFalse(self.run_tool()['success'])
    def test_wrong_saved_geometry_is_failure_and_source_restored(self):
        self.sw.app.wrong_child=True;r=self.run_tool();self.assertFalse(r['success']);self.assertEqual(self.sw.doc,self.sw.app.ActiveDoc)
    def test_failed_rebuild_is_failure(self):
        self.sw.doc.rebuild=False;self.assertFalse(self.run_tool()['success'])
    def test_restore_failure_is_not_reported_as_success(self):
        self.sw.app.restore_fails=True;self.assertFalse(self.run_tool()['success'])
    def test_same_basename_in_two_folders_is_rejected(self):
        self.assertFalse(self.run_tool(output_paths=[str(self.root/'a/body.SLDPRT'),str(self.root/'b/body.SLDPRT')])['success'])
        self.sw.get_active_doc.assert_not_called()
    def test_open_document_with_colliding_title_is_never_closed(self):
        other=Doc(self.root/'unrelated/large.SLDPRT');self.sw.app.opened[other.path]=other
        self.assertFalse(self.run_tool()['success']);self.assertEqual([],self.sw.doc.calls);self.assertEqual([],self.sw.app.closed)

if __name__=='__main__':unittest.main()
