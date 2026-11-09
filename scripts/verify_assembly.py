"""Close everything, reopen the assembly, and verify the component count and extents."""
import json
import sys
from pathlib import Path

PKG_DIR = Path(r"C:\Users\Jan\Documents\Claude-Solidworks mcp")
OUT_DIR = Path(r"C:\Users\Jan\Documents\SolidWorks-projekti MCP\output\stair-U-winder-20260930")
ASM = OUT_DIR / "Sestav-stopnice-U.SLDASM"
if str(PKG_DIR) not in sys.path:
    sys.path.insert(0, str(PKG_DIR))

from solidworks_mcp.automation import SolidWorksAutomation      # noqa: E402
from solidworks_mcp.registry import execute                     # noqa: E402

SW = SolidWorksAutomation()


def call(name, **args):
    res = execute(name, SW, args).result
    if not res.get("success"):
        raise RuntimeError(f"{name} failed: {res.get('message')} | {res.get('data')}")
    return res.get("data", {})


def try_call(name, **args):
    return execute(name, SW, args).result


call("connect_solidworks")
for _ in range(200):
    r = try_call("list_open_documents")
    if not r.get("data", {}).get("documents"):
        break
    try_call("bind_active_document")
    try_call("close_document", save=False)
print("zaprto vse")

call("open_document", filepath=str(ASM))
info = call("get_solidworks_info")["session"]
print("aktivni:", info.get("active_document"), "| tip:", info.get("document_type"),
      "| GPU", f"{info['gpu_dedicated_mb']:.0f} MB")

comp = call("list_components", depth=1, mode="fast")
items = comp.get("components", [])
print("komponent:", len(items))
names = {}
for c in items:
    n = (c.get("name") or "").rsplit("-", 1)[0]
    names[n] = names.get(n, 0) + 1
for k in sorted(names):
    print(f"  {k:28} x{names[k]}")
print("feat:", len(call("list_features").get("features", [])))
