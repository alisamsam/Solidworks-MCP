"""Build size recipes for standard fasteners from the Toolbox SQLite database.

The Toolbox database (``swbrowser.sldedb``, an SQLite file next to the Toolbox
data) describes, for every standard part, which model dimensions are driven by
which data columns and what the standard values are. This script turns that
into ``standard_library/size_recipes.json`` so the MCP can materialise any of
those sizes without guessing a single number.

Usage:
    .venv\\Scripts\\python.exe scripts\\build_std_size_recipes.py

The database is opened from a private copy, so a running SolidWorks never sees
its file locked.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(r"C:\SOLIDWORKS Data\lang\english\swbrowser.sldedb")
DEFAULT_OUT = REPO / "solidworks_mcp" / "standard_library" / "size_recipes.json"
LIBRARY_INDEX = REPO / "solidworks_mcp" / "standard_library" / "index.json"

# (type table, master file name, family id, standard designation used in size
# names). Only coarse-thread, everyday fasteners are listed. The fine-pitch
# Toolbox variants share a master file and would collide on the same library
# row, so they are left out; grades that differ only in material are also out
# of scope (material belongs to the static-test phase).
WANTED = [
    # bolts and screws
    ("ISO_TYPE_BS", "Socket Head Cap Screw_ISO.SLDPRT", "iso4762", "ISO 4762"),
    ("ISO_TYPE_BS", "Socket Countersunk Head Screw_ISO.SLDPRT", "iso10642", "ISO 10642"),
    ("ISO_TYPE_BS", "Socket Button Head Screw_ISO.SLDPRT", "iso7380", "ISO 7380"),
    ("ISO_TYPE_BS", "Hex Screw GradeAB_ISO.SLDPRT", "iso4017", "ISO 4017"),
    ("ISO_TYPE_BS", "Hex Bolt GradeAB_ISO.SLDPRT", "iso4014", "ISO 4014"),
    ("ISO_TYPE_BS", "Socket Set Screw Flat Point_ISO.SLDPRT", "iso4026", "ISO 4026"),
    ("ISO_TYPE_BS", "Socket Set Screw Cone Point_ISO.SLDPRT", "iso4027", "ISO 4027"),
    ("ISO_TYPE_BS", "Socket Set Screw Dog Point_ISO.SLDPRT", "iso4028", "ISO 4028"),
    ("ISO_TYPE_BS", "Socket Set Screw Cup Point_ISO.SLDPRT", "iso4029", "ISO 4029"),
    ("DIN_TYPE_BS", "Socket Head Cap Screw_DIN.SLDPRT", "din912", "DIN 912"),
    ("DIN_TYPE_BS", "Socket Countersunk Head Screw_DIN.SLDPRT", "din7991", "DIN 7991"),
    ("DIN_TYPE_BS", "Socket Head Thin Cap Screw_DIN.SLDPRT", "din7984", "DIN 7984"),
    ("DIN_TYPE_BS", "Socket Thin Pilot Cap Screw_DIN.SLDPRT", "din6912", "DIN 6912"),
    ("DIN_TYPE_BS", "Socket Csink Head Cap Screw 10642_DIN.SLDPRT", "din10642", "DIN 10642"),
    ("DIN_TYPE_BS", "Hex Screw GradeC_DIN.SLDPRT", "din933", "DIN 933"),
    ("DIN_TYPE_BS", "Hex Bolt GradeB_DIN.SLDPRT", "din931", "DIN 931"),
    ("DIN_TYPE_BS", "Socket Set Screw Flat Point_DIN.SLDPRT", "din913", "DIN 913"),
    ("DIN_TYPE_BS", "Socket Set Screw Cone Point_DIN.SLDPRT", "din914", "DIN 914"),
    ("DIN_TYPE_BS", "Socket Set Screw Dog Point_DIN.SLDPRT", "din915", "DIN 915"),
    ("DIN_TYPE_BS", "Socket Set Screw Cup Point_DIN.SLDPRT", "din916", "DIN 916"),
    # nuts
    ("ISO_TYPE_NUTS", "Hex Nut Style 1 GradeAB_ISO.SLDPRT", "iso4032", "ISO 4032"),
    ("ISO_TYPE_NUTS", "Hex Nut Style 2 GradeAB_ISO.SLDPRT", "iso4033", "ISO 4033"),
    ("ISO_TYPE_NUTS", "Hex Thin Nut Chamfered GradeAB_ISO.SLDPRT", "iso4035", "ISO 4035"),
    ("ISO_TYPE_NUTS", "Hex Nut GradeC_ISO.SLDPRT", "iso4034", "ISO 4034"),
    ("ISO_TYPE_NUTS", "Hex Flange Nut GradeA_ISO.SLDPRT", "iso4161", "ISO 4161"),
    ("ISO_TYPE_NUTS", "Torque nut 01_ISO.SLDPRT", "iso7040", "ISO 7040"),
    ("ISO_TYPE_NUTS", "Torque nut 02_ISO.SLDPRT", "iso7041", "ISO 7041"),
    ("ISO_TYPE_NUTS", "Torque nut 03_ISO.SLDPRT", "iso7042", "ISO 7042"),
    ("DIN_TYPE_NUTS", "Hex Thin Nut GradeB_DIN.SLDPRT", "din936", "DIN 936"),    ("DIN_TYPE_NUTS", "Hex Flange Nut_DIN.SLDPRT", "din6923", "DIN 6923"),
    ("DIN_TYPE_NUTS", "Domed cap nut_DIN.SLDPRT", "din1587", "DIN 1587"),
    ("DIN_TYPE_NUTS", "prevailing torque nut style 1-2_DIN.SLDPRT", "din985", "DIN 985"),
    ("DIN_TYPE_NUTS", "prevailing torque nut style 2_DIN.SLDPRT", "din982", "DIN 982"),
    ("DIN_TYPE_NUTS", "Square Nut Grade C_DIN.SLDPRT", "din557", "DIN 557"),
    ("DIN_TYPE_NUTS", "Hex Nut GradeC_DIN.SLDPRT", "din934c", "DIN 934-4.8"),
    # washers
    ("ISO_TYPE_WASHERS", "Plain Washer Normal Grade A_ISO.sldprt", "iso7089", "ISO 7089"),
    ("ISO_TYPE_WASHERS", "Plain Washer Chamfered Grade A_ISO.sldprt", "iso7090", "ISO 7090"),
    ("ISO_TYPE_WASHERS", "Plain Washer Large Grade AC_ISO.sldprt", "iso7093", "ISO 7093"),
    ("ISO_TYPE_WASHERS", "Plain Washer Normal Grade C_ISO.sldprt", "iso7091", "ISO 7091"),
    ("ISO_TYPE_WASHERS", "Plain Washer Small Grade A_ISO.sldprt", "iso7092", "ISO 7092"),
    ("DIN_TYPE_WASHERS", "Plain Washer Grade C_DIN.sldprt", "din125c", "DIN 125C"),
    ("DIN_TYPE_WASHERS", "Plain Washer Large_DIN.sldprt", "din9021", "DIN 9021"),
    ("DIN_TYPE_WASHERS", "Plain Washer Small Grade A_DIN.sldprt", "din433", "DIN 433"),
    ("DIN_TYPE_WASHERS", "Plain Washer 7349 Heavy_DIN.sldprt", "din7349", "DIN 7349"),
    ("DIN_TYPE_WASHERS", "Spring Lock Washer 2_DIN.sldprt", "din127", "DIN 127"),
    ("DIN_TYPE_WASHERS", "Curved Spring Lock Washer 2_DIN.sldprt", "din137", "DIN 137"),
    ("DIN_TYPE_WASHERS", "Toothed Lock Washer 1_DIN.SLDPRT", "din6797", "DIN 6797"),
    ("DIN_TYPE_WASHERS", "Serrated Lock Washer 1_DIN.SLDPRT", "din6798", "DIN 6798"),
]

PLACEHOLDER = re.compile(r"\{\[(\w+)\]\}")
SQRT2 = 1.4142135623730951
SQRT3 = 1.7320508075688772
SQUARE_NUTS = {"din557"}


def clean_table(name: str) -> str:
    return str(name or "").lstrip("+")


def as_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def get_ci(row, key):
    """Toolbox column names are upper case in some tables and lower in others."""
    if key in row:
        return row[key]
    wanted = str(key).casefold()
    for name, value in row.items():
        if str(name).casefold() == wanted:
            return value
    return None


def read_table(db, name):
    cur = db.cursor()
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info([{name}])")]
    rows = [dict(zip(cols, r)) for r in cur.execute(f"select * from [{name}]")]
    return cols, rows


def type_rows(db, table):
    return read_table(db, table)[1]


def find_row(db, type_table, filename):
    for row in type_rows(db, type_table):
        if str(row.get("Filename", "")).replace("/", "\\").split("\\")[-1].casefold() == filename.casefold():
            return row
    return None


def reference_prefix(template, size_label):
    """The literal part of the Toolbox configuration-name template.

    ``{DIN 912 [size_desig] x <Grid10> --- <Grid30><Grid33>}`` -> ``DIN 912``:
    everything before the first placeholder is the standard designation.
    """
    text = str(template or "").strip().strip("{}")
    cut = [i for i in (text.find("["), text.find("<")) if i >= 0]
    if cut:
        text = text[:min(cut)]
    return re.sub(r"\s+", " ", text).strip(" -")


def build_family(db, type_table, filename, family_id, prefix):
    row = find_row(db, type_table, filename)
    if row is None:
        return None, f"not listed in {type_table}"
    std_prefix = row_standard(type_table) + "_"
    cfg_name = std_prefix + clean_table(row["ConfigurationTable"])
    data_name = std_prefix + clean_table(row["DataTable"])
    index_name = filename.casefold()

    _, cfg_rows = read_table(db, cfg_name)
    data_cols, data_rows = read_table(db, data_name)

    grid = {int(r["Grid_Item_Number"]): r for r in cfg_rows}
    template = ""
    for key in sorted(grid):
        name = str(grid[key].get("Grid_Item_Name") or "")
        if name == "Configuration Name":
            template = str(grid[key].get("ValueList") or "")
    size_item = next((r for r in cfg_rows if int(r["Grid_Item_Number"]) == 1), None)
    if size_item is None:
        return None, "no size controller"
    size_col = PLACEHOLDER.fullmatch(str(size_item.get("ValueList") or "").strip())
    size_col = size_col.group(1) if size_col else "SIZE"

    length_item = None
    for r in cfg_rows:
        if str(r.get("Grid_Item_Type")) == "NUMERIC_COMBO" and "LENGTH" in str(r.get("AltDataSource", "")).upper():
            length_item = r
            break

    # Drivers: a grid row is a driver when its value comes from a placeholder
    # in a data column. Constant rows are left to the master's own default.
    drivers = []
    for r in sorted(cfg_rows, key=lambda x: int(x["Grid_Item_Number"])):
        dim = str(r.get("Dimension") or "")
        if not dim or dim == "SUPPRESSION":
            continue
        match = PLACEHOLDER.fullmatch(str(r.get("ValueList") or "").strip())
        if not match:
            continue
        column = match.group(1)
        alt = str(r.get("AltDataSource") or "").lstrip("+")
        if alt.upper().endswith("_LENGTHS"):
            source = "lengths"
        elif "THRD" in alt.upper():
            source = "thread"
        else:
            source = "data"
        source_table = std_prefix + alt if alt else data_name
        if source == "data" and source_table.casefold() != data_name.casefold():
            raise ValueError(f"{family_id}: unsupported alternate data table {source_table}")
        if source == "thread" and source_table.casefold() != (std_prefix + "DATA_THRD").casefold():
            raise ValueError(f"{family_id}: unsupported thread table {source_table}")
        drivers.append({"dim": dim, "col": column, "src": source,
                        "source_table": source_table,
                        "unit": dim_unit(dim, column),
                        "len_dim": bool(length_item is not None
                                        and int(r["Grid_Item_Number"]) == int(length_item["Grid_Item_Number"]))})

    _, thrd_rows = read_table(db, std_prefix + "DATA_THRD")
    thrd = {}
    for t in thrd_rows:
        dia, tpu = as_float(t.get("THD_DIA")), as_float(t.get("TPU"))
        if dia is not None and tpu is not None:
            thrd.setdefault((dia, tpu), []).append(t)

    def thread_for(dia, pitch):
        dia, pitch = as_float(dia), as_float(pitch)
        if dia is None or pitch is None:
            return {}
        matches = thrd.get((dia, pitch), [])
        if not matches:
            return {}
        columns = {d["col"] for d in drivers if d["src"] == "thread"}
        expected = {c: as_float(get_ci(matches[0], c)) for c in columns}
        if any({c: as_float(get_ci(t, c)) for c in columns} != expected for t in matches[1:]):
            raise ValueError(f"{family_id}: conflicting thread rows for {dia} x {pitch}")
        return matches[0]

    def values_for(data_row, base):
        out = {}
        for driver in drivers:
            if driver["src"] == "data":
                raw = get_ci(data_row, driver["col"])
            elif driver["src"] == "thread":
                raw = get_ci(base.get("thread", {}), driver["col"])
            else:
                raw = None
            value = as_float(raw)
            if driver["src"] != "lengths":
                if value is None:
                    raise ValueError(f"{family_id}: missing {driver['src']}.{driver['col']}")
                out[driver["dim"]] = value
        return out

    family = {
        "id": family_id, "standard": row_standard(type_table),
        "master": filename, "index_file": index_name,
        "configuration_table": cfg_name, "data_table": data_name,
        "rel_suffix": None, "kind": "size", "prefix": "",
        "drivers": [d for d in drivers if d["src"] != "lengths"],
        "sizes": [], "diameters": [],
    }
    family["prefix"] = prefix
    if not family["prefix"]:
        family["prefix"] = family_id.upper()

    if length_item is None:
        for data_row in data_rows:
            label = str(get_ci(data_row, size_col) or "").strip()
            if not label:
                continue
            base = {"thread": thread_for(get_ci(data_row, "DIAMETER") or get_ci(data_row, "SIZE"),
                                         get_ci(data_row, "PITCH"))}
            values = values_for(data_row, base)
            values.setdefault("_size_desig", label)
            family["sizes"].append({"label": f"{family['prefix']} {label}", "size_desig": label,
                                    "values": values})
        family["kind"] = "size"
    else:
        family["kind"] = "screw"
        lengths_table = std_prefix + clean_table(length_item["AltDataSource"])
        for driver in drivers:
            if driver["src"] == "lengths" and driver["source_table"].casefold() != lengths_table.casefold():
                raise ValueError(f"{family_id}: unsupported length source {driver['source_table']}")
        _, length_rows = read_table(db, lengths_table)
        by_size = {}
        for lr in length_rows:
            by_size.setdefault(str(lr["SIZE"]).strip(), []).append(lr)
        for data_row in data_rows:
            size = str(get_ci(data_row, "SIZE") or "").strip()
            label = str(get_ci(data_row, size_col) or size).strip()
            base = {"thread": thread_for(get_ci(data_row, "DIAMETER") or size,
                                         get_ci(data_row, "PITCH"))}
            values = values_for(data_row, base)
            lengths = []
            for lr in by_size.get(size, []):
                length = as_float(lr.get("LENGTH"))
                if length is None:
                    continue
                length_values = {}
                for driver in drivers:
                    if driver["src"] == "lengths":
                        value = as_float(get_ci(lr, driver["col"]))
                        if value is None:
                            raise ValueError(
                                f"{family_id}/{size}/{length}: missing {driver['col']}")
                        length_values[driver["dim"]] = value
                lengths.append({"length": length,
                                "thread": as_float(get_ci(lr, "THREAD_LENGTH")),
                                "values": length_values})
            family["diameters"].append({"size": size, "size_desig": label,
                                        "values": values, "lengths": lengths})
        family["length_dims"] = [{"dim": d["dim"], "col": d["col"], "unit": d["unit"]}
                                 for d in drivers if d["src"] == "lengths"]

    family["units"] = {d["dim"]: d["unit"]
                       for d in list(family["drivers"]) + list(family.get("length_dims") or [])
                       if d.get("unit", "mm") != "mm"}
    family["box"] = box_spec(family)
    return family, None


def row_standard(type_table):
    return "ISO" if type_table.startswith("ISO") else "DIN"


def dim_unit(dim, col):
    """Native unit of a Toolbox grid value: lengths are mm, angles degrees and
    tooth counts are plain numbers (Toolbox stores them that way)."""
    name = str(dim).lower()
    column = str(col).lower()
    # Flange contains 'ang', but flange diameters and radii are lengths.
    tokens = re.split(r"[^a-z]+", name.split("@", 1)[0])
    if "ang" in tokens or "angle" in tokens:
        return "deg"
    if "teeth" in name or column.startswith(("number", "num", "count")):
        return "count"
    return "mm"


def box_spec(family):
    """Expected body box as (overall size, across range).

    A hexagon or square body meets the axes at an angle that depends on the
    model, so its two cross extents can be anything between the across-flats
    and the across-corners distance. The cross part is therefore a range; the
    overall size (length, height or thickness) is exact, except for the point
    geometries of set screws, which Toolbox measures from the thread end.
    """
    dims = [d["dim"] for d in family["drivers"]] + [d["dim"] for d in family.get("length_dims", [])]
    countersunk = any(d.startswith("Head_ang@") for d in dims)
    teethed = any("Teeth" in d for d in dims)

    def find(*prefixes):
        return next((d for d in dims if any(d.startswith(p) for p in prefixes)), None)

    length = find("Length@")
    head_ht = find("Head_ht@")
    head_dia = find("Head_dia@")
    flats = find("Width_flats@")
    outside = find("Outside_dia@", "OutsideDia@")
    flange = find("Flange_dia@")
    thicknesses = [d for d in dims if d.startswith("Thickness")]
    overall = find("Overall_ht@")
    across = ["*", flats, 2 / SQRT3] if flats else None

    if length:
        box = {}
        if head_dia:
            cross = ([head_dia], [head_dia])
            # A countersunk head sits inside the stated length; every other
            # head adds its height to the overall extent.
            box["overall"] = [length] if countersunk else ["+", length, head_ht]
        elif flats:
            cross = ([flats], across)
            box["overall"] = [length] if countersunk else ["+", length, head_ht]
        else:
            diameter = find("Diameter@")
            cross = ([diameter], [diameter]) if diameter else (None, None)
            box["overall"] = [length]
            if diameter:
                # cone/cup/flat/dog points are modelled relative to the thread
                # end, so the axial extent may be shorter than the stated
                # length and a cup rim adds a little to the across size
                box["overall_tol"] = ["max", 0.25, ["*", diameter, 0.35]]
                box["cross_tol"] = ["max", 0.15, ["*", diameter, 0.05]]
        if cross[0] is None:
            return None
        if flange:
            cross = (["max", cross[0][0], flange], ["max", across, flange])
        box["cross_min"], box["cross_max"] = cross
        return box

    if outside and thicknesses:
        low = ["*", outside, 0.9] if teethed else [outside]
        return {"overall": [thicknesses[0]], "cross_min": low, "cross_max": [outside]}

    if flats:
        if len(thicknesses) > 1:
            height = ["max", thicknesses[0], thicknesses[1]]
        elif thicknesses:
            height = [thicknesses[0]]
        elif overall:
            height = [overall]
        else:
            return None
        if family["id"] in SQUARE_NUTS:
            across = ["*", flats, SQRT2]
        low, high = [flats], across
        if flange:
            low, high = ["max", low[0], flange], ["max", high[0] if len(high) == 1 else high, flange]
        box = {"overall": height, "cross_min": low, "cross_max": high}
        if any(d.startswith("MinWren") for d in dims):
            # A prevailing-torque nut's locking top can sit outside the
            # across-corners circle, so allow some slack there.
            box["cross_slack"] = 1.2
        return box
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--index", type=Path, default=LIBRARY_INDEX)
    parser.add_argument("--check", action="store_true",
                        help="print the plan and do not write the output")
    parser.add_argument("--dump", default="",
                        help="comma separated family ids: print their drivers")
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"Toolbox database not found: {args.db}", file=sys.stderr)
        return 1
    index = json.loads(args.index.read_text(encoding="utf-8")) if args.index.is_file() else []
    by_file: dict[str, dict] = {}
    for row in index:
        by_file.setdefault(row["file"].casefold(), row)

    work = Path(args.out).with_suffix(".work.sldedb")
    work.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.db, work)
    db = sqlite3.connect(str(work))

    families, problems = [], []
    for type_table, filename, family_id, prefix in WANTED:
        family, error = build_family(db, type_table, filename, family_id, prefix)
        if family is None:
            problems.append(f"{family_id}: {error}")
            continue
        row = by_file.get(filename.casefold())
        if row is None:
            problems.append(f"{family_id}: master not in index ({filename})")
            continue
        family["rel"] = row["rel"]
        family["standard"] = row["standard"]
        family["category"] = row["category"]
        family["type"] = row["type"]
        family["box"] = box_spec(family)
        if family["kind"] == "screw":
            counts = {}
            for d in family["diameters"]:
                if not d["lengths"]:
                    problems.append(f"{family_id}/{d['size']}: no lengths")
                for entry in d["lengths"]:
                    counts[(d["size_desig"], entry["length"])] = counts.get((d["size_desig"], entry["length"]), 0) + 1
            family["duplicated_lengths"] = sorted({k for k, v in counts.items() if v > 1})
            for d in family["diameters"]:
                for entry in d["lengths"]:
                    entry["label"] = (f"{family['prefix']} {d['size_desig']} x {trim(entry['length'])}"
                                      + (f" - {trim(entry['thread'])}"
                                         if (d["size_desig"], entry["length"]) in set(family["duplicated_lengths"])
                                         and entry["thread"] else ""))
        else:
            family["sizes"] = [s for s in family["sizes"] if s["values"]]
            if not family["sizes"]:
                problems.append(f"{family_id}: no usable sizes")
        families.append(family)

    db.close()
    total = 0
    for family in families:
        if family["kind"] == "screw":
            count = sum(len(d["lengths"]) for d in family["diameters"])
        else:
            count = len(family["sizes"])
        total += count
        box = family["box"] and family["box"]["overall"]
        print(f"{family['id']:14s} {family['standard']:4s} {family['kind']:7s} "
              f"driver={len(family['drivers']):2d} ldim={len(family.get('length_dims', [])):2d} "
              f"count={count:5d} prefix={family['prefix']!r:22s} box_a={box}")
        if args.dump and family["id"] in args.dump.split(","):
            for driver in family["drivers"] + family.get("length_dims", []):
                print(f"      {driver['src']:8s} {driver['col']:22s} {driver['dim']}")
            if family["kind"] == "size":
                print("      sample:", family["sizes"][0] if family["sizes"] else None)
    print(f"families={len(families)} sizes={total}")
    for problem in problems:
        print("  !", problem)

    if args.check:
        work.unlink(missing_ok=True)
        return 0

    payload = {"schema_version": 2, "source": "swbrowser.sldedb", "families": families}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=False), encoding="utf-8")
    size = args.out.stat().st_size / 1024
    print(f"wrote {args.out} ({size:.0f} KB)")
    work.unlink(missing_ok=True)
    return 0


def trim(value):
    number = as_float(value)
    if number is None:
        return str(value)
    return f"{number:g}"


if __name__ == "__main__":
    raise SystemExit(main())
