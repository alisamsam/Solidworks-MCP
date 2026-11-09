"""Launch the local parameter workspace without connecting to SolidWorks."""

import argparse
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidworks_mcp.workspace.parameter_http import create_server
from solidworks_mcp.workspace.parameter_store import DEFAULT_PATH, ParameterStore


def main():
    parser = argparse.ArgumentParser(description="Local SolidWorks parameter workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the local page in the default browser")
    options = parser.parse_args()
    store = ParameterStore(DEFAULT_PATH)
    server, token = create_server(store, port=options.port)
    url = f"http://127.0.0.1:{server.server_port}/?token={token}"
    print(url, flush=True)
    if options.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
