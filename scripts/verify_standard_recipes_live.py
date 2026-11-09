"""Verify selected Toolbox recipes through production preparation and final reopen.

All CAD copies and reports stay in standard_library. Original masters are
hash-checked and never saved. This is a sampled check, not catalogue coverage.
"""
import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools import standard_parts as sp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", default="", help="comma-separated ids; empty means all")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--start-after", default="", help="resume after this exact sampled size label")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("samples must be positive")
    import pythoncom
    import win32com.client as wc

    lib = sp.library_dir()
    rows = json.loads((lib / "index.json").read_text(encoding="utf-8"))
    families = sp._recipe_families(lib)
    wanted = set(args.families.split(",")) if args.families else set()
    sw = SolidWorksAutomation()
    connection = sw.connect()
    if not connection["success"]:
        raise RuntimeError(connection)
    app = wc.dynamic.Dispatch(sw.app)
    records = []
    hashes = {}
    resume_pending = bool(args.start_after)
    output = lib / "verification" / (datetime.now().strftime("%Y%m%d_%H%M%S")
                                    + "_" + uuid.uuid4().hex[:8] + ".json")
    sw._path_policy.require_write(output, sp.OperationClass.MUTATE)
    output.parent.mkdir(parents=True, exist_ok=True)
    recipe_hash = hashlib.sha256((lib / sp.RECIPES_FILE).read_bytes()).hexdigest()

    def checkpoint(complete=False):
        unchanged = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                        for p, h in hashes.items())
        report = {"scope": "sampled recipes, not full catalogue", "complete": complete,
                  "resumed_after": args.start_after or None, "checks": records,
                  "masters_unchanged": unchanged, "master_sha256": hashes,
                  "recipe_sha256": recipe_hash}
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return unchanged

    for family in families:
        if wanted and family["id"] not in wanted:
            continue
        row = next(r for r in rows if r["standard"] == family["standard"]
                   and r["file"].casefold() == family["master"].casefold()
                   and r["rel"] == family["rel"])
        master = Path(sp._master_file(lib, row))
        hashes[str(master)] = hashlib.sha256(master.read_bytes()).hexdigest()
        entries = list(sp._family_size_entries(family))
        if args.samples == 1 and family["kind"] == "screw":
            samples = [next((e for e in entries if " M8 x " in e[0]), entries[0])]
        else:
            indices = sorted({round(i * (len(entries) - 1) / max(1, args.samples - 1))
                              for i in range(min(args.samples, len(entries)))})
            samples = [entries[i] for i in indices]
        for label, values in samples:
            if resume_pending:
                if label == args.start_after:
                    resume_pending = False
                continue
            record = {"family": family["id"], "size": label, "success": False}
            path = sp._prepare_recipe(sw, lib, row, family, label, values)
            if path:
                e = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                w = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                doc = com(app, "OpenDoc6", path, 1, 3, "", e, w)
                owns_doc = False
                try:
                    record["path"] = path
                    if doc is not None:
                        actual = str(com(doc, "GetPathName"))
                        owns_doc = Path(actual).resolve() == Path(path).resolve()
                    record["open_error"] = e.value
                    record["path_identity_verified"] = owns_doc
                    record["success"] = bool(owns_doc and not e.value and com(doc, "EditRebuild3")
                                              and sp._recipe_valid(doc, label, values,
                                                                   family["box"], family["units"]))
                    if owns_doc and not e.value:
                        bodies = com(doc, "GetBodies2", 0, False) or ()
                        if len(bodies) == 1:
                            box = com(bodies[0], "GetBodyBox")
                            record["box_mm"] = [(box[i + 3] - box[i]) * 1000 for i in range(3)]
                finally:
                    if owns_doc:
                        com(app, "CloseDoc", com(doc, "GetTitle"))
            records.append(record)
            checkpoint()
            print(f"{family['id']}: {label}: {'PASS' if record['success'] else 'FAIL'}", flush=True)
    if resume_pending:
        raise ValueError("start-after label was not in the sampled sizes")
    unchanged = checkpoint(complete=True)
    print(f"PASS {sum(r['success'] for r in records)}/{len(records)}; masters unchanged: {unchanged}")
    print(output.resolve())
    return 0 if unchanged and records and all(r["success"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
