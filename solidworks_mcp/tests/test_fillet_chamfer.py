"""Feature fillet and chamfer use the sldworks.tlb signatures (live, §34)."""

import math
import unittest
from unittest.mock import Mock,patch
from solidworks_mcp.core.policy import PathPolicy
from pathlib import Path

from solidworks_mcp.automation.features import FeatureOperations


class Feature:
    def __init__(self,kind):self.kind=kind;self.Name=kind+'1'
    def GetTypeName2(self):return self.kind
    def GetErrorCode2(self,warning):return 0

class Mass:
    def __init__(self,doc):self.doc=doc
    @property
    def Volume(self):return self.doc.volume

class Selection:
    def __init__(self):self.count=1;self.kind=1
    def GetSelectedObjectCount2(self,mark):return self.count
    def GetSelectedObjectType3(self,index,mark):return self.kind

class Edge:
    def __init__(self):self.calls=[]
    def Select4(self,append,data):self.calls.append(append);return True

class FeatureManager:
    def __init__(self,doc):
        self.doc=doc;self.no_effect=False;self.missing=False
        self.calls = []

    def add(self,kind):
        if not self.no_effect:self.doc.volume-=1e-7
        f=Feature(kind)
        if not self.missing:self.doc.features[f.Name]=f
        return f

    def FeatureFillet3(self, *args):
        self.calls.append(("FeatureFillet3", args))
        return self.add('Fillet')

    def InsertFeatureChamfer(self, *args):
        self.calls.append(("InsertFeatureChamfer", args))
        return self.add('Chamfer')


class Extension:
    def __init__(self, hits,doc):
        self.doc=doc
        self.hits = hits
        self.picks = []

    def SelectByID2(self, name, kind, x, y, z, append, mark, callout, option):
        self.picks.append((kind, (x, y, z), append))
        self.doc.SelectionManager.count=(self.doc.SelectionManager.count+1) if append else 1
        return self.hits

    def CreateMassProperty(self):return Mass(self.doc)


class Document:
    def __init__(self, hits=True):
        self.volume=1e-4;self.features={};self.SelectionManager=Selection()
        self.FeatureManager = FeatureManager(self)
        self.Extension = Extension(hits,self)

    def GetType(self):return 1
    def GetPathName(self):return ''
    def FeatureByName(self,name):return self.features.get(name)
    def EditRebuild3(self):return True

    def ClearSelection2(self, all_):
        return True


class Units:
    def to_meters(self, value, unit):
        return value / 1000.0

    class default_unit:
        value = "mm"


class Automation(FeatureOperations):
    def __init__(self, document):
        self.document = document
        self._units = Units()

    def get_active_doc(self):
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class FeatureFilletTests(unittest.TestCase):
    def test_native_index_selection_does_not_use_view_hit_test(self):
        doc=Document(hits=False);edge=Edge()
        with patch('solidworks_mcp.tools.inspection.part_edges',return_value=[{'edge':edge}]):
            r=Automation(doc).fillet_edges(2,edge_indices=[0])
        self.assertTrue(r['success'],r)
        self.assertEqual([False],edge.calls)
        self.assertEqual([],doc.Extension.picks)

    def test_invalid_indices_never_read_document(self):
        for indices,points in [([],None),([True],None),([-1],None),([0,0],None),([1.2],None),([0],[[0,0,0]])]:
            sw=Automation(Document());sw.get_active_doc=Mock(side_effect=RuntimeError('COM forbidden'))
            self.assertFalse(sw.fillet_edges(edge_indices=indices,edge_points=points)['success'])
            sw.get_active_doc.assert_not_called()

    def test_tangent_propagation_can_be_disabled(self):
        doc=Document();r=Automation(doc).fillet_edges(2,tangent_propagation=False)
        self.assertTrue(r['success'],r)
        self.assertEqual(2,doc.FeatureManager.calls[0][1][0])

    def test_invalid_radius_never_reads_document(self):
        for value in (-1,0,True,float('inf'),float('nan')):
            sw=Automation(Document());sw.get_active_doc=Mock(side_effect=RuntimeError('COM forbidden'))
            self.assertFalse(sw.fillet_edges(radius=value)['success'])
            sw.get_active_doc.assert_not_called()

    def test_saved_reference_part_is_not_mutated(self):
        doc=Document();doc.GetPathName=Mock(return_value=str(Path('protected/source.SLDPRT').resolve()))
        sw=Automation(doc);sw._path_policy=PathPolicy([Path('output/edge-finishing-20261018-R01')])
        self.assertFalse(sw.fillet_edges()['success'])
        self.assertEqual([],doc.FeatureManager.calls)

    def test_fillet_passes_the_fourteen_argument_signature(self):
        document = Document()
        result = Automation(document).fillet_edges(5, "mm")

        self.assertTrue(result["success"], result["message"])
        name, args = document.FeatureManager.calls[0]
        self.assertEqual("FeatureFillet3", name)
        self.assertEqual(14, len(args))
        # Propagate + uniform radius, R1 = 5 mm, simple fillet.
        self.assertEqual((3, 0.005, 0.0, 0.0, 0), args[:5])

    def test_fillet_selects_edges_at_the_given_points(self):
        document = Document()
        result = Automation(document).fillet_edges(
            5, "mm", edge_points=[[0, 50, 50], [40, 50, 0]])

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            [("EDGE", (0.0, 0.05, 0.05), False), ("EDGE", (0.04, 0.05, 0.0), True)],
            document.Extension.picks)

    def test_fillet_reports_an_edge_point_that_hits_nothing(self):
        document = Document(hits=False)
        result = Automation(document).fillet_edges(5, "mm", edge_points=[[1, 2, 3]])

        self.assertFalse(result["success"])
        self.assertEqual("SELECTION_EMPTY", result["data"]["code"])
        self.assertEqual([], document.FeatureManager.calls)


class FeatureChamferTests(unittest.TestCase):
    def test_failed_rebuild_does_not_claim_verified_geometry(self):
        for operation in ('chamfer_edges', 'fillet_edges'):
            with self.subTest(operation=operation):
                doc=Document();doc.EditRebuild3=lambda:False
                result=getattr(Automation(doc),operation)()
                self.assertFalse(result['success'])
                self.assertTrue(result['data']['document_may_be_modified'])
                self.assertFalse(result['data'].get('geometry_verified',False))

    def test_two_distances_use_native_runtime_width_and_otherdist(self):
        doc=Document();r=Automation(doc).chamfer_edges(3,unit='mm',
            chamfer_type='distance_distance',distance2=5,tangent_propagation=False,flip_direction=True)
        self.assertTrue(r['success'],r)
        self.assertEqual((1,2,.003,0.,.005,0.,0.,0.),doc.FeatureManager.calls[0][1])
        self.assertAlmostEqual(100.,abs(r['data']['volume_delta_mm3']))

    def test_invalid_inputs_never_reach_com(self):
        for args in [dict(distance=0),dict(distance=float('nan')),dict(distance=True),
                     dict(angle=90),dict(angle=0),dict(chamfer_type='unknown'),
                     dict(chamfer_type='distance_distance'),
                     dict(chamfer_type='distance_distance',distance2=-1),
                     dict(distance2=4),dict(tangent_propagation='false'),
                     dict(edge_points=[]),dict(edge_points=[[0,0]]),
                     dict(edge_points=[[0,0,float('inf')]]),
                     dict(edge_points=[[0,0,0],[0,0,0]])]:
            with self.subTest(args=args):
                sw=Automation(Document())
                sw.get_active_doc=Mock(side_effect=RuntimeError('COM forbidden'))
                self.assertFalse(sw.chamfer_edges(**args)['success'])
                sw.get_active_doc.assert_not_called()

    def test_native_proxy_without_persisted_feature_fails(self):
        doc=Document();doc.FeatureManager.missing=True
        self.assertFalse(Automation(doc).chamfer_edges()['success'])

    def test_native_proxy_without_geometry_change_fails(self):
        doc=Document();doc.FeatureManager.no_effect=True
        self.assertFalse(Automation(doc).chamfer_edges()['success'])

    def test_non_edge_selection_never_mutates(self):
        doc=Document();doc.SelectionManager.kind=2
        self.assertFalse(Automation(doc).chamfer_edges()['success'])
        self.assertEqual([],doc.FeatureManager.calls)

    def test_chamfer_passes_the_eight_argument_signature(self):
        document = Document()
        result = Automation(document).chamfer_edges(5, 45, "mm")

        self.assertTrue(result["success"], result["message"])
        name, args = document.FeatureManager.calls[0]
        self.assertEqual("InsertFeatureChamfer", name)
        # Tangent propagation, angle-distance, width 5 mm at 45 degrees.
        self.assertEqual((4, 1, 0.005, math.radians(45), 0.0, 0.0, 0.0, 0.0), args)

    def test_chamfer_selects_edges_at_the_given_points(self):
        document = Document()
        Automation(document).chamfer_edges(5, 45, "mm", edge_points=[[0, 50, 50]])

        self.assertEqual([("EDGE", (0.0, 0.05, 0.05), False)],
                         document.Extension.picks)


if __name__ == "__main__":
    unittest.main()
