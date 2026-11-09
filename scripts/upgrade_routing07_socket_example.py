"""Extend a verified independent R01 copy into a catalogue-bound socket envelope.

This is a PARTIAL coordination representation. The catalogue gives limiting
diameters/lengths, not the seal-groove profile. It must never be promoted to an
exact manufacturer solid, a fabrication master, or a validated physical joint.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path


def require_routing_enabled():
    from solidworks_mcp.catalog import routing_enabled
    if not routing_enabled():
        raise RuntimeError("Routing is disabled; no CAD mutation is permitted.")


def verify_native_result(plan, inspection, body_box):
    if not inspection.get("success"):
        raise RuntimeError("Final native CPoint inspection failed.")
    data = inspection.get("data", {})
    points = data.get("connection_points", [])
    if data.get("coverage", {}).get("complete") is not True or data.get("count") != 2 or len(points) != 2:
        raise RuntimeError("Final native CPoint coverage/count is not exactly two complete points.")
    for point in points:
        for key in ("position_mm", "direction"):
            value=point.get(key)
            if not isinstance(value,(list,tuple)) or len(value)!=3:
                raise RuntimeError("Final native CPoint has an invalid XYZ vector.")
    points = sorted(points, key=lambda p:p["position_mm"][0])
    for point, x, direction in zip(points,(0.,plan["overall_length_mm"]),(-1.,1.)):
        if (not point.get("read_complete") or point.get("route_type_raw") != 2
            or not math.isclose(point["nominal_diameter_mm"],plan["nominal_od_mm"],abs_tol=1e-6)
            or not math.isclose(point["stub_length_mm"],0.,abs_tol=1e-6)
            or any(not math.isfinite(v) or not math.isclose(v,w,abs_tol=1e-5)
                   for v,w in zip(list(point["position_mm"])+list(point["direction"]),[x,0.,0.,direction,0.,0.]))):
            raise RuntimeError("Final native CPoint values do not match the intended endpoints.")
    r=plan["maximum_diameter_mm"]/2000
    expected=[0.,-r,-r,plan["overall_length_mm"]/1000,r,r]
    if len(body_box)!=6 or any(not math.isfinite(v) or not math.isclose(v,w,abs_tol=1e-5)
                              for v,w in zip(body_box,expected)):
        raise RuntimeError("Native body bounding box does not verify the catalogue envelope.")


def socket_plan(article):
    if article.get("family") != "PIPELIFE_KG_SN4_PIPE":
        raise ValueError("Only the reviewed KG SN4 pipe family is supported.")
    dims = article["dimensions"]
    def n(key):
        value = float(str(dims[key]).replace(",", "."))
        if not math.isfinite(value) or value <= 0: raise ValueError(f"Invalid dimension {key}.")
        return value
    od, s, maximum, bore, a, c = [n(k) for k in
        ("DN/OD", "s", "Dmax", "Dsm min.", "A min.", "C max.")]
    length = float(article["pipe_length_m"]) * 1000
    if not math.isfinite(length) or length <= 0 or od <= 2*s or bore <= od:
        raise ValueError("Invalid barrel/socket dimensions.")
    ro, ri, rb = od/2, od/2-s, bore/2
    rn = rb+s  # Explicit envelope assumption, not a printed socket wall thickness.
    rm = maximum/2
    transition = (rb-ri)/math.tan(math.radians(15))
    x = length-transition
    if x <= 0 or rm <= rn: raise ValueError("Degenerate socket envelope.")
    profile = [(0,ro),(x,ro),(length,rn),(length+a,rn),(length+a,rm),
               (length+a+c,rm),(length+a+c,rb),(length,rb),(x,ri),(0,ri)]
    frustum = lambda l,u,v: math.pi*l*(u*u+u*v+v*v)/3
    volume = (math.pi*(ro*ro-ri*ri)*x + frustum(transition,ro,rn)-frustum(transition,ri,rb)
              + math.pi*(rn*rn-rb*rb)*a + math.pi*(rm*rm-rb*rb)*c)
    return {"article_id": article["id"], "article_code": article["article_code"],
            "source_page": article["source_page"], "profile_mm": profile,
            "nominal_od_mm": od, "overall_length_mm": length+a+c,
            "maximum_diameter_mm": maximum, "expected_volume_mm3": volume,
            "geometry_status": "PARTIAL_CATALOGUE_BOUND_SOCKET_ENVELOPE",
            "native_wizard_verified": False, "physical_joint_verified": False,
            "qto_include": False,
            "assumptions": [
                "Dmax/Cmax and Dsm_min/Amin are limiting values, not measured exact production dimensions.",
                "Socket neck wall is idealised as barrel wall s; manufacturer socket wall is not tabulated.",
                "A and C are read as stacked axial intervals; L terminates at the socket taper's large end.",
                "15 degree transition is a straight idealisation; seal groove, seal ring and fillet radii are not modelled.",
                "The real structured pipe wall is homogenised. Volume/mass are not product takeoff values.",
                "CPoints denote geometric end planes only; insertion depth and physical joint are unverified.",
            ]}


def main():
    from solidworks_mcp.automation import SolidWorksAutomation
    from solidworks_mcp.comutil import com
    from solidworks_mcp.config import get_config
    from solidworks_mcp.core.policy import OperationClass
    from solidworks_mcp.tools.routing_create import list_routing_reference_edges, create_routing_connection_point
    from solidworks_mcp.tools.routing import list_routing_connection_points
    import pythoncom
    import win32com.client
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--article", default="PIPELIFE_KG_SN4_PIPE__3296104002")
    args = parser.parse_args()
    require_routing_enabled()
    policy = get_config().create_path_policy()
    if policy is None: raise RuntimeError("An explicit approved write policy is required.")
    part = policy.require_write(args.part.resolve(), OperationClass.MUTATE)
    manifest = json.loads((part.parent / ".solidworks-project-copy.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "verified" or not any(Path(f["copy"]).resolve()==part for f in manifest["files"]):
        raise ValueError("Requires the verified independent project-copy part.")
    catalogue = json.loads(args.catalog.read_text(encoding="utf-8"))
    article = next(a for a in catalogue["articles"] if a["id"] == args.article)
    report = socket_plan(article)
    report["part_path"] = str(part)
    report["catalog_path"] = str(args.catalog.resolve())
    report["catalog_sha256"] = hashlib.sha256(args.catalog.read_bytes()).hexdigest()
    sw = SolidWorksAutomation()
    sw.set_path_policy(policy)
    if not sw.connect()["success"]: raise RuntimeError("No SolidWorks connection.")
    doc = sw.app.ActiveDoc
    if Path(com(doc,"GetPathName")).resolve() != part: raise RuntimeError("Wrong active document.")
    sw.bind_active_document()
    feature = doc.FeatureByName("Boss-Extrude1")
    empty = win32com.client.VARIANT(pythoncom.VT_EMPTY, None)
    if feature is None or not feature.SetSuppression2(0,1,empty):
        raise RuntimeError("Could not suppress the preserved R01 barrel reference.")
    if com(doc,"GetBodies2",0,True): raise RuntimeError("R01 reference body remains active.")
    planes = []
    f = com(doc,"FirstFeature")
    while f is not None:
        if com(f,"GetTypeName2") == "RefPlane": planes.append(f)
        f = com(f,"GetNextFeature")
    sk = com(doc,"SketchManager")
    for plane in planes:
        doc.ClearSelection2(True)
        if not plane.Select2(False,0): continue
        sk.InsertSketch(True)
        active = com(doc,"GetActiveSketch2")
        tf = list(com(com(active,"ModelToSketchTransform"),"ArrayData"))
        if abs(tf[2]) < 1e-8: break  # This sketch plane contains model X.
        sk.InsertSketch(True)
    else: raise RuntimeError("No standard plane containing the existing global X axis.")
    ax = (tf[0],tf[1])
    radial = (-ax[1],ax[0])
    point = lambda x,r: ((x*ax[0]+r*radial[0])/1000,(x*ax[1]+r*radial[1])/1000,0.)
    sk.AddToDB = True
    retained = []
    polygon = report["profile_mm"]
    for start,end in zip(polygon,polygon[1:]+polygon[:1]):
        retained.append(sk.CreateLine(*point(*start),*point(*end)))
    retained.append(sk.CreateCenterLine(*point(0,0),*point(report["overall_length_mm"],0)))
    sk.AddToDB = False
    result = sw.revolve_sketch()
    if not result["success"]: raise RuntimeError(json.dumps(result))
    new_feature = doc.FeatureByName(result["data"]["feature_name"])
    new_feature.Name = "KG_SN4_socket_ENVELOPE_R03"
    bodies = list(com(doc,"GetBodies2",0,True) or [])
    volume = com(com(com(doc,"Extension"),"CreateMassProperty"),"Volume")*1e9
    if len(bodies)!=1 or not math.isclose(volume,report["expected_volume_mm3"],rel_tol=1e-6):
        raise RuntimeError(f"Native geometry verification failed: {len(bodies)} bodies, volume {volume}.")
    report["native_body_count"] = len(bodies)
    report["native_volume_mm3"] = volume
    report["body_box_m"] = list(com(bodies[0],"GetBodyBox"))
    for axial, outward in ((0.,-1.),(report["overall_length_mm"],1.)):
        refs = list_routing_reference_edges(sw)
        if not refs["success"]: raise RuntimeError(json.dumps(refs))
        matches = [e for e in refs["data"]["edges"] if abs(e["center_mm"][0]-axial)<1e-5
                   and abs(e["center_mm"][1])<1e-5 and abs(e["center_mm"][2])<1e-5]
        reference = min(matches,key=lambda e:e["radius_mm"])
        created = create_routing_connection_point(sw,reference["reference_index"],
                      report["nominal_od_mm"],0.,reference["axis"][0]*outward<0,"pipe")
        if not created["success"]: raise RuntimeError(json.dumps(created))
    report["native_connection_points"] = list_routing_connection_points(sw)
    verify_native_result(report, report["native_connection_points"], report["body_box_m"])
    report["status"] = "NATIVE_GEOMETRY_ENVELOPE_AND_CPOINTS_VERIFIED_NOT_SAVED"
    report_path = part.parent / "socket-envelope-verification.json"
    if report_path.exists(): raise FileExistsError(report_path)
    report_path.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__": main()
