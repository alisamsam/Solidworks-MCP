"""Insert five verified standard-part sizes, save/reopen an assembly, check references.

An insertion test only. No mates, Smart Fasteners or strength claims.
Writes exclusively under standard_library/verification.
"""
import json
import os
import sys
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools import standard_parts as sp
from solidworks_mcp.tools.saving import save_document


def main():
    import pythoncom
    import win32com.client as wc
    lib = sp.library_dir()
    index = json.loads((lib / "index.json").read_text(encoding="utf-8"))
    families = sp._recipe_families(lib)
    requests = [("DIN", sp.DIN934_MASTER, "DIN 934 M10", None),
                ("DIN", sp.DIN125A_MASTER, "DIN 125A M10", None)]
    for fid, label in (("iso4762", "ISO 4762 M10 x 25"),
                       ("iso4161", "ISO 4161 M5"), ("iso7380", "ISO 7380 M8 x 25")):
        f = next(f for f in families if f["id"] == fid)
        requests.append((f["standard"], f["master"], label, f))
    sw = SolidWorksAutomation()
    assert sw.connect()["success"]
    assert sw.create_new_assembly()["success"]
    sw.bind_active_document()
    app = wc.dynamic.Dispatch(sw.app)
    asm = com(app, "ActiveDoc")
    original_get_active = sw.get_active_doc
    owned_identity = asm._oleobj_.QueryInterface(pythoncom.IID_IUnknown)

    def owned_active():
        current, error = original_get_active()
        if error:
            return current, error
        if current._oleobj_.QueryInterface(pythoncom.IID_IUnknown) != owned_identity:
            raise RuntimeError("active document drift; refusing insertion/save on a user document")
        # Downstream methods mutate this captured COM document, not a second
        # ActiveDoc lookup which could point at a different document.
        return asm, None

    sw.get_active_doc = owned_active

    def canonical(path):
        return os.path.normcase(os.path.abspath(path))
    expected = {}
    results = []
    for i, (standard, master, label, family) in enumerate(requests):
        row = next(r for r in index if r["standard"] == standard and r["file"].casefold() == master.casefold())
        result = sp.insert_standard_part(sw, standard=standard, file=master, size=label, x=i * .05)
        results.append({"size": label, "success": result["success"], "message": result["message"]})
        print(label, result["success"], flush=True)
        if not result["success"]:
            raise RuntimeError(result)
        expected[canonical(str(sp._sized_cache_path(lib, row, label)))] = (label, family)

    def verify(document):
        records = []
        if not com(document, "EditRebuild3") or not sp._features_clear(document):
            return False, records
        components = com(document, "GetComponents", True) or ()
        actual_references = []
        for component in components:
            path = str(com(component, "GetPathName"))
            configuration = com(component, "ReferencedConfiguration")
            actual_references.append((canonical(path), configuration))
            if canonical(path) not in expected:
                records.append({"path": path, "geometry_verified": False, "error": "unexpected reference"})
                continue
            label, family = expected[canonical(path)]
            model = com(component, "GetModelDoc2")
            if (configuration != label or model is None
                    or canonical(str(com(model, "GetPathName"))) != canonical(path)):
                records.append({"path": path, "configuration": configuration,
                                "geometry_verified": False, "error": "model/configuration mismatch"})
                continue
            if family:
                values = dict(sp._family_size_entries(family))[label]
                valid = sp._recipe_valid(model, label, values, family["box"], family["units"])
            elif label.startswith("DIN 934"):
                valid = sp._nut_valid(model, label, sp.DIN934_NUTS[label])
            else:
                valid = sp._washer_valid(model, label, sp.DIN125A_WASHERS[label])
            records.append({"size": label, "path": path,
                            "configuration": configuration,
                            "geometry_verified": valid})
        expected_references = Counter((path, label) for path, (label, _) in expected.items())
        return (Counter(actual_references) == expected_references
                and all(r["geometry_verified"] for r in records)), records

    before, records = verify(asm)
    if not before:
        raise RuntimeError("assembly geometry/reference validation failed")
    root = lib / "verification" / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_assembly_" + uuid.uuid4().hex[:8])
    sw._path_policy.require_write(root / "assembly.SLDASM", sp.OperationClass.MUTATE)
    root.mkdir(parents=True, exist_ok=False)
    path = root / "assembly.SLDASM"
    owned_active()
    saved = save_document(sw, path=str(path), overwrite=False)
    if (not saved["success"] or canonical(saved["data"]["path"]) != canonical(str(path))
            or canonical(str(com(asm, "GetPathName"))) != canonical(str(path))):
        raise RuntimeError("owned assembly was not saved at the expected path")
    com(app, "CloseDoc", com(asm, "GetTitle"))
    if com(app, "GetOpenDocumentByName", str(path)) is not None:
        raise RuntimeError("assembly did not close; refusing to claim a reopen test")
    e = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    w = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    reopened = com(app, "OpenDoc6", str(path), 2, 1, "", e, w)
    identity = reopened is not None and Path(com(reopened, "GetPathName")).resolve() == path.resolve()
    after, reopened_records = verify(reopened) if identity and not e.value else (False, [])
    report = {"scope": "insertion and saved references, not mating or strength",
              "insertions": results, "before_save": before, "after_reopen": after,
              "components": reopened_records, "path": str(path)}
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if identity:
        com(app, "CloseDoc", com(reopened, "GetTitle"))
    print("PASS" if after else "FAIL", root.resolve(), flush=True)
    return 0 if after else 1


if __name__ == "__main__":
    raise SystemExit(main())
