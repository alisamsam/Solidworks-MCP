import unittest
from solidworks_mcp.tools.inspection import part_edges
from solidworks_mcp.tests.test_weldment_weld_bead import Body, Edge

class ClosedEdge:
    def GetCurve(self):return self
    def IsLine(self):return False
    def GetStartVertex(self):return None
    def GetEndVertex(self):return None

class Document:
    def __init__(self,bodies):self.bodies=bodies
    def GetBodies2(self,*args):return self.bodies

class PartEdgeTests(unittest.TestCase):
    def test_native_cache_invalidates_after_update_stamp_changes(self):
        class NativeBody(Body):
            _oleobj_=object()
            calls=0
            def GetEdges(self):
                self.calls+=1
                return self.faces[0].edges
        class NativeDocument(Document):
            _oleobj_=object()
            stamp=0
            def GetUpdateStamp(self):return self.stamp
        body=NativeBody('post',[Edge((0,0,0),(.096,0,0))])
        doc=NativeDocument([body])
        part_edges(doc);part_edges(doc)
        self.assertEqual(body.calls,1)
        doc.stamp+=1
        part_edges(doc)
        self.assertEqual(body.calls,2)
    def test_native_parameter_array_avoids_vertex_calls(self):
        class NativeEdge(Edge):
            def GetCurveParams2(self):return self.start+self.end+(0,1,0,0,0)
            def GetStartVertex(self):raise AssertionError('Native fast path must avoid vertex calls')
        class NativeBody(Body):
            def GetEdges(self):return self.faces[0].edges
        rows=part_edges(Document([NativeBody('post',[NativeEdge((0,0,0),(.096,0,0))])]))
        self.assertEqual(rows[0]['end_mm'],[96,0,0])
    def test_closed_hole_does_not_break_following_straight_edge(self):
        edge=Edge((0,0,0),(.096,0,0))
        rows=part_edges(Document([Body('post',[ClosedEdge(),edge,edge])]))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['index'],0)
        self.assertEqual(rows[0]['length_mm'],96)

    def test_touching_bodies_retain_separate_coincident_edges(self):
        rows=part_edges(Document([Body('post',[Edge((0,0,0),(.096,0,0))]),Body('plate',[Edge((0,0,0),(.096,0,0))])]))
        self.assertEqual([r['body'] for r in rows],['post','plate'])
        self.assertEqual([r['index'] for r in rows],[0,1])

    def test_tab_slot_matches_same_named_body_at_selected_position(self):
        from solidworks_mcp.tools.sheetmetal import _match_body
        reference={'name':'post','volume_mm3':100,'centroid_m':[0,1,0]}
        rows=[{'name':'post','volume_mm3':100,'centroid_m':[0,2,0]},
              {'name':'post','volume_mm3':101,'centroid_m':[0,1.00001,0]}]
        self.assertIs(_match_body(rows,'Tab and Slot-Tab',reference),rows[1])
