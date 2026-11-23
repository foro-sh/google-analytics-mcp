import asyncio
import json

import httpx
import pytest

from broker import BrokerConfig, BrokerError, BrokerTokens, broker_config_from_env, with_caller_token

CONFIG = BrokerConfig("https://broker.internal", "cap")
CALL = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "run_report", "arguments": {}}}


def broker(handler, now=lambda: 1_000.0) -> BrokerTokens:
    return BrokerTokens(CONFIG, httpx.AsyncClient(transport=httpx.MockTransport(handler)), now)


def tokens_by_caller(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer cap"
    assert request.url.path == "/grants/google"
    caller = request.headers.get("x-foro-caller", "shared")
    return httpx.Response(200, json={"access_token": f"ya29-{caller}", "expires_at": "2100-01-01T00:00:00+00:00"})


async def test_fetches_each_callers_own_token_and_caches_it_per_subject():
    calls = []

    def handler(request):
        calls.append(request.headers.get("x-foro-caller"))
        return tokens_by_caller(request)

    tokens = broker(handler)
    assert await tokens.access_token("h1", "alice") == "ya29-h1"
    assert await tokens.access_token("h2", "bob") == "ya29-h2"
    # The handle rotates; the subject's token is still good.
    assert await tokens.access_token("h3", "alice") == "ya29-h1"
    assert await tokens.access_token(None, None) == "ya29-shared"
    assert calls == ["h1", "h2", None]


async def test_fetches_again_once_the_token_has_expired():
    now = [1_000.0]
    tokens = broker(tokens_by_caller, lambda: now[0])
    await tokens.access_token("h1", "alice")
    now[0] = 5_000_000_000.0
    calls = []
    tokens._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(1) or tokens_by_caller(r)))
    await tokens.access_token("h1", "alice")
    assert calls == [1]


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (
            404,
            {"error": "not_connected", "connect_url": "https://foro.sh/c/t"},
            "Sign in to Google at https://foro.sh/c/t",
        ),
        (404, {}, "Environment tab"),
        (409, {"connect_url": "https://foro.sh/c/t"}, "Sign in to Google again at https://foro.sh/c/t"),
        (401, {"error": "caller_required"}, "could not tell who is calling"),
        (500, {}, "(500)"),
    ],
)
async def test_says_how_to_connect_when_the_broker_has_no_token(status, body, message):
    tokens = broker(lambda r: httpx.Response(status, json=body))
    with pytest.raises(BrokerError, match=message.replace("(", r"\(").replace(")", r"\)")):
        await tokens.access_token("h1", "alice")


def test_needs_the_broker_foro_injects():
    with pytest.raises(RuntimeError, match="FORO_UPSTREAM_BROKER_URL"):
        broker_config_from_env({})
    assert broker_config_from_env(
        {"FORO_UPSTREAM_BROKER_URL": "https://b/", "FORO_UPSTREAM_BROKER_TOKEN": "t"}
    ) == BrokerConfig("https://b", "t")


def recording_app():
    seen = []

    async def app(scope, receive, send):
        message = await receive()
        seen.append((dict(scope["headers"]).get(b"authorization"), message["body"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return app, seen


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_puts_the_callers_google_token_on_a_tool_call_and_passes_the_body_on():
    inner, seen = recording_app()
    async with client(with_caller_token(inner, broker(tokens_by_caller))) as http:
        await http.post("/mcp", json=CALL, headers={"x-foro-caller": "h1", "x-foro-subject": "alice"})
    [(auth, body)] = seen
    assert auth == b"Bearer ya29-h1"
    assert json.loads(body) == CALL


async def test_never_passes_on_a_token_the_client_sent():
    inner, seen = recording_app()
    listing = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    async with client(with_caller_token(inner, broker(tokens_by_caller))) as http:
        await http.post("/mcp", json=listing, headers={"authorization": "Bearer foro-project-token"})
        await http.post("/mcp", json=CALL, headers={"authorization": "Bearer foro-project-token"})
    assert [auth for auth, _ in seen] == [None, b"Bearer ya29-shared"]


async def test_asks_the_broker_only_for_a_tool_call():
    def refuse(request):
        raise AssertionError("no token is needed to list tools")

    inner, seen = recording_app()
    async with client(with_caller_token(inner, broker(refuse))) as http:
        res = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert res.status_code == 200
    assert len(seen) == 1


async def test_two_callers_at_once_each_reach_google_as_themselves():
    async def slow(request):
        await asyncio.sleep(0.01)
        return tokens_by_caller(request)

    async def app(scope, receive, send):
        await receive()
        await asyncio.sleep(0.01)
        auth = dict(scope["headers"])[b"authorization"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": auth})

    tokens = BrokerTokens(CONFIG, httpx.AsyncClient(transport=httpx.MockTransport(slow)))
    async with client(with_caller_token(app, tokens)) as http:
        a, b = await asyncio.gather(
            http.post("/mcp", json=CALL, headers={"x-foro-caller": "ha", "x-foro-subject": "alice"}),
            http.post("/mcp", json=CALL, headers={"x-foro-caller": "hb", "x-foro-subject": "bob"}),
        )
    assert (a.content, b.content) == (b"Bearer ya29-ha", b"Bearer ya29-hb")


async def test_answers_a_tool_call_it_cannot_get_a_token_for_with_how_to_connect():
    inner, seen = recording_app()
    tokens = broker(
        lambda r: httpx.Response(404, json={"error": "not_connected", "connect_url": "https://foro.sh/c/t"})
    )
    async with client(with_caller_token(inner, tokens)) as http:
        res = await http.post("/mcp", json=CALL, headers={"x-foro-caller": "h1"})
    assert seen == []
    assert res.json() == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": "You have not connected Google Analytics yet. Sign in to Google at https://foro.sh/c/t, "
                    "then try again.",
                }
            ],
            "isError": True,
        },
    }
