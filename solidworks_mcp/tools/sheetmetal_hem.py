"""Verified single-edge open/closed hems on folded single-body sheet metal."""
import math

import pythoncom
from win32com.client import VARIANT

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .guard import require_stateful_document_access
from .inspection import part_edges
from .sheetmetal import (_body_volumes, _find_flat_pattern_feature,
                         _find_sheet_metal_feature, _select_edge)


def _number(value, zero=False):
    return (type(value) in (int,float) and math.isfinite(value)
            and (value>=0 if zero else value>0))


@tool(
    name='create_sheet_metal_hem',
    description='Add an open or closed hem to one straight edge. Folded single-body sheet only; inside position, parent bend allowance/relief. Not saved.',
    schema={'type':'object','properties':{
        'edge_index':{'type':'integer','minimum':0,'description':'Fresh list_body_edges index.'},
        'length_mm':{'type':'number','exclusiveMinimum':0},
        'hem_type':{'type':'string','enum':['open','closed'],'default':'open'},
        'gap_mm':{'type':'number','exclusiveMinimum':0,'description':'Open only; default 1 mm. Omit for closed.'},
        'reverse':{'type':'boolean','default':False},
        'miter_gap_mm':{'type':'number','minimum':0,'default':1.0},
    },'required':['edge_index','length_mm']},
    operation_class=OperationClass.MUTATE,
)
def create_sheet_metal_hem(sw,edge_index,length_mm,hem_type='open',gap_mm=None,
                          reverse=False,miter_gap_mm=1.0):
    """Use InsertSheetMetalHem2, then verify native settings and solid geometry."""
    def fail(message,code='VALIDATION_FAILED',modified=False):
        return sw._result(False,message,SwErrors.swFeatureError if modified else SwErrors.swInvalidInput,
                          {'code':code,'document_may_be_modified':modified})
    if type(edge_index) is not int or edge_index<0:
        return fail('edge_index must be a non-negative integer.')
    if not _number(length_mm) or not _number(miter_gap_mm,zero=True):
        return fail('length_mm must be finite and positive; miter_gap_mm finite and non-negative.')
    if hem_type not in ('open','closed') or type(reverse) is not bool:
        return fail('hem_type must be open or closed and reverse must be boolean.')
    if hem_type=='closed' and gap_mm is not None:
        return fail('Omit gap_mm for a closed hem; SolidWorks controls its residual gap.')
    gap=1.0 if gap_mm is None and hem_type=='open' else gap_mm
    if hem_type=='open' and not _number(gap):return fail('gap_mm must be finite and positive.')
    doc,error=sw.get_active_doc()
    if error:return error
    if com(doc,'GetType')!=1:return fail('Active document must be a part.')
    denied=require_stateful_document_access(sw,doc)
    if denied:return denied
    if com(doc,'GetActiveSketch2') is not None:return fail('Close the active sketch first.')
    sm=_find_sheet_metal_feature(doc)
    if sm is None:return fail('Part has no sheet-metal feature.','NO_SHEET_METAL')
    flat=_find_flat_pattern_feature(doc)
    if flat is not None and not com(flat,'IsSuppressed'):
        return fail('Fold the sheet before adding a hem.','SHEET_IS_FLAT')

    attempted=False
    try:
        if len(com(doc,'GetBodies2',0,False) or [])!=1:
            return fail('Exactly one solid body, including hidden bodies, is supported.','BODY_SCOPE_UNSUPPORTED')
        before=_body_volumes(doc)
        if len(before)!=1:return fail('Exactly one solid body is supported.','BODY_SCOPE_UNSUPPORTED')
        edges=part_edges(doc)
        if edge_index>=len(edges):return fail('Edge index is out of range; re-run list_body_edges.')
        row=edges[edge_index]
        if not row['is_line']:return fail('Hem requires a straight sheet edge.')
        thickness=float(com(com(sm,'GetDefinition'),'Thickness'))
        if not math.isfinite(thickness) or thickness<=0:return fail('Invalid sheet thickness.')
        if not _select_edge(doc,row['edge']):return fail('Could not select hem edge.','SELECTION_FAILED')
        attempted=True
        feature=com(com(doc,'FeatureManager'),'InsertSheetMetalHem2',
                    0 if hem_type=='open' else 1,1,reverse,
                    length_mm/1000,(gap or 0)/1000,0.,0.,miter_gap_mm/1000,
                    VARIANT(pythoncom.VT_DISPATCH,None),True,0,0,False,0.,0.,0.)
        if feature is None:
            return fail('SolidWorks created no hem; check edge, length and direction.',
                        'FEATURE_CREATE_FAILED',True)
        name=str(com(feature,'Name'))
        if com(doc,'EditRebuild3') is not True:
            return fail('Hem rebuild failed.','REBUILD_FAILED',True)
        persisted=com(doc,'FeatureByName',name)
        if persisted is None or com(persisted,'GetTypeName2')!='Hem':
            return fail('A persistent native Hem feature was not found.','FEATURE_NOT_PERSISTED',True)
        warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
        native_error=com(persisted,'GetErrorCode2',warning)
        if native_error!=0 or warning.value:
            return fail(f'Hem reports native error {native_error}, warning {warning.value}.',
                        'FEATURE_ERROR',True)
        definition=com(persisted,'GetDefinition')
        actual={key:com(definition,key) for key in ('Type','BendPosition','ReverseDirection','Length','GapDistance','MiterGap')}
        expected={'Type':0 if hem_type=='open' else 1,'BendPosition':1,'ReverseDirection':reverse,
                  'Length':length_mm/1000,'MiterGap':miter_gap_mm/1000}
        if hem_type=='open':expected['GapDistance']=gap/1000
        if any(not isinstance(actual[k],(int,float)) or not math.isfinite(actual[k])
               or not math.isclose(actual[k],v,rel_tol=1e-7,abs_tol=1e-9)
               for k,v in expected.items()):
            return fail('Native hem parameters differ from requested values.','PARAMETER_MISMATCH',True)
        after=_body_volumes(doc)
        gained=sum(b['volume_mm3'] for b in after)-before[0]['volume_mm3']
        if (len(com(doc,'GetBodies2',0,False) or [])!=1 or len(after)!=1 or not math.isfinite(gained) or gained<=1e-6
                or after[0]['faces']<=before[0]['faces']):
            return fail('Hem did not add material/faces to the single sheet body.','NO_GEOMETRY_CHANGE',True)
        current_thickness=float(com(com(sm,'GetDefinition'),'Thickness'))
        if not math.isclose(current_thickness,thickness,rel_tol=1e-7,abs_tol=1e-9):
            return fail('Sheet thickness changed unexpectedly.','THICKNESS_MISMATCH',True)
        return sw._result(True,f"Created {hem_type} hem '{name}'.",data={
            'feature':name,'feature_type':'Hem','edge_index':edge_index,'edge_body':row['body'],
            'hem_type':hem_type,'position':'inside','reverse':reverse,'length_mm':actual['Length']*1000,
            'gap_mm':actual['GapDistance']*1000 if hem_type=='open' else None,
            'native_gap_mm':actual['GapDistance']*1000,'miter_gap_mm':actual['MiterGap']*1000,
            'thickness_mm':current_thickness*1000,'uses_parent_bend_allowance':True,
            'gained_mm3':gained,'volume_before_mm3':before[0]['volume_mm3'],
            'volume_after_mm3':after[0]['volume_mm3'],'faces_before':before[0]['faces'],
            'faces_after':after[0]['faces'],'bodies_before':1,'bodies_after':1})
    except Exception as exc:
        return fail(f'Hem operation failed: {exc}','NATIVE_OPERATION_FAILED',attempted)
    finally:
        com(doc,'ClearSelection2',True)
