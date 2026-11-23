from scripts.smoke import list_tools
from tools import LABELS


def test_serves_googles_read_tools_over_streamable_http_without_credentials():
    tools = list_tools()
    assert {tool["name"] for tool in tools} == set(LABELS)
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
