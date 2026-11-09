"""Read construction evidence without selection access or feature rollback."""
from ..comutil import com
from ..registry import tool
from ..core.policy import OperationClass
from ..constants import SwErrors

@tool(name='inspect_construction_geometry', description=(
    'Read a named sketch line/arc endpoint geometry in sketch coordinates, or structural-member profile path. '
    'Reports endpoint extent midpoint, not a general curve bounding box or mass centroid; never selects, edits or saves.'),
    schema={'type':'object','properties':{'feature_name':{'type':'string'}},'required':['feature_name']},
    operation_class=OperationClass.READ)
def inspect_construction_geometry(sw,feature_name):
    doc,error=sw.get_active_doc()
    if error:return error
    try:
        if not isinstance(feature_name,str) or not feature_name.strip():raise ValueError('Named feature required.')
        feature=com(doc,'FeatureByName',feature_name)
        if feature is None:raise ValueError('Feature not found: '+feature_name)
        kind=com(feature,'GetTypeName2')
        data={'document_path':com(doc,'GetPathName'),'feature_name':feature_name,'feature_type':kind,
              'complete':True,'unresolved':[],'saved':False}
        if kind=='WeldMemberFeat':
            definition=com(feature,'GetDefinition')
            data['profile_path']=com(definition,'WeldmentProfilePath')
            data['profile_insertion_point']=None
            # Selection access would roll the model back; do not infer locate-point evidence.
            data['unresolved'].append('Profile insertion point not read; no AccessSelections/rollback performed.')
            data['complete']=False
            return sw._result(True,'Structural profile path read without changing model.',data=data)
        if kind not in ('ProfileFeature','3DProfileFeature'):
            raise ValueError('Requires a sketch or WeldMemberFeat.')
        sketch=com(feature,'GetSpecificFeature2')
        points=[];segments=[]
        for segment in com(sketch,'GetSketchSegments') or []:
            try:
                if com(segment,'ConstructionGeometry'):continue
                skind=int(com(segment,'GetType'))
                if skind not in (0,1):raise ValueError('Only line/arc endpoints are supported.')
                pair=[]
                for member in ('GetStartPoint2','GetEndPoint2'):
                    point=com(segment,member)
                    pair.append([float(com(point,axis))*1000 for axis in ('X','Y','Z')])
                entry={'type':skind,'start_mm':pair[0],'end_mm':pair[1]}
                if skind==1:
                    center=com(segment,'GetCenterPoint2')
                    entry.update(center_mm=[float(com(center,axis))*1000 for axis in ('X','Y','Z')],
                                 radius_mm=float(com(segment,'GetRadius'))*1000,
                                 rotation_direction=int(com(segment,'GetRotationDir')))
                segments.append(entry)
                points.extend(pair)
            except Exception as exc:data['unresolved'].append(str(exc))
        data['segments']=segments
        data['complete']=not data['unresolved']
        data['endpoint_center_mm']=None;data['centering_translation_mm']=None
        data['origin_at_endpoint_center']=None
        if points and data['complete']:
            low=[min(p[i] for p in points) for i in range(3)]
            high=[max(p[i] for p in points) for i in range(3)]
            center=[(a+b)/2 for a,b in zip(low,high)]
            data.update(endpoint_extent_mm=[low,high],endpoint_center_mm=center,
                        centering_translation_mm=[-v for v in center],
                        origin_at_endpoint_center=all(abs(v)<1e-6 for v in center))
        elif not points and data['complete']:
            data['complete']=False;data['unresolved'].append('No supported non-construction endpoints.')
        try:data['model_to_sketch_transform']=list(com(com(sketch,'ModelToSketchTransform'),'ArrayData'))
        except Exception as exc:
            data['model_to_sketch_transform']=None;data['unresolved'].append(str(exc));data['complete']=False
        return sw._result(True,'Sketch endpoint geometry read; no model changes.',data=data)
    except Exception as exc:
        return sw._result(False,str(exc),SwErrors.swInvalidInput,{'code':'CONSTRUCTION_INSPECTION_FAILED'})


@tool(name='create_centered_profile_sketch',description=(
    'Create a new scratch part with an exact translated line/arc profile sketch, using database insertion to avoid inference. '
    'Requires complete planar sketch evidence; does not alter existing parts or save/install a library profile.'),
    schema={'type':'object','properties':{'geometry':{'type':'object'}},'required':['geometry']},
    operation_class=OperationClass.PROJECT_WRITE)
def create_centered_profile_sketch(sw,geometry):
    from ..stair_recipe import centered_sketch_commands,replay_centered_segments
    try:
        commands=centered_sketch_commands(geometry)
        if len(commands)>1000:raise ValueError('Profile exceeds 1000 segment limit.')
        for command in commands:
            import math
            if any(not math.isfinite(v) for k,v in command['arguments'].items() if k!='unit'):
                raise ValueError('Nonfinite profile coordinate.')
        result=sw.create_new_part()
        if not result['success']:return result
        result=sw.create_sketch('Front')
        if not result['success']:return result
        doc,error=sw.get_active_doc()
        if error:return error
        if com(doc,'GetPathName'):raise ValueError('New unsaved scratch part required.')
        replay_centered_segments(doc,commands)
        com(com(doc,'SketchManager'),'InsertSketch',True)
        result=inspect_construction_geometry(sw,'Sketch1')
        if not result['success'] or not result['data']['complete'] or not result['data']['origin_at_endpoint_center']:
            raise ValueError('Centered profile readback failed; scratch retained.')
        return sw._result(True,'Centered scratch profile sketch created and inspected; not saved.',data=result['data'])
    except Exception as exc:
        return sw._result(False,str(exc),SwErrors.swInvalidInput,{'code':'PROFILE_REPLAY_FAILED','saved':False})
