import asyncio
import json
import unittest
from pathlib import Path

from solidworks_mcp import catalog, server
from solidworks_mcp.knowledge import library
from solidworks_mcp.registry import registered_tools

WORKFLOWS = Path(library.EXPERT) / "workflows"
DATA = Path(__file__).parent / "data"
TOP_SCHEMAS = ["create_tab_and_slot", "create_weldment_gusset", "create_weldment_end_cap",
               "create_structural_member", "edit_component_pattern", "insert_standard_part",
               "edit_feature_definition", "create_configuration", "edit_mate", "insert_component"]
TOP_SCHEMAS_BUDGET = 12_686

# The full catalog is only an upper bound; the per-toolset budgets are what a task loads.
FULL_CATALOG_BUDGET = 200_000
CORE_BUDGET = 12_000
TOOLSET_BUDGET = 20_000


def catalog_bytes(tools):
    """Bytes a client loads for these tool definitions."""
    return sum(
        len(json.dumps({"name": item.name, "description": item.description,
                        "inputSchema": item.inputSchema}, ensure_ascii=False).encode("utf-8"))
        for item in tools
    )


def _without_descriptions(value):
    """Drop description strings; a property that is itself named 'description' stays."""
    if isinstance(value, dict):
        return {k: _without_descriptions(v) for k, v in value.items()
                if not (k == "description" and isinstance(v, str))}
    if isinstance(value, list):
        return [_without_descriptions(v) for v in value]
    return value


class CatalogBudgetTests(unittest.TestCase):
    def test_full_catalog_stays_within_budget(self):
        tools = asyncio.run(server.list_tools())
        self.assertLessEqual(catalog_bytes(tools), FULL_CATALOG_BUDGET)

    def test_each_toolset_stays_within_its_budget(self):
        groups = {}
        for item in registered_tools():
            groups.setdefault(catalog.toolset_of(item.name), []).append(item)
        self.assertLessEqual(catalog_bytes(groups.pop("core")), CORE_BUDGET)
        for name, tools in groups.items():
            with self.subTest(toolset=name):
                self.assertLessEqual(catalog_bytes(tools), TOOLSET_BUDGET)

    def test_server_instructions_fit_the_client_limit(self):
        self.assertLessEqual(len(library.server_instructions()), 1_900)

    def test_instructions_keep_the_entry_points(self):
        text = library.server_instructions()
        for phrase in ("get_modeling_guide", "workflow/operating", "workflow/project-copy",
                       "workflow/parameter-ui", "workflow/engineering-package",
                       "list_components(mode=\"fast\", depth=1)", "operation_id",
                       "custom properties"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_details_removed_from_instructions_live_in_guides(self):
        project_copy = (WORKFLOWS / "project-copy.md").read_text(encoding="utf-8")
        parameter_ui = (WORKFLOWS / "parameter-ui.md").read_text(encoding="utf-8")
        package = (WORKFLOWS / "engineering-package.md").read_text(encoding="utf-8")
        self.assertIn("Shrani kot", project_copy)
        self.assertIn("lastnost", parameter_ui)
        self.assertIn("does not prove the user's desktop displays it", package)
        self.assertIn("process_parameter_workspace_job", package)
        self.assertIn("never promises rollback", package)

    def test_largest_schemas_are_30_percent_smaller(self):
        tools = [t for t in registered_tools() if t.name in TOP_SCHEMAS]
        self.assertEqual(len(TOP_SCHEMAS), len(tools))
        self.assertLessEqual(catalog_bytes(tools), TOP_SCHEMAS_BUDGET)

    def test_shortening_did_not_change_schema_structure(self):
        expected = json.loads((DATA / "a6_structure_snapshot.json").read_text(encoding="utf-8"))
        tools = {t.name: t for t in registered_tools()}
        for name in TOP_SCHEMAS:
            with self.subTest(tool=name):
                self.assertEqual(expected[name], _without_descriptions(tools[name].inputSchema))

    def test_removed_caveats_are_in_tool_notes(self):
        notes = (Path(library.EXPERT) / "references" / "tool-notes.md").read_text(encoding="utf-8")
        for name in TOP_SCHEMAS:
            with self.subTest(tool=name):
                self.assertIn(f"`{name}`", notes)


if __name__ == "__main__":
    unittest.main()
