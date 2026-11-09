"""Batch exports from one isolated assembly graph, with per-item coverage."""
import csv
import json
import os
import re
import tempfile
from pathlib import Path
import pythoncom
from win32com.client import VARIANT
from ..comutil import com
from ..core.policy import OperationClass
from ..core.progress import report_progress
from ..registry import tool
from .assembly_documentation import plan_assembly_documentation, _state, _sha, _cell
from .manufacturing_package import _active, _policy, _failure, _artifact
from .project_copy import copy_project, MANIFEST, _path
from .save_bodies import _close_outputs
from .sheetmetal_body_export import _activate_source, _perform_export
from .sheetmetal_multibody import _snapshot
from .manufacturing_bodies import inspect_part_manufacturing
from .sheetmetal_bodies import list_sheet_metal_bodies
from .export import export_step, export_face_to_dxf, _get_planar_face_by_index
from .documentation_drawing import _create_draft
from ..utils import find_template


def _validate_options(formats,item_ids):
    formats=['step','plate_dxf'] if formats is None else formats
    if not isinstance(formats,list) or not formats or any(f not in ('step','plate_dxf','sheet_dxf','drawing_pdf') for f in formats) or len(set(formats))!=len(formats):
        raise ValueError('formats must be unique nonempty step/plate_dxf/sheet_dxf/drawing_pdf values.')
    if item_ids is not None and (not isinstance(item_ids,list) or not item_ids or
        any(not isinstance(i,str) or re.fullmatch(r'K[0-9]{4,}',i) is None for i in item_ids) or len(set(item_ids))!=len(item_ids)):
        raise ValueError('item_ids must be unique exact K0001-style plan IDs, or omitted for all parts.')
    return formats


def _checked(result):
    if not result.get('success'):raise ValueError(result.get('message','Native operation failed.'))
    return result.get('data',{})


def _publish_report(path,report):
    """Readers always see a complete prior or new JSON document."""
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            json.dump(report,stream,indent=2,ensure_ascii=False)
        os.replace(temporary,path)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()


def _verify_plan_copy(planned,native):
    snapshot=planned.get('source_snapshot')
    if not isinstance(snapshot,list) or not snapshot:raise ValueError('Missing saved dependency snapshot; create a fresh plan.')
    expected={str(_path(row['path'])).casefold():row['sha256'] for row in snapshot}
    actual={str(_path(row['source'])).casefold():row['source_sha256'] for row in native['files']}
    if expected!=actual:raise ValueError('Saved source dependencies changed between planning and copying; inspect a fresh plan.')


@tool(name='request_manufacturing_package_stop',description=(
    'Request cooperative stop of a running assembly export package after its current part. '
    'Works beside the busy COM thread; never kills SolidWorks. Completed outputs remain. Requires approved running package folder.'),
    schema={'type':'object','properties':{'output_folder':{'type':'string'}},'required':['output_folder']},
    operation_class=OperationClass.PROJECT_WRITE,com=False,postflight='none')
def request_manufacturing_package_stop(sw,output_folder):
    try:
        folder=_path(output_folder);marker=folder/'00_Pregled/STOP.request';_policy(sw,marker)
        report_path=folder/'00_Pregled/exports.json'
        report=json.loads(report_path.read_text(encoding='utf-8'))
        if report.get('schema_version')!=1 or report.get('status')!='running' or not isinstance(report.get('items'),list):
            raise ValueError('Folder does not contain a running export package.')
        if not marker.exists():marker.write_text('Stop requested. Finish current item and restore source.\n',encoding='utf-8')
        return sw._result(True,'Stop requested; waiting for current part and normal cleanup.',data={
            'status':'stop_requested','output_folder':str(folder),'completed_items':len(report['items']),
            'current_native_call_interrupted':False})
    except Exception as exc:return _failure(sw,exc)


def _run_parts(sw,parts,mapping,folder,formats,template,projection,report):
    output=folder/'00_Pregled/exports.json'
    _publish_report(output,report)
    report['not_processed']=[]
    for index,item in enumerate(parts):
        if (folder/'00_Pregled/STOP.request').is_file():
            report.update(status='stopped',not_processed=[i['plan_id'] for i in parts[index:]])
            break
        report['items'].append(_process_part(sw,mapping[_path(item['document_path'])],item,folder,formats,template,projection))
        _publish_report(output,report)
        report_progress(index+1,len(parts)+1,f'export {item["plan_id"]}')
    if report['status']!='stopped':
        report['status']='partial_failure' if any(i['status']=='failed' for i in report['items']) else 'exported_needs_review'


def _process_part(sw,path,item,folder,formats,drawing_template=None,projection='first_angle'):
    app=sw.app; doc=None
    row=dict(plan_id=item['plan_id'],source_key=item['source_key'],document_path=item['document_path'],
        configuration=item['configuration'],quantity=item['quantity'],status='preparing',artifacts=[],skipped=[],errors=[])
    stem=item['plan_id']+'_'+re.sub(r'[^\w.-]+','_',Path(item['document_path']).stem)[:65]
    try:
        errors=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        warnings=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        doc=com(app,'OpenDoc6',str(path),1,3,item['configuration'],errors,warnings)
        if doc is None or errors.value or Path(com(doc,'GetPathName')).resolve()!=path:
            raise ValueError(f'Cannot open exact copied part: {errors.value}')
        row['load_warning_code']=int(warnings.value)
        if int(warnings.value)&~34:raise ValueError(f'Unhandled copy load warnings: {warnings.value}')
        _activate_source(app,doc,path)
        if str(com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name'))!=item['configuration']:
            com(doc,'ShowConfiguration2',item['configuration'])
        if str(com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name'))!=item['configuration']:
            raise ValueError('Copied part configuration mismatch.')
        if com(doc,'ForceRebuild3',False) is not True:raise ValueError('Copied part rebuild failed.')
        com(doc,'ClearSelection2',True)
        info=_checked(inspect_part_manufacturing(sw));row['inspection']=info
        if not info['bodies']:raise ValueError('Copied part has no readable solid bodies.')
        if not info['body_read_complete']:raise ValueError('Body geometry/identity inspection is incomplete; exports cannot be verified against requested bodies.')
        expected_faces={b['solid_body_index']:_get_planar_face_by_index(doc,b['plate_candidate']['face_index'])
            for b in info['bodies'] if b.get('plate_candidate') and b.get('visible')}
        if 'step' in formats:
            target=folder/'90_3D'/f'{stem}.step';_policy(sw,target)
            _checked(export_step(sw,str(target)))
            a=_artifact(target,'step');a.update(scope='whole_part',solid_body_count=info['solid_body_count'],
                tube_laser_ready=False,geometry_content_verified=False)
            row['artifacts'].append(a)
        if 'drawing_pdf' in formats:
            stem_path=folder/'01_Delavniske'/f'{stem}_OSNUTEK'
            try:
                draft=_create_draft(sw,doc,path,item['configuration'],stem_path,drawing_template,projection)
                row['drawing']=draft
                row['artifacts'].extend(draft['artifacts'])
            except Exception as exc:
                row['errors'].append({'kind':'drawing_pdf','reason':str(exc),
                    'partial_output_paths':[str(p) for p in (stem_path.with_suffix('.SLDDRW'),stem_path.with_suffix('.pdf')) if p.exists()]})
        if 'plate_dxf' in formats:
            for body in info['bodies']:
                if body.get('classification')!='plate_candidate' or not body.get('visible'):
                    row['skipped'].append({'kind':'plate_dxf','body':body['solid_body_index'],'reason':'Not a visible geometric plate candidate.'});continue
                target=folder/'02_Laser_plosce'/f'{stem}_B{body["solid_body_index"]+1:03d}_KANDIDAT.dxf'
                _policy(sw,target);target.parent.mkdir(parents=True,exist_ok=True)
                try:
                    # Export can refresh body traversal. Never reuse a prior face ordinal blindly.
                    current_faces=[face for native in com(doc,'GetBodies2',0,True) or [] for face in com(native,'GetFaces') or []]
                    indices=[i for i,face in enumerate(current_faces) if com(app,'IsSame',face,expected_faces[body['solid_body_index']])==1]
                    if len(indices)!=1:raise ValueError('Requested copied plate face no longer has unique native identity.')
                    _checked(export_face_to_dxf(sw,indices[0],str(target)))
                    a=_artifact(target,'plate_dxf');a.update(body=body['solid_body_index'],
                        thickness_mm=body['plate_candidate']['thickness_mm'],fabrication_confirmed=False)
                    row['artifacts'].append(a)
                except Exception as exc:row['errors'].append({'kind':'plate_dxf','body':body['solid_body_index'],'reason':str(exc)})
        if 'sheet_dxf' in formats:
            sheets=info.get('sheet_metal')
            if sheets and not sheets['complete']:raise ValueError('Incomplete native sheet-body inventory.')
            for body in info['bodies']:
                if body['classification']!='native_sheet_metal' or not body.get('visible'):
                    row['skipped'].append({'kind':'sheet_dxf','body':body['solid_body_index'],'reason':'Not a visible native sheet-metal body.'});continue
                original=next((b for b in sheets['bodies'] if b['solid_body_index']==body['solid_body_index']),None)
                if original is None:raise ValueError('Native sheet body does not have unique sheet parameters.')
                target=folder/'02_Laser_plosce'/f'{stem}_B{body["solid_body_index"]+1:03d}_RAZVITJE.dxf'
                _policy(sw,target);target.parent.mkdir(parents=True,exist_ok=True)
                try:
                    # Native flat export can reorder bodies; rebind by native-owned feature each time.
                    fresh=_checked(list_sheet_metal_bodies(sw))
                    if not fresh['complete']:raise ValueError('Refreshed native sheet inventory is incomplete.')
                    matches=[b for b in fresh['bodies'] if b['flat_pattern_feature']==original['flat_pattern_feature']]
                    if len(matches)!=1:raise ValueError('Flat-pattern identity is ambiguous after previous export.')
                    current=matches[0];native=com(doc,'GetBodies2',0,False)[current['solid_body_index']]
                    details=_perform_export(sw,doc,current,_snapshot(native),target,item['configuration'])
                    a=_artifact(target,'sheet_dxf');a.update(body=body['solid_body_index'],verification=details)
                    row['artifacts'].append(a)
                except Exception as exc:row['errors'].append({'kind':'sheet_dxf','body':body['solid_body_index'],'reason':str(exc)})
        row['status']='failed' if row['errors'] else 'exported_needs_review'
    except Exception as exc:
        row['status']='failed';row['errors'].append({'reason':str(exc)})
    finally:
        if doc is not None:
            try:com(app,'CloseDoc',com(doc,'GetTitle'))
            except Exception as exc:row['status']='failed';row['errors'].append({'reason':'Cannot close generated part: '+str(exc)})
    return row


@tool(name='export_assembly_manufacturing_package',description=(
    'Create a fresh assembly plan, one isolated native graph and batch exact-configuration part STEP, geometric plate-candidate DXF and optional native sheet-body DXF. '
    'Optional three-view draft PDFs/native drawings; no full dimensioning. Whole-part STEP is not per-body tube laser. '
    'Records per-item failures/skips and quantities, restores source and closes copies. No nesting or manufacturing certification; new output folder required. Up to 200 selected parts.'),
    schema={'type':'object','properties':{'document_path':{'type':'string'},'configuration':{'type':'string'},
        'output_folder':{'type':'string'},'formats':{'type':'array','uniqueItems':True,'minItems':1,
            'items':{'type':'string','enum':['step','plate_dxf','sheet_dxf','drawing_pdf']},'default':['step','plate_dxf']},
        'projection':{'type':'string','enum':['first_angle','third_angle'],'default':'first_angle'},
        'drawing_template_path':{'type':'string','description':'Existing .drwdot for drawing_pdf; omit for installed draft template.'},
        'expected_plan_fingerprint':{'type':'string','minLength':64,'maxLength':64,
            'description':'Required with item_ids: plan_fingerprint from fresh plan_assembly_documentation.'},
        'item_ids':{'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'string'},
            'description':'Exact IDs from a fresh plan on unchanged assembly, or omit for all active parts.'}},
        'required':['document_path','configuration','output_folder']},operation_class=OperationClass.PROJECT_WRITE)
def export_assembly_manufacturing_package(sw,document_path,configuration,output_folder,formats=None,item_ids=None,projection='first_angle',drawing_template_path=None,expected_plan_fingerprint=None):
    folder=None;created=False;doc=None;before=None;copies=[];source_hashes={};report=None;failure=None;cleanup_ok=False
    try:
        formats=_validate_options(formats,item_ids)
        if (item_ids is not None or expected_plan_fingerprint is not None) and (not isinstance(expected_plan_fingerprint,str) or re.fullmatch(r'[0-9a-fA-F]{64}',expected_plan_fingerprint) is None):
            raise ValueError('Subset IDs require expected_plan_fingerprint from a fresh plan; labels alone are not stable identity.')
        folder=_path(output_folder);_policy(sw,folder)
        if folder.exists():raise ValueError('output_folder must be new.')
        if projection not in ('first_angle','third_angle'):raise ValueError('Unsupported drawing projection.')
        template=None
        if 'drawing_pdf' in formats:
            template=_path(drawing_template_path or find_template('drawing'))
            if not template.is_file() or template.suffix.casefold()!='.drwdot':raise ValueError('Existing drawing template required.')
        planned=_checked(plan_assembly_documentation(sw,document_path,configuration,str(folder)));created=True
        if not planned['inventory_complete']:raise ValueError('Resolve inventory exclusions explicitly before batch export.')
        if expected_plan_fingerprint is not None and planned['plan_fingerprint']!=expected_plan_fingerprint.casefold():
            raise ValueError('Plan fingerprint changed; inspect the new plan before choosing subset IDs.')
        all_items={i['plan_id']:i for i in planned['items']}
        if item_ids is not None and any(i not in all_items for i in item_ids):raise ValueError('Unknown plan item ID.')
        selected=[all_items[i] for i in item_ids] if item_ids else list(all_items.values())
        parts=[i for i in selected if i['document_type']=='part']
        if not 1<=len(parts)<=200:raise ValueError('Select between 1 and 200 parts.')
        doc=_active(sw,_path(document_path),configuration);before=_state(doc)
        _checked(copy_project(sw,document_path,str(folder/'99_Native'),include_drawings=False))
        native=json.loads((folder/'99_Native'/MANIFEST).read_text(encoding='utf-8'))
        mapping={_path(r['source']):_path(r['copy']) for r in native['files']}
        copies=list(mapping.values());source_hashes={_path(r['source']):r['source_sha256'] for r in native['files']}
        _verify_plan_copy(planned,native)
        report={'schema_version':1,'status':'running','document_path':document_path,'configuration':configuration,
            'formats':formats,'manufacturing_ready':False,'items':[],
            'source_unchanged':False,'copies_closed':False,'source_restored':False,
            'not_selected':[i['plan_id'] for i in planned['items'] if i not in selected],
            'non_part_items':[i['plan_id'] for i in selected if i['document_type']!='part'],
            'limitations':['Make/buy is unconfirmed: these are review exports, not a released production batch.',
                'Plate DXF is a geometric candidate. Confirm material, thickness, contour, scale and process.',
                'STEP is whole part, including multibody geometry; it is not a split tube-laser order.',
                'Drawing drafts are optional; complete dimensions, nesting and tube-machine compatibility are not verified.']}
        output=folder/'00_Pregled/exports.json';_policy(sw,output)
        _run_parts(sw,parts,mapping,folder,formats,template,projection,report)
    except Exception as exc:failure=str(exc)
    finally:
        if copies:
            try:
                _close_outputs(sw.app,copies);cleanup_ok=True
            except Exception as exc:failure=(failure+'; ' if failure else '')+'Copy cleanup: '+str(exc)
        if doc is not None:
            try:
                _activate_source(sw.app,doc,_path(document_path))
                if _state(doc)!=before:raise ValueError('Source assembly state changed.')
                for path,digest in source_hashes.items():
                    if _sha(path)!=digest:raise ValueError('Source hash changed: '+str(path))
                    loaded=com(sw.app,'GetOpenDocumentByName',str(path))
                    if loaded is not None and com(loaded,'GetSaveFlag'):raise ValueError('Source component has unsaved edits: '+str(path))
                if report is not None:report.update(source_unchanged=True,copies_closed=cleanup_ok,source_restored=True)
            except Exception as exc:failure=(failure+'; ' if failure else '')+str(exc)
    if created:
        try:
            report=report or {'items':[],'manufacturing_ready':False}
            if failure:report.update(status='failed',error=failure)
            output=folder/'00_Pregled/exports.json';_policy(sw,output)
            _publish_report(output,report)
            table=folder/'00_Pregled/kazalo-izvozov.csv';_policy(sw,table)
            with table.open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream,delimiter=';');writer.writerow(['Oznaka','Datoteka','Konfiguracija','Kolicina','Stanje','Izvozi','Napake'])
                for row in report['items']:
                    writer.writerow([_cell(v) for v in (row['plan_id'],row['document_path'],row['configuration'],row['quantity'],row['status'],
                        ' | '.join(a['path'] for a in row['artifacts']),json.dumps(row['errors'],ensure_ascii=False))])
            report['report_path']=str(output);report['artifact_count']=sum(len(r['artifacts']) for r in report['items'])
        except Exception as exc:failure=(failure+'; ' if failure else '')+'Report write: '+str(exc)
    if failure:return _failure(sw,failure,output_folder=str(folder),report=report)
    if report and report['status']=='stopped':return _failure(sw,'Package stopped after completed item; source restored and copies closed.',report=report)
    if report and report['status']=='partial_failure':return _failure(sw,'Some exports failed; successful outputs retained in report.',report=report)
    if report is not None:
        report_progress(1,1,'exported; review required')
        return sw._result(True,'Assembly exports written; manufacturing review remains required.',data=report)
    return _failure(sw,'No export package was created.')
