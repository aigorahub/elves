#!/usr/bin/env python3
"""Evaluate a repository's tracked exact-HEAD project landing profile."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cobbler_runtime.landing_profile import evaluate_landing_profile


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser(
        "check",
        help="Evaluate .elves/landing-profile.json at the exact current HEAD.",
    )
    check.add_argument(
        "--repo-root",
        default=".",
        help="Target Git repository root (default: current directory).",
    )
    check.add_argument(
        "--base",
        default="origin/main",
        help="Base ref to resolve once to an exact commit (default: origin/main).",
    )
    check.add_argument(
        "--head",
        default=None,
        help="Optional exact 40-character HEAD assertion.",
    )
    check.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON.",
    )
    return parser.parse_args(argv)


def _print_human(payload: dict) -> None:
    print(f"Project landing profile: {payload['status']}")
    if payload["head"]:
        print(f"- HEAD: {payload['head']}")
    if payload["base_commit"]:
        print(f"- Base: {payload['base_commit']}")
    if payload["digest"]:
        print(f"- Digest: {payload['digest']}")
    for check in payload["checks"]:
        severity = f"/{check['severity']}" if check.get("severity") else ""
        print(f"- {check['id']} ({check['kind']}{severity}): {check['status']}")
    for diagnostic in payload["diagnostics"]:
        print(f"- ERROR [{diagnostic['code']}]: {diagnostic['message']}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command != "check":
        return 2
    result = evaluate_landing_profile(
        Path(args.repo_root),
        base_ref=args.base,
        expected_head=args.head,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0 if result.green else 1


if __name__ == "__main__":
    sys.exit(main())
