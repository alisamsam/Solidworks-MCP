"""Per-body native sheet parameters without model or selection changes."""
import math

import pythoncom
from win32com.client import VARIANT
from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


def _finite(value,positive=False):
    if type(value) not in (int,float) or not math.isfinite(value) or (positive and value<=0):
        raise ValueError('Invalid native numeric parameter.')
    return float(value)


def _parameters(feature):
    d=com(feature,'GetDefinition')
    thickness=_finite(com(d,'Thickness'),True)*1000
    radius=_finite(com(d,'BendRadius'))*1000
    kind=com(d,'BendAllowanceType')
    # Installed SW2025: 1 table, 2 K-factor, 3 direct, 4 deduction,
    # 5 calculation table. Inactive KFactor may be an invalid sentinel.
    if radius<0 or type(kind) is not int or kind not in (1,2,3,4,5):
        raise ValueError('Unsupported/invalid native bend parameters.')
    k=_finite(com(d,'KFactor')) if kind==2 else None
    if k is not None and not 0<=k<=1:raise ValueError('Invalid active K-factor.')
    if not math.isfinite(thickness) or not math.isfinite(radius):raise ValueError('Native unit conversion overflow.')
    return {'thickness_mm':thickness,'bend_radius_mm':radius,'k_factor':k,
            'bend_allowance_type':kind,'k_factor_is_active':kind==2}


@tool(
    name='list_sheet_metal_bodies',
    description='Read each sheet body’s own native Sheet-Metal parameters and Flat-Pattern state, including hidden bodies. Visible body_index matches Save Bodies; solid_body_index includes hidden bodies. No flatten/rebuild/selection/save. Refresh after edits or reopening.',
    schema={'type':'object','properties':{},'required':[]},
    operation_class=OperationClass.READ,
)
def list_sheet_metal_bodies(sw):
    doc,error=sw.get_active_doc()
    if error:return error
    if com(doc,'GetType')!=1:
        return sw._result(False,'Active document must be a part.',SwErrors.swInvalidFileType)
    warnings=[]
    def warn(code,**details):warnings.append({'code':code,**details})
    def same(a,b):
        value=com(sw.app,'IsSame',a,b)
        if value not in (0,1):raise ValueError(f'Native identity returned {value}.')
        return value==1
    try:
        stamp=com(doc,'GetUpdateStamp')
        configuration=str(com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name'))
        solids=list(com(doc,'GetBodies2',0,False) or [])
        visible=list(com(doc,'GetBodies2',0,True) or [])
        if max(len(solids),len(visible))>256:raise ValueError('Read is limited to 256 solid bodies.')
        rows=[];non_sheet=[];visible_claims=[]
        for i,body in enumerate(solids):
            row={'name':str(com(body,'Name')),'solid_body_index':i,'body_index':None,'visible':None}
            try:
                matches=[j for j,v in enumerate(visible) if same(body,v)]
                if len(matches)>1:raise ValueError('Ambiguous visible body index.')
                row.update(body_index=matches[0] if matches else None,visible=bool(matches))
                visible_claims.extend(matches)
            except Exception as exc:warn('BODY_IDENTITY_FAILED',body=row['name'],message=str(exc))
            row.update(sheet_metal_feature=None,flat_pattern_feature=None,flattened=None,parameters=None)
            try:
                is_sheet=com(body,'IsSheetMetal')
                if type(is_sheet) is not bool:raise ValueError('Invalid native sheet-body flag.')
                if not is_sheet:
                    non_sheet.append({k:row[k] for k in ('name','solid_body_index','body_index','visible')});continue
                features=list(com(body,'GetFeatures') or [])
                if len(features)>10000:raise ValueError('Body feature limit exceeded.')
                sheet=[];flat=[]
                for f in features:
                    kind=com(f,'GetTypeName2')
                    if kind not in ('SheetMetal','FlatPattern'):continue
                    group=sheet if kind=='SheetMetal' else flat
                    if not any(same(f,other) for other in group):group.append(f)
                if len(sheet)!=1:
                    warn('SHEET_DEFINITION_NOT_UNIQUE',body=row['name'],count=len(sheet))
                else:
                    f=sheet[0];row['sheet_metal_feature']=str(com(f,'Name'))
                    warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
                    native_error=com(f,'GetErrorCode2',warning)
                    if native_error or warning.value or com(f,'IsSuppressed'):
                        warn('SHEET_FEATURE_NOT_HEALTHY',body=row['name'],error=native_error,warning=bool(warning.value))
                    try:row['parameters']=_parameters(f)
                    except Exception as exc:warn('PARAMETER_READ_FAILED',body=row['name'],message=str(exc))
                if len(flat)!=1:
                    warn('FLAT_PATTERN_NOT_UNIQUE',body=row['name'],count=len(flat))
                else:
                    row['flat_pattern_feature']=str(com(flat[0],'Name'))
                    warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
                    native_error=com(flat[0],'GetErrorCode2',warning)
                    if native_error or warning.value:
                        warn('FLAT_PATTERN_NOT_HEALTHY',body=row['name'],error=native_error,warning=bool(warning.value))
                    suppressed=com(flat[0],'IsSuppressed')
                    if type(suppressed) is not bool:raise ValueError('Invalid flat-pattern suppression state.')
                    row['flattened']=not suppressed
            except Exception as exc:warn('BODY_READ_FAILED',body=row['name'],message=str(exc))
            rows.append(row)
        if len(visible_claims)!=len(set(visible_claims)) or set(visible_claims)!=set(range(len(visible))):
            warn('VISIBLE_BODY_SET_MISMATCH')
        after=com(doc,'GetUpdateStamp')
        after_config=str(com(com(com(doc,'ConfigurationManager'),'ActiveConfiguration'),'Name'))
        if stamp!=after or configuration!=after_config:warn('DOCUMENT_CHANGED_DURING_READ')
        data={'document_path':com(doc,'GetPathName'),'configuration':configuration,'update_stamp':after,
              'complete':not warnings,'warnings':warnings,'solid_body_count':len(solids),
              'sheet_body_count':len(rows),'visible_body_count':len(visible),'bodies':rows,'non_sheet_bodies':non_sheet}
        return sw._result(True,f'Read {len(rows)} sheet-metal body/bodies; '+
                          ('complete.' if data['complete'] else 'partial; inspect warnings.'),data=data)
    except Exception as exc:
        return sw._result(False,f'Could not read sheet bodies: {exc}',SwErrors.swFeatureError,
                          {'code':'SHEET_BODY_READ_FAILED','complete':False})
