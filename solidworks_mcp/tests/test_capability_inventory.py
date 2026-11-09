import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def load_auditor():
    path = Path(__file__).parents[2] / "scripts" / "audit_capabilities.py"
    spec = importlib.util.spec_from_file_location("audit_capabilities", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CapabilityInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "solidworks_mcp" / "tools").mkdir(parents=True)

    def tearDown(self):
        self.tempdir.cleanup()

    def write(self, relative_path, content):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_discovers_server_tool_and_decorated_tool_without_importing_fixture(self):
        self.write(
            "solidworks_mcp/server.py",
            'TOOLS = [Tool(name="open_document", description="opens")]\n',
        )
        self.write(
            "solidworks_mcp/tools/extension.py",
            '@tool(name="export_pdf", description="exports", schema={})\ndef export_pdf(sw):\n    return {}\n',
        )
        self.write(
            "solidworks_mcp/tools/internal.py",
            'def helper():\n    raise RuntimeError("must never be imported")\n',
        )

        capabilities = load_auditor().audit_repository(self.root)

        self.assertEqual(["export_pdf", "open_document"], [item.name for item in capabilities])
        self.assertEqual("decorated", capabilities[0].registration)
        self.assertEqual("server_tool", capabilities[1].registration)

    def test_reports_duplicate_public_names(self):
        self.write("solidworks_mcp/server.py", 'TOOLS = [Tool(name="open_document")]\n')
        self.write(
            "solidworks_mcp/tools/extension.py",
            '@tool(name="open_document", description="duplicate", schema={})\ndef duplicate(sw):\n    return {}\n',
        )

        report = load_auditor().audit_report(self.root)

        self.assertEqual(["open_document"], report["duplicates"])
        self.assertEqual(2, len(report["capabilities"]))

    def test_requirement_matrix_distinguishes_registered_internal_and_absent(self):
        self.write(
            "solidworks_mcp/server.py",
            '''TOOLS = [Tool(name="open_document", description="opens", inputSchema={"type": "object"})]
async def call_tool(name, arguments):
    if name == "open_document":
        result = sw_automation.open_document(arguments.get("filepath"))
''',
        )
        self.write(
            "solidworks_mcp/automation/documents.py",
            '''class DocumentOperations:
    def open_document(self, filepath):
        return filepath
    def create_new_drawing(self):
        return {}
''',
        )
        requirements = [
            {"requirement_id": "1.5-c", "requested_behavior": "Open document",
             "tool_name": "open_document", "owner_phase": "R1"},
            {"requirement_id": "4.6", "requested_behavior": "Create drawing",
             "tool_name": "create_drawing", "implementation_symbols": ["create_new_drawing"],
             "owner_phase": "R5"},
            {"requirement_id": "9.9", "requested_behavior": "Missing",
             "tool_name": "missing_tool", "owner_phase": "R9"},
        ]

        rows = load_auditor().build_requirement_register(self.root, requirements)

        self.assertEqual("registered", rows[0]["implementation_status"])
        self.assertEqual("solidworks_mcp/automation/documents.py#open_document",
                         rows[0]["handler_path"])
        self.assertEqual({"type": "object"}, rows[0]["schema"])
        self.assertEqual("internal_only", rows[1]["implementation_status"])
        self.assertEqual("solidworks_mcp/automation/documents.py#create_new_drawing",
                         rows[1]["handler_path"])
        self.assertEqual("absent", rows[2]["implementation_status"])

    def test_project_manifest_contains_all_44_numbered_roadmap_ids_once(self):
        manifest_path = Path(__file__).parents[2] / "scripts" / "capability_requirements.json"

        requirements = json.loads(manifest_path.read_text(encoding="utf-8"))
        numbered = [row["requirement_id"] for row in requirements
                    if row.get("category") == "original_numbered"]

        self.assertEqual(44, len(numbered))
        self.assertEqual(44, len(set(numbered)))

    def test_markdown_register_exposes_status_handler_and_next_action(self):
        rows = [{
            "requirement_id": "1.5-c",
            "requested_behavior": "Open document",
            "tool_name": "open_document",
            "implementation_status": "registered",
            "verification_status": "static_only",
            "handler_path": "solidworks_mcp/automation/documents.py#open_document",
            "owner_phase": "R1",
            "next_action": "verify_live",
        }]

        markdown = load_auditor().render_markdown_register(rows)

        self.assertIn("| 1.5-c | Open document | open_document | registered |", markdown)
        self.assertIn("solidworks_mcp/automation/documents.py#open_document", markdown)
        self.assertIn("verify_live", markdown)

    def test_explicit_blocked_status_is_not_promoted_by_registration(self):
        self.write(
            "solidworks_mcp/tools/blocked.py",
            '@tool(name="pack_and_go", description="blocked", schema={})\n'
            'def pack_and_go(sw):\n    return {}\n',
        )
        requirements = [{
            "requirement_id": "B19", "requested_behavior": "Independent copy",
            "tool_name": "pack_and_go", "owner_phase": "R3",
            "implementation_status": "blocked", "verification_status": "failed",
        }]

        row = load_auditor().build_requirement_register(self.root, requirements)[0]

        self.assertEqual("blocked", row["implementation_status"])
        self.assertEqual("failed", row["verification_status"])


if __name__ == "__main__":
    unittest.main()
