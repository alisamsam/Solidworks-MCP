"""Bounded inspection and editing of an already active in-context Routing sketch."""
import math
from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .routing import (_coerce_native_bool, _read_route_manager,
                      _require_active_assembly, _routing_allowed)
from .routing_path import (_segment_data, _finite, _MAX_SEGMENTS,
                           _COORDINATE_SYSTEM, _ROUTING_DISABLED_MESSAGE)

def _running_command(app):
    """GetRunningCommandInfo requires real by-reference output variants."""
    import pythoncom
    import win32com.client
    command = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    title = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, '')
    active = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
    app.GetRunningCommandInfo(command, title, active)
    return {'id': command.value, 'title': title.value, 'active': active.value}


@tool(
    name='routing_properties_command',
    description=('Select the exact FabricatedRoute feature and open native Route Properties '
                 '(documented swCommands_Pipe_Rt_Properties=2257), '
                 'or accept only an already-active exact Route Properties/Route Segment '
                 'Properties page. Requires an exact writable active native route path. '
                 'Verify the resulting exact properties page opened or closed; a native '
                 'true return without the observed effect fails. Does not set library '
                 'fields, save or prove successful pipe generation.'),
    schema={'type':'object','properties':{
        'expected_document_path':{'type':'string','minLength':1},
        'expected_route_path':{'type':'string','minLength':1},
        'route_feature_name':{'type':'string','minLength':1,'default':'Route1'},
        'action':{'type':'string','enum':['open','accept']}},
        'required':['expected_document_path','expected_route_path','action'],'additionalProperties':False},
    operation_class=OperationClass.MUTATE,com=True,
)
def routing_properties_command(sw,expected_document_path,action,expected_route_path,route_feature_name='Route1'):
    from pathlib import Path
    if not _routing_allowed():
        return sw._result(False,_ROUTING_DISABLED_MESSAGE,SwErrors.swInvalidInput)
    data={'document_may_be_modified':False,'generated_pipe_verified':False}
    try:
        if action not in ('open','accept'):
            raise ValueError('Action must be open or accept.')
        doc,_,error=_require_active_assembly(sw)
        if error: return error
        if Path(com(doc,'GetPathName')).resolve()!=Path(expected_document_path).resolve():
            raise ValueError('Active native route path does not match expected_document_path.')
        policy=getattr(sw,'_path_policy',None)
        if policy is None:raise ValueError('An explicit write policy is required.')
        policy.require_write(Path(expected_document_path),OperationClass.MUTATE)
        target=com(doc,'GetEditTarget')
        if target is None or Path(com(target,'GetPathName')).resolve()!=Path(expected_route_path).resolve():
            raise ValueError('Actual properties edit target does not match expected_route_path.')
        policy.require_write(Path(expected_route_path),OperationClass.MUTATE)
        if _coerce_native_bool(com(doc,'IsRouteAssembly')) is not True:
            raise ValueError('Active document is not a verified native route assembly.')
        before=data['command_before']=_running_command(sw.app)
        if action=='open':
            if before['active']:raise ValueError('Another PropertyManager is active.')
            feature=com(doc,'FeatureByName',route_feature_name)
            if feature is None:
                target=com(doc,'GetEditTarget')
                if target is not None and com(target,'GetType')==2:
                    policy.require_write(Path(com(target,'GetPathName')),OperationClass.MUTATE)
                    if _coerce_native_bool(com(target,'IsRouteAssembly')) is True:
                        feature=com(target,'FeatureByName',route_feature_name)
            if feature is None or com(feature,'GetTypeName2')!='FabricatedRoute':
                raise ValueError('The exact FabricatedRoute feature was not found.')
            com(doc,'ClearSelection2',True)
            if not com(feature,'Select2',False,0):
                raise ValueError('Could not select the verified native route feature.')
            command=2257
        else:
            if not before['active'] or before['title'] not in ('Route Properties','Route Segment Properties'):
                raise ValueError('The exact Routing properties page is not active; nothing accepted.')
            command=-2
        data['document_may_be_modified']=True
        data['native_return']=sw.app.RunCommand(command,'')
        if data['native_return'] is not True:
            raise ValueError('SolidWorks did not accept the Routing command.')
        data['command_after']=_running_command(sw.app)
        after=data['command_after']
        data['command_effect_verified']=(after['active'] and after['title'] in
            ('Route Properties','Route Segment Properties')) if action=='open' else not after['active']
        if not data['command_effect_verified']:
            raise ValueError('Routing command was dispatched but its expected page state was not observed; inspect before retrying.')
        return sw._result(True,'Native Routing properties command effect verified.',
                          SwErrors.swSuccess,data)
    except Exception as exc:
        return sw._result(False,str(exc),SwErrors.swInvalidInput,data)


@tool(
    name='inspect_routing_active_edit',
    description=('Read the active assembly, its in-context edit target, current native '
                 'PropertyManager command and active 3D sketch segments without activation, '
                 'selection, route edits or save. Does not prove managed-route membership.'),
    schema={'type':'object', 'properties':{}, 'required':[], 'additionalProperties':False},
    operation_class=OperationClass.READ,
    com=True,
)
def inspect_routing_active_edit(sw):
    if not _routing_allowed():
        return sw._result(False, _ROUTING_DISABLED_MESSAGE, SwErrors.swInvalidInput)
    doc, _, error = _require_active_assembly(sw)
    if error:
        return error
    data = {'segments': None, 'has_active_sketch': None,
            'managed_route_membership_verified': False,
            'coordinate_system': _COORDINATE_SYSTEM, 'errors': []}
    try:
        def identity(model):
            return {'title':com(model,'GetTitle'), 'path':com(model,'GetPathName'),
                    'document_type':com(model,'GetType')}
        data['document'] = identity(doc)
        target = com(doc, 'GetEditTarget')
        data['edit_target'] = identity(target) if target is not None else None
        if target is not None and data['edit_target']['document_type'] == 2:
            data['edit_target']['native_route_assembly'] = _coerce_native_bool(com(target,'IsRouteAssembly'))
        data['route_managers'] = {}
        for role,model in [('container',doc),('edit_target',target)]:
            if model is None:
                continue
            info = {}
            try:
                raw = _read_route_manager(model)
                info['available'] = raw is not None
                if raw is not None:
                    info['segment_count'] = _route_manager_call(raw,'GetAllRouteSegmentCount')
            except Exception as exc:
                info['unavailable'] = str(exc)
            data['route_managers'][role] = info
        data['command'] = _running_command(sw.app)
        sketch = com(doc, 'GetActiveSketch2')
        data['has_active_sketch'] = sketch is not None
        if sketch is not None:
            data['is_3d'] = _coerce_native_bool(com(sketch,'Is3D'))
            if data['is_3d'] is not True:
                raise ValueError('The active sketch is not a verified native 3D sketch.')
            segments = com(sketch, 'GetSketchSegments')
            if not isinstance(segments, (tuple,list)):
                raise ValueError('Active sketch segment sequence is unavailable.')
            if len(segments) > _MAX_SEGMENTS:
                raise ValueError('Active sketch segment limit exceeded.')
            data['segments'] = [_segment_data(s,i) for i,s in enumerate(segments)]
            data['errors'].extend(e for row in data['segments'] for e in row['errors'])
    except Exception as exc:
        data['errors'].append(str(exc))
    ok = not data['errors']
    return sw._result(ok, 'Read active Routing edit context.' if ok else
                      'Routing edit context read is incomplete; see errors.',
                      SwErrors.swSuccess if ok else SwErrors.swUnknownError, data)


def _checked_active_route_edit(sw, expected_document_path, expected_route_path):
    """Both the container and actual edit target must be explicitly writable."""
    from pathlib import Path
    doc, _, error = _require_active_assembly(sw)
    if error:
        raise ValueError(error['message'])
    if Path(com(doc,'GetPathName')).resolve() != Path(expected_document_path).resolve():
        raise ValueError('Active container path does not match expected_document_path.')
    target = com(doc,'GetEditTarget')
    if target is None or Path(com(target,'GetPathName')).resolve() != Path(expected_route_path).resolve():
        raise ValueError('In-context route path does not match expected_route_path.')
    policy = getattr(sw,'_path_policy',None)
    if policy is None:
        raise ValueError('An explicit approved write policy is required.')
    for path in (expected_document_path,expected_route_path):
        policy.require_write(Path(path),OperationClass.MUTATE)
    if com(target,'GetType') != 2 or _coerce_native_bool(com(target,'IsRouteAssembly')) is not True:
        raise ValueError('Edit target is not a verified native route assembly.')
    command = _running_command(sw.app)
    if command['active']:
        raise ValueError('Close the current PropertyManager before editing the route.')
    sketch = com(doc,'GetActiveSketch2')
    if sketch is None or _coerce_native_bool(com(sketch,'Is3D')) is not True:
        raise ValueError('A native active 3D routing sketch is required.')
    return doc,target,sketch


@tool(
    name='resize_active_routing_line',
    description=('Resize the single existing non-construction line in an active native '
                 'route edit, keeping its start and direction. Requires exact writable '
                 'container/route paths and the observed current length. Verifies the '
                 'result; does not exit, save, create a pipe or prove managed membership.'),
    schema={'type':'object','properties':{
        'expected_document_path':{'type':'string','minLength':1},
        'expected_route_path':{'type':'string','minLength':1},
        'expected_length_mm':{'type':'number','exclusiveMinimum':0,'maximum':100000},
        'length_mm':{'type':'number','exclusiveMinimum':0,'maximum':100000}},
        'required':['expected_document_path','expected_route_path','expected_length_mm','length_mm'],
        'additionalProperties':False},
    operation_class=OperationClass.MUTATE, com=True,
)
def resize_active_routing_line(sw, expected_document_path, expected_route_path,
                               expected_length_mm, length_mm):
    if not _routing_allowed():
        return sw._result(False,_ROUTING_DISABLED_MESSAGE,SwErrors.swInvalidInput)
    data = {'document_may_be_modified':False,'managed_route_membership_verified':False}
    try:
        for value in (expected_length_mm,length_mm):
            if not _finite(value) or not 0 < value <= 100000:
                raise ValueError('Lengths must be finite numbers in (0,100000] mm.')
        _,_,sketch = _checked_active_route_edit(sw,expected_document_path,expected_route_path)
        segments = com(sketch,'GetSketchSegments')
        if not isinstance(segments,(tuple,list)) or len(segments)!=1:
            raise ValueError('Exactly one existing route sketch segment is required.')
        line = segments[0]
        before = data['before'] = _segment_data(line,0)
        if not before['read_complete'] or before['type']!='line' or before['construction']:
            raise ValueError('The existing segment must be a fully readable non-construction line.')
        if not math.isclose(before['length_mm'],expected_length_mm,abs_tol=1e-5,rel_tol=1e-8):
            raise ValueError('Current native line length does not match expected_length_mm.')
        start,end = before['start_mm'],before['end_mm']
        wanted = [a+(b-a)*length_mm/before['length_mm'] for a,b in zip(start,end)]
        data['document_may_be_modified'] = True
        data['native_return'] = com(com(line,'GetEndPoint2'),'SetCoords',*(v/1000 for v in wanted))
        after = data['after'] = _segment_data(line,0)
        if not after['read_complete'] or not math.isclose(after['length_mm'],length_mm,abs_tol=1e-5,rel_tol=1e-8):
            raise ValueError('The requested length was not observed after SetCoords.')
        if after['construction'] or after['type']!='line' or any(
                not math.isclose(a,b,abs_tol=1e-5) for a,b in
                zip(after['start_mm']+after['end_mm'],start+wanted)):
            raise ValueError('Start point, direction or line geometry changed unexpectedly.')
        return sw._result(True,'Existing native route sketch line resized and read back.',SwErrors.swSuccess,data)
    except Exception as exc:
        return sw._result(False,str(exc),SwErrors.swInvalidInput,data)


def _route_manager_call(raw, name):
    import pythoncom
    # GetRouteManager returns a raw IDispatch. Do not truth-test or implicitly
    # call its default property; invoke the documented native method directly.
    return raw.Invoke(raw.GetIDsOfNames(name),0,pythoncom.DISPATCH_METHOD,True)


@tool(
    name='enter_routing_edit',
    description=('Select one exact loaded native route component in its writable container '
                 'and call the container IRouteManager.EditRoute. Verify the actual edit '
                 'target and active 3D sketch. Does not save or change library settings.'),
    schema={'type':'object','properties':{
        'expected_document_path':{'type':'string','minLength':1},
        'expected_route_path':{'type':'string','minLength':1},
        'component_name':{'type':'string','minLength':1}},
        'required':['expected_document_path','expected_route_path','component_name'],
        'additionalProperties':False},operation_class=OperationClass.MUTATE,com=True,
)
def enter_routing_edit(sw,expected_document_path,expected_route_path,component_name):
    from pathlib import Path
    if not _routing_allowed():
        return sw._result(False,_ROUTING_DISABLED_MESSAGE,SwErrors.swInvalidInput)
    data={'document_may_be_modified':False}
    try:
        doc,_,error=_require_active_assembly(sw)
        if error:return error
        if Path(com(doc,'GetPathName')).resolve()!=Path(expected_document_path).resolve():
            raise ValueError('Active container path mismatch.')
        policy=getattr(sw,'_path_policy',None)
        if policy is None:raise ValueError('An explicit write policy is required.')
        for path in (expected_document_path,expected_route_path):
            policy.require_write(Path(path),OperationClass.MUTATE)
        if _running_command(sw.app)['active'] or com(doc,'GetActiveSketch2') is not None:
            raise ValueError('Finish the current PropertyManager/sketch before entering route edit.')
        component=com(doc,'GetComponentByName',component_name)
        if component is None or Path(com(component,'GetPathName')).resolve()!=Path(expected_route_path).resolve():
            raise ValueError('Exact route component/path not found.')
        model=com(component,'GetModelDoc2')
        if model is None or com(model,'GetType')!=2 or _coerce_native_bool(com(model,'IsRouteAssembly')) is not True:
            raise ValueError('Component is not a loaded native route assembly.')
        feature=com(doc,'FeatureByName',component_name)
        if feature is None:raise ValueError('Component feature unavailable for selection.')
        raw=_read_route_manager(doc)
        if raw is None:raise ValueError('Container route manager unavailable.')
        com(doc,'ClearSelection2',True)
        if not com(feature,'Select2',False,0):raise ValueError('Route component selection failed.')
        data['document_may_be_modified']=True
        _route_manager_call(raw,'EditRoute')
        _checked_active_route_edit(sw,expected_document_path,expected_route_path)
        return sw._result(True,'Native route edit target and active 3D sketch verified.',SwErrors.swSuccess,data)
    except Exception as exc:
        return sw._result(False,str(exc),SwErrors.swInvalidInput,data)


@tool(
    name='exit_active_routing_edit',
    description=('Call native IRouteManager.ExitRoute on the checked in-context route, '
                 'then IAssemblyDoc.EditAssembly and verify its active sketch closed. Requires exact writable container '
                 'and route paths. Does not save or infer generated-pipe success.'),
    schema={'type':'object','properties':{
        'expected_document_path':{'type':'string','minLength':1},
        'expected_route_path':{'type':'string','minLength':1}},
        'required':['expected_document_path','expected_route_path'], 'additionalProperties':False},
    operation_class=OperationClass.MUTATE,com=True,
)
def exit_active_routing_edit(sw,expected_document_path,expected_route_path):
    if not _routing_allowed():
        return sw._result(False,_ROUTING_DISABLED_MESSAGE,SwErrors.swInvalidInput)
    data={'document_may_be_modified':False,'generated_pipe_verified':False}
    try:
        doc,target,_ = _checked_active_route_edit(sw,expected_document_path,expected_route_path)
        raw = _read_route_manager(doc)
        if raw is None:
            raise ValueError('Native edit-target route manager is unavailable.')
        data['document_may_be_modified']=True
        _route_manager_call(raw,'ExitRoute')
        # Routing's documented exit sequence also leaves assembly edit mode.
        com(doc,'EditAssembly')
        data['has_active_sketch_after']=com(doc,'GetActiveSketch2') is not None
        if data['has_active_sketch_after']:
            raise ValueError('Native ExitRoute did not close the active route sketch.')
        from pathlib import Path
        after_target=com(doc,'GetEditTarget')
        data['edit_target_after']=com(after_target,'GetPathName') if after_target is not None else None
        if after_target is None or Path(data['edit_target_after']).resolve()!=Path(expected_document_path).resolve():
            raise ValueError('Assembly edit target did not return to the expected container.')
        return sw._result(True,'Native route edit exited; active sketch is closed.',SwErrors.swSuccess,data)
    except Exception as exc:
        return sw._result(False,str(exc),SwErrors.swInvalidInput,data)


