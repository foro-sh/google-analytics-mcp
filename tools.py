"""The tools this server serves and what foro shows for them. Google's read-only tools only:
the server runs without --allow-write, so its write tools are never registered."""

from analytics_mcp import coordinator

# A tool Google adds fails the tests until it has a label here, so the sync PR can't merge without one.
LABELS = {
    "get_account_summaries": "List accounts and properties",
    "get_property_details": "Read property details",
    "list_google_ads_links": "List Google Ads links",
    "list_property_annotations": "List annotations",
    "list_key_events": "List key events",
    "get_custom_dimensions_and_metrics": "List custom dimensions and metrics",
    "run_report": "Run a report",
    "run_realtime_report": "Run a realtime report",
    "run_funnel_report": "Run a funnel report",
    "run_conversions_report": "Run a conversions report",
}


def served() -> list:
    return list(coordinator.read_only_tools)


def manifest() -> dict:
    """What foro reads from a release to list the tools and tell reads from writes."""
    return {
        "tools": [
            {
                "name": tool.name,
                "label": LABELS.get(tool.name, tool.name),
                "description": (tool.description or "").strip().split("\n")[0].strip(),
                "writes": False,
            }
            for tool in served()
        ]
    }
