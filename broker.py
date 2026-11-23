"""Google access tokens from foro's upstream broker. foro holds the refresh token and foro's
own Google client; neither ever reaches this container.

Google's server, in its HTTP mode, takes the caller's Google token from the request's
Authorization header. foro's gate adds `x-foro-caller` (a short-lived handle the broker
resolves to the caller) and `x-foro-subject` to each request with a per-user grant, and strips
any a client sent, so the middleware here swaps in that caller's Google token on each
tools/call. Tokens are cached per subject, since the handle rotates; without a handle there is
one shared token."""

import json
import os
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

import httpx

# The upstream grant's name on the foro project.
GRANT_NAME = "google"
# A team is small; past this the least recently used caller's token is fetched again.
MAX_CALLERS = 256


class BrokerError(Exception):
    pass


@dataclass(frozen=True)
class BrokerConfig:
    url: str
    token: str


def broker_config_from_env(env: Mapping[str, str] = os.environ) -> BrokerConfig:
    url, token = env.get("FORO_UPSTREAM_BROKER_URL"), env.get("FORO_UPSTREAM_BROKER_TOKEN")
    if not url or not token:
        raise RuntimeError(
            "This server gets its Google tokens from foro's upstream broker, which only exists inside a foro "
            "deploy. Missing FORO_UPSTREAM_BROKER_URL or FORO_UPSTREAM_BROKER_TOKEN."
        )
    return BrokerConfig(url.rstrip("/"), token)


class BrokerTokens:
    def __init__(
        self,
        config: BrokerConfig,
        http: httpx.AsyncClient | None = None,
        now: Callable[[], float] = time.time,
    ):
        self._config = config
        self._http = http or httpx.AsyncClient(timeout=10)
        self._now = now
        self._cache: OrderedDict[str | None, tuple[str, float]] = OrderedDict()

    async def access_token(self, handle: str | None, key: str | None) -> str:
        cached = self._cache.get(key)
        # The broker already hands out expiry early, so a token is good right up to expires_at.
        if cached and cached[1] > self._now():
            return cached[0]
        fresh = await self._fetch(handle)
        self._cache.pop(key, None)
        self._cache[key] = fresh
        if len(self._cache) > MAX_CALLERS:
            self._cache.popitem(last=False)
        return fresh[0]

    async def _fetch(self, handle: str | None) -> tuple[str, float]:
        headers = {"Authorization": f"Bearer {self._config.token}"}
        if handle:
            headers["x-foro-caller"] = handle
        try:
            response = await self._http.get(f"{self._config.url}/grants/{GRANT_NAME}", headers=headers)
        except httpx.HTTPError as err:
            raise BrokerError("foro could not get a Google access token; try again shortly.") from err
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if response.is_error:
            raise BrokerError(_broker_error(response.status_code, body))
        if not isinstance(body.get("access_token"), str):
            raise BrokerError("foro's broker returned no Google access token.")
        expires_at = body.get("expires_at")
        return body["access_token"], datetime.fromisoformat(expires_at).timestamp() if expires_at else float("inf")


def _broker_error(status: int, body: dict) -> str:
    connect = body.get("connect_url") if isinstance(body.get("connect_url"), str) else None
    if status == 401 and body.get("error") == "caller_required":
        return "foro could not tell who is calling; try again."
    if status == 404 and connect:
        return f"You have not connected Google Analytics yet. Sign in to Google at {connect}, then try again."
    if status == 404:
        return "Google Analytics is not connected yet: sign in to Google from the project's Environment tab on foro."
    if status == 409 and connect:
        return f"Your Google connection has lapsed. Sign in to Google again at {connect}, then try again."
    if status == 409:
        return "The Google connection has lapsed. Reconnect it from the project's Environment tab on foro."
    return f"foro could not get a Google access token ({status}); try again shortly."


def with_caller_token(app, tokens: BrokerTokens):
    """ASGI middleware: the caller's Google token as the Authorization header of each tools/call.
    A token a client sent is never passed on: what reaches Google is always the broker's."""

    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            return await app(scope, receive, send)
        headers = [(k, v) for k, v in scope["headers"] if k != b"authorization"]
        body, more = b"", True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        call = _tool_call(body)
        if call is not None:
            found = dict(headers)
            handle = found.get(b"x-foro-caller", b"").decode() or None
            key = (found.get(b"x-foro-subject", b"").decode() or handle) if handle else None
            try:
                token = await tokens.access_token(handle, key)
            except BrokerError as err:
                return await _tool_error(send, call.get("id"), str(err))
            headers.append((b"authorization", f"Bearer {token}".encode()))

        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        return await app({**scope, "headers": headers}, replay, send)

    return middleware


def _tool_call(body: bytes) -> dict | None:
    try:
        message = json.loads(body)
    except ValueError:
        return None
    return message if isinstance(message, dict) and message.get("method") == "tools/call" else None


async def _tool_error(send, request_id, text: str) -> None:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": True},
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": payload})
