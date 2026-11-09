"""Build an isolated SN4 straight Routing stock from an installed native pipe.

Writes only a new output directory. Does not modify the socketed article or
Routing settings. SN4 geometry is an idealised barrel; excluded from QTO.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import json
import math
from pathlib import Path
import shutil

CONFIG = 'SN4_OD110_ID103p6'
IDENTIFIER = 'SN4 OD110 ID103.6'
HEADERS = ['', '$prp@SWbompartno', '$prp@Pipe Identifier', '$prp@Specification',
           'NominalDiameter@FilterSketch', 'OuterDiameter@PipeSketch',
           'InnerDiameter@PipeSketch', '$prp@Wall Thickness']

def verify_snapshot(s, length_mm):
    def number(value):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError('Native geometry must contain finite numbers.')
        return value
    expected={'length_mm':length_mm,'od_mm':110.,'id_mm':103.6,'nominal_mm':110.,
              'volume_mm3':math.pi*(55.**2-51.8**2)*length_mm}
    for key,want in expected.items():
        if not math.isclose(number(s[key]),want,rel_tol=1e-7,abs_tol=1e-5):
            raise ValueError(f'Native {key} does not verify: {s[key]} versus {want}.')
    if any(type(s[key]) is not int or s[key] != 1 for key in ('body_count','component_type')):
        raise ValueError('Requires exactly one solid and native Pipe type 1.')
    box=s['body_box_mm']
    if len(box)!=6 or any(not math.isclose(number(v),w,abs_tol=1e-4) for v,w in
                          zip(box,[-55.,-55.,0.,55.,55.,length_mm])):
        raise ValueError('Native bounding box must verify the +Z barrel.')
    if s['configurations'] != [CONFIG] or s['pipe_identifier'] != IDENTIFIER:
        raise ValueError('Requires the unique SN4 stock configuration and identifier.')
    if any(s.get(key) != 'NO' for key in ('qto_include_value','native_route_verified_value')):
        raise ValueError('Stock must persist QTO_INCLUDE=NO and NATIVE_ROUTE_VERIFIED=NO.')
    headers=s['design_table_headers']
    if 'Length@Extrusion' in headers or not {HEADERS[2],*HEADERS[4:7]}.issubset(headers):
        raise ValueError('Design table must define pipe stock while leaving length uncontrolled.')

def native_method(obj,name,*args):
    import pythoncom
    return obj._oleobj_.Invoke(obj._oleobj_.GetIDsOfNames(name),0,pythoncom.DISPATCH_METHOD,True,*args)

def inspect_stock(doc):
    import pythoncom,win32com.client
    from solidworks_mcp.comutil import com
    values={key:com(doc.Parameter(name),'SystemValue')*1000 for key,name in
            [('length_mm','Length@Extrusion'),('od_mm','OuterDiameter@PipeSketch'),
             ('id_mm','InnerDiameter@PipeSketch'),('nominal_mm','NominalDiameter@FilterSketch')]}
    bodies=list(com(doc,'GetBodies2',0,True) or [])
    values.update(body_count=len(bodies),body_box_mm=[v*1000 for v in com(bodies[0],'GetBodyBox')],
        volume_mm3=com(com(com(doc,'Extension'),'CreateMassProperty'),'Volume')*1e9,
        component_type=native_method(com(com(doc,'Extension'),'GetRoutingComponentManager'),'GetComponentType'),
        configurations=list(com(doc,'GetConfigurationNames') or []))
    table=com(doc,'GetDesignTable')
    if table is None or not com(table,'Attach'):
        raise ValueError('Cannot inspect the native design table.')
    sheet=None
    try:
        sheet=com(table,'Worksheet')
        values['design_table_headers']=[str(v or '') for v in sheet.UsedRange.Rows(1).Value[0]]
    finally:
        sheet=None
        gc.collect()
        com(table,'Detach')
    props=com(com(doc,'Extension'),'CustomPropertyManager',CONFIG)
    raw=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BSTR,'')
    resolved=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BSTR,'')
    props.Get2('Pipe Identifier',raw,resolved)
    values['pipe_identifier']=resolved.value
    props=com(com(doc,'Extension'),'CustomPropertyManager','')
    for name,key in [('QTO_INCLUDE','qto_include_value'),('NATIVE_ROUTE_VERIFIED','native_route_verified_value')]:
        raw.value='';resolved.value=''
        props.Get2(name,raw,resolved)
        values[key]=resolved.value
    return values

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    from solidworks_mcp.catalog import routing_enabled
    if not routing_enabled():
        raise RuntimeError('Routing is disabled; enable it explicitly for this process.')
    root=args.output.resolve()
    workspace=Path(__file__).resolve().parents[1]
    if not root.is_relative_to(workspace/'output') or root.exists():
        raise ValueError('Output must be a new directory under this workspace/output.')
    source=Path('C:/ProgramData/SOLIDWORKS/SOLIDWORKS 2025/design library/routing/piping/pipes/pipe.sldprt')
    source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    root.mkdir(parents=True)
    target=root/'SN4_OD110_STRAIGHT_STOCK_R06.SLDPRT'
    shutil.copy2(source,target)
    import pythoncom,win32com.client
    from solidworks_mcp.automation import SolidWorksAutomation
    from solidworks_mcp.comutil import com
    from solidworks_mcp.core.policy import PathPolicy
    from solidworks_mcp.tools.connection import get_modeling_guide
    pythoncom.CoInitialize()
    sw=SolidWorksAutomation()
    assert sw.connect()['success']
    sw.set_path_policy(PathPolicy([root],[source.parent]))
    for topic in ['index','workflow/operating','workflow/part']:
        guide=get_modeling_guide(sw,topic)
        assert guide['success'],guide
    app=sw.app
    if com(app,'GetDocuments'):
        raise RuntimeError('Close other documents before running this isolated stock builder.')
    errors=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    warnings=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    doc=app.OpenDoc6(str(target),1,1,'',errors,warnings)
    assert doc is not None,(errors.value,warnings.value)
    sw.bind_active_document()
    table=com(doc,'GetDesignTable')
    sheet=table.EditTable2(True)
    if sheet is None: raise RuntimeError('Native design table did not expose its worksheet.')
    sheet.UsedRange.Clear()
    sheet.Range('A1:H2').Value=(tuple(HEADERS),(CONFIG,CONFIG,IDENTIFIER,'SN4',
        '110mm','110mm','103.6mm','3.2mm'))
    sheet=None;gc.collect()
    assert table.UpdateTable(2,True),'Design table update failed.'
    assert doc.ShowConfiguration2(CONFIG),'New SN4 configuration missing.'
    for name in list(com(doc,'GetConfigurationNames') or []):
        if name!=CONFIG:
            assert doc.DeleteConfiguration2(name),f'Could not remove inherited config {name}'
    props=com(com(doc,'Extension'),'CustomPropertyManager','')
    for name,value in [('QTO_INCLUDE','NO'),('GEOMETRY_STATUS','IDEALISED_STRAIGHT_BARREL'),
                       ('SOURCE_ARTICLE_ID','PIPELIFE_KG_SN4_PIPE__3296104002'),('NATIVE_ROUTE_VERIFIED','NO')]:
        props.Add3(name,30,value,2)
    report={'source_template':str(source),'source_sha256':source_sha,'part':str(target),
        'test_lengths_mm':[500.,1000.],'qto_include':False,'native_route_verified':False,'snapshots':[]}
    for length in report['test_lengths_mm']:
        dim=doc.Parameter('Length@Extrusion')
        status=dim.SetSystemValue3(length/1000,1,win32com.client.VARIANT(pythoncom.VT_EMPTY,None))
        assert status==0,('SetSystemValue3',status)
        assert doc.ForceRebuild3(False)
        snapshot=inspect_stock(doc)
        verify_snapshot(snapshot,length)
        report['snapshots'].append(snapshot)
        print('VERIFIED',length,snapshot['volume_mm3'],flush=True)
    doc.ShowNamedView2('*Isometric',7);doc.ViewZoomtofit2()
    doc.ClearSelection2(True)
    assert doc.SaveBMP(str(root/'sn4-stock.bmp'),0,0)
    saved=sw.save_document(str(target))
    assert saved['success'],saved
    app.CloseDoc(com(doc,'GetTitle'))
    doc=app.OpenDoc6(str(target),1,1,CONFIG,errors,warnings)
    assert doc is not None
    saved_clean_before_read=not com(doc,'GetSaveFlag')
    snapshot=inspect_stock(doc)
    verify_snapshot(snapshot,1000.)
    report['reopened_snapshot']=snapshot
    # Native design-table Attach/Detach can dirty an otherwise clean document.
    # Record that observable side effect instead of claiming this is a pure read.
    report['saved_clean_before_read']=saved_clean_before_read
    report['saveflag_after_design_table_read']=bool(com(doc,'GetSaveFlag'))
    report['source_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==source_sha
    assert report['source_unchanged'] and report['saved_clean_before_read']
    report['status']='STOCK_GEOMETRY_AND_REOPEN_VERIFIED_NATIVE_ROUTE_PENDING'
    (root/'stock-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    from solidworks_mcp.tools.views import _bmp_to_png
    import struct
    bmp=root/'sn4-stock.bmp'
    width,height=struct.unpack_from('<ii',bmp.read_bytes(),18)
    _bmp_to_png(bmp,root/'sn4-stock.png',width,abs(height))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()


