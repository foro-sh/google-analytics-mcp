# Google Analytics MCP

An [MCP](https://modelcontextprotocol.io) server for Google Analytics, built to deploy on
[foro.sh](https://foro.sh) as the Google Analytics blueprint. The server is
[Google's own](https://github.com/googleanalytics/google-analytics-mcp) (`analytics-mcp` on PyPI,
Apache-2.0), pinned and run unchanged behind foro's gate. Google is not affiliated with foro; see
`NOTICE`.

## Read-only

The server runs in Google's streamable HTTP mode without `--allow-write`, so only Google's read
tools are registered: account and property details, and standard, realtime, funnel and conversions
reports. foro asks Google for `analytics.readonly` and nothing else.

[`foro-tools.json`](foro-tools.json) is what foro reads to list the tools. It is generated from
[`tools.py`](tools.py), which also labels each tool: run `uv run scripts/write_manifest.py` after
changing it. A tool Google adds fails the tests until it has a label.

## Sign-in

The server holds no Google credentials. foro signs each member in to Google with foro's own Google
client and keeps the refresh token. Google's HTTP mode reads the caller's token from the
`Authorization` header, so [`broker.py`](broker.py) asks foro's upstream broker for the caller's
access token under the `google` grant and puts it there on each tool call, replacing any header a
client sent. It only runs inside a foro deploy, which sets `FORO_UPSTREAM_BROKER_URL` and
`FORO_UPSTREAM_BROKER_TOKEN`.

## Updates

`[tool.foro.upstream]` in `pyproject.toml` pins Google's release. A daily workflow
(`upstream-sync.yml`) opens a pull request when Google publishes a new one: it relocks, regenerates
`foro-tools.json` and writes the served tool list to `tools.json`, whose diff the pull request
shows.

## Development

```sh
uv sync
uv run pytest
./smoke.sh   # serve, list the tools, write tools.json
```
