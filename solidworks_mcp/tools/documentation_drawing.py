"""Verified drawing references and projection; dimension coverage stays explicit."""
import json
import math
from pathlib import Path
import pythoncom
from win32com.client import VARIANT
from ..comutil import com, set_com
from ..core.policy import OperationClass
from ..registry import tool
from ..utils import find_template
from .assembly_documentation import _state, _sha
from .manufacturing_package import _active, _policy, _failure, _artifact
from .project_copy import copy_project, MANIFEST, _path
from .sheetmetal_body_export import _activate_source
from .save_bodies import _close_outputs, _read_saved
from .export import _export_native_model


def _set_projection(sheet,projection):
    props=list(com(sheet,'GetProperties2'))
    first=projection=='first_angle'
    com(sheet,'SetProperties2',int(props[0]),int(props[1]),float(props[2]),float(props[3]),first,float(props[5]),float(props[6]),bool(props[7]))
    if bool(com(sheet,'GetProperties2')[4])!=first:raise ValueError('Sheet projection did not match the requested projection.')


def _views(drawing):
    first=com(drawing,'GetFirstView');view=com(first,'GetNextView') if first is not None else None
    result=[]
    while view is not None:
        result.append(view)
        if len(result)>20:raise ValueError('Unexpected excessive view count in new drawing.')
        view=com(view,'GetNextView')
    return result


def _set_position(view,x,y):
    # Raw Python lists/tuples become SAFEARRAY(VARIANT), which silently writes
    # [0,x] in SW2025. IView.Position requires SAFEARRAY(double).
    set_com(view,'Position',VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,[float(x),float(y)]))
    actual=list(com(view,'Position'))
    if len(actual)!=2 or abs(actual[0]-x)>1e-6 or abs(actual[1]-y)>1e-6:
        raise ValueError('Native view position did not match the requested sheet coordinates.')


def _view_snapshot(views,path,configuration):
    result=[]
    for view in views:
        reference=Path(com(view,'GetReferencedModelName')).resolve()
        if reference!=path:raise ValueError('Drawing view references a different model.')
        cfg=str(com(view,'ReferencedConfiguration'))
        if cfg!=configuration:raise ValueError('Drawing view configuration mismatch.')
        outline=[float(x) for x in com(view,'GetOutline')]
        if len(outline)!=4 or not all(math.isfinite(x) for x in outline) or outline[2]<=outline[0] or outline[3]<=outline[1]:
            raise ValueError('Drawing view has an empty or invalid outline.')
        result.append({'name':str(com(view,'GetName2')),'reference':str(reference),'configuration':cfg,'outline_m':outline})
    return result


def _finish(sw,copies,source,before,path,hashes):
    failures=[]
    try:
        if copies:_close_outputs(sw.app,copies)
    except Exception as exc:failures.append('Copy cleanup: '+str(exc))
    # Cleanup errors must not suppress restoration or integrity checks.
    if source is not None:
        try:
            _activate_source(sw.app,source,path)
            if _state(source)!=before:raise ValueError('Source state changed.')
            if any(_sha(p)!=digest for p,digest in hashes.items()):raise ValueError('Source hash changed.')
        except Exception as exc:failures.append('Source restoration: '+str(exc))
    return failures


def _layout(drawing,views,path,configuration):
    sheet=com(drawing,'GetCurrentSheet');props=list(com(sheet,'GetProperties2'))
    width,height=float(props[5]),float(props[6])
    if width<.1 or height<.1:raise ValueError('Invalid sheet dimensions.')
    # Keep room for the draft heading and template title block. Preserve native
    # relative view alignment; never force a model orientation from its filename.
    box=[.018,.055,width-.018,height-.035]
    positions=[list(com(v,'Position')) for v in views]
    vertical=min((1,2),key=lambda i:abs(positions[i][0]-positions[0][0])/(abs(positions[i][1]-positions[0][1])+1e-9))
    horizontal=3-vertical
    dx=positions[horizontal][0]-positions[0][0];dy=positions[vertical][1]-positions[0][1]
    if abs(dx)<1e-6 or abs(dy)<1e-6:raise ValueError('Native standard-view arrangement is ambiguous.')
    def sizes():
        return [(r['outline_m'][2]-r['outline_m'][0],r['outline_m'][3]-r['outline_m'][1])
                for r in _view_snapshot(views,path,configuration)]
    dims=sizes();gap=.012
    needed_width=max(dims[0][0],dims[vertical][0])+dims[horizontal][0]
    needed_height=max(dims[0][1],dims[horizontal][1])+dims[vertical][1]
    factor=min((box[2]-box[0]-gap)/needed_width,(box[3]-box[1]-gap)/needed_height)
    # Installed templates may start at 1:50. Fit upwards as well as downwards
    # so an otherwise valid draft does not leave its useful view miniature.
    if factor<.95 or factor>1.1:
        scale=float(props[2])/float(props[3])*factor*.92
        denominator=max(1,math.ceil(1/scale))
        com(sheet,'SetScale',1.,float(denominator),True,True)
        com(drawing,'ForceRebuild3',False)
    # Sheet-scale changes resize geometry, but leave the original center gaps.
    # Place the three aligned views explicitly inside two columns/two rows.
    dims=sizes();column=max(dims[0][0],dims[vertical][0]);row_height=max(dims[0][1],dims[horizontal][1])
    base_x=box[0]+column/2 if dx>0 else box[2]-column/2
    side_x=box[2]-dims[horizontal][0]/2 if dx>0 else box[0]+dims[horizontal][0]/2
    base_y=box[3]-row_height/2 if dy<0 else box[1]+row_height/2
    vertical_y=box[1]+dims[vertical][1]/2 if dy<0 else box[3]-dims[vertical][1]/2
    _set_position(views[0],base_x,base_y)
    _set_position(views[vertical],base_x,vertical_y)
    _set_position(views[horizontal],side_x,base_y)
    com(drawing,'ForceRebuild3',False)
    rows=_view_snapshot(views,path,configuration)
    outside=[r['name'] for r in rows if r['outline_m'][0]<box[0]-.001 or r['outline_m'][1]<box[1]-.001 or r['outline_m'][2]>box[2]+.001 or r['outline_m'][3]>box[3]+.001]
    overlaps=[]
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            aa,bb=a['outline_m'],b['outline_m']
            if min(aa[2],bb[2])-max(aa[0],bb[0])>.001 and min(aa[3],bb[3])-max(aa[1],bb[1])>.001:
                overlaps.append([a['name'],b['name']])
    return {'sheet_width_m':width,'sheet_height_m':height,'view_bounds_checked':True,
        'views_outside_reserved_area':outside,'overlapping_view_boxes':overlaps,'views':rows,
        'layout_needs_review':bool(outside or overlaps)}


def _create_draft(sw,model,path,configuration,stem,template,projection):
    """Only callers' generated copied models are accepted by the public workflows."""
    drawing=None;app=sw.app;native=stem.with_suffix('.SLDDRW');pdf=stem.with_suffix('.pdf')
    for target in (native,pdf):
        _policy(sw,target)
        if target.exists():raise ValueError('Drawing output already exists.')
    stem.parent.mkdir(parents=True,exist_ok=True)
    try:
        drawing=com(app,'NewDocument',str(template),0,0.,0.)
        if drawing is None or com(drawing,'GetType')!=3:raise ValueError('Cannot create native drawing from template.')
        sheet=com(drawing,'GetCurrentSheet');_set_projection(sheet,projection)
        method='Create1stAngleViews2' if projection=='first_angle' else 'Create3rdAngleViews2'
        if com(drawing,method,str(path)) is not True:raise ValueError('Native standard-view creation failed.')
        views=_views(drawing)
        if len(views)!=3:raise ValueError('Native drawing did not create exactly three model views.')
        for view in views:set_com(view,'ReferencedConfiguration',configuration)
        if com(drawing,'ForceRebuild3',False) is not True:raise ValueError('Drawing rebuild failed.')
        layout=_layout(drawing,views,path,configuration)
        if layout['layout_needs_review']:raise ValueError('Generated drawing view layout needs correction: '+json.dumps(layout))
        com(drawing,'ClearSelection2',True)
        note=com(drawing,'InsertNote','OSNUTEK - NI ZA IZDELAVO\nMere in tolerance zahtevajo pregled.')
        if note is None:raise ValueError('Cannot insert mandatory draft heading.')
        annotation=com(note,'GetAnnotation')
        com(annotation,'SetPosition2',.018,layout['sheet_height_m']-.012,0.)
        _view_snapshot(views,path,configuration)
        for target,extensions,label in [(native,{'.slddrw'},'SLDDRW'),(pdf,{'.pdf'},'PDF')]:
            result=_export_native_model(sw,str(target),extensions,label)
            if not result.get('success'):raise ValueError(result.get('message','Drawing save failed.'))
            if result.get('data',{}).get('save_warning_code'):raise ValueError('Drawing save returned warnings; inspect output.')
        title=com(drawing,'GetTitle');com(app,'CloseDoc',title);drawing=None
        def readback(saved):
            saved_sheet=com(saved,'GetCurrentSheet')
            if bool(com(saved_sheet,'GetProperties2')[4])!=(projection=='first_angle'):raise ValueError('Reopened projection differs.')
            actual=_views(saved)
            if len(actual)!=3:raise ValueError('Reopened view count differs.')
            return _view_snapshot(actual,path,configuration)
        reopened,warnings=_read_saved(app,native,3,readback)
        if warnings&~2:raise ValueError('Reopened drawing warnings: '+str(warnings))
        return {'status':'draft_needs_review','projection':projection,'configuration':configuration,
            'artifacts':[_artifact(native,'native_drawing'),_artifact(pdf,'drawing_pdf')],
            'layout':layout,'reopened_views':reopened,'native_reopen_verified':True,
            'dimension_coverage_verified':False,'dimensions_added':0,'manufacturing_ready':False,
            'limitations':['Three native orthographic views; no automatic complete dimensioning or drawing release.',
                'Template title block, material, tolerances and project-specific views require review.']}
    finally:
        if drawing is not None:com(app,'CloseDoc',com(drawing,'GetTitle'))
        _activate_source(app,model,path)


@tool(name='create_documentation_drawing',description=(
    'Create a NEW isolated model graph and native/PDF three-view drawing draft from an exact clean saved active part or assembly. '
    'Explicit first/third angle projection, copied model/configuration references and saved drawing readback verified; draft heading mandatory. '
    'No full dimensioning, BOM, welding/installation engineering or production release. Closes own documents, restores source.'),
    schema={'type':'object','properties':{'document_path':{'type':'string'},'configuration':{'type':'string'},
        'output_folder':{'type':'string'},'projection':{'type':'string','enum':['first_angle','third_angle'],'default':'first_angle'},
        'template_path':{'type':'string','description':'Existing .drwdot; omit for installed drawing template (draft only).'}},
        'required':['document_path','configuration','output_folder']},operation_class=OperationClass.PROJECT_WRITE)
def create_documentation_drawing(sw,document_path,configuration,output_folder,projection='first_angle',template_path=None):
    source=None;before=None;folder=None;created=False;copies=[];hashes={};result=None;failure=None
    try:
        folder=_path(output_folder);_policy(sw,folder)
        if folder.exists():raise ValueError('output_folder must be new.')
        if projection not in ('first_angle','third_angle'):raise ValueError('Unsupported projection.')
        template=_path(template_path or find_template('drawing'))
        if not template.is_file() or template.suffix.casefold()!='.drwdot':raise ValueError('An existing drawing template is required.')
        path=_path(document_path);source=_active(sw,path,configuration);before=_state(source)
        kind=int(com(source,'GetType'))
        if kind not in (1,2) or before[3] or not path.is_file():raise ValueError('Clean saved part or assembly required.')
        folder.mkdir(parents=True,exist_ok=False);created=True
        copied=copy_project(sw,str(path),str(folder/'99_Native'),include_drawings=False)
        if not copied.get('success'):raise ValueError(copied.get('message','Copy failed.'))
        manifest=copied['data'];copies=[_path(r['copy']) for r in manifest['files']]
        hashes={_path(r['source']):r['source_sha256'] for r in manifest['files']}
        model_path=_path(manifest['root_document'])
        errors=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0);warnings=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        model=com(sw.app,'OpenDoc6',str(model_path),kind,3,configuration,errors,warnings)
        if model is None or errors.value or warnings.value&~34:raise ValueError('Cannot open generated model without unhandled warnings.')
        _activate_source(sw.app,model,model_path)
        if str(com(com(com(model,'ConfigurationManager'),'ActiveConfiguration'),'Name'))!=configuration:com(model,'ShowConfiguration2',configuration)
        if str(com(com(com(model,'ConfigurationManager'),'ActiveConfiguration'),'Name'))!=configuration:raise ValueError('Copy configuration mismatch.')
        if com(model,'ForceRebuild3',False) is not True:raise ValueError('Copy rebuild failed.')
        target=folder/('01_Delavniske' if kind==1 else '05_Sestavne')/'OSNUTEK'
        result=_create_draft(sw,model,model_path,configuration,target,template,projection)
        result.update(template_path=str(template),source_document=str(path),source_configuration=configuration)
    except Exception as exc:failure=str(exc)
    finally:
        final_errors=_finish(sw,copies,source,before,_path(document_path) if source is not None else None,hashes)
        if final_errors:failure=(failure+'; ' if failure else '')+'; '.join(final_errors)
    if created:
        try:
            report=dict(result or {},status='failed' if failure else 'draft_needs_review',error=failure,manufacturing_ready=False)
            report_path=folder/'drawing.json';_policy(sw,report_path)
            report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        except Exception as exc:failure=(failure+'; ' if failure else '')+str(exc)
    if failure:return _failure(sw,failure,output_folder=str(folder),report=result)
    return sw._result(True,'Drawing draft created and reopened; dimension coverage remains unverified.',data=result)
