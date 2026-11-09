"""Verified copy batches. HTTP only queues; CAD runs on the MCP COM thread."""
from contextlib import contextmanager
from pathlib import Path
import math
import pythoncom
import win32com.client
from ..comutil import com
from ..core.policy import OperationClass
from ..registry import tool
from ..automation.document_safety import managed_operation
from .project_copy import require_editable_copy, _fail, _graph
from .model_edit import (_configuration, _factor, _dim_value, _number,
    _equations, _lhs, _canonical_dimension, set_model_dimension, list_model_parameters, _rebuild_checked)


@contextmanager
def open_exact(sw, path, *, allow_dirty=False):
    path = str(Path(path).resolve())
    if not sw.is_connected:
        result = sw.connect()
        if not result['success']: raise ValueError(result['message'])
    original = com(sw.app, 'ActiveDoc')
    title = com(original, 'GetTitle') if original is not None else None
    original_path = com(original, 'GetPathName') if original is not None else None
    existing = com(sw.app, 'GetOpenDocumentByName', path)
    if existing is not None and com(existing, 'GetSaveFlag') and not allow_dirty:
        raise ValueError('Document has unsaved changes; save or discard them before batch editing.')
    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    kind = {'.sldprt': 1, '.sldasm': 2, '.slddrw': 3}.get(Path(path).suffix.casefold())
    if kind is None: raise ValueError('Only native CAD documents are supported.')
    doc = win32com.client.dynamic.Dispatch(sw.app).OpenDoc6(path, kind, 1, '', errors, warnings)
    if doc is None or errors.value: raise ValueError(f'Open failed: {errors.value}')
    com(sw.app, 'ActivateDoc3', com(doc, 'GetTitle'), False, 1, 0)
    active = com(sw.app, 'ActiveDoc')
    if active is None or Path(com(active, 'GetPathName')).resolve() != Path(path):
        raise ValueError('Activated document does not match the exact requested path.')
    if hasattr(sw, '_adopt_newly_opened_output'):
        sw._adopt_newly_opened_output(doc, was_loaded=existing is not None)
    try:
        with managed_operation(sw):
            yield doc
    finally:
        # Leave unsaved partial results available; never silently discard writes.
        if existing is None and not com(doc, 'GetSaveFlag'):
            com(sw.app, 'CloseDoc', path)
        if title:
            com(sw.app, 'ActivateDoc3', title, False, 1, 0)
            restored=com(sw.app,'ActiveDoc')
            if restored is None or com(restored,'GetTitle') != title:raise ValueError('Original document activation failed')
            if original_path and Path(com(restored,'GetPathName')).resolve()!=Path(original_path).resolve():raise ValueError('Restored document path differs from original')
        if hasattr(sw,'bind_active_document') and com(sw.app,'ActiveDoc') is not None:sw.bind_active_document()


def _preflight(sw, changes):
    for change in changes:
        with open_exact(sw, change['document_path']) as doc:
            denied = require_editable_copy(sw, change['document_path'])
            if denied: raise ValueError(denied['message'])
            _configuration(doc, change['configuration'])
            dim = com(doc, 'Parameter', change['name'])
            if dim is None: raise ValueError('Dimension not found: ' + change['name'])
            factor = _factor(dim, change['unit'])
            target = _number(change['value']) * factor
            expected = _number(change['expected_value']) * factor
            if not math.isfinite(target) or not math.isfinite(expected): raise ValueError('Nonfinite converted value')
            if int(com(dim, 'GetType')) == 2 and not target.is_integer(): raise ValueError('Expected integer')
            if not math.isclose(_dim_value(dim), expected, rel_tol=1e-9, abs_tol=1e-12): raise ValueError('Stale dimension value')
            if com(dim, 'ReadOnly') or int(com(dim, 'DrivenState')) != 2: raise ValueError('Not a writable driving dimension')
            _, rows = _equations(doc)
            if any(_canonical_dimension(_lhs(r['expression'])) == _canonical_dimension(change['name']) for r in rows if not r['disabled']):
                raise ValueError('Equation controlled: change upstream equation instead')


CHANGE_SCHEMA = {'type':'object','properties':{
    'document_path':{'type':'string'}, 'configuration':{'type':'string'},
    'name':{'type':'string'}, 'value':{'type':'number'}, 'unit':{'type':'string'},
    'expected_value':{'type':'number'}},
    'required':['document_path','configuration','name','value','unit','expected_value'],
    'additionalProperties':False}

@tool(name='apply_parameter_changes', description='Preflight every requested dimension on verified copies, then apply exact active-configuration changes; partial failures never imply rollback.',
      schema={'type':'object','properties':{'changes':{'type':'array','items':CHANGE_SCHEMA,'minItems':1,'maxItems':100},'save':{'type':'boolean','default':False},'root_document':{'type':'string','description':'Optional copied assembly to rebuild and save after its changed children.'}},'required':['changes'],'additionalProperties':False},
      operation_class=OperationClass.PROJECT_WRITE)
def apply_parameter_changes(sw, changes, save=False, root_document=None):
    results=[]; saved=[]; attempted=False
    try:
        if type(save) is not bool: raise ValueError('save must be boolean')
        if not isinstance(changes,list) or not 1 <= len(changes) <= 100: raise ValueError('Expected 1..100 changes')
        seen=set()
        for change in changes:
            if not isinstance(change,dict) or set(change)!=set(CHANGE_SCHEMA['required']): raise ValueError('Invalid change fields')
            if any(not isinstance(change[k],str) or not change[k].strip() for k in ('document_path','configuration','name','unit')): raise ValueError('Missing target identity')
            key=(str(Path(change['document_path']).resolve()).casefold(), change['configuration'], _canonical_dimension(change['name']))
            if key in seen: raise ValueError('Duplicate driver in batch')
            seen.add(key); _number(change['value']); _number(change['expected_value'])
        _preflight(sw, changes)
        if root_document:
            with open_exact(sw,root_document):
                denied=require_editable_copy(sw,root_document)
                if denied:raise ValueError(denied['message'])
        for change in changes:
            with open_exact(sw, change['document_path'], allow_dirty=True):
                before = sw.bind_active_document() if hasattr(sw,'bind_active_document') else None
                attempted=True
                result=set_model_dimension(sw,**{k:v for k,v in change.items() if k!='document_path'})
                results.append({'document_path':change['document_path'],'configuration':change['configuration'],'name':change['name'],'result':result})
                if not result['success']: raise ValueError(result['message'])
                if before is not None: sw.mark_active_document_mutated(before)
                if save:
                    result=sw.save_document(change['document_path'])
                    if not result['success']: raise ValueError(result['message'])
                    saved.append(change['document_path'])
        if root_document:
            with open_exact(sw,root_document,allow_dirty=True) as doc:
                before=sw.bind_active_document() if hasattr(sw,'bind_active_document') else None
                if not com(doc,'ForceRebuild3',False) or not _rebuild_checked(doc):raise ValueError('Root assembly rebuild failed')
                if before is not None:sw.mark_active_document_mutated(before)
                if save:
                    r=sw.save_document(root_document)
                    if not r['success']:raise ValueError(r['message'])
                    saved.append(root_document)
        return sw._result(True,'Batch applied and read back.',data={'results':results,'saved_documents':sorted(set(saved)), 'saved':save,'root_document':root_document,'root_rebuild_verified':bool(root_document),'rollback_performed':False})
    except Exception as exc:
        return _fail(sw,str(exc),'BATCH_EDIT_FAILED',results=results,saved_documents=sorted(set(saved)),document_may_be_modified=attempted,rollback_performed=False)


@tool(name='inspect_parameter_dependencies', description='Read native document dependency graph, shared assembly occurrences and active equation drivers; does not infer missing engineering relationships.',
      schema={'type':'object','properties':{},'additionalProperties':False},operation_class=OperationClass.READ)
def inspect_parameter_dependencies(sw):
    doc,error=sw.get_active_doc()
    if error:return error
    try:
        path=com(doc,'GetPathName')
        graph=_graph(sw.app,[Path(path).resolve()])
        params=list_model_parameters(sw)
        occurrences=[]
        if int(com(doc,'GetType'))==2:
            occurrences=[{'instance':com(c,'Name2'),'document_path':com(c,'GetPathName'),'configuration':com(c,'ReferencedConfiguration')} for c in com(doc,'GetComponents',False) or []]
        return sw._result(True,'Saved file dependencies and current drivers read.',data={'document_path':path,'documents':[{'path':str(p),'references':[str(r) for r in refs]} for p,refs in graph.items()], 'occurrences':occurrences,'parameters':params,'coverage':'Native file references and active equations; no inferred design intent.'})
    except Exception as exc:return _fail(sw,str(exc),'DEPENDENCY_INSPECTION_FAILED')


@tool(name='import_parameter_workspace', description='Create a new workspace project from exact active-copy native documents and existing driving dimensions; no CAD dimensions changed.',
      schema={'type':'object','properties':{'name':{'type':'string'},'include_references':{'type':'boolean','default':True}},'required':['name'],'additionalProperties':False},operation_class=OperationClass.PROJECT_WRITE)
def import_parameter_workspace(sw,name,include_references=True):
    from ..workspace.parameter_store import ParameterStore
    project=None
    try:
        doc,error=sw.get_active_doc()
        if error:return error
        path=Path(com(doc,'GetPathName')).resolve()
        denied=require_editable_copy(sw,str(path))
        if denied:return denied
        graph=_graph(sw.app,[path]) if include_references else {path:[]}
        collected=[]
        for file in graph:
            with open_exact(sw,str(file)):
                r=list_model_parameters(sw)
                if not r['success']:raise ValueError(r['message'])
                collected.append(r['data'])
        store=ParameterStore();project=store.create_project(name);pid=project['id'];parent=None
        for p in collected:
            owner=store.add_owner(pid,{'kind':'assembly' if Path(p['path']).suffix.casefold()=='.sldasm' else 'part','name':Path(p['path']).stem,
                'parent_id':parent,'document_path':p['path'],'configuration':p['configuration']})
            if parent is None:parent=owner['id']
            for dim in p['dimensions']:
                writable=not dim['read_only'] and dim['driven_state']==2 and not dim['equation_controlled'] and dim['unit'] is not None
                store.add_parameter(pid,{'owner_id':owner['id'],'key':dim['name'],'label':dim['name'].split('@')[0]+' · '+dim['feature'],
                    'value_type':'integer' if dim['dimension_type']==2 else 'number','unit':dim['unit'],'role':'input' if writable else 'measurement',
                    'observed_value':dim['value'],'source':'Read from SolidWorks active configuration',
                    'binding':{'kind':'dimension','document_path':p['path'],'configuration':p['configuration'],'name':dim['name']}})
        return sw._result(True,'Existing CAD dimensions imported; engineering meanings need user confirmation.',data=store.snapshot(pid))
    except Exception as exc:return _fail(sw,str(exc),'WORKSPACE_IMPORT_FAILED',partial_project=project)


@tool(name='process_parameter_workspace_job', description='Claim one queued GUI job, apply its immutable dimension changes on verified copies via MCP, save and report results to the shared register.',
      schema={'type':'object','properties':{'project_id':{'type':'string'},'job_id':{'type':'string'}},'required':['project_id','job_id'],'additionalProperties':False},operation_class=OperationClass.PROJECT_WRITE)
def process_parameter_workspace_job(sw,project_id,job_id):
    from ..workspace.parameter_store import ParameterStore
    try:
        store=ParameterStore();job=store.claim_cad_job(project_id,job_id)
    except Exception as exc:return _fail(sw,str(exc),'WORKSPACE_JOB_CONFLICT')
    try:
        snap=store.snapshot(project_id)
        roots=[o['document_path'] for o in snap['owners'] if o['kind']=='assembly' and o['parent_id'] is None and o['document_path']]
        result=apply_parameter_changes(sw,[{k:v for k,v in c.items() if k!='parameter_id'} for c in job['changes']],save=True,root_document=roots[0] if len(roots)==1 else None)
    except Exception as exc:result=_fail(sw,str(exc),'WORKSPACE_EXECUTION_FAILED',document_may_be_modified=True)
    try:store.finish_cad_job(project_id,job_id,result)
    except Exception as exc:return _fail(sw,str(exc),'WORKSPACE_RESULT_RECORD_FAILED',cad_result=result,document_may_be_modified=True)
    return result
