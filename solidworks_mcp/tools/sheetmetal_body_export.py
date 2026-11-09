"""Export one sheet body's flat pattern only in a verified disposable copy."""
import hashlib
import json
from pathlib import Path

import pythoncom
from win32com.client import VARIANT

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .guard import require_output_write,require_stateful_document_access
from .project_copy import copy_project,_hash
from .save_bodies import _read_saved,_close_outputs
from .sheetmetal_bodies import list_sheet_metal_bodies
from .sheetmetal_multibody import _snapshot,_unchanged
from .component_edges import _selections,_restore


def _activate_source(app,doc,path):
    error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    # swDontRebuildActiveDoc=1: never prompt or rebuild the source on activation.
    activated=com(app,'ActivateDoc3',com(doc,'GetTitle'),False,1,error)
    active=com(app,'ActiveDoc')
    if activated is None or active is None or Path(com(active,'GetPathName')).resolve()!=path:
        raise ValueError('Cannot activate the exact expected document.')
    if error.value:raise ValueError(f'Activation reported {error.value}; no automatic source rebuild attempted.')


def _source_state(doc):
    bodies=list(com(doc,'GetBodies2',0,False) or [])
    if not 1<=len(bodies)<=256:raise ValueError('Source must have 1..256 solid bodies.')
    return dict(path=str(com(doc,'GetPathName')),stamp=int(com(doc,'GetUpdateStamp')),
        configuration=str(com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name')),
        dirty=bool(com(doc,'GetSaveFlag')),sha=_hash(Path(com(doc,'GetPathName'))),
        geometry=[_snapshot(body) for body in bodies])


def _same_source(before,after):
    return ({k:v for k,v in before.items() if k!='geometry'}=={k:v for k,v in after.items() if k!='geometry'}
        and len(before['geometry'])==len(after['geometry'])
        and all(_unchanged(a,b) for a,b in zip(before['geometry'],after['geometry'])))


def _same_selection(sw,before,after):
    return len(before)==len(after) and all(m==n and com(sw.app,'IsSame',a,b)==1 for (a,m),(b,n) in zip(before,after))


def _perform_export(sw,clone,target_row,source_geometry,out,configuration):
    if str(com(com(com(clone,'ConfigurationManager'),'ActiveConfiguration'),'Name'))!=configuration:
        com(clone,'ShowConfiguration2',configuration)
    if str(com(com(com(clone,'ConfigurationManager'),'ActiveConfiguration'),'Name'))!=configuration:
        raise ValueError('Copy configuration does not match the source.')
    if com(clone,'ForceRebuild3',False) is not True:
        raise ValueError('Disposable copy could not be rebuilt before export.')
    info=list_sheet_metal_bodies(sw)
    if not info['success'] or not info['data']['complete']:raise ValueError('Copy sheet-body inventory is incomplete.')
    matches=[row for row in info['data']['bodies'] if row['flat_pattern_feature']==target_row['flat_pattern_feature']]
    if len(matches)!=1:raise ValueError('Source flat-pattern identity is not unique in the verified copy.')
    row=matches[0];bodies=com(clone,'GetBodies2',0,False)
    body=bodies[row['solid_body_index']]
    if not _unchanged(source_geometry,_snapshot(body)) or row['parameters']!=target_row['parameters']:
        raise ValueError('Copy body geometry/parameters differs from requested source body.')
    flats=[f for f in com(body,'GetFeatures') or [] if com(f,'GetTypeName2')=='FlatPattern']
    unique=[]
    for flat in flats:
        if not any(com(sw.app,'IsSame',flat,other)==1 for other in unique):unique.append(flat)
    if len(unique)!=1 or str(com(unique[0],'Name'))!=target_row['flat_pattern_feature']:
        raise ValueError('Flat-pattern feature does not belong uniquely to the requested body.')
    flat=unique[0];com(clone,'ClearSelection2',True)
    if com(flat,'Select2',False,0) is not True:raise ValueError('Cannot select the exact copy flat pattern.')
    selected=_selections(clone)
    if len(selected)!=1 or com(sw.app,'IsSame',selected[0][0],flat)!=1:
        raise ValueError('Native selected flat pattern differs from requested body.')
    alignment=VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,[0.]*12)
    if com(clone,'ExportToDWG2',str(out),com(clone,'GetPathName'),1,True,alignment,False,False,1,VARIANT(pythoncom.VT_DISPATCH,None)) is not True:
        raise ValueError('Native per-body flat-pattern export failed.')
    return dict(selected_body_verified=True,copy_rebuilt=True,flat_pattern_feature=target_row['flat_pattern_feature'],
        geometry_verified=False,export_options='flat-pattern geometry only; no bend lines, sketches or nesting')


@tool(name='export_sheet_metal_body_dxf',description=(
    'Export one visible sheet body to flat.dxf in a NEW approved folder via an isolated saved-project copy. '
    'Requires fresh body_index/update_stamp from list_sheet_metal_bodies and a clean saved working source. '
    'Native export may reorder/dirty only the disposable copy. Verifies exact copied flat-pattern ownership and unchanged source/selection; closes copies without saving. '
    'Retains native-copy provenance; geometry-only DXF, no automatic nesting or all-body batch.'),
    schema={'type':'object','properties':{
        'body_index':{'type':'integer','minimum':0,'description':'Visible body_index from fresh list_sheet_metal_bodies.'},
        'expected_update_stamp':{'type':'integer','minimum':0,'description':'update_stamp returned by the same fresh inventory.'},
        'destination_folder':{'type':'string','description':'New approved folder outside the source project folder; contains flat.dxf, export.json and native-copy.'}},
        'required':['body_index','expected_update_stamp','destination_folder']},operation_class=OperationClass.EXPORT)
def export_sheet_metal_body_dxf(sw,body_index,expected_update_stamp,destination_folder):
    doc=None;before=None;saved_selection=None;copied=None;folder=None;created=False
    errors=[];exported={};restored=False;unchanged=False
    try:
        if type(body_index) is not int or body_index<0 or type(expected_update_stamp) is not int or expected_update_stamp<0:
            raise ValueError('body_index and expected_update_stamp must be nonnegative integers.')
        if not isinstance(destination_folder,str) or not destination_folder.strip():raise ValueError('New output folder required.')
        if getattr(sw,'_path_policy',None) is None:raise ValueError('Approved source/output path policy required.')
        folder=Path(destination_folder).expanduser().resolve()
        denied=require_output_write(sw,str(folder))
        if denied:return denied
        if folder.exists():raise ValueError('Destination must be a new folder; no overwrite.')
        doc,error=sw.get_active_doc()
        if error:return error
        if com(doc,'GetType')!=1:raise ValueError('Active document must be a part.')
        denied=require_stateful_document_access(sw,doc)
        if denied:return denied
        source_path=com(doc,'GetPathName')
        if not source_path or not Path(source_path).is_file():raise ValueError('Source must be a saved part.')
        dirty=com(doc,'GetSaveFlag')
        if type(dirty) is not bool:raise ValueError('Source saved-state flag is unavailable; refusing to assume clean.')
        if dirty:raise ValueError('Save the approved working source before exporting; unsaved changes are not copied.')
        if com(doc,'GetUpdateStamp')!=expected_update_stamp:raise ValueError('Stale body index; list sheet bodies again.')
        info=list_sheet_metal_bodies(sw)
        if not info['success'] or not info['data']['complete'] or info['data']['update_stamp']!=expected_update_stamp:
            raise ValueError('Fresh complete sheet-body inventory required.')
        matches=[row for row in info['data']['bodies'] if row['body_index']==body_index]
        if len(matches)!=1:raise ValueError('Visible sheet-body index not found; hidden/ordinary bodies cannot be exported by this index.')
        row=matches[0];before=_source_state(doc);saved_selection=_selections(doc)
        if before['stamp']!=expected_update_stamp:raise ValueError('Source changed after inventory; list sheet bodies again.')
        if len(saved_selection)>1024:raise ValueError('Source selection exceeds restoration limit.')
        source_geometry=_snapshot(com(doc,'GetBodies2',0,True)[body_index])
        folder.mkdir(parents=True,exist_ok=False);created=True
        result=copy_project(sw,source_path,str(folder/'native-copy'),include_drawings=False)
        if not result['success']:raise ValueError(result.get('message','Independent copy failed.'))
        copied=result['data'];clone_path=Path(copied['root_document'])
        def export(clone):
            _activate_source(sw.app,clone,clone_path)
            return _perform_export(sw,clone,row,source_geometry,folder/'flat.dxf',before['configuration'])
        exported,warning=_read_saved(sw.app,clone_path,1,export)
        # swFileLoadWarning_ReadOnly=2, NeedsRegen=32. Only the disposable copy
        # is rebuilt; a source activation warning is never solved by rebuilding.
        if warning & ~34 or (warning & 32 and not exported.get('copy_rebuilt')):
            raise ValueError(f'Native copy opened with unhandled warning {warning}; export not verified.')
        exported['copy_load_warning']=warning
        output=folder/'flat.dxf'
        if not output.is_file() or output.stat().st_size==0:raise ValueError('Native export did not produce a nonempty DXF.')
        exported.update(path=str(output),sha256=_hash(output),bytes=output.stat().st_size,body=row,
                        source_path=source_path,source_configuration=before['configuration'])
    except Exception as exc:errors.append(str(exc))
    finally:
        if copied is not None:
            try:_close_outputs(sw.app,[Path(f['copy']) for f in copied['files']])
            except Exception as exc:errors.append('Copy closure failed: '+str(exc))
        if before is not None:
            try:
                _activate_source(sw.app,doc,Path(before['path']));restored=True
                if not _same_selection(sw,saved_selection,_selections(doc)) and not _restore(sw,doc,saved_selection):
                    raise ValueError('Source selection could not be restored.')
                unchanged=_same_source(before,_source_state(doc))
                if copied:
                    unchanged=unchanged and all(_hash(Path(f['source']))==f['source_sha256'] for f in copied['files'])
                if not unchanged:errors.append('Source state or saved bytes changed; inspect source before further work.')
            except Exception as exc:errors.append('Source restoration/verification failed: '+str(exc))
    data={**exported,'source_unchanged':unchanged,'source_restored':restored,'saved_source':False,
          'output_folder':str(folder) if created else None,'native_copy_folder':str(folder/'native-copy') if copied else None,
          'status':'failed' if errors else 'verified','errors':errors}
    if created:
        try:
            with (folder/'export.json').open('x',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
        except Exception as exc:
            errors.append('Cannot write export manifest: '+str(exc));data['status']='failed'
    return sw._result(not errors,'; '.join(errors) if errors else 'Selected sheet body exported via isolated copy; source unchanged.',
                      SwErrors.swExportError if errors else SwErrors.swSuccess,data)
