from analytics_mcp import server as upstream

from broker import BrokerTokens, broker_config_from_env, with_caller_token

# Google's own HTTP mode, read-only (no --allow-write) and stateless: each call
# carries its caller's Google token, which the middleware puts in Authorization.
args = upstream.parse_args(["--transport", "http", "--host", "0.0.0.0", "--stateless-http"])
app = with_caller_token(upstream.build_http_app(args), BrokerTokens(broker_config_from_env()))

if __name__ == "__main__":
    import uvicorn

    # foro sets PORT. Bind all interfaces: a server on 127.0.0.1 fails the health check.
    uvicorn.run(app, host=args.host, port=args.port)
