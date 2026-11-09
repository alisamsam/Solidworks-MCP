"""Repair obsolete shipped sample references in CLOSED, hash-checked COPIES only.

This is a bounded recovery for the installed SW2025 sample, not a general
basename search. The repaired staging project is subsequently handed to the
normal copy_project tool for the final independent deliverable.
"""
from __future__ import annotations
import json
from pathlib import Path
import shutil

SAMPLE = Path(r"C:\Users\Public\Documents\SOLIDWORKS\SOLIDWORKS 2025\samples\tutorial\routing-pipes")
LIBRARY = Path(r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\design library\routing")
OLD = Path(r"F:\WS\SampleFilesConverted_2025_SP0_8367d687")
PREFIXES = ((OLD / "samples/tutorial/routing-pipes", SAMPLE),
            (OLD / "sldworks/data/design library/routing", LIBRARY))
# The shipped flange/valve sample also retains this single author-workstation
# reference. Its installed replacement is explicitly identified, never searched
# by basename (the sample contains other duplicate component basenames).
EXACT_REFERENCES = {Path(r"C:\Users\HC8\Desktop\Repaired Data\Ball Valve.SLDPRT"):
                    SAMPLE / "fittings/Ball Valve.SLDPRT"}
DESTINATION = Path(__file__).resolve().parents[1] / "output/routing-native-skid-20261016-R01/staging"


def resolve_reference(reference):
    ref = Path(reference)
    if ref in EXACT_REFERENCES:
        return EXACT_REFERENCES[ref].resolve()
    for root in (SAMPLE, LIBRARY):
        if ref.is_relative_to(root):
            local = ref.resolve()
            if not local.is_relative_to(root.resolve()):
                raise ValueError("Reference escapes its explicit source root.")
            return local
    for old, root in PREFIXES:
        if ref.is_relative_to(old):
            local = (root / ref.relative_to(old)).resolve()
            if not local.is_relative_to(root.resolve()):
                raise ValueError("Reference escapes its explicit source root.")
            return local
    raise ValueError(f"Reference is outside both explicit relocation maps: {ref}")


def decode_references(raw, owner):
    if raw is None:
        if owner.suffix.lower() == ".sldasm":
            raise ValueError(f"Assembly dependency response is unavailable: {owner}")
        return []
    if not isinstance(raw, (list, tuple)) or len(raw) % 2:
        raise ValueError("Malformed native dependency response.")
    if owner.suffix.lower() == ".sldasm" and not raw:
        raise ValueError("The expected sample assembly has an empty dependency response.")
    result = []
    for name, value in zip(raw[::2], raw[1::2]):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Unresolved native reference: {name}")
        ref = Path(value)
        candidate = ref if ref.is_absolute() else owner.parent / ref
        result.append((value, resolve_reference(candidate)))
    return result


def require_sample_members(graph):
    required = {SAMPLE / name for name in ("finalskid.sldasm", "routeassy1-finalskid.sldasm", "routeassy2-finalskid.sldasm")}
    if not required.issubset(set(graph)) or not graph.get(SAMPLE / "finalskid.sldasm"):
        raise RuntimeError("Sample graph is missing its root or expected native Routing assemblies.")


def main():
    from solidworks_mcp.comutil import com
    from solidworks_mcp.config import get_config
    from solidworks_mcp.core.policy import OperationClass
    from solidworks_mcp.tools.project_copy import _dependencies, _hash, NATIVE

    policy = get_config().create_path_policy()
    if policy is None:
        raise RuntimeError("An approved output policy is required.")
    destination = policy.require_write(DESTINATION, OperationClass.EXPORT)
    if destination.exists():
        raise FileExistsError(destination)
    import win32com.client
    try:
        app = win32com.client.GetActiveObject("SldWorks.Application")
    except Exception as exc:
        raise RuntimeError("No existing SolidWorks instance; recovery does not launch or alter visibility.") from exc
    source = (SAMPLE / "finalskid.sldasm").resolve()
    graph, pending = {}, [source]
    while pending:
        path = pending.pop()
        if path in graph:
            continue
        if len(graph) >= 200:
            raise RuntimeError("Sample graph exceeds 200 documents.")
        if path.suffix.lower() not in NATIVE or not path.is_file():
            raise RuntimeError(f"Missing or unsupported native source: {path}")
        if not any(path.is_relative_to(root.resolve()) for root in (SAMPLE, LIBRARY)):
            raise RuntimeError("Source escapes the two permitted read roots.")
        opened = com(app, "GetOpenDocumentByName", str(path))
        if opened is not None and com(opened, "GetSaveFlag"):
            raise RuntimeError(f"Source has unsaved changes: {path}")
        raw = com(app, "GetDocumentDependencies2", str(path), False, False, False)
        refs = decode_references(raw, path)
        graph[path] = refs
        pending.extend(local for _, local in refs)
    require_sample_members(graph)
    hashes = {path: _hash(path) for path in graph}
    mapping = {path: destination / f"{path.stem}__stage_{i:03d}{path.suffix}"
               for i, path in enumerate(graph)}
    manifest = {"status": "preparing", "purpose": "repair shipped obsolete paths only in independent closed copies",
                "source": str(source), "root_document": str(mapping[source]),
                "files": [{"source": str(path), "copy": str(mapping[path]), "source_sha256": hashes[path]}
                          for path in graph]}
    destination.mkdir(parents=True, exist_ok=False)
    evidence = destination / "recovery-manifest.json"
    def write_manifest():
        evidence.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_manifest()
    try:
        for path, target in mapping.items():
            policy.require_write(target, OperationClass.EXPORT)
            with path.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            if _hash(target) != hashes[path]:
                raise RuntimeError(f"Copied bytes do not match source: {target}")
        for path, refs in graph.items():
            target = mapping[path]
            if com(app, "GetOpenDocumentByName", str(target)) is not None:
                raise RuntimeError("A staging copy unexpectedly became open.")
            for old, local in refs:
                if not com(app, "ReplaceReferencedDocument", str(target), str(old), str(mapping[local])):
                    raise RuntimeError(f"Closed-copy reference repair failed: {target} -> {old}")
        for path, refs in graph.items():
            if set(_dependencies(app, mapping[path])) != {mapping[local] for _, local in refs}:
                raise RuntimeError(f"Staging dependencies differ from expected: {mapping[path]}")
            if _hash(path) != hashes[path]:
                raise RuntimeError(f"Source changed: {path}")
        manifest["status"] = "verified"
        manifest["document_count"] = len(graph)
        manifest["reference_relocations"] = [{"owner": str(mapping[path]), "old": str(old),
                                               "resolved_source": str(local), "copy": str(mapping[local])}
                                              for path, refs in graph.items() for old, local in refs]
        write_manifest()
        print(json.dumps({"status": "verified", "root_document": str(mapping[source]), "documents": len(graph)}))
    except Exception as exc:
        manifest.update(status="failed", error=str(exc))
        write_manifest()
        raise


if __name__ == "__main__":
    main()
