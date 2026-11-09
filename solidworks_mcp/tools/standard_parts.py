"""
Standard parts tools (part E, Toolbox milestone).

Design: the MCP **never reads the SOLIDWORKS Toolbox directly**; it reads its
own generated library (solidworks_mcp/standard_library/, overridable with the
SW_MCP_STANDARD_LIBRARY env var). The library is filled by
scripts/sync_standard_library.py (see docs/upgrade/STANDARD-LIBRARY-FLOW.md).

- index.json : catalog rows {standard, category, subcategory, type, file,
                               rel, source, path}
- sizes.json : {rel: [materialised configuration names, e.g. "ISO 4762 M10 x
                              16 - 16N"]}

The library directory must be explicitly approved as an output root for JIT
copies. Catalog synchronization remains a separate CLI operation.
"""

import hashlib
import json
import logging
import math
import os
import shutil
import uuid
from pathlib import Path

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass, WriteDeniedError
from ..registry import tool
from .assembly import insert_component

logger = logging.getLogger("SolidWorksMCP")

LIBRARY_ENV_VAR = "SW_MCP_STANDARD_LIBRARY"
DEFAULT_LIBRARY_DIR = Path(__file__).resolve().parent.parent / "standard_library"
INDEX_FILE = "index.json"
SIZES_FILE = "sizes.json"

# DIN 934 (1987), style 1, coarse thread; (major, pitch, s, m, tap drill), mm.
# Nominal s and m from:
# https://boltingspecialist.com/dimensions/din-934-hex-nuts/
# Coarse pitch and recommended tapping drill from:
# https://fullerfasteners.com/tech/recommended-tapping-drill-size/
# Tap drill is the modeled bore, NOT the nominal thread ID. Four driving
# dimension names were verified on a Toolbox copy (nut_true_drivers_probe.py).
# Each row must still pass live rebuild and saved-copy checks before publication.
DIN934_NUTS = {
    "DIN 934 M3": (3, 0.5, 5.5, 2.4, 2.5),
    "DIN 934 M3.5": (3.5, 0.6, 6, 2.8, 2.9),
    "DIN 934 M4": (4, 0.7, 7, 3.2, 3.3),
    "DIN 934 M5": (5, 0.8, 8, 4, 4.2),
    "DIN 934 M6": (6, 1, 10, 5, 5),
    "DIN 934 M7": (7, 1, 11, 5.5, 6),
    "DIN 934 M8": (8, 1.25, 13, 6.5, 6.75),
    "DIN 934 M10": (10, 1.5, 17, 8, 8.5),
    "DIN 934 M12": (12, 1.75, 19, 10, 10.2),
    "DIN 934 M14": (14, 2, 22, 11, 12),
    "DIN 934 M16": (16, 2, 24, 13, 14),
    "DIN 934 M18": (18, 2.5, 27, 15, 15.5),
    "DIN 934 M20": (20, 2.5, 30, 16, 17.5),
    "DIN 934 M22": (22, 2.5, 32, 18, 19.5),
    "DIN 934 M24": (24, 3, 36, 19, 21),
    "DIN 934 M27": (27, 3, 41, 22, 24),
    "DIN 934 M30": (30, 3.5, 46, 24, 26.5),
}
DIN934_MASTER = "hex nut style 1 gradeab_din.sldprt"

# DIN 125 A / ISO 7089 normal series: (bore, OD, thickness), nominal mm.
# Source table identifies DIN 125 A as equivalent and gives d1 min, d2 max,
# and nominal midpoint of the h tolerance band:
# https://www.fasteners.eu/standards/iso/7089/
DIN125A_WASHERS = {
    "DIN 125A M3": (3.2, 7, 0.5),
    "DIN 125A M3.5": (3.7, 8, 0.5),
    "DIN 125A M4": (4.3, 9, 0.8),
    "DIN 125A M5": (5.3, 10, 1),
    "DIN 125A M6": (6.4, 12, 1.6),
    "DIN 125A M7": (7.4, 14, 1.6),
    "DIN 125A M8": (8.4, 16, 1.6),
    "DIN 125A M10": (10.5, 20, 2),
    "DIN 125A M12": (13, 24, 2.5),
    "DIN 125A M14": (15, 28, 2.5),
    "DIN 125A M16": (17, 30, 3),
    "DIN 125A M18": (19, 34, 3),
    "DIN 125A M20": (21, 37, 3),
    "DIN 125A M22": (23, 39, 3),
    "DIN 125A M24": (25, 44, 4),
    "DIN 125A M27": (28, 50, 4),
    "DIN 125A M30": (31, 56, 4),
}
DIN125A_MASTER = "plain washer grade a_din.sldprt"

SYNC_HINT = (
    "Run: .venv\\Scripts\\python.exe scripts\\sync_standard_library.py "
    "--out solidworks_mcp\\standard_library"
)


def library_dir() -> Path:
    override = os.environ.get(LIBRARY_ENV_VAR)
    return Path(override) if override else DEFAULT_LIBRARY_DIR


def _load_json(path: Path):
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as error:
        logger.warning("could not read %s: %s", path, error)
        return None


def _matches(rows, standard=None, type_=None, file_=None):
    std = standard.strip().casefold() if standard else ""
    typ = type_.strip().casefold() if type_ else ""
    fil = file_.strip().casefold() if file_ else ""
    for row in rows:
        if std and not (row["standard"].casefold() == std
                        or row["standard_folder"].casefold() == std):
            continue
        if typ and typ not in row["type"].casefold():
            continue
        if fil and row["file"].casefold() != fil:
            continue
        yield row


def _is_fastener(row: dict) -> bool:
    category = str(row.get("category") or "").casefold()
    return category in {"bolts and screws", "nuts", "washers"}


def _select_row(sw, rows, standard, type_, file_):
    matched = list(_matches(rows, standard, type_, file_))
    if not matched:
        return None, sw._result(
            False,
            f"Standard part not found (standard={standard!r}, type={type_!r}, "
            f"file={file_!r}).",
            SwErrors.swInvalidInput, {"code": "STANDARD_PART_NOT_FOUND"})
    # the same logical part is usually present twice: once from browser, once
    # from the custom Toolbox tree; browser rows come first, so keep the first
    # occurrence of each (file, standard) pair
    unique: list = []
    seen: set = set()
    for row in matched:
        key = (row["file"].casefold(), row["standard"].casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    matched = unique
    if len(matched) > 1 and not file_:
        candidates = [{"standard": r["standard"], "type": r["type"],
                       "rel": r["rel"]} for r in matched[:20]]
        return None, sw._result(
            False,
            f"{len(matched)} parts match; pass file= to disambiguate.",
            SwErrors.swInvalidInput,
            {"code": "AMBIGUOUS_STANDARD_PART", "candidates": candidates})
    return matched[0], None


def _source_copy(lib: Path, row: dict) -> Path:
    """Portable copy of a sized part, if it was copied with --copy-sized."""
    rel = row["rel"]
    if row.get("source") == "custom" and "/" in rel:
        rel = rel.split("/", 1)[1]
    return lib / "source" / row["standard"] / rel


def _master_file(lib: Path, row: dict) -> str:
    """Master file for a row: the portable source copy when present, else the
    original Toolbox path recorded at sync time."""
    copy = _source_copy(lib, row)
    if copy.is_file():
        return str(copy)
    return row.get("path") or ""


def _sized_cache_path(lib: Path, row: dict, size: str) -> Path:
    """Prepared-copy path for one (part, size) under lib/sized/ (gitignored)."""
    rel = row["rel"]
    if row.get("source") == "custom" and "/" in rel:
        rel = rel.split("/", 1)[1]
    safe_size = "".join(c if c not in '<>:"/\\|?*' else "_" for c in size)
    digest = hashlib.md5(f"{row['rel']}|{size}".encode("utf-8", "surrogatepass")).hexdigest()[:10]
    stem = Path(rel).stem
    return lib / "sized" / row["standard"] / f"{stem}__{digest}__{safe_size}.sldprt"


def _din934_nut(row: dict) -> bool:
    return (row.get("standard") == "DIN" and row.get("category") == "nuts"
            and row.get("file", "").casefold() == DIN934_MASTER
            and row.get("rel", "").replace("\\", "/").casefold().endswith(
                "nuts/hex nuts/" + DIN934_MASTER))


def _din125a_washer(row: dict) -> bool:
    return (row.get("standard") == "DIN" and row.get("category") == "washers"
            and row.get("file", "").casefold() == DIN125A_MASTER
            and row.get("rel", "").replace("\\", "/").casefold().endswith(
                "washers/plain washers/" + DIN125A_MASTER))


def _features_clear(doc):
    feature = com(doc, "FirstFeature")
    while feature is not None:
        if com(feature, "GetErrorCode") != 0:
            return False
        feature = com(feature, "GetNextFeature")
    return True


def _nut_geometry(doc, dimensions):
    """Check actual solid, not equation-driven sketch dimensions or cosmetics."""
    major, _pitch, flats, thickness, bore = dimensions
    bodies = com(doc, "GetBodies2", 0, False) or ()
    if len(bodies) != 1:
        return False
    body = bodies[0]
    box = com(body, "GetBodyBox")
    if not box or len(box) != 6:
        return False
    close = lambda actual, expected: math.isclose(actual, expected / 1000, abs_tol=0.00005)
    if not (close(box[3] - box[0], flats)
            and close(box[4] - box[1], 2 * flats / math.sqrt(3))
            and close(box[5] - box[2], thickness)):
        return False
    bore_found = False
    for face in com(body, "GetFaces") or ():
        surface = com(face, "GetSurface")
        if com(surface, "IsCylinder"):
            cylinder = com(surface, "CylinderParams")
            # This model also has a cosmetic thread cylinder beyond the body.
            if (cylinder and len(cylinder) >= 7 and
                    close(2 * cylinder[6], bore) and
                    abs(cylinder[0]) < 0.00005 and abs(cylinder[1]) < 0.00005 and
                    abs(cylinder[2] - box[2]) < 0.00005):
                bore_found = True
    return bore_found


def _nut_valid(doc, size, dimensions):
    active = com(com(com(doc, "ConfigurationManager"), "ActiveConfiguration"), "Name")
    if active != size:
        return False
    for key, mm in zip(("Thread_major@ThreadCosmetic", "Width_flats@BaseNutSke",
                        "Thickness@BaseNut", "Tap_drill@BaseNutSke"),
                       (dimensions[0], dimensions[2], dimensions[3], dimensions[4])):
        dim = com(doc, "Parameter", key)
        if dim is None or not math.isclose(com(dim, "SystemValue"), mm / 1000, abs_tol=0.000001):
            return False
    return _features_clear(doc) and _nut_geometry(doc, dimensions)


def _washer_valid(doc, size, dimensions):
    bore, outer, thickness = dimensions
    active = com(com(com(doc, "ConfigurationManager"), "ActiveConfiguration"), "Name")
    if active != size:
        return False
    for key, mm in (("Inside_dia@Sketch1", bore), ("Outside_dia@Sketch1", outer),
                    ("Thickness@Sketch1", thickness)):
        dim = com(doc, "Parameter", key)
        if dim is None or not math.isclose(com(dim, "SystemValue"), mm / 1000, abs_tol=0.000001):
            return False
    bodies = com(doc, "GetBodies2", 0, False) or ()
    if len(bodies) != 1 or not _features_clear(doc):
        return False
    body = bodies[0]
    box = com(body, "GetBodyBox")
    if not box or len(box) != 6:
        return False
    close = lambda actual, expected: math.isclose(actual, expected / 1000, abs_tol=0.00005)
    if not (close(box[3] - box[0], thickness)
            and close(box[4] - box[1], outer)
            and close(box[5] - box[2], outer)):
        return False
    for face in com(body, "GetFaces") or ():
        surface = com(face, "GetSurface")
        if com(surface, "IsCylinder"):
            cylinder = com(surface, "CylinderParams")
            if (cylinder and len(cylinder) >= 7
                    and close(2 * cylinder[6], bore)
                    and abs(abs(cylinder[3]) - 1) < 0.00001
                    and abs(cylinder[4]) < 0.00001
                    and abs(cylinder[5]) < 0.00001):
                return True
    return False


def _prepare_verified_copy(sw, lib: Path, row: dict, size: str, drivers, valid,
                           base_configuration: str | None = None,
                           mid_rebuild_at: int = 0):
    """Publish one prepared copy only after rebuild, save and reopen checks."""
    policy = getattr(sw, "_path_policy", None)
    target = _sized_cache_path(lib, row, size)
    if policy is None:
        return None
    try:
        policy.require_write(target, OperationClass.MUTATE)
    except WriteDeniedError:
        return None
    master = _master_file(lib, row)
    if not master or not os.path.isfile(master) or sw.app is None:
        return None
    app = sw.app
    if hasattr(app, "_oleobj_"):
        import win32com.client
        app = win32com.client.dynamic.Dispatch(app)
    import pythoncom
    import win32com.client as wc
    def open_copy(path):
        errors = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        doc = com(app, "OpenDoc6", str(path), 1, 1, "", errors, warnings)
        if doc is not None:
            actual = str(com(doc, "GetPathName"))
            if os.path.normcase(os.path.abspath(actual)) != os.path.normcase(os.path.abspath(path)):
                raise RuntimeError("OpenDoc6 returned a different document; refusing to modify it")
            if errors.value:
                close_copy(doc)
                doc = None
        return doc, errors, warnings
    def close_copy(doc):
        if doc is not None:
            com(app, "CloseDoc", com(doc, "GetTitle"))
    def receipt_path():
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        spec = hashlib.sha256(json.dumps([size, dict(drivers)], sort_keys=True).encode()).hexdigest()
        return target.with_name(target.stem + ".verified-" + digest[:16] + "-" + spec[:16] + ".json")
    doc = None
    allow_overwrite = False
    stale_hash = None
    try:
        if target.is_file():
            # Do not close an assembly's already-open instance of this part.
            if hasattr(app, "GetOpenDocumentByName") and com(app, "GetOpenDocumentByName", str(target)) is not None:
                return None
            doc, _, _ = open_copy(target)
            if doc is None:
                return None
            receipt = receipt_path()
            evidence = _load_json(receipt) or {}
            keep = (evidence.get("sha256") == hashlib.sha256(target.read_bytes()).hexdigest()
                    and evidence.get("size") == size
                    and com(doc, "EditRebuild3") and valid(doc))
            close_copy(doc)
            doc = None
            if keep:
                return str(target)
            # A cached copy that no longer matches its recipe is rebuilt rather
            # than trusted; only this library's own generated file is replaced.
            logger.info("rebuilding stale sized copy: %s", target.name)
            allow_overwrite = True
            stale_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        staging = target.with_name(target.stem + ".pending-" + uuid.uuid4().hex + ".sldprt")
        policy.require_write(staging, OperationClass.MUTATE)
        staging.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(master, staging)
        os.chmod(staging, 0o666)
        doc, errors, warnings = open_copy(staging)
        if doc is None:
            return None
        manager = com(doc, "ConfigurationManager")
        if base_configuration:
            if com(doc, "GetConfigurationByName", base_configuration) is None:
                return None
            com(doc, "ShowConfiguration2", base_configuration)
            if com(com(manager, "ActiveConfiguration"), "Name") != base_configuration:
                return None
        if com(doc, "GetConfigurationByName", size) is None:
            if com(manager, "AddConfiguration", size, "", "", 0, "", "") is None:
                return None
        com(doc, "ShowConfiguration2", size)  # may return False even when activated
        active = com(com(manager, "ActiveConfiguration"), "Name")
        if active != size:
            return None
        null = wc.VARIANT(pythoncom.VT_EMPTY, None)
        for index, (key, value) in enumerate(drivers):
            # drivers carry SolidWorks system values (metres, radians, counts)
            dim = com(doc, "Parameter", key)
            if dim is None:
                return None
            com(dim, "SetSystemValue3", value, 1, null)
            if not math.isclose(com(dim, "SystemValue"), value, abs_tol=0.000001):
                return None
            if mid_rebuild_at and (index + 1) % mid_rebuild_at == 0:
                # Some parts re-solve a sketch on every set; a rebuild after the
                # shape dimensions keeps the next ones valid.
                com(doc, "EditRebuild3")
        com(com(doc, "GetEquationMgr"), "EvaluateAll")
        if not com(doc, "EditRebuild3") or not com(doc, "ForceRebuild3", False):
            return None
        if not com(doc, "EditRebuild3") or not valid(doc):
            return None
        errors.value = 0
        if not com(doc, "Save3", 0, errors, warnings) or errors.value:
            return None
        close_copy(doc)
        doc = None
        doc, _, _ = open_copy(staging)
        if doc is None or not com(doc, "EditRebuild3") or not valid(doc):
            return None
        close_copy(doc)
        doc = None
        # Preserve rejected caches. Never replace a file another writer changed.
        if target.exists():
            if not allow_overwrite or hashlib.sha256(target.read_bytes()).hexdigest() != stale_hash:
                return None
            if hasattr(app, "GetOpenDocumentByName") and com(app, "GetOpenDocumentByName", str(target)) is not None:
                return None
            archive = target.with_name(target.stem + ".unverified-" + uuid.uuid4().hex + ".sldprt")
            policy.require_write(archive, OperationClass.MUTATE)
            os.rename(target, archive)
        os.rename(staging, target)
        # Renaming can change SolidWorks' reference resolution. Validate the
        # actual published path, not just a staging file with a different name.
        final_ok = False
        closed_ok = False
        try:
            doc, _, _ = open_copy(target)
            final_ok = doc is not None and com(doc, "EditRebuild3") and valid(doc)
        finally:
            try:
                close_copy(doc)
                closed_ok = True
            finally:
                doc = None
                if not final_ok or not closed_ok:
                    rejected = target.with_name(target.stem + ".pending-" + uuid.uuid4().hex + ".sldprt")
                    policy.require_write(rejected, OperationClass.MUTATE)
                    os.rename(target, rejected)
        if not final_ok or not closed_ok:
            return None
        receipt = receipt_path()
        policy.require_write(receipt, OperationClass.MUTATE)
        if not receipt.exists():
            receipt.write_text(json.dumps({"size": size,
                                          "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                                          "drivers_system": dict(drivers)}), encoding="utf-8")
        return str(target)
    except Exception as error:
        logger.warning("standard part preparation failed for %s: %s", size, error)
        return None
    finally:
        if doc is not None:
            try:
                close_copy(doc)
            except Exception:
                pass


def _prepare_din934_nut(sw, lib: Path, row: dict, size: str):
    dimensions = DIN934_NUTS[size]
    return _prepare_verified_copy(sw, lib, row, size,
        (("Tap_drill@BaseNutSke", dimensions[4] / 1000),
         ("Thread_major@ThreadCosmetic", dimensions[0] / 1000),
         ("Width_flats@BaseNutSke", dimensions[2] / 1000),
         ("Thickness@BaseNut", dimensions[3] / 1000)),
        lambda doc: _nut_valid(doc, size, dimensions))


def _prepare_din125a_washer(sw, lib: Path, row: dict, size: str):
    dimensions = DIN125A_WASHERS[size]
    return _prepare_verified_copy(sw, lib, row, size,
        (("Inside_dia@Sketch1", dimensions[0] / 1000),
         ("Outside_dia@Sketch1", dimensions[1] / 1000),
         ("Thickness@Sketch1", dimensions[2] / 1000)),
        lambda doc: _washer_valid(doc, size, dimensions))


# ---------------------------------------------------------------------------
# Verified size recipes
#
# The Toolbox database (swbrowser.sldedb) names, for every standard part, the
# model dimensions the Toolbox drives and the data columns that feed them. The
# recipes file is that mapping, resolved to concrete sizes by
# scripts/build_std_size_recipes.py. Every prepared copy is still rebuilt,
# saved, reopened and measured before it is published.
# ---------------------------------------------------------------------------
RECIPES_FILE = "size_recipes.json"


def _recipe_families(lib: Path):
    data = _load_json(lib / RECIPES_FILE)
    if not isinstance(data, dict):
        return []
    if data.get("schema_version") != 2:
        return []  # old recipes omitted length-dependent drivers; regenerate
    families = data.get("families")
    return families if isinstance(families, list) else []


def _family_for_row(families, row: dict):
    key = (str(row.get("standard", "")).casefold(), str(row.get("file", "")).casefold())
    rel = str(row.get("rel", "")).replace("\\", "/").casefold()
    fallback = None
    for family in families:
        if (str(family.get("standard", "")).casefold(),
                str(family.get("master", "")).casefold()) != key:
            continue
        if str(family.get("rel", "")).replace("\\", "/").casefold() == rel:
            return family
        fallback = fallback or family
    return fallback


def _driver_values(values: dict) -> dict:
    return {name: mm for name, mm in values.items() if not name.startswith("_")}


def _eval_box(expr, values: dict) -> float:
    if isinstance(expr, (int, float)):
        return float(expr)
    if isinstance(expr, str):
        return float(values[expr])
    if len(expr) == 1:
        return _eval_box(expr[0], values)
    operator, args = expr[0], expr[1:]
    if operator == "+":
        return sum(_eval_box(arg, values) for arg in args)
    if operator == "*":
        result = 1.0
        for arg in args:
            result *= _eval_box(arg, values)
        return result
    if operator == "max":
        return max(_eval_box(arg, values) for arg in args)
    if operator == "min":
        return min(_eval_box(arg, values) for arg in args)
    raise ValueError(f"unknown box operator: {operator!r}")


def _family_size_entries(family: dict):
    """Yield (label, driver values) for every concrete size of one family."""
    length_dims = [item["dim"] for item in family.get("length_dims") or []]
    if family.get("kind") == "screw":
        for diameter in family.get("diameters") or []:
            for entry in diameter.get("lengths") or []:
                values = dict(diameter.get("values") or {})
                length_values = entry.get("values") or {}
                if any(name not in length_values for name in length_dims):
                    continue  # incomplete recipe is not an available size
                values.update(length_values)
                if not _complete_recipe_values(family, values):
                    continue
                yield entry["label"], values
    else:
        for size in family.get("sizes") or []:
            values = dict(size.get("values") or {})
            if _complete_recipe_values(family, values):
                yield size["label"], values


def _complete_recipe_values(family, values):
    required = {item["dim"] for item in family.get("drivers", []) + family.get("length_dims", [])}
    return bool(required) and all(name in values and isinstance(values[name], (int, float))
                                  and not isinstance(values[name], bool) and math.isfinite(values[name])
                                  for name in required)


def _recipe_size_count(families) -> int:
    total = 0
    for family in families:
        if family.get("kind") == "screw":
            total += sum(len(d.get("lengths") or []) for d in family.get("diameters") or [])
        else:
            total += len(family.get("sizes") or [])
    return total


def _dim_unit(units, name: str) -> str:
    return (units or {}).get(name, "mm")


def _system_value(unit: str, value: float) -> float:
    if unit == "deg":
        return math.radians(value)
    if unit == "count":
        if not math.isfinite(value) or value != int(value):
            raise ValueError("pattern counts must be finite integers")
        return float(value)
    if unit == "mm":
        return value / 1000.0
    raise ValueError(f"unsupported dimension unit: {unit!r}")


def _recipe_valid(doc, label: str, values: dict, box, units: dict | None = None) -> bool:
    """One prepared copy is trusted only when it is the right size, everywhere."""
    active = com(com(com(doc, "ConfigurationManager"), "ActiveConfiguration"), "Name")
    if active != label:
        return False
    drivers = _driver_values(values)
    for name, value in drivers.items():
        dim = com(doc, "Parameter", name)
        if dim is None or not math.isclose(com(dim, "SystemValue"),
                                           _system_value(_dim_unit(units, name), value),
                                           abs_tol=0.000001):
            return False
    if not _features_clear(doc):
        return False
    bodies = com(doc, "GetBodies2", 0, False) or ()
    if len(bodies) != 1:
        return False
    if not box:
        return False
    try:
        overall = _eval_box(box["overall"], drivers)
        cross_min = _eval_box(box["cross_min"], drivers)
        cross_max = _eval_box(box["cross_max"], drivers)
    except KeyError:
        return False  # missing geometry expectations must fail closed
    except (ValueError, TypeError):
        return False  # a malformed recipe must fail closed, not pass
    raw = com(bodies[0], "GetBodyBox")
    if not raw or len(raw) != 6:
        return False
    measured = sorted(((raw[3] - raw[0]) * 1000, (raw[4] - raw[1]) * 1000,
                       (raw[5] - raw[2]) * 1000))
    if "overall_tol" in box:
        try:
            allowance = _eval_box(box["overall_tol"], drivers)
        except KeyError:
            return False
    else:
        allowance = max(0.05, 0.01 * abs(overall))
    allowance = max(0.05, allowance)
    # The overall extent must match one of the three; with a generous
    # tolerance (point geometries) pick the closest, not the first.
    best = None
    for index, extent in enumerate(measured):
        delta = abs(extent - overall)
        if delta <= allowance and (best is None or delta < best[0]):
            best = (delta, index)
    if best is None:
        return False
    remaining = [extent for index, extent in enumerate(measured) if index != best[1]]
    if "cross_tol" in box:
        try:
            cross_tol = _eval_box(box["cross_tol"], drivers)
        except KeyError:
            return False
    else:
        cross_tol = None
    slack = float(box.get("cross_slack", 1.0))
    for extent in remaining:
        low = cross_min - (cross_tol if cross_tol is not None
                           else max(0.05, 0.01 * abs(cross_min)))
        high = cross_max * slack + (cross_tol if cross_tol is not None
                                    else max(0.05, 0.01 * abs(cross_max)))
        if not low <= extent <= high:
            return False
    return True


def _prepare_recipe(sw, lib: Path, row: dict, family: dict, label: str,
                    values: dict):
    """Prepare one size, retrying with a different driver order if needed.

    Some Toolbox parts re-solve their sketches on every dimension set, so the
    order the dimensions are written in can decide whether an intermediate
    state is valid (verified on the flange-nut masters). Geometry is still
    validated identically for every attempt; the order only changes how the
    part is driven there.
    """
    box = family.get("box")
    units = family.get("units")
    if not _complete_recipe_values(family, values):
        return None
    drivers = _driver_values(values)
    hole = lambda name: any(key in name.lower() for key in ("drill", "minor", "thread_min"))
    shape_first = ([name for name in drivers if not hole(name)]
                   + [name for name in drivers if hole(name)])
    plans = [(list(drivers), 0), (shape_first, 0), (list(drivers), 3)]
    seen = set()
    for order, mid in plans:
        key = (tuple(order), mid)
        if key in seen:
            continue
        seen.add(key)
        prepared = _prepare_verified_copy(
            sw, lib, row, label,
            tuple((name, _system_value(_dim_unit(units, name), drivers[name])) for name in order),
            lambda doc: _recipe_valid(doc, label, values, box, units),
            mid_rebuild_at=mid)
        if prepared:
            return prepared
    return None


def _prepare_sized_copy(sw, lib: Path, row: dict, size: str):
    """JIT: turn one Toolbox size into a real part file.

    Verified live (2026-09-23): AddComponent5 with a configuration *name* on a
    Toolbox part silently inserts the part's active configuration instead of
    the requested one. The working recipe is to prep a writable copy whose
    active configuration is the requested size -- ShowConfiguration2, rebuild,
    save -- then insert that copy. Returns the prepared path, or None.
    """
    target = _sized_cache_path(lib, row, size)
    policy = getattr(sw, "_path_policy", None)
    if policy is not None:
        try:
            policy.require_write(target, OperationClass.MUTATE)
        except WriteDeniedError as error:
            logger.warning("sized prep: write denied: %s", error)
            return None
    if os.path.isfile(target):
        return str(target)
    master = _master_file(lib, row)
    if not master or not os.path.isfile(master):
        logger.warning("sized prep: master missing for %s", row["rel"])
        return None

    app = getattr(sw, "app", None)
    if app is None:
        logger.warning("sized prep: no app connection")
        return None
    if hasattr(app, "_oleobj_"):
        import win32com.client
        app = win32com.client.dynamic.Dispatch(app)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(master, target)
        os.chmod(target, 0o666)
    except OSError as error:
        logger.warning("sized prep: copy failed: %s", error)
        return None

    import pythoncom
    import win32com.client as wc
    doc = None
    try:
        errors = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        # swOpenDocOptions_Silent (1) + writable
        doc = com(app, "OpenDoc6", str(target), 1, 1, "", errors, warnings)
        if doc is None:
            logger.warning("sized prep: could not open %s", target)
            return None
        cfg = com(doc, "GetConfigurationByName", size)
        if cfg is None:
            logger.warning("sized prep: config %r not found in %s", size, row["rel"])
            return None
        if not com(doc, "ShowConfiguration2", size):  # activates the size
            logger.warning("sized prep: ShowConfiguration2 failed for %r", size)
            return None
        if not com(doc, "EditRebuild3"):
            logger.warning("sized prep: rebuild failed for %r", size)
            return None
        if not com(doc, "Save3", 0, errors, warnings):
            logger.warning("sized prep: save failed for %r", size)
            return None
        return str(target)
    except Exception as error:
        logger.warning("sized prep failed for %s %r: %s", row["rel"], size, error)
        return None
    finally:
        if doc is not None:
            try:
                com(app, "CloseDoc", com(doc, "GetTitle"))
            except Exception:
                pass


@tool(
    name="list_standard_parts",
    description=(
        "List standard parts from the synced library: per-standard counts, or "
        "the full parts list for one standard. Data comes from the generated "
        "index.json; no SolidWorks calls are made."
    ),
    schema={
        "type": "object",
        "properties": {
            "standard": {"type": "string",
                         "description": "Standard id or folder, e.g. ISO, DIN, ANSI_Metric, SKF."},
        },
        "required": [],
    },
    operation_class=OperationClass.READ,
)
def list_standard_parts(sw, standard: str | None = None) -> dict:
    """Catalog of standard parts from the synced library (no COM)."""
    lib = library_dir()
    index = _load_json(lib / INDEX_FILE)
    if not isinstance(index, list) or not index:
        return sw._result(
            False,
            "Standard library not found. " + SYNC_HINT,
            SwErrors.swFileNotFoundError, {"code": "STANDARD_LIBRARY_NOT_FOUND",
                                           "library": str(lib)})

    if standard:
        rows = list(_matches(index, standard=standard))
        if not rows:
            return sw._result(False, f"No parts for standard: {standard}.",
                              SwErrors.swInvalidInput,
                              {"code": "STANDARD_NOT_FOUND"})
        parts = [{"standard": r["standard"], "type": r["type"],
                  "subcategory": r["subcategory"], "file": r["file"],
                  "rel": r["rel"], "source": r["source"]} for r in rows]
        return sw._result(True, f"{len(parts)} parts for {standard}.",
                          data={"standard": standard, "parts": parts})

    by_standard: dict[str, dict] = {}
    for row in index:
        entry = by_standard.setdefault(
            row["standard"], {"part_count": 0, "categories": set()})
        entry["part_count"] += 1
        entry["categories"].add(row["category"] or row["subcategory"] or row["type"])
    summary = {std: {"part_count": e["part_count"],
                     "categories": sorted(c for c in e["categories"] if c)}
               for std, e in sorted(by_standard.items())}
    return sw._result(True, f"{len(index)} parts across {len(summary)} standards.",
                      data={"standards": summary})


@tool(
    name="get_standard_part_sizes",
    description=(
        "Return the materialised sizes of a standard part, e.g. the Toolbox "
        "configurations 'ISO 4762 M10 x 16 - 16N'. Pass the same filters as "
        "list_standard_parts. Sizes come from sizes.json; parts SolidWorks has "
        "never configured have none. Sizes this library can prepare on demand "
        "from the Toolbox recipes are listed under preparable_sizes and are "
        "inserted only after geometry and save/reopen verification."
    ),
    schema={
        "type": "object",
        "properties": {
            "standard": {"type": "string", "description": "Standard id or folder, e.g. ISO."},
            "type": {"type": "string", "description": "Substring of the part type, e.g. 'socket head cap'."},
            "file": {"type": "string", "description": "Exact master file name, to disambiguate."},
        },
        "required": ["standard"],
    },
    operation_class=OperationClass.READ,
)
def get_standard_part_sizes(sw, standard: str, type: str = "",
                            file: str = "") -> dict:
    """Materialised sizes of one standard part type."""
    lib = library_dir()
    index = _load_json(lib / INDEX_FILE)
    sizes = _load_json(lib / SIZES_FILE) or {}
    if not isinstance(index, list):
        return sw._result(
            False, "Standard library not found. " + SYNC_HINT,
            SwErrors.swFileNotFoundError,
            {"code": "STANDARD_LIBRARY_NOT_FOUND", "library": str(lib)})

    matched = list(_matches(index, standard=standard, type_=type, file_=file))
    if not matched:
        return sw._result(False, f"Standard part not found: {standard}"
                          f"{'/' + type_ if type_ else ''}{'/' + file_ if file_ else ''}.",
                          SwErrors.swInvalidInput,
                          {"code": "STANDARD_PART_NOT_FOUND"})
    entries = []
    families = _recipe_families(lib)
    for row in matched:
        part_sizes = sizes.get(row["rel"], [])
        family = _family_for_row(families, row)
        recipe_labels = [label for label, _ in _family_size_entries(family)] if family else []
        preparable = [s for s in (
            DIN934_NUTS if _din934_nut(row) else
            DIN125A_WASHERS if _din125a_washer(row) else ()) if s not in part_sizes]
        preparable += [s for s in recipe_labels if s not in part_sizes and s not in preparable]
        entries.append({
            "standard": row["standard"], "type": row["type"],
            "file": row["file"], "rel": row["rel"], "source": row["source"],
            "sizes": part_sizes, "size_count": len(part_sizes),
            "recipe_family": family["id"] if family else None,
            "preparable_sizes": preparable,
            "preparable_count": len(preparable),
        })
    total = sum(len(e["sizes"]) for e in entries)
    return sw._result(
        True, f"{total} materialised size(s) for {len(entries)} part(s).",
        data={"parts": entries})


@tool(
    name="insert_standard_part",
    description=(
        "Insert a standard part (e.g. ISO 4017 M10 x 40) into the active assembly at x,y,z via insert_component. Fasteners require size= (e.g. 'ISO 4762 M10 x 16 - 16N'), which prepares that Toolbox size."
    ),
    schema={
        "type": "object",
        "properties": {
            "standard": {"type": "string", "description": "Standard id or folder, e.g. ISO, DIN"},
            "type": {"type": "string", "description": "Part type substring, e.g. 'hex screw'"},
            "file": {"type": "string", "description": "Exact master file name"},
            "size": {"type": "string", "description": "Configuration, e.g. 'ISO 4762 M10 x 16 - 16N'"},
            "x": {"type": "number", "description": "Meters, default 0"},
            "y": {"type": "number", "description": "Meters, default 0"},
            "z": {"type": "number", "description": "Meters, default 0"},
            "place": {"type": "string", "enum": ["center", "origin"],
                      "description": "As in insert_component"},
        },
        "required": ["standard"],
    },
    operation_class=OperationClass.MUTATE,
)
def insert_standard_part(sw, standard: str, type: str = "", file: str = "",
                         size: str = "", x: float = 0.0, y: float = 0.0,
                         z: float = 0.0, place: str = "center") -> dict:
    """Insert a standard part into the active assembly."""
    lib = library_dir()
    index = _load_json(lib / INDEX_FILE)
    sizes = _load_json(lib / SIZES_FILE) or {}
    if not isinstance(index, list):
        return sw._result(
            False, "Standard library not found. " + SYNC_HINT,
            SwErrors.swFileNotFoundError,
            {"code": "STANDARD_LIBRARY_NOT_FOUND", "library": str(lib)})

    row, err = _select_row(sw, index, standard, type, file)
    if err:
        return err

    if not size and _is_fastener(row):
        return sw._result(
            False, "Fasteners require a verified size; the master preview may have "
            "incorrect geometry. Call get_standard_part_sizes for sizes or preparable_sizes.",
            SwErrors.swInvalidInput,
            {"code": "SIZE_REQUIRED", "rel": row["rel"]})

    if size:
        # verified live: a Toolbox part ignores the configuration name passed
        # to AddComponent5; the requested size must be materialised first
        part_sizes = sizes.get(row["rel"], [])
        wanted = size.strip().casefold()
        exact = next((s for s in part_sizes if s.casefold() == wanted), None)
        generated = next((s for s in DIN934_NUTS if s.casefold() == wanted), None) if _din934_nut(row) else None
        washer = next((s for s in DIN125A_WASHERS if s.casefold() == wanted), None) if _din125a_washer(row) else None
        family = _family_for_row(_recipe_families(lib), row)
        recipe = next(((label, values) for label, values in _family_size_entries(family)
                       if label.casefold() == wanted), None) if family else None
        if exact is not None and generated is None and washer is None and recipe is None and _is_fastener(row):
            return sw._result(
                False, "A scanned configuration name is not geometry verification. "
                "Choose a size from preparable_sizes instead.", SwErrors.swInvalidInput,
                {"code": "SIZE_REQUIRES_VALIDATOR", "size": exact, "rel": row["rel"]})
        if exact is None and generated is None and washer is None and recipe is None:
            available = list(part_sizes) + ([s for s in (DIN934_NUTS if _din934_nut(row)
                                            else DIN125A_WASHERS if _din125a_washer(row)
                                            else ())])
            if family:
                available += [label for label, _ in _family_size_entries(family)]
            return sw._result(
                False,
                f"Size {size!r} is not materialised for this part.",
                SwErrors.swInvalidInput,
                {"code": "SIZE_NOT_AVAILABLE",
                 "available": available[:50],
                 "available_count": len(available)})
        # A scanned configuration is still a legitimate size; the opt-in
        # generated name always uses the geometry-validated preparation path.
        filepath = (_prepare_din934_nut(sw, lib, row, generated) if generated is not None
                    else _prepare_din125a_washer(sw, lib, row, washer) if washer is not None
                    else _prepare_recipe(sw, lib, row, family, recipe[0], recipe[1]) if recipe is not None
                    else _prepare_sized_copy(sw, lib, row, exact))
        chosen = exact or generated or washer or (recipe[0] if recipe else None)
        if filepath is None:
            return sw._result(
                False,
                f"Could not prepare size {chosen!r} (toolbox part must be "
                f"rebuilt with that configuration).",
                SwErrors.swFeatureError,
                {"code": "SIZE_PREPARATION_FAILED",
                 "size": chosen, "rel": row["rel"]})
        configuration = ""
    else:
        filepath = _master_file(lib, row)
        configuration = ""
        if not filepath or not os.path.isfile(filepath):
            return sw._result(
                False,
                f"Part file missing: {filepath}. " + SYNC_HINT,
                SwErrors.swFileNotFoundError,
                {"code": "STANDARD_PART_FILE_MISSING"})

    result = insert_component(sw, filepath=filepath, x=x, y=y, z=z,
                              place=place, configuration=configuration)
    if result.get("success"):
        result["data"] = {
            **(result.get("data") or {}),
            "standard": row["standard"], "type": row["type"],
            "file": row["file"],
            "requested_size": size or None,
            "configuration": configuration or None,
            "library_source": row["source"],
        }
    return result


@tool(
    name="standard_library_status",
    description=(
        "Report the state of the standard-parts library (path, catalog and "
        "size counts, last sync) and print the exact CLI command to rebuild it."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.READ,
)
def standard_library_status(sw) -> dict:
    """Library state and the rebuild command. The fill itself is a CLI."""
    lib = library_dir()
    index = _load_json(lib / INDEX_FILE)
    sizes = _load_json(lib / SIZES_FILE) or {}
    families = _recipe_families(lib)
    report_path = lib / "report.json"
    last_sync = None
    if report_path.is_file():
        last_sync = _load_json(report_path)

    state = {
        "library": str(lib),
        "index_present": isinstance(index, list) and bool(index),
        "index_count": len(index) if isinstance(index, list) else 0,
        "sizes_present": bool(sizes),
        "parts_with_sizes": sum(1 for v in sizes.values() if v),
        "recipe_present": bool(families),
        "recipe_families": len(families),
        "recipe_sizes": _recipe_size_count(families),
        "last_sync": last_sync,
        "rebuild_command": SYNC_HINT + " --scan-sizes",
        "recipe_command": ("Run: .venv\\Scripts\\python.exe "
                           "scripts\\build_std_size_recipes.py"),
        "env_override": LIBRARY_ENV_VAR,
    }
    ok = state["index_present"]
    return sw._result(
        ok,
        "Standard library ready." if ok else "Standard library missing.",
        int(SwErrors.swFileNotFoundError) if not ok else 0,
        data=state)
