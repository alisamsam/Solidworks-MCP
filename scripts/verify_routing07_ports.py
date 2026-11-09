"""Verify clean saved CPoint labels on the independent R04 copy, without CAD edits."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.config import get_config
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.tools.routing import list_routing_connection_points
from solidworks_mcp.tools.properties import _read_property
from upgrade_routing07_socket_example import verify_native_result
from verify_routing07_example import require_clean_document


def verify_labels(inspection):
    if not inspection.get("success"):
        raise RuntimeError("Native CPoint inspection failed.")
    data = inspection.get("data", {})
    points = data.get("connection_points", [])
    if data.get("coverage", {}).get("complete") is not True or data.get("count") != 2 or len(points) != 2:
        raise RuntimeError("Expected exactly two completely inspected native ports.")
    expected = {"CPoint1": "SPIGOT", "CPoint2": "SOCKET"}
    observed = {point.get("feature_name"): point.get("port_id") for point in points}
    if observed != expected or any(point.get("read_complete") is not True for point in points):
        raise RuntimeError("Saved native port labels do not match the intended ends.")
    for point in points:
        x, direction = (0., -1.) if point["feature_name"] == "CPoint1" else (1058., 1.)
        for key, values in (("position_mm", [x, 0., 0.]), ("direction", [direction, 0., 0.])):
            actual = point.get(key)
            if not isinstance(actual, (list, tuple)) or len(actual) != 3 or any(
                    not math.isfinite(v) or not math.isclose(v, w, abs_tol=1e-6)
                    for v, w in zip(actual, values)):
                raise RuntimeError("Native port label is on the wrong geometric end.")
        if point.get("nominal_diameter_mm") != 110.:
            raise RuntimeError("Native port nominal diameter differs from OD110 specification.")


def verify_baseline(baseline, path, entry):
    source = Path(entry["source"]).resolve()
    if (path.resolve() != source.parent / "socket-envelope-verification.json"
            or source.name != "PIPELIFE_KG_SN4_3296104002_SOCKET_ENVELOPE_R03.SLDPRT"
            or entry["source_sha256"] != "a52351350686b5ba76e4648453f662719153bde844fc9d507d1da3a931702d6c"):
        raise RuntimeError("Baseline is not the established R03 source evidence.")
    expected = {"article_id": "PIPELIFE_KG_SN4_PIPE__3296104002", "overall_length_mm": 1058.,
                "nominal_od_mm": 110., "maximum_diameter_mm": 127.,
                "geometry_status": "PARTIAL_CATALOGUE_BOUND_SOCKET_ENVELOPE"}
    if any(baseline.get(key) != value for key, value in expected.items()) or not math.isclose(
            baseline.get("expected_volume_mm3", math.inf), 1191122.7784001548, rel_tol=1e-12):
        raise RuntimeError("Baseline differs from the reviewed SN4 OD110 PARTIAL specification.")
    # Baseline predates SaveAs. Its old copy path is lineage, not the saved R03 name.
    old_name = "SN4_PIPELIFE_OD110_BARREL_R01__copy_0000_b6415b0608.SLDPRT"
    if Path(baseline.get("part_path", "")).resolve() != source.parent / old_name:
        raise RuntimeError("Baseline pre-SaveAs lineage does not match the reviewed R03 model.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    policy = get_config().create_path_policy()
    if policy is None:
        raise RuntimeError("Approved output policy required.")
    path = args.part.resolve()
    target = policy.require_write(path.parent / "saved-port-verification.json", OperationClass.EXPORT)
    if target.exists():
        raise FileExistsError(target)
    manifest = json.loads((path.parent / ".solidworks-project-copy.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "verified" or len(manifest.get("files", [])) != 1:
        raise RuntimeError("Expected a verified single-part independent copy.")
    entry = manifest["files"][0]
    if Path(entry["copy"]).resolve() != path:
        raise RuntimeError("Part identity differs from the verified copy manifest.")
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    if sha(entry["source"]) != entry["source_sha256"]:
        raise RuntimeError("Source R03 changed.")
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    verify_baseline(baseline, args.baseline, entry)
    sw = SolidWorksAutomation()
    if not sw.connect()["success"]:
        raise RuntimeError("SolidWorks connection failed.")
    doc = sw.app.ActiveDoc
    if Path(com(doc, "GetPathName")).resolve() != path or com(doc, "GetType") != 1:
        raise RuntimeError("Wrong active document.")
    require_clean_document(doc, "R04 before inspection")
    points = list_routing_connection_points(sw)
    verify_labels(points)
    bodies = list(com(doc, "GetBodies2", 0, True) or [])
    if len(bodies) != 1:
        raise RuntimeError("Native body count changed.")
    box = list(com(bodies[0], "GetBodyBox"))
    verify_native_result(baseline, points, box)
    volume = com(com(com(doc, "Extension"), "CreateMassProperty"), "Volume") * 1e9
    if not math.isclose(volume, baseline["expected_volume_mm3"], rel_tol=1e-9):
        raise RuntimeError("Native geometry volume changed.")
    manager = com(com(doc, "Extension"), "CustomPropertyManager", "")
    labels = {key: _read_property(manager, key)[1] for key in
              ("QTO_INCLUDE", "MODEL_REPRESENTATION", "PHYSICAL_JOINT_VERIFIED", "WIZARD_VERIFIED")}
    if (labels["QTO_INCLUDE"] != "NO" or labels["PHYSICAL_JOINT_VERIFIED"] != "NO"
            or labels["WIZARD_VERIFIED"] != "NOT_CHECKED"
            or labels["MODEL_REPRESENTATION"] != baseline["geometry_status"]):
        raise RuntimeError("Saved PARTIAL/QTO/joint/Wizard labels changed.")
    require_clean_document(doc, "R04 after inspection")
    evidence = {"status": "SAVED_CLEAN_NATIVE_PORT_LABELS_VERIFIED", "part_path": str(path),
                "part_sha256": sha(path), "source_sha256": entry["source_sha256"],
                "source_unchanged": True, "connection_points": points["data"],
                "labels": labels,
                "volume_mm3": volume, "box_m": box, "geometry_metrics_match_baseline": True,
                "full_geometric_identity_verified": False,
                "baseline_path": str(args.baseline.resolve()), "baseline_sha256": sha(args.baseline),
                "native_route_verified": False, "physical_joint_verified": False,
                "qto_include": False, "geometry_status": baseline["geometry_status"],
                "reopened_by_this_verifier": False}
    require_clean_document(doc, "R04 before report")
    with target.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2, allow_nan=False)
    print(json.dumps({"status": evidence["status"], "report": str(target)}))


if __name__ == "__main__":
    main()
