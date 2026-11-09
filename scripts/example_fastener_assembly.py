#!/usr/bin/env python
"""Example: standard fastener assembly -- plate with 4 holes + 4 screw sets.

Builds a 100 x 60 x 10 mm plate with 4 x 11 mm holes, saves it, opens a new
assembly, inserts the plate, then inserts 4 complete fastener sets (one per
hole):

    screw  ISO 4762 M10 x 16 - 16N        -> insert_standard_part(size=...)
    washer DIN 125 A (plain washer grade a)-> insert_standard_part (master)
    nut    DIN 934  (hex nut style 1)      -> insert_standard_part (master)

Every set is mated concentrically (screw shank <-> plate hole, screw shank <->
washer bore, screw shank <-> nut bore). The screw size is a real materialised
Toolbox size: the part is JIT-prepared (writable copy, configuration switched
to "ISO 4762 M10 x 16 - 16N", rebuilt, saved) and inserted, so the geometry is
exactly the requested size (measured ~26 mm for M10 x 16).

Run:   .venv\\Scripts\\python.exe scripts\\example_fastener_assembly.py
The assembly is left open (unsaved) for review.

Requires SolidWorks running; mirrors tools/assembly + tools/standard_parts MCP
tools, with direct COM only where the MCP face-index API cannot distinguish
identical hole faces (hole attribution by axis position).
"""

import os
import sys

SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

import solidworks_mcp.automation  # noqa: E402,F401  (registers COM plumbing)
from solidworks_mcp.automation import SolidWorksAutomation  # noqa: E402
from solidworks_mcp.comutil import com  # noqa: E402
from solidworks_mcp.tools.assembly import (  # noqa: E402
    _component_faces,
    insert_component,
    list_components,
    mate_concentric,
)
from solidworks_mcp.tools.saving import save_document  # noqa: E402
from solidworks_mcp.tools.standard_parts import insert_standard_part  # noqa: E402

SCREW_SIZE = "ISO 4762 M10 x 16 - 16N"
HOLE_RADIUS_MM = 5.5     # 11 mm clearance hole for M10
SHANK_RADIUS_MM = 5.0    # M10 shank

# hole centers in the plate part (mm) -- one quadrant is enough, mirrored
HOLES_MM = [(30, 15), (30, -15), (-30, 15), (-30, -15)]


def plate_face_cylinders(comp):
    """(index, (ax, ay), radius_mm) for every cylindrical face of a component."""
    out = []
    for index, (face, kind) in enumerate(_component_faces(comp)):
        if kind != "cylindrical":
            continue
        params = com(com(face, "GetSurface"), "CylinderParams")  # p1, dir, radius
        out.append((index, (params[0], params[1]), params[6] * 1000.0))
    return out


def build_plate(automation, plate_path):
    """Plate 100x60x10 with 4 through holes, saved to plate_path."""
    def check(result, label):
        if not result.get("success"):
            raise RuntimeError(f"{label}: {result.get('message')}")
        return result

    check(automation.create_new_part(), "create_new_part")
    check(automation.create_sketch("Front", exact_geometry=True), "sketch front")
    check(automation.draw_rectangle(-50, -30, 50, 30, "mm"), "boss rectangle")
    check(automation.extrude_sketch(10, False, "mm"), "plate boss")

    check(automation.create_sketch_on_face(0, 0, 10, "mm"), "sketch on top face")
    for x, y in HOLES_MM:
        check(automation.draw_circle(x, y, HOLE_RADIUS_MM, "mm"), f"hole @ {x},{y}")
    check(automation.cut_extrude(through_all=True), "cut 4 holes")

    saved = check(save_document(automation, path=str(plate_path)), "save plate")
    return saved


def main():
    automation = SolidWorksAutomation()

    output_root = PathOf(automation)
    demo_dir = output_root / "fastener_demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    plate_path = demo_dir / "plate_100x60.SLDPRT"

    print("== 1/5 plate with 4 holes ==")
    build_plate(automation, plate_path)
    print("plate saved:", plate_path)

    print("== 2/5 new assembly + plate ==")
    created = automation.create_new_assembly()
    assert created["success"], created["message"]
    assembly_title = created["data"]["name"]
    plate = insert_component(automation, str(plate_path), 0.0, 0.0, 0.0)
    assert plate["success"], plate["message"]
    plate_name = plate["data"]["name"]
    print("  plate component:", plate_name)

    print("== 3/5 insert 4 screw sets (screw+washer+nut) at the holes ==")
    sets = []
    for i, (hx, hy) in enumerate(HOLES_MM):
        wx, wy = hx / 1000.0, hy / 1000.0  # meters
        screw = insert_standard_part(automation, standard="ISO",
                                     type="socket head cap",
                                     file="socket head cap screw_iso.sldprt",
                                     size=SCREW_SIZE, x=wx, y=wy, z=0.004)
        assert screw["success"], {"label": "screw", "result": screw}
        washer = insert_standard_part(automation, standard="DIN",
                                      type="plain washer grade a", x=wx, y=wy,
                                      z=0.006)
        assert washer["success"], {"label": "washer", "result": washer}
        nut = insert_standard_part(automation, standard="DIN",
                                   type="hex nut style 1 gradeab", x=wx, y=wy,
                                   z=-0.009)
        assert nut["success"], {"label": "nut", "result": nut}
        sets.append((screw, washer, nut))
        print(f"  hole {i} @ ({hx}, {hy}) mm: "
              f"{screw['data']['name']} + {washer['data']['name']} + "
              f"{nut['data']['name']}")

    print("== 4/5 concentric mates ==")
    plate_comp = find_component(automation, plate_name)
    plate_cyls = plate_face_cylinders(plate_comp)

    mate_count = 0
    for (screw, washer, nut), (hx, hy) in zip(sets, HOLES_MM):
        hx_m, hy_m = hx / 1000.0, hy / 1000.0

        screw_comp = find_component(automation, screw["data"]["name"])
        washer_comp = find_component(automation, washer["data"]["name"])
        nut_comp = find_component(automation, nut["data"]["name"])

        # Concentric mates instead use the screw's HEAD cylinder (largest
        # radius): its probe point sits above the plate, so SelectByID2 is
        # unambiguous even though the screw already lies on the hole axis
        # (api-findings 21.3). Head and shank share the same axis.
        hole_idx = nearest_axis(plate_cyls, hx_m, hy_m)
        washer_idx = smallest_radius(_component_faces(washer_comp))
        nut_idx = first_cylindrical(_component_faces(nut_comp))

        for label, idx2, comp2 in (("plate hole", hole_idx, plate_name),
                                   ("washer", washer_idx, washer["data"]["name"]),
                                   ("nut", nut_idx, nut["data"]["name"])):
            # components move as mates resolve; refresh the screw's head index
            screw_idx = largest_radius_index(
                find_component(automation, screw["data"]["name"]))
            m = mate_concentric(automation, screw["data"]["name"], screw_idx,
                                comp2, idx2)
            assert m["success"], {"label": label, "result": m}
            mate_count += 1
    print(f"  added {mate_count} concentric mates")

    print("== 5/5 verify ==")
    components = list_components(automation)
    assert components["success"], components["message"]
    comps = components["data"]["components"]
    print(f"  components: {len(comps)} (1 plate + 12 fasteners)")
    screws = [c for c in comps if "screw" in c["name"]]
    for c in comps:
        print("   -", c["name"])
    # prove the screw size materialised: measure one screw's body length
    screw_doc = com(find_component(automation, screws[0]["name"]), "GetModelDoc2")
    boxes = [list(com(b, "GetBodyBox")) for b in
             (com(screw_doc, "GetBodies2", 0, True) or [])]
    longest_mm = max((b[3] - b[0]) for b in boxes) * 1000.0
    print(f"  screw body length: {longest_mm:.1f} mm (expected ~26 for M10 x 16)")
    print()
    print(f"Demo assembly '{assembly_title}' left open for review (unsaved).")


def PathOf(automation):
    return automation._path_policy.output_roots[0]


def find_component(automation, name):
    from solidworks_mcp.tools.assembly import _find_component
    asm, err = automation.get_active_doc()
    assert err is None, err
    comp = _find_component(asm, name)
    assert comp is not None, f"component {name} not found"
    return comp


def shank_index(comp, radius_mm):
    """Index of the cylindrical face whose radius is closest to the shank."""
    best, best_d = None, 1e9
    for index, (face, kind) in enumerate(_component_faces(comp)):
        if kind != "cylindrical":
            continue
        r = com(com(face, "GetSurface"), "CylinderParams")[6] * 1000.0
        d = abs(r - radius_mm)
        if d < best_d:
            best, best_d = index, d
    return best


def smallest_radius(faces):
    best, best_r = None, 1e18
    for index, (face, kind) in enumerate(faces):
        if kind != "cylindrical":
            continue
        r = com(com(face, "GetSurface"), "CylinderParams")[6] * 1000.0
        if r < best_r:
            best, best_r = index, r
    return best


def first_cylindrical(faces):
    for index, (face, kind) in enumerate(faces):
        if kind == "cylindrical":
            return index
    return None


def nearest_axis(cyl_faces, x_m, y_m, tol_mm=3.0):
    best, best_d = None, 1e18
    for index, (ax, ay), radius in cyl_faces:
        d = (ax - x_m) ** 2 + (ay - y_m) ** 2
        if d < best_d:
            best, best_d = index, d
    return best


if __name__ == "__main__":
    main()