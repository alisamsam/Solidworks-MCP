"""Statically inventory MCP tools without importing the SolidWorks server."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any


class Capability:
    def __init__(self, name: str, registration: str, source: str, line: int,
                 handler: str | None = None, schema: dict[str, Any] | None = None):
        self.name = name
        self.registration = registration
        self.source = source
        self.line = line
        self.handler = handler
        self.schema = schema

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "registration": self.registration,
            "source": self.source,
            "line": self.line,
            "handler": self.handler,
            "schema": self.schema,
            "verification": "static_only",
        }


def _call_name(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
    return None


def _literal_keyword(call: ast.Call, name: str) -> Any:
    for keyword in call.keywords:
        if keyword.arg == name:
            try:
                return ast.literal_eval(keyword.value)
            except (ValueError, TypeError):
                return None
    return None


def _is_named(call: ast.Call, expected: str) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id == expected
    if isinstance(call.func, ast.Attribute):
        return call.func.attr == expected
    return False


def _scan_file(path: Path, root: Path) -> list[Capability]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    source = path.relative_to(root).as_posix()
    found: list[Capability] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_named(node, "Tool"):
            name = _call_name(node)
            if name:
                found.append(Capability(
                    name, "server_tool", source, node.lineno,
                    schema=_literal_keyword(node, "inputSchema")))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and _is_named(decorator, "tool"):
                    name = _call_name(decorator)
                    if name:
                        found.append(Capability(
                            name, "decorated", source, node.lineno, node.name,
                            _literal_keyword(decorator, "schema")))
    return found


def audit_repository(root: Path) -> list[Capability]:
    """Return public MCP capability declarations from source only (no imports)."""

    root = root.resolve()
    paths = [root / "solidworks_mcp" / "server.py"]
    tools_dir = root / "solidworks_mcp" / "tools"
    if tools_dir.exists():
        paths.extend(sorted(tools_dir.rglob("*.py")))
    found: list[Capability] = []
    for path in paths:
        if path.exists():
            found.extend(_scan_file(path, root))
    return sorted(found, key=lambda item: (item.name, item.source, item.line))


def audit_report(root: Path) -> dict[str, Any]:
    capabilities = audit_repository(root)
    counts: dict[str, int] = {}
    for capability in capabilities:
        counts[capability.name] = counts.get(capability.name, 0) + 1
    return {
        "verification": "static_only",
        "capabilities": [capability.to_dict() for capability in capabilities],
        "duplicates": sorted(name for name, count in counts.items() if count > 1),
    }


def _scan_implementation_symbols(root: Path) -> dict[str, list[str]]:
    """Map Python function/method names to stable source-path identifiers."""
    symbols: dict[str, list[str]] = {}
    package = root / "solidworks_mcp"
    if not package.exists():
        return symbols
    for path in sorted(package.rglob("*.py")):
        relative_parts = path.relative_to(package).parts
        if "tests" in relative_parts or any(part.startswith("backup_") for part in relative_parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        source = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.setdefault(node.name, []).append(f"{source}#{node.name}")
    return symbols


def build_requirement_register(root: Path,
                               requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join roadmap requirements to public tools and internal implementations."""
    root = root.resolve()
    capabilities = audit_repository(root)
    public: dict[str, list[Capability]] = {}
    for capability in capabilities:
        public.setdefault(capability.name, []).append(capability)
    symbols = _scan_implementation_symbols(root)

    rows: list[dict[str, Any]] = []
    for requirement in requirements:
        row = dict(requirement)
        tool_name = row.get("tool_name")
        matches = public.get(tool_name, []) if tool_name else []
        implementation_symbols = row.get("implementation_symbols") or ([tool_name] if tool_name else [])
        handler_candidates = [candidate for symbol in implementation_symbols
                              for candidate in symbols.get(symbol, [])]

        explicit_status = row.get("implementation_status")
        if matches:
            status = (explicit_status if explicit_status in {"blocked", "superseded", "partial"}
                      else "registered" if len(matches) == 1 else "partial")
            capability = matches[0]
            if capability.registration == "decorated":
                handler_path = f"{capability.source}#{capability.handler}"
            else:
                handler_path = handler_candidates[0] if handler_candidates else capability.source
            schema = capability.schema
        elif handler_candidates:
            status = "internal_only"
            handler_path = handler_candidates[0]
            schema = None
        else:
            status = row.get("implementation_status", "absent")
            handler_path = None
            schema = None

        row.update({
            "schema": schema,
            "handler_path": handler_path,
            "dependencies": row.get("dependencies", []),
            "implementation_status": status,
            "verification_status": row.get(
                "verification_status",
                "static_only" if status in {"registered", "internal_only", "partial"} else "not_run"),
            "evidence": row.get("evidence", []),
            "next_action": row.get(
                "next_action",
                "verify_live" if status == "registered" else
                "register_tool" if status == "internal_only" else "implement"),
        })
        rows.append(row)
    return rows


def render_markdown_register(rows: list[dict[str, Any]]) -> str:
    """Render a compact, reviewable capability matrix."""
    def cell(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Capability register",
        "",
        "Generated by `scripts/audit_capabilities.py`. Registration and live verification are separate statuses.",
        "",
        "| ID | Requested behavior | Tool | Implementation | Verification | Handler | Owner | Next action | Dependencies | Evidence |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        values = [
            row.get("requirement_id"), row.get("requested_behavior"),
            row.get("tool_name"), row.get("implementation_status"),
            row.get("verification_status"), row.get("handler_path"),
            row.get("owner_phase"), row.get("next_action"),
            row.get("dependencies", []), row.get("evidence", []),
        ]
        lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--format", choices=("json",), default="json")
    parser.add_argument("--requirements", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    args = parser.parse_args()
    if args.requirements:
        requirements = json.loads(args.requirements.read_text(encoding="utf-8"))
        payload: Any = build_requirement_register(args.root, requirements)
        if args.output_json:
            args.output_json.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.output_markdown:
            args.output_markdown.write_text(render_markdown_register(payload), encoding="utf-8")
    else:
        payload = audit_report(args.root)
    if not args.output_json and not args.output_markdown:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
