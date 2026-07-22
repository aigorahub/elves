#!/usr/bin/env python3
"""Evaluate and evolve a repository's tracked exact-HEAD project landing profile."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cobbler_runtime.landing_profile import evaluate_landing_profile
from cobbler_runtime.landing_profile_learn import (
    clear_exact_head_waiver,
    list_candidates,
    observe_landing,
    promote_candidate,
    propose_candidates,
    set_exact_head_waiver,
)


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

    observe = subparsers.add_parser(
        "observe",
        help="Record an exact-HEAD observation under .elves/runtime/landing-profile/.",
    )
    observe.add_argument("--repo-root", default=".")
    observe.add_argument("--base", default="origin/main")
    observe.add_argument("--note", default=None, help="Optional operator note.")
    observe.add_argument("--propose-id", default=None, help="Optional explicit candidate id.")
    observe.add_argument(
        "--propose-when",
        action="append",
        default=None,
        help="Glob for explicit path_touched when condition (repeatable).",
    )
    observe.add_argument(
        "--propose-paths",
        action="append",
        default=None,
        help="Glob for explicit path_touched required paths (repeatable).",
    )
    observe.add_argument(
        "--propose-severity",
        choices=("blocking", "advisory"),
        default="advisory",
    )
    observe.add_argument(
        "--propose-kind",
        choices=("path_touched", "post_merge_checklist"),
        default="path_touched",
    )
    observe.add_argument("--propose-description", default=None)
    observe.add_argument("--json", action="store_true")

    propose = subparsers.add_parser(
        "propose",
        help="Synthesize candidates from observations (never writes the tracked profile).",
    )
    propose.add_argument("--repo-root", default=".")
    propose.add_argument(
        "--min-support",
        type=int,
        default=2,
        help="Minimum co-occurrence count for path-prefix proposals (default: 2).",
    )
    propose.add_argument("--json", action="store_true")

    candidates = subparsers.add_parser(
        "candidates",
        help="List synthesized candidates.",
    )
    candidates.add_argument("--repo-root", default=".")
    candidates.add_argument("--json", action="store_true")

    promote = subparsers.add_parser(
        "promote",
        help="Promote one candidate into tracked .elves/landing-profile.json.",
    )
    promote.add_argument("--repo-root", default=".")
    promote.add_argument("--id", required=True, help="Candidate check id to promote.")
    promote.add_argument(
        "--severity",
        choices=("blocking", "advisory"),
        default=None,
        help="Override severity for path_touched promotions.",
    )
    promote.add_argument("--json", action="store_true")

    waive = subparsers.add_parser(
        "waive",
        help="Record a host-owned exact-HEAD waiver for one check id.",
    )
    waive.add_argument("--repo-root", default=".")
    waive.add_argument("--base", default="origin/main")
    waive.add_argument("--id", required=True, help="Check id to waive at the current HEAD.")
    waive.add_argument("--reason", required=True, help="Human reason bound into the outcome.")
    waive.add_argument("--json", action="store_true")

    clear = subparsers.add_parser(
        "clear-waiver",
        help="Clear exact-HEAD waivers (optionally filtered by id and/or head).",
    )
    clear.add_argument("--repo-root", default=".")
    clear.add_argument("--id", default=None)
    clear.add_argument("--head", default=None)
    clear.add_argument("--json", action="store_true")

    return parser.parse_args(argv)


def _print_check_human(payload: dict) -> None:
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


def _print_learn_human(payload: dict) -> None:
    print(f"Landing profile learn: {payload['status']}")
    body = payload.get("payload") or {}
    for key in (
        "observation_count",
        "candidate_count",
        "check_id",
        "remaining_candidates",
        "removed",
        "remaining",
        "path",
        "profile_path",
        "min_support",
        "head",
        "reason",
    ):
        if key in body and body[key] is not None:
            print(f"- {key}: {body[key]}")
    candidates = body.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                print(
                    f"- candidate {candidate.get('id')} "
                    f"({candidate.get('kind')}/{candidate.get('source')} "
                    f"support={candidate.get('support', 1)})"
                )
    for diagnostic in payload.get("diagnostics") or []:
        print(f"- ERROR [{diagnostic['code']}]: {diagnostic['message']}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root)

    if args.command == "check":
        result = evaluate_landing_profile(
            repo_root,
            base_ref=args.base,
            expected_head=args.head,
        )
        payload = result.to_dict()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_check_human(payload)
        return 0 if result.green else 1

    if args.command == "observe":
        result = observe_landing(
            repo_root,
            base_ref=args.base,
            note=args.note,
            propose_id=args.propose_id,
            propose_when=args.propose_when,
            propose_paths=args.propose_paths,
            propose_severity=args.propose_severity,
            propose_kind=args.propose_kind,
            propose_description=args.propose_description,
        )
    elif args.command == "propose":
        result = propose_candidates(repo_root, min_support=args.min_support)
    elif args.command == "candidates":
        result = list_candidates(repo_root)
    elif args.command == "promote":
        result = promote_candidate(
            repo_root,
            check_id=args.id,
            severity=args.severity,
        )
    elif args.command == "waive":
        result = set_exact_head_waiver(
            repo_root,
            check_id=args.id,
            reason=args.reason,
            base_ref=args.base,
        )
    elif args.command == "clear-waiver":
        result = clear_exact_head_waiver(
            repo_root,
            check_id=args.id,
            head=args.head,
        )
    else:
        return 2

    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_learn_human(payload)
    return 0 if result.green else 1


if __name__ == "__main__":
    sys.exit(main())
