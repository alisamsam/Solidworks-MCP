"""Bounded exact-instance edge inspection and checked, reversible selection."""
from collections import OrderedDict
import math
import time
from uuid import uuid4

import pythoncom
from win32com.client import VARIANT
from ..comutil import com,set_com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .assembly import _local_to_global
from .guard import require_stateful_document_access

MAX_SCAN=2000


def _finite(value,minimum=0):
    return type(value) in (int,float) and math.isfinite(value) and value>=minimum


def _assembly(sw):
    doc,error=sw.get_active_doc()
    if error:raise ValueError(error.get('message','No active document.'))
    if com(doc,'GetType')!=2:raise ValueError('Active document must be an assembly.')
    if not com(doc,'GetPathName'):raise ValueError('Save an approved working assembly first.')
    return doc


def _component(doc,path):
    if not isinstance(path,str) or not path or path.strip()!=path:
        raise ValueError('Exact native component path is required.')
    pieces=path.split('/')
    if len(pieces)>32 or any(not p for p in pieces):raise ValueError('Invalid component path.')
    children=list(com(doc,'GetComponents',True) or [])
    target=None
    for i in range(len(pieces)):
        if len(children)>20000:raise ValueError('Component branch exceeds the inspection limit.')
        prefix='/'.join(pieces[:i+1])
        found=[c for c in children if str(com(c,'Name2'))==prefix]
        if len(found)!=1:raise ValueError(f'Exact component not found or ambiguous: {prefix}. Use native Name2, not a suffix.')
        target=found[0]
        if com(target,'GetSuppression')!=2:
            raise ValueError(f'Component is suppressed/lightweight/unresolved: {prefix}. Resolve only this branch first.')
        if i+1<len(pieces):children=list(com(target,'GetChildren') or [])
    return target


def _context(doc,component):
    part=com(component,'GetModelDoc2')
    if part is None or com(part,'GetType')!=1:raise ValueError('Target must be one loaded part instance, not a subassembly.')
    tf=[float(v) for v in com(com(component,'Transform2'),'ArrayData')]
    if len(tf)!=16 or any(not math.isfinite(v) for v in tf) or tf[12]<=0:
        raise ValueError('Invalid native component transform.')
    rows=[tf[i:i+3] for i in (0,3,6)]
    if any(abs(sum(a*b for a,b in zip(rows[i],rows[j]))-(1 if i==j else 0))>1e-6 for i in range(3) for j in range(3)):
        raise ValueError('Unsupported non-rigid component transform.')
    return {'document_path':str(com(doc,'GetPathName')),'configuration':str(com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name')),
            'assembly_stamp':int(com(doc,'GetUpdateStamp')),'component_path':str(com(component,'Name2')),
            'component_file_path':str(com(component,'GetPathName')),'component_configuration':str(com(component,'ReferencedConfiguration')),
            'part_stamp':int(com(part,'GetUpdateStamp')),'transform':tf}


def _point(point,tf):
    local=[float(v) for v in point]
    if len(local)!=3 or any(not math.isfinite(v) for v in local):raise ValueError('Invalid native edge point.')
    result=[v*1000 for v in _local_to_global(local,tf)]
    if any(not math.isfinite(v) for v in result):raise ValueError('Edge coordinate overflow.')
    return result


def _local_point(point_mm,tf):
    delta=[point_mm[i]/1000-tf[9+i] for i in range(3)]
    return [sum(delta[j]*tf[3*i+j] for j in range(3))/tf[12] for i in range(3)]


def _geometry(edge,tf,near):
    curve=com(edge,'GetCurve');params=com(edge,'GetCurveParams3')
    kind='line' if com(curve,'IsLine') else ('circle' if com(curve,'IsCircle') else 'other')
    length=float(com(curve,'GetLength3',com(params,'UMinValue'),com(params,'UMaxValue')))*1000*tf[12]
    if not math.isfinite(length) or length<=0:raise ValueError('Invalid native edge length.')
    row={'curve_type':kind,'length_mm':length,'start_mm':_point(com(params,'StartPoint'),tf),'end_mm':_point(com(params,'EndPoint'),tf)}
    if kind=='circle':
        circle=list(com(curve,'CircleParams'));radius=float(circle[6])*1000*tf[12]
        if not math.isfinite(radius) or radius<=0:raise ValueError('Invalid circle radius.')
        axis=[sum(float(circle[3+i])*tf[3*i+j] for i in range(3)) for j in range(3)]
        norm=math.sqrt(sum(v*v for v in axis))
        if not math.isfinite(norm) or norm<=0:raise ValueError('Invalid circle axis.')
        row.update(center_mm=_point(circle[:3],tf),radius_mm=radius,circle_axis=[v/norm for v in axis])
    if near is not None:
        local=_local_point(near,tf);closest=com(edge,'GetClosestPointOn',*local)
        row['distance_mm']=math.dist(near,_point(list(closest)[:3],tf))
    return row


def _owner(sw,entity,component):
    if com(entity,'GetType')!=1:raise ValueError('Persistent object is not a native edge.')
    owner=com(entity,'GetComponent')
    if owner is None or com(sw.app,'IsSame',owner,component)!=1:
        raise ValueError('Edge belongs to a different component instance.')


def _cache(sw):
    cache=getattr(sw,'_component_edge_pages',None)
    if cache is None:cache=OrderedDict();sw._component_edge_pages=cache
    for key in list(cache):
        if time.monotonic()-cache[key]['created']>900:del cache[key]
    return cache


@tool(name='list_component_edges',description='Inspect edges of one exact native component Name2 path, including nested instances. Paged/filterable in assembly mm; circles retained. Returns session-bound snapshot/edge IDs for select_component_edges. No whole-assembly edge scan or model changes.',
      schema={'type':'object','properties':{
          'component_path':{'type':'string'},'body_index':{'type':'integer','minimum':0},
          'curve_type':{'type':'string','enum':['all','line','circle','other'],'default':'all'},
          'min_length_mm':{'type':'number','minimum':0,'default':0},
          'near_point_mm':{'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3},
          'within_mm':{'type':'number','exclusiveMinimum':0},
          'offset':{'type':'integer','minimum':0,'default':0},'limit':{'type':'integer','minimum':1,'maximum':100,'default':20}},
          'required':['component_path']},operation_class=OperationClass.READ)
def list_component_edges(sw,component_path,body_index=None,curve_type='all',min_length_mm=0.,near_point_mm=None,within_mm=None,offset=0,limit=20):
    try:
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
            raise ValueError('offset/limit must be nonnegative/1..100 integers.')
        if body_index is not None and (type(body_index) is not int or body_index<0):raise ValueError('Invalid component body index.')
        if curve_type not in ('all','line','circle','other') or not _finite(min_length_mm):raise ValueError('Invalid curve/length filter.')
        if near_point_mm is not None:
            if not isinstance(near_point_mm,(list,tuple)) or len(near_point_mm)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in near_point_mm):raise ValueError('near_point_mm requires three finite assembly coordinates.')
            if not _finite(within_mm) or within_mm==0:raise ValueError('within_mm is required and positive with near_point_mm.')
        elif within_mm is not None:raise ValueError('within_mm requires near_point_mm.')
        doc=_assembly(sw);component=_component(doc,component_path);context=_context(doc,component)
        bodies=list(com(component,'GetBodies2',0) or [])
        if not bodies or len(bodies)>256:raise ValueError('Component has no loaded solid bodies, or exceeds 256 bodies.')
        if body_index is not None and body_index>=len(bodies):raise ValueError('Component body index is out of range.')
        entries=[]
        for i,body in enumerate(bodies):
            if body_index is None or i==body_index:
                body_name=str(com(body,'Name'))
                entries.extend((i,body_name,e) for e in com(body,'GetEdges') or [])
                if len(entries)>100000:raise ValueError('Component exceeds 100000 native edges; use body_index.')
        if offset>len(entries):raise ValueError('offset exceeds edge count.')
        rows=[];refs={};warnings=[];scanned=0;position=offset
        extension=com(doc,'Extension')
        while position<len(entries) and len(rows)<limit and scanned<MAX_SCAN:
            edge_id=position;i,body_name,edge=entries[position];position+=1;scanned+=1
            try:
                geometry=_geometry(edge,context['transform'],near_point_mm)
                if curve_type!='all' and geometry['curve_type']!=curve_type:continue
                if geometry['length_mm']<min_length_mm:continue
                if near_point_mm is not None and geometry['distance_mm']>within_mm:continue
                _owner(sw,edge,component)
                raw=com(extension,'GetPersistReference3',edge)
                if raw is None or not 0<len(raw)<=65536:raise ValueError('No bounded native persistent edge reference.')
                refs[edge_id]=bytes(raw);rows.append({'edge_id':edge_id,'component_body_index':i,'body':body_name,**geometry})
            except Exception as exc:warnings.append({'edge_id':edge_id,'message':str(exc)})
        if _context(doc,component)!=context:raise ValueError('Assembly/component changed during edge inspection; retry.')
        token=uuid4().hex;cache=_cache(sw);cache[token]={'created':time.monotonic(),'context':context,'references':refs}
        while len(cache)>32:cache.popitem(last=False)
        return sw._result(True,f'Read {len(rows)} edge(s) of {component_path}.',data={
            'snapshot_id':token,'component_path':component_path,'component_file_path':context['component_file_path'],
            'component_configuration':context['component_configuration'],'coordinate_system':'assembly','units':'mm',
            'edges':rows,'complete':not warnings,'coverage_scope':'scanned_page','warnings':warnings,
            'total_native_edges':len(entries),'scanned_edges':scanned,'next_offset':position if position<len(entries) else None})
    except Exception as exc:return sw._result(False,str(exc),SwErrors.swInvalidInput,{'code':'COMPONENT_EDGE_READ_FAILED'})


def _selections(doc):
    manager=com(doc,'SelectionManager')
    return [(com(manager,'GetSelectedObject6',i,-1),int(com(manager,'GetSelectedObjectMark',i)))
            for i in range(1,com(manager,'GetSelectedObjectCount2',-1)+1)]


def _restore(sw,doc,saved):
    com(doc,'ClearSelection2',True);manager=com(doc,'SelectionManager')
    for obj,mark in saved:
        data=com(manager,'CreateSelectData');set_com(data,'Mark',mark)
        com(com(doc,'Extension'),'MultiSelect2',VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_DISPATCH,[obj]),True,data)
    actual=_selections(doc)
    return len(actual)==len(saved) and all(m==n and com(sw.app,'IsSame',a,b)==1 for (a,m),(b,n) in zip(actual,saved))


@tool(name='select_component_edges',description='Select only edges returned by list_component_edges in this MCP session. Rejects stale document/configuration/part/transform or wrong-instance references. Verifies actual selected edge owners; restores prior selection on failure. No geometry/save or automatic resolve.',
      schema={'type':'object','properties':{'snapshot_id':{'type':'string'},
          'edge_ids':{'type':'array','items':{'type':'integer','minimum':0},'minItems':1,'maxItems':64,'uniqueItems':True},
          'append':{'type':'boolean','default':False},'mark':{'type':'integer','minimum':0,'default':0}},
          'required':['snapshot_id','edge_ids']},operation_class=OperationClass.STATEFUL_READ)
def select_component_edges(sw,snapshot_id,edge_ids,append=False,mark=0):
    doc=None;saved=None;changed=False
    try:
        if not isinstance(snapshot_id,str) or not isinstance(edge_ids,(list,tuple)) or not 1<=len(edge_ids)<=64 or any(type(i) is not int or i<0 for i in edge_ids) or len(set(edge_ids))!=len(edge_ids):raise ValueError('Supply one current snapshot and 1..64 distinct integer edge IDs.')
        if type(append) is not bool or type(mark) is not int or not 0<=mark<=2147483647:raise ValueError('Invalid append/mark.')
        record=_cache(sw).get(snapshot_id)
        if record is None:raise ValueError('Edge snapshot expired or belongs to another MCP session; list edges again.')
        doc=_assembly(sw);component=_component(doc,record['context']['component_path'])
        if _context(doc,component)!=record['context']:raise ValueError('Stale assembly/component context; list edges again.')
        denied=require_stateful_document_access(sw,doc)
        if denied:return denied
        entities=[];extension=com(doc,'Extension')
        for edge_id in edge_ids:
            raw=record['references'].get(edge_id)
            if raw is None:raise ValueError('Edge ID was not returned in this snapshot page.')
            status=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
            entity=com(extension,'GetObjectByPersistReference3',VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_UI1,raw),status)
            if entity is None or status.value!=0:raise ValueError('Persistent edge is unavailable; list edges again.')
            _owner(sw,entity,component);entities.append(entity)
        saved=_selections(doc)
        if len(saved)>1024:raise ValueError('Existing selection exceeds rollback limit.')
        additions=[]
        for entity in entities:
            existing=[m for obj,m in saved if com(sw.app,'IsSame',obj,entity)==1] if append else []
            if existing and any(m!=mark for m in existing):raise ValueError('Edge already selected with a different mark.')
            if not existing:additions.append(entity)
        changed=True
        if not append:com(doc,'ClearSelection2',True)
        manager=com(doc,'SelectionManager');data=com(manager,'CreateSelectData');set_com(data,'Mark',mark)
        for entity in additions:
            if com(entity,'Select4',True,data) is not True:raise ValueError('Native edge selection failed.')
        actual=_selections(doc);expected=(saved if append else [])+[(e,mark) for e in additions]
        if len(actual)!=len(expected) or any(a_mark!=b_mark or com(sw.app,'IsSame',a,b)!=1 for (a,a_mark),(b,b_mark) in zip(actual,expected)):
            raise ValueError('Selected native entities/marks differ from requested selection.')
        for entity in entities:
            indices=[i+1 for i,(obj,m) in enumerate(actual) if m==mark and com(sw.app,'IsSame',obj,entity)==1]
            if len(indices)!=1:raise ValueError('Selected edge missing/ambiguous.')
            i=indices[0]
            if com(manager,'GetSelectedObjectType3',i,-1)!=1 or com(sw.app,'IsSame',com(manager,'GetSelectedObjectsComponent4',i,-1),component)!=1:
                raise ValueError('Selection belongs to another component or entity type.')
        if _context(doc,component)!=record['context']:raise ValueError('Component changed during selection.')
        return sw._result(True,'Exact component edge selection verified; no geometry/save.',data={
            'component_path':record['context']['component_path'],'selected_edge_ids':list(edge_ids),'selected_count':len(actual),'mark':mark,'append':append})
    except Exception as exc:
        restored=None
        if changed and doc is not None and saved is not None:
            try:restored=_restore(sw,doc,saved)
            except Exception:restored=False
        return sw._result(False,str(exc),SwErrors.swSelectionError,{'code':'COMPONENT_EDGE_SELECTION_FAILED','selection_restored':restored,'selection_may_be_modified':changed and restored is not True})
