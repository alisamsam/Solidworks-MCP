"""Verified additional Base Flange mode; called by the existing MCP tool."""
import math
import pythoncom
from win32com.client import VARIANT

from ..comutil import com,set_com
from ..constants import SwErrors
from .guard import require_stateful_document_access
from .save_bodies import _geometry,_same_geometry


def _snapshot(body):
    result=_geometry(body);mass=com(body,'GetMassProperties',0.)
    result['centroid_m']=[float(v) for v in mass[:3]]
    result['area_m2']=float(mass[4]);result['faces']=int(com(body,'GetFaceCount'))
    if (any(not math.isfinite(v) for v in result['centroid_m'])
            or not math.isfinite(result['area_m2']) or result['area_m2']<=0 or result['faces']<1):
        raise ValueError('Invalid existing body geometry.')
    return result


def _unchanged(first,second):
    return (_same_geometry(first,second) and first['faces']==second['faces']
            and math.isclose(first['area_m2'],second['area_m2'],rel_tol=1e-8,abs_tol=1e-12)
            and all(abs(a-b)<1e-8 for a,b in zip(first['centroid_m'],second['centroid_m'])))


def _sheet_features(doc):
    return [f for f in com(com(doc,'FeatureManager'),'GetFeatures',False) or [] if com(f,'GetTypeName2')=='SheetMetal']


def add_sheet_metal_body(sw,doc,thickness_mm,radius_mm,width_mm):
    # Import at call time: sheetmetal owns the registered tool and shared call.
    from .sheetmetal import _find_sheet_metal_feature,_insert_base_flange
    attempted=False
    def fail(message,code,modified=None):
        return sw._result(False,message,SwErrors.swFeatureError,
                          {'code':code,'document_may_be_modified':attempted if modified is None else modified})
    if com(doc,'GetType')!=1:return fail('Active document must be a part.','WRONG_DOCUMENT_TYPE')
    denied=require_stateful_document_access(sw,doc)
    if denied:return denied
    try:
        before=list(com(doc,'GetBodies2',0,False) or [])
        parent=_find_sheet_metal_feature(doc)
        if not before or parent is None:
            return fail('new_body requires existing sheet metal; create the first base flange normally.','NO_SHEET_METAL')
        if len(before)>256:return fail('Additional-body verification is limited to 256 existing solids.','BODY_LIMIT')
        old_geometry=[_snapshot(b) for b in before]
        previous_sheet_names={str(com(f,'Name')) for f in _sheet_features(doc)}
        parent_definition=com(parent,'GetDefinition')
        seed_thickness=float(com(parent_definition,'Thickness'))*1000
        seed_radius=float(com(parent_definition,'BendRadius'))*1000
        if not math.isfinite(seed_thickness) or seed_thickness<=0 or not math.isfinite(seed_radius) or seed_radius<0:
            return fail('Invalid parent sheet-metal defaults.','INVALID_PARENT_PARAMETERS')
        # Closing/selecting a sketch can modify document state before feature creation.
        attempted=True
        selected,sketch,message=sw._close_and_select_sketch(doc)
        if not selected:return fail('Could not select a fresh base-flange sketch: '+message,'SKETCH_SELECTION_FAILED')
        # Passing a different thickness here changes the shared defaults and
        # thickens older bodies. Seed with existing defaults, then override
        # the newly created per-body Sheet-Metal feature (native probe proven).
        feature=_insert_base_flange(doc,seed_thickness,seed_radius,width_mm)
        if feature is None:return fail('SolidWorks created no additional base flange.','FEATURE_CREATE_FAILED')
        new_sheets=[f for f in _sheet_features(doc) if str(com(f,'Name')) not in previous_sheet_names]
        if len(new_sheets)!=1:return fail('Expected one new per-body Sheet-Metal definition.','SHEET_DEFINITION_SCOPE_FAILED')
        sheet=new_sheets[0];definition=com(sheet,'GetDefinition');empty=VARIANT(pythoncom.VT_DISPATCH,None)
        if com(definition,'AccessSelections',doc,empty) is not True:
            return fail('Cannot access the new per-body sheet definition.','DEFINITION_ACCESS_FAILED')
        try:
            if com(definition,'SetOverrideDefaultParameter2',0,True)!=0:
                return fail('Native bend-parameter override failed.','OVERRIDE_FAILED')
            set_com(definition,'Thickness',thickness_mm/1000.)
            set_com(definition,'BendRadius',radius_mm/1000.)
            if com(sheet,'ModifyDefinition',definition,doc,empty) is not True:
                return fail('Could not apply independent sheet-body parameters.','MODIFY_FAILED')
        finally:com(definition,'ReleaseSelectionAccess')
        if com(doc,'EditRebuild3') is not True:return fail('Additional base flange rebuild failed.','REBUILD_FAILED')
        name=str(com(feature,'Name'));persisted=com(doc,'FeatureByName',name)
        if persisted is None or com(persisted,'GetTypeName2')!='SMBaseFlange':
            return fail('Persistent native Base Flange was not found.','FEATURE_NOT_PERSISTED')
        warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
        error=com(persisted,'GetErrorCode2',warning)
        if error or warning.value:return fail(f'Base Flange error {error}, warning {warning.value}.','FEATURE_ERROR')
        sheet=com(doc,'FeatureByName',str(com(sheet,'Name')))
        if sheet is None:return fail('Per-body Sheet-Metal definition did not persist.','FEATURE_NOT_PERSISTED')
        warning.value=False
        if com(sheet,'GetErrorCode2',warning) or warning.value:return fail('Per-body sheet definition reports an error/warning.','FEATURE_ERROR')
        definition=com(sheet,'GetDefinition')
        thickness=float(com(definition,'Thickness'))*1000
        radius=float(com(definition,'BendRadius'))*1000
        if (not math.isfinite(thickness) or not math.isfinite(radius)
                or not math.isclose(thickness,thickness_mm,rel_tol=1e-7,abs_tol=1e-6)
                or not math.isclose(radius,radius_mm,rel_tol=1e-7,abs_tol=1e-6)):
            return fail('Native thickness or radius differs from request.','PARAMETER_MISMATCH')
        after=list(com(doc,'GetBodies2',0,False) or [])
        if len(after)!=len(before)+1:return fail('Expected exactly one separate new solid; merging/splitting is not accepted.','BODY_COUNT_MISMATCH')
        faces=list(com(persisted,'GetFaces') or [])
        if not faces:return fail('The new Base Flange has no native faces.','BODY_IDENTITY_FAILED')
        feature_body=com(faces[0],'GetBody')
        new_indices=[i for i,b in enumerate(after) if com(sw.app,'IsSame',feature_body,b)==1]
        if len(new_indices)!=1:return fail('Could not identify the feature-owned new sheet body.','BODY_IDENTITY_FAILED')
        new_index=new_indices[0];body=after[new_index]
        if any(com(sw.app,'IsSame',com(f,'GetBody'),body)!=1 for f in faces):
            return fail('Base Flange faces span more than the new body.','BODY_IDENTITY_FAILED')
        # Rebuild can regenerate old native body identities. Compare the
        # remaining geometry as a multiset, with area/centroid/face count too.
        remaining=[_snapshot(b) for i,b in enumerate(after) if i!=new_index]
        for geometry in old_geometry:
            match=next((i for i,g in enumerate(remaining) if _unchanged(geometry,g)),None)
            if match is None:return fail('An existing solid changed or disappeared.','EXISTING_GEOMETRY_CHANGED')
            remaining.pop(match)
        if remaining:return fail('Existing body set changed.','EXISTING_GEOMETRY_CHANGED')
        if not com(body,'IsSheetMetal'):return fail('The new body is not native sheet metal.','NOT_SHEET_METAL')
        geometry=_geometry(body)
        return sw._result(True,f"Created separate sheet body '{com(body,'Name')}' from '{sketch}'.",data={
            'feature':name,'feature_type':'SMBaseFlange','sketch':sketch,'new_body':True,
            'sheet_metal_feature':str(com(sheet,'Name')),'independent_bend_parameters':True,
            'new_body_name':str(com(body,'Name')),'solid_body_index':new_index,
            'new_body_volume_mm3':geometry['volume_m3']*1e9,
            'new_body_box_mm':[x*1000 for x in geometry['box_m']],
            'thickness_mm':thickness,'bend_radius_mm':radius,'width_mm':width_mm,
            'bodies_before':len(before),'bodies_after':len(after),'existing_geometry_unchanged':True})
    except Exception as exc:return fail(f'Additional sheet body failed: {exc}','NATIVE_OPERATION_FAILED')
    finally:
        com(doc,'ClearSelection2',True)
