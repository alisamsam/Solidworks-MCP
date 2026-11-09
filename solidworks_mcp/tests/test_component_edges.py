"""Instance-bound, paged geometry and checked native selection contracts."""
import math
from types import SimpleNamespace
import unittest
from solidworks_mcp.tools.component_edges import list_component_edges,select_component_edges


class Curve:
    def __init__(self,kind):self.kind=kind
    def IsLine(self):return self.kind=='line'
    def IsCircle(self):return self.kind=='circle'
    def CircleParams(self):return [0.,0.,0.,0.,0.,1.,.005]
    def GetLength3(self,a,b):return b-a

class Edge:
    def __init__(self,key,component,kind='line'):
        self.key=key;self.component=component;self.kind=kind;self.fail_select=False
    def GetComponent(self):return self.component
    def GetCurve(self):return Curve(self.kind)
    def GetCurveParams3(self):
        return SimpleNamespace(StartPoint=[0.,0.,0.] if self.kind=='line' else [.005,0.,0.],
            EndPoint=[.1,0.,0.] if self.kind=='line' else [.005,0.,0.],UMinValue=0.,UMaxValue=.1 if self.kind=='line' else 2*math.pi*.005)
    def GetClosestPointOn(self,x,y,z):return [min(.1,max(0,x)),0.,0.]
    def GetType(self):return 1
    def Select4(self,append,data):
        if self.fail_select:return False
        selected=self.component.doc.selected
        if not append:selected.clear()
        selected.append((self,data.Mark));return True

class Body:
    def __init__(self,comp):self.name_reads=0;self.edges=[Edge('line@'+comp.Name2,comp),Edge('circle@'+comp.Name2,comp,'circle')]
    @property
    def Name(self):self.name_reads+=1;return 'Body'
    def GetEdges(self):return self.edges

class Part:
    def __init__(self):self.stamp=10
    def GetUpdateStamp(self):return self.stamp
    def GetType(self):return 1

class Component:
    def __init__(self,name,doc):
        self.Name2=name;self.key=name;self.doc=doc;self.ReferencedConfiguration='Default';self.part=Part();self.suppression=2
        self.Transform2=SimpleNamespace(ArrayData=[1.,0.,0.,0.,1.,0.,0.,0.,1.,.2,0.,0.,1.,0.,0.,0.])
        self.children=[];self.bodies=[Body(self)]
    def GetPathName(self):return 'C:/own/BLOCK.SLDPRT' if self.bodies else 'C:/own/SUB.SLDASM'
    def GetModelDoc2(self):return self.part
    def GetSuppression(self):return self.suppression
    def GetChildren(self):return self.children
    def GetBodies2(self,kind):return self.bodies

class Selection:
    def __init__(self,doc):self.doc=doc
    def CreateSelectData(self):return SimpleNamespace(Mark=0)
    def GetSelectedObjectCount2(self,mark):return len(self.doc.selected)
    def GetSelectedObject6(self,index,mark):return self.doc.selected[index-1][0]
    def GetSelectedObjectMark(self,index):return self.doc.selected[index-1][1]
    def GetSelectedObjectType3(self,index,mark):return 1
    def GetSelectedObjectsComponent4(self,index,mark):return self.doc.selected[index-1][0].component

class Extension:
    def __init__(self,doc):self.doc=doc;self.refs={};self.wrong=None
    def GetPersistReference3(self,obj):
        payload=obj.key.encode();self.refs[payload]=obj;return payload
    def GetObjectByPersistReference3(self,array,status):
        status.value=0;return self.wrong or self.refs.get(bytes(array.value))
    def MultiSelect2(self,array,append,data):
        if not append:self.doc.selected.clear()
        for obj in array.value:self.doc.selected.append((obj,data.Mark))
        return len(self.doc.selected)

class Doc:
    def __init__(self):
        self.path='C:/own/MAIN.SLDASM';self.stamp=3;self.selected=[];self.clears=0
        self.ConfigurationManager=SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name='Default'))
        self.SelectionManager=Selection(self);self.Extension=Extension(self)
        self.top=Component('BLOCK-1',self);self.sub=Component('SUB-1',self);self.sub.bodies=[]
        self.child=Component('SUB-1/BLOCK-1',self);self.sub.children=[self.child];self.components=[self.top,self.sub]
    def GetType(self):return 2
    def GetPathName(self):return self.path
    def GetUpdateStamp(self):return self.stamp
    def GetComponents(self,top):
        if not top:raise AssertionError('must not scan whole assembly recursively')
        return self.components
    def ClearSelection2(self,value):self.clears+=1;self.selected.clear()

class App:
    def IsSame(self,a,b):return 1 if a.key==b.key else 0

class Automation:
    def __init__(self):self.doc=Doc();self.app=App()
    def get_active_doc(self):return self.doc,None
    def _result(self,success,message,error_code=None,data=None):return dict(success=success,message=message,data=data,error_code=error_code)


class ComponentEdgeTests(unittest.TestCase):
    def setUp(self):self.sw=Automation();self.doc=self.sw.doc
    def listed(self,**kw):return list_component_edges(self.sw,'SUB-1/BLOCK-1',**kw)
    def select(self,listed,ids=None,**kw):
        d=listed['data'];return select_component_edges(self.sw,d['snapshot_id'],ids if ids is not None else [d['edges'][0]['edge_id']],**kw)
    def test_exact_nested_context_and_assembly_coordinates(self):
        r=self.listed();self.assertTrue(r['success'],r);d=r['data'];self.assertEqual('SUB-1/BLOCK-1',d['component_path'])
        self.assertEqual([200.,0.,0.],d['edges'][0]['start_mm']);self.assertEqual(100.,d['edges'][0]['length_mm'])
        self.assertEqual(0,self.doc.clears)
    def test_circle_with_no_distinct_vertices_is_retained(self):
        r=self.listed(curve_type='circle');self.assertTrue(r['success'],r)
        edge=r['data']['edges'][0];self.assertEqual('circle',edge['curve_type']);self.assertAlmostEqual(5,edge['radius_mm'])
        self.assertAlmostEqual(10*math.pi,edge['length_mm'])
    def test_paging_is_bounded_and_context_scoped(self):
        r=self.listed(limit=1);self.assertEqual(1,len(r['data']['edges']));self.assertEqual(1,r['data']['next_offset'])
        r2=self.listed(offset=1,limit=1);self.assertEqual('circle',r2['data']['edges'][0]['curve_type']);self.assertIsNone(r2['data']['next_offset'])
    def test_body_metadata_is_read_once_even_for_large_component(self):
        body=self.doc.child.bodies[0];body.edges=[Edge(str(i),self.doc.child) for i in range(1000)]
        r=self.listed(limit=1);self.assertTrue(r['success'],r);self.assertEqual(1,body.name_reads)
    def test_near_filter_uses_assembly_space(self):
        r=self.listed(curve_type='line',near_point_mm=[250,0,0],within_mm=1)
        self.assertEqual(1,len(r['data']['edges']))
        self.assertFalse(self.listed(curve_type='line',near_point_mm=[250,20,0],within_mm=1)['data']['edges'])
    def test_missing_component_does_not_fall_back_to_suffix(self):
        self.assertFalse(list_component_edges(self.sw,'BLOCK-9')['success'])
        self.assertTrue(self.listed()['success'])
    def test_subassembly_is_not_silently_scanned(self):
        self.assertFalse(list_component_edges(self.sw,'SUB-1')['success'])
    def test_lightweight_is_reported_without_auto_resolve(self):
        self.doc.child.suppression=1;self.assertFalse(self.listed()['success'])
    def test_checked_selection_owns_exact_nested_instance(self):
        r=self.listed();s=self.select(r);self.assertTrue(s['success'],s)
        self.assertEqual('SUB-1/BLOCK-1',self.doc.selected[0][0].component.Name2)
    def test_wrong_instance_persistent_resolution_is_rejected_before_clear(self):
        r=self.listed();self.doc.Extension.wrong=self.doc.top.bodies[0].edges[0]
        self.assertFalse(self.select(r)['success']);self.assertEqual(0,self.doc.clears)
    def test_stale_assembly_or_part_or_transform_is_rejected(self):
        for attr in ['assembly','part','transform']:
            with self.subTest(attr=attr):
                r=self.listed()
                if attr=='assembly':self.doc.stamp+=1
                elif attr=='part':self.doc.child.part.stamp+=1
                else:self.doc.child.Transform2.ArrayData[9]+=.1
                before=self.doc.clears;self.assertFalse(self.select(r)['success']);self.assertEqual(before,self.doc.clears)
    def test_other_document_is_rejected(self):
        r=self.listed();self.doc.path='C:/own/OTHER.SLDASM';self.assertFalse(self.select(r)['success'])
    def test_failure_restores_original_selection(self):
        r=self.listed();old=self.doc.top.bodies[0].edges[0];self.doc.selected=[(old,7)]
        self.doc.child.bodies[0].edges[0].fail_select=True
        s=self.select(r);self.assertFalse(s['success']);self.assertEqual([(old,7)],self.doc.selected)
        self.assertTrue(s['data']['selection_restored'])
    def test_append_is_idempotent_for_same_edge_and_mark(self):
        r=self.listed();self.assertTrue(self.select(r)['success']);self.assertTrue(self.select(r,append=True)['success'])
        self.assertEqual(1,len(self.doc.selected))
    def test_edge_not_returned_in_page_is_rejected(self):
        r=self.listed(limit=1);self.assertFalse(self.select(r,[999])['success']);self.assertEqual(0,self.doc.clears)
    def test_bad_inputs_rejected_without_clear(self):
        for kw in [dict(limit=0),dict(limit=True),dict(offset=-1),dict(curve_type='bad'),dict(min_length_mm=float('nan')),
                   dict(near_point_mm=[1,2,3]),dict(within_mm=2),dict(body_index=True)]:
            with self.subTest(kw=kw):self.assertFalse(self.listed(**kw)['success'])
        r=self.listed();self.assertFalse(self.select(r,[True])['success']);self.assertEqual(0,self.doc.clears)

if __name__=='__main__':unittest.main()
