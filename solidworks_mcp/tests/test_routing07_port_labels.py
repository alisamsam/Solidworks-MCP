import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SPEC = importlib.util.spec_from_file_location("verify_ports", SCRIPTS / "verify_routing07_ports.py")
MODULE = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
    SPEC.loader.exec_module(MODULE)


class SavedPortLabelTests(unittest.TestCase):
    def test_labels_require_complete_unique_exact_native_ports(self):
        good = {"success": True, "data": {"coverage": {"complete": True}, "count": 2,
                "connection_points": [{"feature_name": "CPoint1", "port_id": "SPIGOT", "read_complete": True,
                                       "position_mm": [0., 0., 0.], "direction": [-1., 0., 0.], "nominal_diameter_mm": 110.},
                                      {"feature_name": "CPoint2", "port_id": "SOCKET", "read_complete": True,
                                       "position_mm": [1058., 0., 0.], "direction": [1., 0., 0.], "nominal_diameter_mm": 110.}]}}
        MODULE.verify_labels(good)
        for field, value in (("feature_name", "CPoint1"), ("port_id", "SPIGOT"), ("read_complete", False)):
            bad = copy.deepcopy(good)
            bad["data"]["connection_points"][1][field] = value
            with self.assertRaises(RuntimeError):
                MODULE.verify_labels(bad)
        bad = copy.deepcopy(good)
        bad["data"]["coverage"]["complete"] = False
        with self.assertRaises(RuntimeError):
            MODULE.verify_labels(bad)
        swapped = copy.deepcopy(good)
        one, two = swapped["data"]["connection_points"]
        one["position_mm"], two["position_mm"] = two["position_mm"], one["position_mm"]
        one["direction"], two["direction"] = two["direction"], one["direction"]
        with self.assertRaises(RuntimeError):
            MODULE.verify_labels(swapped)

    def test_baseline_is_bound_to_reviewed_source_and_specification(self):
        root = Path("output/routing-07-example-20261015-R03/library-revision").resolve()
        entry = {"source": str(root / "PIPELIFE_KG_SN4_3296104002_SOCKET_ENVELOPE_R03.SLDPRT"),
                 "source_sha256": "a52351350686b5ba76e4648453f662719153bde844fc9d507d1da3a931702d6c"}
        baseline = {"article_id": "PIPELIFE_KG_SN4_PIPE__3296104002", "overall_length_mm": 1058.,
                    "nominal_od_mm": 110., "maximum_diameter_mm": 127.,
                    "geometry_status": "PARTIAL_CATALOGUE_BOUND_SOCKET_ENVELOPE",
                    "expected_volume_mm3": 1191122.7784001548,
                    "part_path": str(root / "SN4_PIPELIFE_OD110_BARREL_R01__copy_0000_b6415b0608.SLDPRT")}
        path = root / "socket-envelope-verification.json"
        MODULE.verify_baseline(baseline, path, entry)
        for key, value in (("overall_length_mm", 1000.), ("nominal_od_mm", 125.),
                           ("geometry_status", "COMPLETE"), ("expected_volume_mm3", 1.)):
            with self.assertRaises(RuntimeError):
                MODULE.verify_baseline(dict(baseline, **{key: value}), path, entry)
        with self.assertRaises(RuntimeError):
            MODULE.verify_baseline(baseline, root / "unrelated.json", entry)
