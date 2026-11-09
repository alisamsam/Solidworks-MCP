"""Read current cut-list membership without updating, resolving or selecting."""
import math

import pythoncom
from win32com.client import VARIANT

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool

MAX_BODIES=2048
MAX_FEATURES=20000


def _properties(feature):
    manager=com(feature,'CustomPropertyManager')
    if manager is None:return {}
    names=list(com(manager,'GetNames') or [])
    if len(names)>1000:raise ValueError('Cut-list property limit exceeded.')
    result={}
    for name in names:
        raw=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BSTR,'')
        evaluated=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BSTR,'')
        resolved=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
        code=com(manager,'Get5',name,True,raw,evaluated,resolved)
        result[str(name)]={'raw':raw.value,'evaluated':evaluated.value,
                           'was_resolved':bool(resolved.value),'result_code':int(code)}
    return result


def _geometry(body):
    volume=float(com(body,'GetMassProperties',0.)[3])*1e9
    box=[float(x)*1000 for x in com(body,'GetBodyBox')]
    if not math.isfinite(volume) or volume<=0 or len(box)!=6 or any(not math.isfinite(x) for x in box):
        raise ValueError('Invalid solid geometry.')
    return {'volume_mm3':volume,'bounding_box_mm':box}


@tool(
    name='get_cut_list_body_map',
    description='Read current cut-list folders and exact solid membership. body_index matches visible Save Bodies indices; hidden bodies have null. Cached properties retain native text/units; no refresh or model changes. Refresh indices after edits/visibility changes.',
    schema={'type':'object','properties':{
        'include_properties':{'type':'boolean','default':True},
    },'required':[]},
    operation_class=OperationClass.READ,
)
def get_cut_list_body_map(sw,include_properties=True):
    """Map using ISldWorks.IsSame; names only narrow candidates, never prove identity."""
    if type(include_properties) is not bool:
        return sw._result(False,'include_properties must be boolean.',SwErrors.swInvalidInput,
                          {'code':'VALIDATION_FAILED'})
    doc,error=sw.get_active_doc()
    if error:return error
    if com(doc,'GetType')!=1:
        return sw._result(False,'Active document must be a part.',SwErrors.swInvalidFileType)
    warnings=[]
    def warn(code,**details):warnings.append({'code':code,**details})
    try:
        stamp=com(doc,'GetUpdateStamp')
        configuration=str(com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name'))
        solids=list(com(doc,'GetBodies2',0,False) or [])
        visible=list(com(doc,'GetBodies2',0,True) or [])
        features=list(com(com(doc,'FeatureManager'),'GetFeatures',False) or [])
        if len(solids)>MAX_BODIES or len(visible)>MAX_BODIES or len(features)>MAX_FEATURES:
            raise ValueError('Snapshot exceeds the supported body/feature limit.')
        solid_names=[str(com(b,'Name')) for b in solids]
        visible_names=[str(com(b,'Name')) for b in visible]
        def matches(body,candidates,names):
            # Typical unique names keep this linear in model size. Even with
            # coincident geometry / duplicate names, only native identity wins.
            name=str(com(body,'Name'))
            preferred=[i for i,n in enumerate(names) if n==name]
            remaining=[i for i,n in enumerate(names) if n!=name]
            found=[]
            for indices in (preferred,remaining):
                for i in indices:
                    try:
                        equality=com(sw.app,'IsSame',body,candidates[i])
                        if equality==1:found.append(i)
                        elif equality!=0:raise ValueError(f'Native identity returned {equality}.')
                    except Exception as exc:warn('IDENTITY_READ_FAILED',body=name,message=str(exc))
                if found:break
            return found

        body_rows=[]
        for i,body in enumerate(solids):
            found=matches(body,visible,visible_names)
            row={'name':solid_names[i],'solid_body_index':i,'body_index':found[0] if len(found)==1 else None,
                 'visible':len(found)==1}
            if len(found)>1:warn('AMBIGUOUS_VISIBLE_INDEX',body=row['name'])
            try:row.update(_geometry(body))
            except Exception as exc:
                row.update(volume_mm3=None,bounding_box_mm=None)
                warn('GEOMETRY_READ_FAILED',body=row['name'],message=str(exc))
            body_rows.append(row)
        visible_claims=[b['body_index'] for b in body_rows if b['body_index'] is not None]
        if len(visible_claims)!=len(set(visible_claims)) or set(visible_claims)!=set(range(len(visible))):
            warn('VISIBLE_BODY_SET_MISMATCH',unmatched_visible_indices=sorted(set(range(len(visible)))-set(visible_claims)))
        assigned={};items=[];seen_features={}
        for feature in features:
            if com(feature,'GetTypeName2')!='CutListFolder':continue
            name=str(com(feature,'Name'))
            # GetFeatures(False) may return the same folder through more than
            # one tree occurrence. Do not count a second native occurrence.
            repeated=False
            for previous in seen_features.get(name,[]):
                if com(sw.app,'IsSame',feature,previous)==1:repeated=True;break
            if repeated:continue
            seen_features.setdefault(name,[]).append(feature)
            item={'folder':name,'body_count':None,'mapped_body_count':0,'bodies':[]}
            try:
                folder=com(feature,'GetSpecificFeature2')
                count=com(folder,'GetBodyCount')
                members=list(com(folder,'GetBodies') or [])
                if type(count) is not int or not 0<=count<=MAX_BODIES or len(members)>MAX_BODIES:
                    raise ValueError('Invalid or excessive cut-list body count.')
                item['body_count']=count
                if count!=len(members):warn('FOLDER_COUNT_MISMATCH',folder=name,reported=count,enumerated=len(members))
                if count==0 and not members:continue
                member_indices=set()
                for member in members:
                    found=matches(member,solids,solid_names)
                    if len(found)!=1:
                        item['bodies'].append({'name':str(com(member,'Name')),'solid_body_index':None,
                                               'body_index':None,'visible':None})
                        warn('UNMATCHED_FOLDER_BODY',folder=name,body=str(com(member,'Name')))
                        continue
                    i=found[0]
                    item['bodies'].append(dict(body_rows[i]))
                    if i in member_indices:warn('DUPLICATE_FOLDER_BODY',folder=name,body=solid_names[i])
                    member_indices.add(i)
                    if i in assigned:warn('DUPLICATE_MEMBERSHIP',folder=name,other_folder=assigned[i],body=solid_names[i])
                    else:assigned[i]=name
                item['mapped_body_count']=len(member_indices)
            except Exception as exc:warn('FOLDER_READ_FAILED',folder=name,message=str(exc))
            if include_properties:
                try:item['properties']=_properties(feature)
                except Exception as exc:
                    item['properties']={};warn('PROPERTIES_READ_FAILED',folder=name,message=str(exc))
            items.append(item)
        unassigned=[dict(b) for i,b in enumerate(body_rows) if i not in assigned]
        if unassigned:warn('UNASSIGNED_SOLIDS',count=len(unassigned))
        if not items:warn('NO_CUT_LIST_ITEMS')
        after_stamp=com(doc,'GetUpdateStamp')
        after_configuration=str(com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name'))
        if stamp!=after_stamp or configuration!=after_configuration:warn('DOCUMENT_CHANGED_DURING_READ')
        try:unit_code=com(doc,'GetUnits')[0]
        except Exception:unit_code=None
        # Properties may be stale despite a valid membership map. Keep them
        # verbatim, without inferring millimetres from arbitrary/localised text.
        mapping_errors=[w for w in warnings if w['code']!='PROPERTIES_READ_FAILED']
        data={'document_path':com(doc,'GetPathName'),'configuration':configuration,'update_stamp':after_stamp,
              'document_length_unit_code':unit_code,'properties_freshness':'not_verified',
              'refreshed':False,'mapping_complete':not mapping_errors,'warnings':warnings,
              'solid_body_count':len(solids),'visible_body_count':len(visible),'items':items,
              'unassigned_bodies':unassigned}
        return sw._result(True,f'Read {len(items)} cut-list folder(s); '+
                          ('body mapping complete.' if data['mapping_complete'] else 'body mapping incomplete; inspect warnings.'),data=data)
    except Exception as exc:
        return sw._result(False,f'Could not read cut-list body map: {exc}',SwErrors.swFeatureError,
                          {'code':'CUT_LIST_READ_FAILED','mapping_complete':False})
