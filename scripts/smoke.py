"""Starts the wrapped server, calls tools/list and writes it to tools.json, for the upstream sync."""

import json
import os
import sys
from pathlib import Path

from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# No credentials: listing tools never reaches the broker or Google.
os.environ.setdefault("FORO_UPSTREAM_BROKER_URL", "http://broker.invalid")
os.environ.setdefault("FORO_UPSTREAM_BROKER_TOKEN", "smoke")

import server  # noqa: E402

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def rpc(http: TestClient, method: str, params: dict) -> dict:
    res = http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, headers=HEADERS)
    res.raise_for_status()
    if res.headers["content-type"].startswith("text/event-stream"):
        data = [line[6:] for line in res.text.splitlines() if line.startswith("data: ")]
        return json.loads(data[-1])
    return res.json()


def list_tools() -> list[dict]:
    with TestClient(server.app, base_url="http://localhost") as http:
        rpc(
            http,
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}},
        )
        return rpc(http, "tools/list", {})["result"]["tools"]


if __name__ == "__main__":
    tools = list_tools()
    (ROOT / "tools.json").write_text(json.dumps({"tools": tools}, indent=2) + "\n")
    writes = [tool["name"] for tool in tools if not tool.get("annotations", {}).get("readOnlyHint")]
    if writes:
        sys.exit(f"Served without readOnlyHint, but this server is read-only: {', '.join(writes)}")
