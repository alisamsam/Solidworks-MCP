# SolidWorks MCP Server 🔧

> Automate SolidWorks using natural language through Claude AI and the Model Context Protocol (MCP)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![SolidWorks 2025](https://img.shields.io/badge/SolidWorks-2023--2025-red.svg)](https://www.solidworks.com/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

---

## 🎯 What is This?

**SolidWorks MCP Server** is a production-ready [Model Context Protocol](https://modelcontextprotocol.io/) server that lets Claude AI control SolidWorks through natural language. Instead of manually clicking through menus, you simply tell Claude what to design — and it builds it for you.

**Example prompts you can use:**
- *"Create a new part, draw a circle with radius 30mm and extrude it 15mm"*
- *"Add a fillet of 2mm to all edges"*
- *"Draw a hexagon and cut extrude it 10mm"*
- *"List all features in the current part"*

---

## ✨ Features

- ✅ **Extensible tool catalog** covering parts, sketches, features, and utilities; use `get_capabilities` for the current list
- ✅ **SolidWorks 2023–2025 Compatible** with version-aware API fallbacks
- ✅ **Auto-detects SolidWorks** installation via Windows registry
- ✅ **Multi-unit support** — mm, cm, inch, meter, foot
- ✅ **Modular architecture** — clean, extensible Python package
- ✅ **Robust error handling** — cascading fallback chains for COM API
- ✅ **JSON configuration** — easy to customize without touching code
- ✅ **Comprehensive logging** — full debug output for troubleshooting

---

## 🛠️ Available Tools

The table below lists core examples, not the complete current catalog.
Before modeling, use `get_modeling_guide(topic="index")` to select an ordered
workflow or an expert topic. The same read-only knowledge is available at
`solidworks://guides/index`. It covers feature order, prerequisite checks,
verification and currently advertised workflow tools without connecting to CAD.
See [shared knowledge and verification](solidworks_mcp/knowledge/documentation/integration.md).

A local parameter workspace now shares project owners, drafts, calculations
and agent requests between the browser and MCP clients. Start it with the
project Python environment: `python scripts/parameter_workspace.py --open`.
The tools `read_parameter_workspace` and `write_parameter_workspace` access
the same persistent register without a CAD connection. This first stage
does not discover or mutate CAD dimensions; see the
[current workspace capabilities](solidworks_mcp/knowledge/solidworks-2025-expert/references/parameter-workspace-operations.md).

| Category | Tool | Description |
|----------|------|-------------|
| **Connection** | `connect_solidworks` | Connect to running SolidWorks instance |
| **Connection** | `get_solidworks_info` | Get version and installation info |
| **Documents** | `create_new_part` | Create a new part document |
| **Documents** | `create_new_assembly` | Create a new assembly document |
| **Documents** | `open_document` | Open an existing SolidWorks file |
| **Documents** | `close_document` | Close the active document |
| **Documents** | `save_document` | Save the active document |
| **Documents** | `list_open_documents` | List all open documents |
| **Sketches** | `create_sketch` | Create a sketch on a plane (Front/Top/Right) |
| **Sketches** | `close_sketch` | Exit the active sketch |
| **Sketches** | `draw_circle` | Draw a circle by center and radius |
| **Sketches** | `draw_rectangle` | Draw a rectangle by two corners |
| **Sketches** | `draw_line` | Draw a line between two points |
| **Sketches** | `draw_arc` | Draw an arc by center and angles |
| **Sketches** | `draw_polygon` | Draw a regular polygon (triangle, hex, etc.) |
| **Features** | `extrude_sketch` | Boss-extrude the active sketch |
| **Features** | `cut_extrude` | Cut-extrude to remove material |
| **Features** | `fillet_edges` | Add fillets to selected edges |
| **Features** | `chamfer_edges` | Add chamfers to selected edges |
| **Features** | `list_features` | List all features in the model |
| **Utilities** | `set_units` | Change default unit (mm/inch/cm/m/ft) |
| **Utilities** | `execute_python` | Execute custom Python code in SW context |

---

## 📋 Requirements

- **OS:** Windows 10 or Windows 11
- **SolidWorks:** 2023, 2024, or 2025 (must be installed and licensed)
- **Python:** 3.10 or higher
- **Claude:** Claude Desktop app or Claude Code

---

## ⚡ Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/alisamsam/solidworks-mcp.git
cd solidworks-mcp
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Claude Desktop

Add the following to your `claude_desktop_config.json`:

**Location:** `C:\Users\YOUR_NAME\AppData\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "python",
      "args": ["C:\\path\\to\\solidworks-mcp\\solidworks_mcp_server.py"]
    }
  }
}
```

### 4. Launch

1. Open **SolidWorks** first
2. Restart **Claude Desktop**
3. In Claude, type: *"Connect to SolidWorks"*
4. Start designing! 🎉

---

## 📁 Project Structure

```
solidworks-mcp/
├── solidworks_mcp_server.py      # Entry point
├── solidworks_mcp/               # Main package
│   ├── __init__.py              # Package exports (v3.0.0)
│   ├── server.py                # MCP server & tool definitions
│   ├── config.py                # Configuration management
│   ├── config.json              # Default settings
│   ├── constants.py             # SolidWorks constants & enums
│   ├── automation/              # Core automation modules
│   │   ├── base.py             # Connection management
│   │   ├── documents.py        # Document operations
│   │   ├── sketches.py         # Sketch operations
│   │   └── features.py         # Feature operations (SW 2025 fixed)
│   └── utils/                   # Utility modules
│       ├── units.py            # Unit conversion system
│       └── sw_finder.py        # Auto-detect SolidWorks
├── requirements.txt
├── .gitignore
└── DEVELOPMENT_ROADMAP.md       # Future development plan
```

---

## ⚙️ Configuration

Edit `solidworks_mcp/config.json` to customize behavior:

```json
{
  "exe_path": "auto",
  "default_unit": "mm",
  "startup_timeout": 120,
  "log_level": "INFO",
  "default_extrude_depth": 10.0,
  "default_fillet_radius": 2.0
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `exe_path` | `"auto"` | Path to SLDWORKS.exe or auto-detect |
| `default_unit` | `"mm"` | Default unit for all dimensions |
| `startup_timeout` | `120` | Seconds to wait for SW startup |
| `log_level` | `"INFO"` | Logging verbosity |

---

## 🔧 SolidWorks 2025 Compatibility

This server includes special handling for SolidWorks 2025 API changes:

- **Extrusion fallback chain:** `FeatureExtrusion3` → `FeatureExtrusion2` → `FeatureBossSimple`
- **Safe property access** for `feat.Name`, `feat.GetTypeName2()`, `IsSuppressed2()`
- **stdout capture** fix for `execute_python` tool
- **Registry-based** SolidWorks auto-detection

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m "Add my feature"`
4. Push to the branch: `git push origin feature/my-feature`
5. Open a Pull Request

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

## 👤 Original author

**Samsaam Ali Baig**
- GitHub: [@alisamsam](https://github.com/alisamsam)

Additional development on the `additional-upgrades` branch: **PksOck**.
This branch is being prepared as a consolidated pull request for the original
author's review; its changes have not been merged upstream.

---

## 🙏 Acknowledgements

- [Anthropic](https://anthropic.com) for Claude AI and the MCP framework
- [SolidWorks](https://www.solidworks.com) COM API documentation
- Inspired by [ros2-claude-code-template](https://github.com/harunkurt/ros2-claude-code-template) by Harun KURT

---

⭐ **If this project helps you, please give it a star!**
