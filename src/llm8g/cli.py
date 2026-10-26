"""The supported command-line entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm8g")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="run the HTTP inference gateway")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=9000)
    serve.add_argument("--profile", type=Path, help="dotenv-style serving profile")
    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn

        from llm8g.serving.config import GatewaySettings
        from llm8g.serving.http import create_app

        settings = (
            GatewaySettings.from_file(args.profile)
            if args.profile
            else GatewaySettings.from_env()
        )
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

