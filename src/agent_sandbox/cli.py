"""Command-line entry point: ``agent-sandbox serve`` and ``agent-sandbox openapi``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from agent_sandbox import __version__
from agent_sandbox.config import ConfigError, Settings


def _openapi(output: str | None) -> int:
    from agent_sandbox.api import create_app

    # The spec does not depend on runtime settings, so a throwaway config is enough.
    app = create_app(Settings(insecure_no_auth=True), manager=_NoManager())  # type: ignore[arg-type]
    text = json.dumps(app.openapi(), indent=2, sort_keys=False) + "\n"
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


class _NoManager:
    """Placeholder manager used only to render the OpenAPI document."""


def _serve(host: str | None, port: int | None) -> int:
    import uvicorn

    from agent_sandbox.api import create_app

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    if settings.insecure_no_auth:
        logging.getLogger("agent_sandbox").warning("authentication is DISABLED; never expose this server")
    uvicorn.run(
        create_app(settings),
        host=host or settings.host,
        port=port or settings.port,
        log_level="info",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-sandbox", description=__doc__)
    parser.add_argument("--version", action="version", version=f"agent-sandbox {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the REST API server")
    serve.add_argument("--host", help="bind address (default: AGENT_SANDBOX_HOST or 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port (default: AGENT_SANDBOX_PORT or 8080)")

    spec = sub.add_parser("openapi", help="print the OpenAPI document")
    spec.add_argument("-o", "--output", help="write to a file instead of stdout")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "serve":
        return _serve(args.host, args.port)
    return _openapi(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
