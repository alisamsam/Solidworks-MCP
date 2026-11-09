"""Read-only inspection of an open document's features, bodies and faces.

Activates a document by title, then prints:
  * every solid body with its bounding box and volume,
  * every planar face with the same global index list_planar_faces reports,
  * the whole feature tree, including features nested inside folders,
  * readable details of every weld-bead feature and cosmetic-weld folder.

Nothing is written or saved, and the previously active document is restored.
Useful for reading back a manual example the user built in the SolidWorks UI.

Run:
  $env:PYTHONPATH='.'; .venv\\Scripts\\python.exe scripts\\inspect_part_features.py Part200
"""

import sys

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com

BEAD_PROPS = (
    # IWeldmentBeadFeatureData (modeled fillet bead)
    "Thickness", "ThicknessType", "BeadSize", "BeadType", "BeadLength",
    "BeadPitch", "TangentPropagation", "UseOtherSide",
    # ICosmeticWeldBeadFeatureData
    "Side", "IntermittentWeld", "IntermittentWeldLength", "Gap", "Pitch",
    "GapOrPitch", "Staggered", "FromToLength", "FromToWeldLength",
    "FromToReverse", "WeldSymbol",
)

BEAD_METHODS = ("GetFacesCount", "GetVirtualEdgesCount", "GetFaces",
                "GetVirtualEdges", "GetReferenceEdges", "GetWeldBeadFolder")


def features(document):
    items = []
    feature = com(document, "FirstFeature")
    while feature is not None:
        items.append(feature)
        feature = com(feature, "GetNextFeature")
    return items


def all_features(document):
    """Every feature, descending into sub-features (folders hide theirs)."""
    items = []

    def walk(feature, next_getter):
        while feature is not None:
            items.append(feature)
            child = com(feature, "GetFirstSubFeature")
            if child is not None:
                walk(child, "GetNextSubFeature")
            feature = com(feature, next_getter)

    walk(com(document, "FirstFeature"), "GetNextFeature")
    return items


def folder_props(feature, label):
    print(f"  == folder {label} ({com(feature, 'GetTypeName2')}) ==")
    for getter in ("GetSpecificFeature2", "GetSpecificFeature"):
        try:
            specific = com(feature, getter)
        except Exception as exc:
            print(f"     {getter}() = <{exc}>")
            continue
        print(f"     {getter}() = {specific}")
        if specific is None:
            continue
        for prop in ("TotalLength", "TotalNumber", "TotalMass", "Material",
                     "NumberOfWeldPasses", "Process"):
            try:
                print(f"        {prop} = {com(specific, prop)}")
            except Exception as exc:
                print(f"        {prop} = <{exc}>")


def planar_faces(document):
    rows = []
    index = 0
    for body in com(document, "GetBodies2", 0, True) or []:
        for face in com(body, "GetFaces") or []:
            if com(com(face, "GetSurface"), "IsPlane"):
                normal = [round(float(v), 4) for v in com(face, "Normal")]
                rows.append((index, str(com(body, "Name")), normal,
                             round(float(com(face, "GetArea")) * 1e6, 2), face))
            index += 1
    return rows


def main():
    title = sys.argv[1] if len(sys.argv) > 1 else "Part200"
    automation = SolidWorksAutomation()
    if not automation.connect()["success"]:
        print("connect failed")
        return 1
    documents = com(automation.app, "GetDocuments")
    if not any(str(com(d, "GetTitle")) == title for d in documents):
        print(f"open document not found: {title}")
        return 2
    previous = com(automation.app, "ActiveDoc")
    previous_title = str(com(previous, "GetTitle")) if previous else None
    result = com(automation.app, "ActivateDoc3", title, False, 1, 0)
    document = result[0] if isinstance(result, tuple) else result
    if document is None:
        print(f"could not activate {title}")
        return 3

    print(f"== {title} ==")
    for body in com(document, "GetBodies2", 0, True) or []:
        box = [round(float(v) * 1000, 2) for v in com(body, "GetBodyBox")]
        volume = float(com(body, "GetMassProperties", 0.0)[3]) * 1e9
        print(f"  body {com(body, 'Name')!r} box={box} vol={volume:.1f}")

    rows = planar_faces(document)
    print(f"  planar faces: {len(rows)}")
    for index, body, normal, area, _face in rows[:4]:
        print(f"    [{index}] {body} n={normal} area={area} ...")

    print("  feature tree:")
    for feature in all_features(document):
        print(f"    {com(feature, 'Name')!r:40} {com(feature, 'GetTypeName2')}")

    for feature in all_features(document):
        name = str(com(feature, "Name"))
        type_name = str(com(feature, "GetTypeName2"))
        folded = type_name.casefold()
        if type_name == "CosmeticWeldCutList":
            folder_props(feature, name)
            continue
        if "bead" not in folded:
            continue
        print(f"  -- {name!r} ({type_name}) --")
        try:
            definition = com(feature, "GetDefinition")
        except Exception as exc:
            print(f"     GetDefinition failed: {exc}")
            continue
        for prop in BEAD_PROPS:
            try:
                print(f"     {prop} = {com(definition, prop)}")
            except Exception as exc:
                print(f"     {prop} = <{exc}>")
        for method in BEAD_METHODS:
            try:
                value = com(definition, method)
            except Exception as exc:
                print(f"     {method}() = <{exc}>")
                continue
            if method in ("GetFaces", "GetVirtualEdges", "GetReferenceEdges"):
                items = list(value) if value else []
                print(f"     {method}() = {len(items)} item(s)")
                for item in items:
                    match = next((row for row in rows if row[4] is item), None)
                    if match:
                        print(f"        face index {match[0]} {match[1]} "
                              f"n={match[2]} area={match[3]}")
                    else:
                        print(f"        {item} (not a listed planar face)")
            else:
                print(f"     {method}() = {value}")

    if previous_title:
        com(automation.app, "ActivateDoc3", previous_title, False, 1, 0)
        print(f"(active document restored to {previous_title!r})")
    automation.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
