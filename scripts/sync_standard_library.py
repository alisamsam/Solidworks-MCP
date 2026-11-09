#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_standard_library.py — thin CLI over solidworks_mcp.stdlib_sync.

Harvest the SOLIDWORKS Toolbox into the MCP standard library:

    1. Catalog  -- walk <data root>\\browser\\<standard>\\... for master part
                   files (fast, no COM). Also sweep the custom
                   <data root>\\Toolbox\\ tree and CopiedParts\\.
    2. Sizes    --scan-sizes: open each part in SolidWorks (silent,
                   read-only) and record configurations beyond
                   Default/PreviewCfg -- the sizes already materialised.
    3. Harvest   --copy-sized: copy sized masters and generated copies into
                   the library so the bundle is portable.

Data root: HKCU\\Software\\SolidWorks\\SOLIDWORKS <ver>\\General\\
            Toolbox Data Location (registry), or --data-root.

Output (--out, default solidworks_mcp/standard_library/):
  index.json   full catalog [{standard, category, subcategory, type, file,
                              rel, source, path}]
  sizes.json   per-part size configurations [{rel: [configs]}]
  sizes.cache.tsv  resumable scan journal
  source/      portability copies of sized material
  report.json  run summary (for another model to verify)

The output folder is gitignored; re-run on any machine. Parts that have no
sizes yet are filled when SolidWorks generates them (insert once via the
Task Pane, then re-run with --scan-sizes).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from solidworks_mcp.stdlib_sync import build_catalog, find_data_root, is_master_part

logger = logging.getLogger("sync_standard_library")

EXCLUDED_CONFIGS = {"default", "previewcfg"}

# swOpenDocOptions_e: Silent(1) | ReadOnly(2) -- no prompts, no save dialog
OPEN_TIMEOUT_OPTIONS = 1 | 2


class ComDied(Exception):
    """SolidWorks COM server went away (RPC unavailable)."""


def connect_sw():
    """Late-bound SolidWorks application object (dynamic dispatch)."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    sw = win32com.client.GetObject(Class="SldWorks.Application")
    return win32com.client.dynamic.Dispatch(sw)


def reconnect_sw() -> object | None:
    """Retry connect a few times; return None when SolidWorks is truly down."""
    for attempt in range(3):
        try:
            return connect_sw()
        except Exception as exc:
            logger.warning("reconnect attempt %d failed: %s", attempt + 1, exc)
            time.sleep(3)
    return None


def scan_part_configs(sw, part_path: str) -> list[str]:
    """Open a part silently, read-only, and return size configuration names."""
    import pythoncom
    import win32com.client
    from solidworks_mcp.comutil import com

    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    try:
        doc = com(sw, "OpenDoc6", part_path, 1, OPEN_TIMEOUT_OPTIONS, "",
                  errors, warnings)
    except Exception as exc:
        if "RPC server is unavailable" in str(exc):
            raise ComDied(exc)
        logger.warning("open failed %s: %s", part_path, exc)
        return []
    if doc is None:
        code = int(getattr(errors, "value", 0) or 0)
        logger.debug("open returned None (error %s): %s", code, part_path)
        return []
    try:
        configs = com(doc, "GetConfigurationNames") or []
        return [c for c in list(configs) if c.lower() not in EXCLUDED_CONFIGS]
    except Exception as exc:
        if "RPC server is unavailable" in str(exc):
            raise ComDied(exc)
        logger.warning("read failed %s: %s", part_path, exc)
        return []
    finally:
        try:
            com(sw, "CloseDoc", com(doc, "GetTitle"))
        except Exception:
            pass


def scan_sizes(catalog: list[dict], cache_path: Path,
               progress_every: int = 25) -> tuple[dict, int]:
    """Open every catalogued part once; record size configs. Resumable.

    Returns (cache, completed_count). On persistent COM failure it stops with
    partial results instead of losing the whole run.
    """
    sw = reconnect_sw()
    if sw is None:
        logger.error("cannot connect to SolidWorks; scan skipped")
        return {}, 0

    cache: dict[str, list[str]] = {}
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rel, cfg = line.split("\t", 1)
                    cache[rel] = json.loads(cfg)

    todo = [r for r in catalog if r["rel"] not in cache]
    logger.info("size scan: %d cached, %d to scan", len(cache), len(todo))
    start = time.time()
    carried = len(cache)
    with open(cache_path, "a", encoding="utf-8") as fh:
        for i, row in enumerate(todo, 1):
            configs = None
            for attempt in range(3):
                try:
                    configs = scan_part_configs(sw, row["path"])
                    break
                except ComDied:
                    logger.warning("COM lost at %s; reconnect attempt %d",
                                   row["rel"], attempt + 1)
                    sw = reconnect_sw()
                    if sw is None:
                        break
            if configs is None:
                logger.error("SolidWorks unavailable at %s; scan stopped at %d/%d",
                             row["rel"], i, len(todo))
                break
            cache[row["rel"]] = configs
            fh.write(f"{row['rel']}\t{json.dumps(configs)}\n")
            fh.flush()
            if (carried + i) % progress_every == 0 or i == len(todo):
                rate = (time.time() - start) / i
                logger.info("size scan %d/%d (%.1f%%) ~%.1fs/part last=%s cfg=%d",
                            i, len(todo), 100.0 * i / len(todo),
                            rate, row["rel"], len(configs))
    return cache, len(cache)


def harvest_copied_parts(data_root: str, dest: Path) -> int:
    """Copy SmartFastener-generated parts from CopiedParts into source/."""
    copied = os.path.join(data_root, "CopiedParts")
    count = 0
    if not os.path.isdir(copied):
        return count
    for dirpath, _dirs, files in os.walk(copied):
        for f in files:
            if not is_master_part(f):
                continue
            src = os.path.join(dirpath, f)
            rel = os.path.relpath(src, copied).replace("\\", "/")
            target = dest / "source" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, target)
                count += 1
            except OSError as e:
                logger.warning("copy failed %s: %s", src, e)
    return count


def rel_tail(row: dict) -> str:
    """Path of a catalog row relative to its standard folder.

    Browser rows are already relative to ``browser/<standard>/``. Custom rows
    are relative to ``Toolbox/`` and start with the standard folder, which is
    stripped here so both sources share one layout under ``source/``.
    """
    rel = row["rel"]
    if row.get("source") == "custom" and "/" in rel:
        return rel.split("/", 1)[1]
    return rel


def copy_sized_masters(catalog: list[dict], sizes: dict, dest: Path) -> int:
    """Copy parts with materialised sizes into source/ (portability)."""
    count = 0
    for row in catalog:
        if not sizes.get(row["rel"]):
            continue
        tail = rel_tail(row)
        target = dest / "source" / row["standard"] / tail
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(row["path"], target)
            count += 1
        except OSError as e:
            logger.warning("copy failed %s: %s", row["rel"], e)
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", help="Toolbox data root (default: registry)")
    parser.add_argument("--standard", action="append", default=None,
                        help="Standard folder to include in the catalog (repeatable); default: all")
    parser.add_argument("--scan-standard", action="append", default=None,
                        help="Standards to size-scan (repeatable); default: same as --standard")
    parser.add_argument("--out", default=r"solidworks_mcp\standard_library",
                        help="Library output folder")
    parser.add_argument("--scan-sizes", action="store_true",
                        help="Open parts in SolidWorks to record materialised sizes")
    parser.add_argument("--copy-sized", action="store_true",
                        help="Copy parts that carry sizes into the library")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")

    data_root = find_data_root(args.data_root)
    if not data_root or not os.path.isdir(data_root):
        print(json.dumps(
            {"ok": False, "error": "TOOLBOX_NOT_CONFIGURED",
             "hint": "set --data-root or configure Hole Wizard/Toolbox"},
            indent=2, ensure_ascii=False))
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    catalog = build_catalog(data_root, args.standard)
    (out / "index.json").write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    by_std: dict[str, int] = {}
    for row in catalog:
        by_std[row["standard"]] = by_std.get(row["standard"], 0) + 1

    sizes: dict[str, list[str]] = {}
    scan_completed = 0
    scan_requested_total = 0
    if args.scan_sizes:
        cache_file = out / "sizes.cache.tsv"
        scan_rows = catalog
        if args.scan_standard:
            wanted = {s.casefold() for s in args.scan_standard}
            scan_rows = [r for r in catalog
                         if r["standard_folder"].casefold() in wanted]
            logger.info("size scan limited to %d rows", len(scan_rows))
        scan_requested_total = len(scan_rows)
        try:
            sizes, scan_completed = scan_sizes(scan_rows, cache_file)
        except Exception as exc:  # never lose the partial cache/journal
            logger.error("size scan aborted: %s", exc)
            scan_completed = -1
        # sizes.json always rebuilt from the cache journal (source of truth)
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rel, cfg = line.split("\t", 1)
                        sizes[rel] = json.loads(cfg)
        (out / "sizes.json").write_text(
            json.dumps(sizes, indent=2, ensure_ascii=False), encoding="utf-8")

    harvested = harvest_copied_parts(data_root, out)
    copied_sized = 0
    if args.copy_sized:
        copied_sized = copy_sized_masters(catalog, sizes, out)

    report = {
        "ok": True,
        "data_root": data_root,
        "standard_count": len(by_std),
        "part_count": len(catalog),
        "per_standard": by_std,
        "size_scan": bool(args.scan_sizes),
        "scan_completed": scan_completed,
        "scan_requested": scan_requested_total,
        "parts_with_sizes": sum(1 for v in sizes.values() if v),
        "harvested_copied_parts": harvested,
        "copied_sized_masters": copied_sized,
        "out": str(out),
    }
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())