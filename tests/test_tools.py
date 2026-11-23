import json
from pathlib import Path

from analytics_mcp import coordinator

from tools import LABELS, manifest, served

ROOT = Path(__file__).resolve().parent.parent


def test_foro_tools_json_is_current():
    assert json.loads((ROOT / "foro-tools.json").read_text()) == manifest(), "run: uv run scripts/write_manifest.py"


def test_every_served_tool_has_a_label():
    assert {tool.name for tool in served()} == set(LABELS)


def test_serves_none_of_googles_write_tools():
    writes = {tool.name for tool in coordinator.write_tools}
    assert writes, "Google's write tools moved; check what --allow-write still gates"
    assert not writes & {tool.name for tool in served()}
