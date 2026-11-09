import copy
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("socket_example", Path(__file__).resolve().parents[2] / "scripts" / "upgrade_routing07_socket_example.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ARTICLE = {"id":"PIPELIFE_KG_SN4_PIPE__3296104002", "family":"PIPELIFE_KG_SN4_PIPE",
           "article_code":"3296104002", "source_page":5, "pipe_length_m":1.,
           "dimensions":{"DN/OD":"110", "s":"3,2", "Dmax":"127,0", "Dsm min.":"110,4", "A min.":"32,0", "C max.":"26,0"}}


class SocketPlanTests(unittest.TestCase):
    def test_disabled_script_never_constructs_automation(self):
        with patch("sys.argv",["example","--part","C:/never.sldprt","--catalog","C:/never.json"]), \
                patch("solidworks_mcp.catalog.routing_enabled",return_value=False), \
                patch("solidworks_mcp.automation.SolidWorksAutomation") as automation:
            with self.assertRaisesRegex(RuntimeError,"Routing is disabled"):
                MODULE.main()
        automation.assert_not_called()

    def test_final_readback_and_bbox_are_required(self):
        plan=MODULE.socket_plan(ARTICLE)
        def point(x,d):
            return {"read_complete":True,"position_mm":[x,0.,0.],"direction":[d,0.,0.],
                    "nominal_diameter_mm":110.,"stub_length_mm":0.,"route_type_raw":2}
        inspection={"success":True,"data":{"coverage":{"complete":True},"count":2,
                    "connection_points":[point(0,-1),point(1058,1)]}}
        box=[0.,-.0635,-.0635,1.058,.0635,.0635]
        MODULE.verify_native_result(plan,inspection,box)
        for changed in (dict(inspection,success=False),
                        {"success":True,"data":dict(inspection["data"],count=3)},
                        {"success":True,"data":dict(inspection["data"],coverage={"complete":False})}):
            with self.assertRaises(RuntimeError): MODULE.verify_native_result(plan,changed,box)
        with self.assertRaises(RuntimeError): MODULE.verify_native_result(plan,inspection,[0.,0.,0.,1.,1.,1.])
        inspection["data"]["connection_points"][1]["direction"]=[-1,0,0]
        with self.assertRaises(RuntimeError): MODULE.verify_native_result(plan,inspection,box)

    def test_source_bounds_and_explicit_partial_status(self):
        plan = MODULE.socket_plan(ARTICLE)
        self.assertEqual(1058., plan["overall_length_mm"])
        self.assertEqual(127., plan["maximum_diameter_mm"])
        self.assertEqual("PARTIAL_CATALOGUE_BOUND_SOCKET_ENVELOPE", plan["geometry_status"])
        self.assertFalse(plan["qto_include"])
        self.assertFalse(plan["physical_joint_verified"])
        self.assertGreater(plan["expected_volume_mm3"], math.pi*(55**2-51.8**2)*1000)

    def test_profiles_nonnegative_and_no_source_mutation(self):
        before = copy.deepcopy(ARTICLE)
        plan = MODULE.socket_plan(ARTICLE)
        self.assertTrue(all(x>=0 and r>0 for x,r in plan["profile_mm"]))
        self.assertEqual(ARTICLE,before)
        self.assertEqual(10,len(plan["profile_mm"]))

    def test_incomplete_wrong_family_and_degenerate_rejected(self):
        for key,value in (("s","60"),("Dsm min.","109"),("Dmax","115"),("s","nan")):
            article = copy.deepcopy(ARTICLE)
            article["dimensions"][key]=value
            with self.assertRaises(ValueError): MODULE.socket_plan(article)
        article = copy.deepcopy(ARTICLE)
        article["family"]="HTEM"
        with self.assertRaises(ValueError): MODULE.socket_plan(article)
