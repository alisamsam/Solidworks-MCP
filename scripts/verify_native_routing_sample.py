"""Read-only saved-state evidence for the recovered official native Routing skid."""
import json
from pathlib import Path

from solidworks_mcp.comutil import com
from solidworks_mcp.config import get_config
from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.tools.project_copy import _graph, _hash


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    import win32com.client
    base = Path(__file__).resolve().parents[1] / "output/routing-native-skid-20261016-R01"
    policy = get_config().create_path_policy()
    require(policy is not None, "Approved output policy required.")
    target = policy.require_write(base / "native-routing-verification.json", OperationClass.EXPORT)
    require(not target.exists(), "Evidence already exists; do not overwrite it.")
    manifest = json.loads((base / "assembly/.solidworks-project-copy.json").read_text())
    recovery = json.loads((base / "staging/recovery-manifest.json").read_text())
    require(manifest["status"] == recovery["status"] == "verified", "Unverified copy chain.")
    expected = {Path(entry["copy"]).resolve() for entry in manifest["files"]}
    require(len(expected) == 23 and all(p.parent == base / "assembly" for p in expected), "Unexpected copy set.")
    app = win32com.client.GetActiveObject("SldWorks.Application")
    root = Path(manifest["root_document"]).resolve()
    require(root in expected, "Unexpected root identity.")
    # Do not rely on ActiveDoc: the user can inspect another open project.
    doc = com(app, "GetOpenDocumentByName", str(root))
    require(doc is not None and Path(com(doc, "GetPathName")).resolve() == root, "Target is not loaded.")
    require(com(doc, "GetSaveFlag") is False, "Root has unsaved changes.")
    graph = _graph(app, [root])
    require(set(graph) == expected, "Saved graph differs from the verified copy set.")
    components = list(com(doc, "GetComponents", False) or [])
    require(len(components) == 50, "Unexpected instance count.")
    rows, routes, docs = [], [], {root: doc}
    for component in components:
        path = Path(com(component, "GetPathName")).resolve()
        require(path in expected, f"Unexpected live component path: {path}")
        child = com(component, "GetModelDoc2")
        require(child is not None and Path(com(child, "GetPathName")).resolve() == path, "Unloaded or substituted component.")
        configuration = com(component, "ReferencedConfiguration")
        require(com(child, "GetConfigurationByName", configuration) is not None, "Missing referenced configuration.")
        docs[path] = child
        rows.append({"name": com(component, "Name2"), "path": str(path), "configuration": configuration})
    require(set(docs) == expected, "Live document coverage is incomplete.")
    for path, child in docs.items():
        require(com(child, "GetSaveFlag") is False, f"Unsaved document: {path}")
        if com(child, "GetType") != 2 or com(child, "IsRouteAssembly") is not True:
            continue
        sketches = []
        feature = com(child, "FirstFeature")
        visited = 0
        while feature is not None:
            visited += 1
            require(visited <= 2000, "Feature traversal limit exceeded.")
            if com(feature, "GetTypeName2") == "3DProfileFeature":
                sketch = com(feature, "GetSpecificFeature2")
                sketches.append({"name": com(feature, "Name"), "segment_count": len(com(sketch, "GetSketchSegments") or [])})
            feature = com(feature, "GetNextFeature")
        require(sketches and sum(s["segment_count"] for s in sketches) > 0, "Native route has no readable 3D sketch.")
        routes.append({"path": str(path), "native_route_assembly": True, "sketches": sketches,
                       "top_level_component_count": len(com(child, "GetComponents", True) or [])})
    require(len(routes) == 3, "Expected three native route subassemblies.")
    for entry in recovery["files"] + manifest["files"]:
        require(_hash(Path(entry["source"])) == entry["source_sha256"], "An original or staging source changed.")
    require(all(com(d, "GetSaveFlag") is False for d in docs.values()), "Document became dirty during inspection.")
    report = {"status": "SAVED_NATIVE_ROUTING_SAMPLE_VERIFIED",
              "basis": "Independent recovered official SW2025 finalskid sample, not generated from scratch",
              "root_document": str(root), "native_document_count": len(graph),
              "component_instance_count": len(rows), "native_route_count": len(routes),
              "routes": routes, "components": rows, "all_live_paths_in_final_manifest": True,
              "all_referenced_configurations_exist": True, "all_loaded_documents_clean": True,
              "saved_dependency_graph_internal_only": True, "original_and_staging_hashes_unchanged": True,
              "file_hashes": {str(path): _hash(path) for path in expected},
              "reopened_by_this_verifier": False,
              "external_reopen_operation": "2cf9cc82-f0a4-4ddd-8837-b457e04622d5",
              "unattended_new_route_creation_verified": False, "manufacturing_or_pressure_design_verified": False}
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps({"status": report["status"], "documents": len(graph), "instances": len(rows),
                      "routes": routes, "report": str(target)}, indent=2))


if __name__ == "__main__":
    main()
