"""Read-only CAD verification of the reopened, explicitly PARTIAL library example."""
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
from solidworks_mcp.tools.routing_components import get_component_connection_points
from solidworks_mcp.tools.routing_measure import measure_routing_connection_gap
from solidworks_mcp.tools.properties import _read_property
from upgrade_routing07_socket_example import verify_native_result


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_clean_document(document, label):
    try:
        dirty=com(document,"GetSaveFlag")
    except Exception as exc:
        raise RuntimeError(f"Cannot establish clean saved state for {label}.") from exc
    if not isinstance(dirty,bool) or dirty:
        raise RuntimeError(f"{label} has unsaved or unreadable changes; saved-file verification denied.")


def verify_placement(transform, fixed, expected_x):
    expected=[1.,0.,0.,0.,1.,0.,0.,0.,1.,expected_x,0.,0.,1.,0.,0.,0.]
    if (fixed is not True or len(transform)!=16 or
        any(not math.isfinite(v) or not math.isclose(v,w,abs_tol=1e-9) for v,w in zip(transform,expected))):
        raise RuntimeError("Saved rigid placement/orientation/fixed state did not verify.")


def verify_gap(result):
    if not result.get("success"): raise RuntimeError("Saved gap read failed.")
    gap=result.get("data",{}).get("measurement",{})
    if (not math.isclose(gap.get("distance_mm",math.inf),100.,abs_tol=1e-6)
        or not math.isclose(gap.get("opposition_angle_deg",math.inf),0.,abs_tol=1e-6)
        or not math.isclose(gap.get("direction_dot",math.inf),-1.,abs_tol=1e-6)
        or not math.isclose(gap.get("diameter_difference_mm",math.inf),0.,abs_tol=1e-6)
        or gap.get("route_type_equal") is not True):
        raise RuntimeError("Saved gap/opposition/nominal-type comparison did not verify.")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--report-name",default="saved-example-verification.json")
    parser.add_argument("--external-reopen-operation",default=None)
    args=parser.parse_args()
    policy=get_config().create_path_policy()
    if policy is None: raise RuntimeError("Approved output policy required.")
    root=policy.require_write(args.root.resolve(),OperationClass.EXPORT)
    if Path(args.report_name).name!=args.report_name or not args.report_name.endswith(".json"):
        raise ValueError("report-name must be a simple JSON filename.")
    target=root/args.report_name
    if target.exists(): raise FileExistsError(target)
    plan=json.loads((root/"library-revision/socket-envelope-verification.json").read_text())
    manifest=json.loads((root/"library-revision/.solidworks-project-copy.json").read_text())
    original=manifest["files"][0]
    if sha(original["source"])!=original["source_sha256"]:
        raise RuntimeError("Original R01 source hash changed.")
    if sha(plan["catalog_path"])!=plan["catalog_sha256"]:
        raise RuntimeError("Existing source article catalogue changed.")
    sw=SolidWorksAutomation()
    if not sw.connect()["success"]: raise RuntimeError("SolidWorks connection failed.")
    doc=sw.app.ActiveDoc
    assembly=Path(com(doc,"GetPathName")).resolve()
    if com(doc,"GetType")!=2 or assembly.parent!=root:
        raise RuntimeError("Expected the saved example assembly to be active.")
    require_clean_document(doc,"assembly before read")
    components=list(com(doc,"GetComponents",True) or [])
    if len(components)!=2: raise RuntimeError("Expected exactly two library component instances.")
    first="PIPELIFE_KG_SN4_3296104002_SOCKET_ENVELOPE_R03-1"
    second="PIPELIFE_KG_SN4_3296104002_SOCKET_ENVELOPE_R03-2"
    if {com(c,"Name2") for c in components}!={first,second}: raise RuntimeError("Wrong component identities.")
    identities=[]
    part=None
    for component in components:
        part_path=Path(com(component,"GetPathName")).resolve()
        expected_part=root/"library-revision/PIPELIFE_KG_SN4_3296104002_SOCKET_ENVELOPE_R03.SLDPRT"
        if part_path!=expected_part: raise RuntimeError("Unexpected or external CAD dependency.")
        part=com(component,"GetModelDoc2")
        require_clean_document(part,"referenced part before read")
        transform=list(com(com(component,"Transform2"),"ArrayData"))
        name=com(component,"Name2")
        expected=0. if name==first else 1.158
        verify_placement(transform,com(component,"IsFixed"),expected)
        read=get_component_connection_points(sw,name)
        if not read["success"] or not read["data"]["coverage"]["complete"]: raise RuntimeError(str(read))
        identities.append({"name":name,"path":str(part_path),"transform":transform,
                           "fixed":True,"configuration":read["data"]["configuration"],
                           "connection_points":read["data"]["connection_points"]})
    point_data=get_component_connection_points(sw,first)["data"]
    native_points={"success":True,"data":{"coverage":point_data["coverage"],
                    "count":point_data["count"],"connection_points":point_data["connection_points"]}}
    bodies=list(com(part,"GetBodies2",0,True) or [])
    if len(bodies)!=1: raise RuntimeError("Expected one saved native part body.")
    box=list(com(bodies[0],"GetBodyBox"))
    verify_native_result(plan,native_points,box)
    volume=com(com(com(part,"Extension"),"CreateMassProperty"),"Volume")*1e9
    if not math.isclose(volume,plan["expected_volume_mm3"],rel_tol=1e-6): raise RuntimeError("Saved volume mismatch.")
    manager=com(com(part,"Extension"),"CustomPropertyManager","")
    labels={key:_read_property(manager,key)[1] for key in
            ("QTO_INCLUDE","MODEL_REPRESENTATION","SEAL_GROOVE","WIZARD_VERIFIED","PHYSICAL_JOINT_VERIFIED")}
    if labels["QTO_INCLUDE"]!="NO" or labels["MODEL_REPRESENTATION"]!="PARTIAL_CATALOGUE_BOUND_SOCKET_ENVELOPE":
        raise RuntimeError("Saved PARTIAL/QTO labels do not verify.")
    gap=measure_routing_connection_gap(sw,first,"CPoint2",second,"CPoint1")
    verify_gap(gap)
    require_clean_document(doc,"assembly after read")
    require_clean_document(part,"referenced part after read")
    report={"status":"SAVED_CLEAN_COORDINATION_EXAMPLE_VERIFIED", "assembly_path":str(assembly),
            "library_origin":str(Path(plan["catalog_path"]).parents[2]),
            "article_id":plan["article_id"], "geometry_status":plan["geometry_status"],
            "native_route_verified":False,"physical_joint_verified":False,"qto_include":False,
            "components":identities,"native_part_volume_mm3":volume,"native_part_box_m":box,
            "labels":labels,"gap_measurement":gap["data"]["measurement"],
            "source_original_unchanged":True,"source_original_sha256":original["source_sha256"],
            "source_catalog_unchanged":True,"source_catalog_sha256":plan["catalog_sha256"],
            "assembly_sha256":sha(assembly),"part_sha256":sha(identities[0]["path"]),
            "documents_clean_before_and_after":True,
            "reopened_by_this_verifier":False,
            "external_reopen_operation":args.external_reopen_operation,
            "external_reopen_evidence_verified_by_script":False,
            "assumptions":plan["assumptions"],
            "placement_note":"Two fixed instances in an exploded display, not a dimension-driven physical socket joint."}
    require_clean_document(doc,"assembly before report")
    require_clean_document(part,"referenced part before report")
    with target.open("x",encoding="utf-8") as stream:
        json.dump(report,stream,indent=2,allow_nan=False)
    print(json.dumps({"status":report["status"],"gap_mm":100.,"source_original_unchanged":True,
                      "geometry_status":report["geometry_status"],"report":str(target)}))


if __name__=="__main__":main()
