#!/usr/bin/env python3
"""Elves continuity resume watchdog (v2.24).

Fired by an operator-owned OS timer (launchd / systemd user unit). Stateless
per fire: acquire the single-flight claim, then let the existing full-run
machinery decide everything —

    implement full-run-prepare --resume --check   (detect-and-report default)
    implement full-run-prepare --resume            (only with auto_resume)
    implement full-run-launch  --resume            (only after prepare passed)

A possibly-live run refuses (`full_run_resume_prepare_live` — quiet tick).
A terminal or unverifiable run refuses byte-for-byte unchanged (v2.23
`full_run_resume_prepare_terminal` / `full_run_resume_event_log_unverifiable`)
and the watchdog only logs it. The watchdog never resumes a terminal run,
holds no landing or merge authority, and grants no credentials.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cobbler_runtime import continuity  # noqa: E402

SUBPROCESS_TIMEOUT_SECONDS = 600
QUIET_CODES = frozenset({"full_run_resume_prepare_live"})
TERMINAL_CODES = frozenset(
    {"full_run_resume_prepare_terminal", "full_run_resume_event_log_unverifiable"}
)


def _run_hub(config: dict, verb_args: list[str]) -> subprocess.CompletedProcess[bytes]:
    argv = [
        str(config.get("python") or sys.executable),
        str(SCRIPT_DIR / "cobbler_agents.py"),
        "implement",
        *verb_args,
        "--repo-root",
        str(config["repo_root"]),
        "--json",
    ]
    return subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )


def _classify(completed: subprocess.CompletedProcess[bytes]) -> tuple[str, str]:
    text = (completed.stdout + b"\n" + completed.stderr).decode("utf-8", "replace")
    for code in TERMINAL_CODES:
        if code in text:
            return "terminal_refused", code
    for code in QUIET_CODES:
        if code in text:
            return "live_quiet", code
    if completed.returncode == 0:
        return "resumable", ""
    return "refused_other", text.strip()[-400:]


def run_once(repo_root: Path, *, now: float | None = None) -> dict:
    config = continuity.read_config(repo_root)
    outcome: dict = {"ts": now if now is not None else time.time()}
    with continuity.claim(repo_root) as held:
        if not held:
            return {**outcome, "outcome": "claim_busy"}
        prepare_args = [
            "full-run-prepare",
            "--session-id",
            str(config["session_id"]),
            "--branch",
            str(config["branch"]),
            "--start-head",
            str(config["start_head"]),
            "--packet",
            str(config["packet"]),
            "--resume",
        ]
        if config.get("session"):
            prepare_args.extend(["--session", str(config["session"])])
        # Belt to read_config's type validation: only the literal boolean True
        # ever relaunches; any other value stays detect-and-report.
        auto_resume = config.get("auto_resume") is True
        if not auto_resume:
            prepare_args.append("--check")
        prepared = _run_hub(config, prepare_args)
        state, detail = _classify(prepared)
        outcome.update({"outcome": state, "detail": detail, "auto_resume": auto_resume})
        if state == "resumable" and auto_resume:
            launched = _run_hub(
                config,
                ["full-run-launch", "--session-id", str(config["session_id"]), "--resume"],
            )
            outcome["launch_exit"] = launched.returncode
            outcome["outcome"] = (
                "resumed" if launched.returncode == 0 else "launch_failed"
            )
        elif state == "resumable":
            outcome["outcome"] = "resumable_report_only"
    continuity.append_log(repo_root, outcome)
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args(argv)
    try:
        outcome = run_once(Path(args.repo_root))
    except continuity.ContinuityError as exc:
        print(json.dumps({"outcome": "error", "code": exc.code, "error": exc.message}))
        return 1
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
