#!/usr/bin/env python3
"""Launch the local PolySignal read-only Web Console.

The server is intentionally loopback-only by default. It reads existing run
artifacts and never starts an ingestion, paper-trading, or execution loop.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from polysignal.interface.web_console import PROJECT_ROOT, serve


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the PolySignal read-only Web Console")
    parser.add_argument("--host", default="127.0.0.1", help="Loopback host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Web Console is loopback-only; use 127.0.0.1, localhost, or ::1")
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"PolySignal Web Console: http://{args.host}:{args.port}")
    print("Mode: READ-ONLY RESEARCH | live execution disabled")
    serve(args.host, args.port, args.project_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
