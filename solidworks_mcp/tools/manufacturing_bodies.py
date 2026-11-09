"""Bound current body identity and conservative geometric plate candidates."""
import math
import pythoncom
from win32com.client import VARIANT
from ..comutil import com
from ..core.policy import OperationClass
from ..registry import tool
from .assembly_documentation import _state
from .cutlist_bodies import get_cut_list_body_map
from .sheetmetal_bodies import list_sheet_metal_bodies
from .manufacturing_package import _failure


def _plate_candidate(faces, volume_mm3, start_index):
    if not math.isfinite(volume_mm3) or volume_mm3<=0: return None
    planes=[]
    for index,face in enumerate(faces):
        surface=com(face,'GetSurface')
        if not com(surface,'IsPlane'): continue
        area=float(com(face,'GetArea'))*1e6
        normal=[float(v) for v in com(face,'Normal')[:3]]
        point=[float(v)*1000 for v in com(surface,'PlaneParams')[3:6]]
        if not math.isfinite(area) or area<=0 or len(normal)!=3 or len(point)!=3: continue
        if not all(math.isfinite(v) for v in normal+point): continue
        length=math.sqrt(sum(v*v for v in normal))
        if length<1e-9: continue
        planes.append(dict(face_index=start_index+index,area_mm2=area,point_mm=point,normal=[v/length for v in normal]))
    planes.sort(key=lambda p:p['area_mm2'],reverse=True)
    if len(planes)<2: return None
    a,b=planes[:2]
    if abs(a['area_mm2']-b['area_mm2'])>a['area_mm2']*1e-6: return None
    if sum(x*y for x,y in zip(a['normal'],b['normal']))>-.999999: return None
    thickness=abs(sum((x-y)*n for x,y,n in zip(a['point_mm'],b['point_mm'],a['normal'])))
    if not 1e-6<thickness<=math.sqrt(a['area_mm2'])*.25: return None
    predicted=a['area_mm2']*thickness
    if abs(volume_mm3-predicted)>max(.001,volume_mm3*1e-5): return None
    return dict(kind='plate_candidate',face_index=a['face_index'],opposite_face_index=b['face_index'],
        thickness_mm=thickness,face_area_mm2=a['area_mm2'],volume_matches_prism=True,
        fabrication_confirmed=False,material_confirmed=False)


@tool(name='inspect_part_manufacturing',description=(
    'Read solid bodies, exact visible indices and cut-list membership, native sheet flags, material name and conservative plate candidates. '
    'No refresh or selection/configuration changes. Plate candidates are geometry only, not confirmed fabrication/material. Indices expire on model changes.'),
    schema={'type':'object','properties':{},'required':[]},operation_class=OperationClass.READ)
def inspect_part_manufacturing(sw):
    try:
        doc,error=sw.get_active_doc()
        if error:return error
        if com(doc,'GetType')!=1: raise ValueError('Active document must be a part.')
        before=_state(doc)
        mapping=get_cut_list_body_map(sw,include_properties=True)
        if not mapping.get('success'): raise ValueError('Cut-list body inventory could not be read.')
        data=mapping['data']; members={}; rows=[]; warnings=[]
        benign={'NO_CUT_LIST_ITEMS','UNASSIGNED_SOLIDS','PROPERTIES_READ_FAILED'}
        read_warnings=[w for w in data['warnings'] if w['code'] not in benign]
        warnings.extend({'scope':'cut_list_body_read',**w} for w in read_warnings)
        for item in data['items']:
            for member in item['bodies']:
                index=member['solid_body_index']
                if index is not None: members.setdefault(index,[]).append({'folder':item['folder'],'properties':item.get('properties',{})})
        geometry={b['solid_body_index']:b for item in data['items'] for b in item['bodies'] if b['solid_body_index'] is not None}
        geometry.update({b['solid_body_index']:b for b in data['unassigned_bodies']})
        bodies=list(com(doc,'GetBodies2',0,False) or [])
        if len(bodies)>256: raise ValueError('Body inspection supports at most 256 solids per part.')
        # Face indices deliberately use the visible-body traversal of list_planar_faces.
        visible=list(com(doc,'GetBodies2',0,True) or []); starts={}; offset=0
        for i,body in enumerate(visible):
            faces=list(com(body,'GetFaces') or [])
            if len(faces)>2000: raise ValueError('Body face limit exceeded.')
            starts[i]=offset;offset+=len(faces)
        for index,body in enumerate(bodies):
            row=dict(geometry.get(index,{})); row.update(solid_body_index=index,name=str(com(body,'Name')),
                cut_list=members.get(index,[]),classification='unknown',plate_candidate=None)
            try:
                if com(body,'IsSheetMetal'):
                    row['classification']='native_sheet_metal'
                elif row.get('visible') and row.get('volume_mm3') is not None:
                    faces=list(com(body,'GetFaces') or [])
                    candidate=_plate_candidate(faces,row['volume_mm3'],starts[row['body_index']])
                    if candidate:row.update(classification='plate_candidate',plate_candidate=candidate)
            except Exception as exc:
                warnings.append({'body':index,'reason':str(exc)})
            rows.append(row)
        body_read_complete=not warnings and len(geometry)==len(bodies) and all(
            r.get('volume_mm3') is not None and math.isfinite(r['volume_mm3']) and r['volume_mm3']>0 and
            'visible' in r for r in rows)
        sheet=None
        if any(r['classification']=='native_sheet_metal' for r in rows):
            sheet_result=list_sheet_metal_bodies(sw)
            if not sheet_result.get('success'):warnings.append({'reason':'Sheet parameters could not be inspected.'})
            else:sheet=sheet_result['data']
        material=None
        try:
            database=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BSTR,'')
            material={'name':str(com(doc,'GetMaterialPropertyName2',before[1],database) or ''),'database':database.value}
        except Exception as exc: warnings.append({'reason':'Material read unavailable: '+str(exc)})
        if _state(doc)!=before:raise ValueError('Document changed during body inspection; retry.')
        result={'document_path':before[0],'configuration':before[1],'update_stamp':before[2],
            'dirty':before[3],'bodies':rows,'solid_body_count':len(bodies),'visible_body_count':len(visible),
            'cut_list':data,'sheet_metal':sheet,'material':material,'warnings':warnings,
            'inspection_complete':not warnings and len(geometry)==len(bodies),
            'body_read_complete':body_read_complete,'cut_list_mapping_complete':data['mapping_complete'],
            'manufacturing_ready':False,'properties_freshness':'not_verified',
            'limitations':['Plate classification proves only a geometric prism candidate, not make/buy, stock or cutting requirements.',
                'Hidden solids remain listed but have no face-export index. Body indices are current-state tokens only.']}
        return sw._result(True,f'Inspected {len(bodies)} manufacturing body candidates.',data=result)
    except Exception as exc:return _failure(sw,exc)
