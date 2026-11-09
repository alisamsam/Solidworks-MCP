#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solidworks_mcp/stdlib_sync.py — standard-parts library harvest (pure, testable).

The MCP standard-parts tools never read the SOLIDWORKS Toolbox directly;
they read a generated library folder. The Toolbox is one (optional) inlet
for filling that folder. This module builds the catalog from the filesystem
and discovers the Toolbox data root -- no COM involved.

See scripts/sync_standard_library.py (thin CLI) and
docs/upgrade/STANDARD-LIBRARY-FLOW.md.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("solidworks_mcp.stdlib_sync")

# ---------------------------------------------------------------------------
# Catalog walk (no COM)
# ---------------------------------------------------------------------------

# standard folder name -> canonical standard id
STANDARD_IDS = {
    "ansi inch": "ANSI_Inch",
    "ansi metric": "ANSI_Metric",
    "as": "AS",
    "bsi": "BSI",
    "cisc": "CISC",
    "din": "DIN",
    "gb": "GB",
    "is": "IS",
    "iso": "ISO",
    "jis": "JIS",
    "ks": "KS",
    "mil": "MIL",
    "pem inch": "PEM_Inch",
    "pem metric": "PEM_Metric",
    "skf": "SKF",
    "torrington inch": "TORRINGTON_Inch",
    "torrington metric": "TORRINGTON_Metric",
    "truarc": "TRUARC",
    "unistrut": "UNISTRUT",
    "steellib": "STEEL",
}

# per-standard suffix SolidWorks appends to part file names
STANDARD_SUFFIXES = {
    "ansi inch": "_ai",
    "ansi metric": "_am",
    "as": "_as",
    "bsi": "_bsi",
    "cisc": "_cisc",
    "din": "_din",
    "gb": "_gb",
    "is": "_is",
    "iso": "_iso",
    "jis": "_jis",
    "ks": "_ks",
    "mil": "_mil",
    "pem inch": "_pi",
    "pem metric": "_pm",
    "skf": "_skf",
    "torrington inch": "_ti",
    "torrington metric": "_tm",
    "truarc": "_tr",
    "unistrut": "_un",
}

DEFAULT_DATA_ROOTS = [
    r"C:\SOLIDWORKS Data",
    r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\Toolbox",
    r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\Toolbox",
]


def registry_data_root() -> str | None:
    """Read SolidWorks 'Toolbox Data Location' from HKCU (registry), any
    installed version key. Pure reader; returns None when absent."""
    try:
        import winreg
    except ImportError:
        return None
    base = r"SOFTWARE\SolidWorks"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as sw:
            for i in range(winreg.QueryInfoKey(sw)[0]):
                ver = winreg.EnumKey(sw, i)
                if not ver.upper().startswith("SOLIDWORKS"):
                    continue
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                        f"{base}\\{ver}\\General") as gen:
                        value, _ = winreg.QueryValueEx(gen, "Toolbox Data Location")
                        if value and os.path.isdir(value):
                            return value
                except OSError:
                    continue
    except OSError:
        return None
    return None


def find_data_root(override: str | None = None,
                   registry_reader=registry_data_root) -> str:
    """Resolve the toolbox data root: --override, registry, known defaults."""
    if override:
        return os.path.abspath(override)
    reg = registry_reader()
    if reg:
        logger.info("data root from registry: %s", reg)
        return reg
    for candidate in DEFAULT_DATA_ROOTS:
        if os.path.isdir(candidate):
            logger.info("data root fallback: %s", candidate)
            return candidate
    return ""


def is_master_part(name: str) -> bool:
    return name.lower().endswith(".sldprt")


def normalize_type(filename: str, standard: str) -> str:
    """File name -> human type name: strip the _<suffix>.sldprt tail."""
    base = os.path.splitext(filename)[0]
    suffix = STANDARD_SUFFIXES.get(standard)
    if suffix and base.endswith(suffix):
        base = base[: -len(suffix)]
    return base.strip().replace("_", " ").strip()


def walk_standards(data_root: str,
                   standards: list[str] | None) -> list[tuple[str, str, str]]:
    """Return [(standard_id, folder_name, abs_root)] for requested standards."""
    browser = os.path.join(data_root, "browser")
    result: list[tuple[str, str, str]] = []
    if not os.path.isdir(browser):
        return result
    wanted = {s.casefold() for s in standards} if standards else None
    for entry in sorted(os.listdir(browser)):
        folder = os.path.join(browser, entry)
        if not os.path.isdir(folder):
            continue
        std = STANDARD_IDS.get(entry.casefold())
        if std is None:
            continue
        if wanted and entry.casefold() not in wanted:
            continue
        result.append((std, entry, folder))
    return result


def _row(standard_id: str, std_folder: str, rel_dir: str, filename: str,
         source: str, full_path: str) -> dict:
    return {
        "standard": standard_id,
        "standard_folder": std_folder,
        "category": os.path.dirname(rel_dir),
        "subcategory": os.path.basename(rel_dir) if rel_dir and rel_dir != "." else "",
        "type": normalize_type(filename, std_folder),
        "file": filename,
        "rel": os.path.join(rel_dir, filename).replace("\\", "/").replace("//", "/"),
        "source": source,
        "path": full_path,
    }


def build_catalog(data_root: str,
                  standards: list[str] | None = None) -> list[dict]:
    """Full catalog via filesystem walk of browser + custom Toolbox tree."""
    rows: list[dict] = []
    for std_id, folder_name, root in walk_standards(data_root, standards):
        for dirpath, _dirs, files in os.walk(root):
            for f in sorted(files):
                if not is_master_part(f):
                    continue
                rel_dir = os.path.relpath(dirpath, root)
                rows.append(_row(std_id, folder_name, rel_dir, f,
                                 "browser", os.path.join(dirpath, f)))

    # custom / configured tree under <root>\Toolbox\<standard>\...
    custom = os.path.join(data_root, "Toolbox")
    if os.path.isdir(custom):
        requested = {s.casefold() for s in standards} if standards else None
        for dirpath, _dirs, files in os.walk(custom):
            for f in sorted(files):
                if not is_master_part(f):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, f), custom)
                parts = rel.split(os.sep)
                std_folder = parts[0]
                if requested and std_folder.casefold() not in requested:
                    continue
                std_id = STANDARD_IDS.get(std_folder.casefold(), std_folder)
                rel_dir = os.path.dirname(rel) if len(parts) > 1 else ""
                rows.append(_row(std_id, std_folder, rel_dir, f,
                                 "custom", os.path.join(dirpath, f)))
    return rows