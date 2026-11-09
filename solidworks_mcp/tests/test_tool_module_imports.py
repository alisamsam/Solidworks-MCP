"""Every tool module must be imported by solidworks_mcp.tools.

The runtime registers tools by importing the tools package, while the
capability audit scans the tool sources statically. A module that exists
but is never imported therefore looks implemented to the audit yet is
missing at runtime. This test keeps the two views consistent.
"""

import ast
import unittest
from pathlib import Path

import solidworks_mcp.tools as tools_package
from solidworks_mcp.registry import registered_tools

TOOLS_DIR = Path(tools_package.__file__).parent
SERVER_PATH = TOOLS_DIR.parent / "server.py"
IGNORED_MODULES = {"__init__", "guard"}


def _inline_tool_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Tool"):
            for keyword in node.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    names.add(keyword.value.value)
    return names


def _declares_tools(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Name) and target.id == "tool":
                    return True
    return False


class ToolModuleImportTests(unittest.TestCase):
    def test_every_tool_module_is_imported_at_runtime(self):
        imported = {
            name for name in vars(tools_package)
            if not name.startswith("_")
        }
        missing = []
        for path in sorted(TOOLS_DIR.glob("*.py")):
            if path.stem in IGNORED_MODULES or not _declares_tools(path):
                continue
            if path.stem not in imported:
                missing.append(path.name)

        self.assertEqual(
            [], missing,
            "Tool modules are not imported by solidworks_mcp/tools/__init__.py "
            f"and are therefore absent at runtime: {missing}",
        )

    def test_runtime_registers_a_named_tool_for_every_module(self):
        names = {item.name for item in registered_tools()}

        self.assertIn("save_document", names)
        self.assertIn("trim_entities", names)
        self.assertIn("extend_entities", names)
        self.assertIn("insert_marked_dimensions", names)
        self.assertIn("auto_balloon", names)
        self.assertIn("create_sheet_metal_base_flange", names)

    def test_inline_server_tools_do_not_shadow_registry_tools(self):
        inline = _inline_tool_names(SERVER_PATH)
        registry = {item.name for item in registered_tools()}

        self.assertEqual(
            set(), inline & registry,
            "server.py advertises its own definition of a tool that the "
            "registry also defines, so the inline dispatcher shadows the "
            f"registry version: {sorted(inline & registry)}",
        )


if __name__ == "__main__":
    unittest.main()
