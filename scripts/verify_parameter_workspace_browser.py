"""Temporary isolated workspace for manual browser regression tests. Ctrl+C cleans up."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidworks_mcp.workspace.parameter_store import ParameterStore
from solidworks_mcp.workspace.parameter_http import create_server


def main():
    with tempfile.TemporaryDirectory(prefix="parameter-ui-review-") as folder:
        store = ParameterStore(Path(folder) / "fixture.sqlite3")
        project = store.create_project("Preizkus pregleda · začasno")
        owner = store.add_owner(project["id"], {"name": "Steber", "kind": "part"})
        fields = []
        for key, label, value in [("width", "Širina", 100), ("height", "Višina", 200)]:
            fields.append(store.add_parameter(project["id"], {"owner_id": owner["id"],
                "key": key, "label": label, "value_type": "number", "observed_value": value,
                "source": "Poskusna vrednost; ni CAD meritev"}))
        store.add_parameter(project["id"], {"owner_id": owner["id"], "key": "ratio",
            "label": "Razmerje", "value_type": "number", "role": "derived",
            "formula": {"op": "divide", "inputs": [f["id"] for f in fields]}})
        server, token = create_server(store)
        print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/?token={token}",
                          "project": project["id"], "fields": {f["key"]: f["id"] for f in fields}}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
