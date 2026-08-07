"""Continuity resume watchdog support (v2.24).

Elves is not a scheduler: the **OS owns the timer** (launchd / systemd user
units), and Elves ships only templates, a manager CLI, and a thin stateless
watchdog that delegates every safety decision to the existing full-run
machinery. `implement full-run-prepare --resume` is the single authority —
a possibly-live run refuses (`full_run_resume_prepare_live`), a terminal or
unverifiable run refuses byte-for-byte unchanged (v2.23 semantics), and only
a genuinely resumable run proceeds. Default posture is **detect-and-report**
(`--check` dry validation + notification); actually relaunching requires the
explicit ``auto_resume`` opt-in in the config. Claim-before-act: a
non-blocking flock makes overlapping timer fires safe, and missed fires
coalesce because every fire is a stateless check.

Design adapted, with attribution and without vendored code, from
prime-agent's daemon continuity and claim-before-deliver scheduling (MIT).
The watchdog never resumes a terminal run and never holds landing, merge, or
readiness authority.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

CONTINUITY_SCHEMA = 1
DEFAULT_INTERVAL_SECONDS = 900
LOG_FILE_NAME = "watchdog-log.jsonl"
LOG_MAX_BYTES = 256 * 1024
CLAIM_FILE_NAME = "claim.lock"
CONFIG_FILE_NAME = "config.json"
REQUIRED_CONFIG_KEYS = ("repo_root", "session_id", "branch", "start_head", "packet")


class ContinuityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def continuity_dir(repo_root: Path | str) -> Path:
    return Path(repo_root) / ".elves" / "runtime" / "continuity"


def config_path(repo_root: Path | str) -> Path:
    return continuity_dir(repo_root) / CONFIG_FILE_NAME


def _slug(raw: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw) or "run"


def label_for(session_id: str) -> str:
    return f"dev.elves.continuity.{_slug(session_id)}"


def write_config(repo_root: Path | str, config: dict[str, Any]) -> Path:
    for key in REQUIRED_CONFIG_KEYS:
        if not str(config.get(key, "")).strip():
            raise ContinuityError(
                "continuity_config_invalid", f"config requires non-empty `{key}`"
            )
    payload = {
        "schema": CONTINUITY_SCHEMA,
        "interval_seconds": DEFAULT_INTERVAL_SECONDS,
        "auto_resume": False,
        "python": sys.executable,
        **config,
    }
    if not isinstance(payload["auto_resume"], bool):
        raise ContinuityError(
            "continuity_config_invalid", "auto_resume must be a boolean"
        )
    path = config_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_config(repo_root: Path | str) -> dict[str, Any]:
    path = config_path(repo_root)
    if not path.is_file():
        raise ContinuityError(
            "continuity_not_installed",
            f"{path} does not exist; run `continuity install` first",
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in REQUIRED_CONFIG_KEYS:
        if not str(data.get(key, "")).strip():
            raise ContinuityError(
                "continuity_config_invalid", f"stored config lacks `{key}`"
            )
    if not isinstance(data.get("auto_resume", False), bool):
        # Fail closed on hand-edited configs: a string like "false" is truthy
        # in Python, which would silently invert the operator's intent for the
        # single most safety-relevant knob this module owns.
        raise ContinuityError(
            "continuity_config_invalid",
            "auto_resume must be a JSON boolean (true/false), not a string",
        )
    return data


def watchdog_argv(config: dict[str, Any]) -> list[str]:
    scripts_dir = Path(__file__).resolve().parent.parent
    return [
        str(config.get("python") or sys.executable),
        str(scripts_dir / "resume_watchdog.py"),
        "--repo-root",
        str(config["repo_root"]),
    ]


def render_launchd_plist(config: dict[str, Any]) -> str:
    argv = watchdog_argv(config)
    args_xml = "\n".join(f"      <string>{arg}</string>" for arg in argv)
    log_dir = continuity_dir(config["repo_root"])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{label_for(config["session_id"])}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>StartInterval</key>
    <integer>{int(config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))}</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log_dir / "launchd-stdout.log"}</string>
    <key>StandardErrorPath</key>
    <string>{log_dir / "launchd-stderr.log"}</string>
  </dict>
</plist>
"""


def render_systemd_units(config: dict[str, Any]) -> dict[str, str]:
    argv = watchdog_argv(config)
    label = label_for(config["session_id"])
    interval = int(config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))
    service = (
        "[Unit]\n"
        f"Description=Elves continuity watchdog ({config['session_id']}); "
        "operator-owned OS timer; never resumes a terminal run\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={' '.join(argv)}\n"
    )
    timer = (
        "[Unit]\n"
        f"Description=Timer for {label}\n\n"
        "[Timer]\n"
        f"OnUnitActiveSec={interval}s\n"
        f"OnBootSec={interval}s\n"
        "Persistent=false\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return {"service": service, "timer": timer}


def install(repo_root: Path | str, config: dict[str, Any]) -> dict[str, Any]:
    """Write config + timer templates. Never activates anything.

    Activation stays operator-owned: the returned instructions name the exact
    copy + `launchctl` / `systemctl --user` commands for the operator to run.
    """

    path = write_config(repo_root, config)
    stored = read_config(repo_root)
    templates_dir = continuity_dir(repo_root) / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    label = label_for(stored["session_id"])
    plist_path = templates_dir / f"{label}.plist"
    plist_path.write_text(render_launchd_plist(stored), encoding="utf-8")
    units = render_systemd_units(stored)
    service_path = templates_dir / f"{label}.service"
    timer_path = templates_dir / f"{label}.timer"
    service_path.write_text(units["service"], encoding="utf-8")
    timer_path.write_text(units["timer"], encoding="utf-8")
    return {
        "installed": True,
        "config": str(path),
        "templates": [str(plist_path), str(service_path), str(timer_path)],
        "activation": {
            "darwin": [
                f"cp {plist_path} ~/Library/LaunchAgents/",
                f"launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/{label}.plist",
            ],
            "linux": [
                f"cp {service_path} {timer_path} ~/.config/systemd/user/",
                f"systemctl --user enable --now {label}.timer",
            ],
            "note": (
                "activation is operator-owned; Elves never runs launchctl or "
                "systemctl and defaults to detect-and-report (auto_resume off)"
            ),
        },
    }


def status(repo_root: Path | str) -> dict[str, Any]:
    directory = continuity_dir(repo_root)
    cfg = config_path(repo_root)
    log_path = directory / LOG_FILE_NAME
    last = None
    if log_path.is_file():
        lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            try:
                last = json.loads(lines[-1])
            except ValueError:
                last = {"malformed_tail": True}
    templates_dir = directory / "templates"
    return {
        "installed": cfg.is_file(),
        "config": str(cfg) if cfg.is_file() else None,
        "templates": sorted(str(p) for p in templates_dir.glob("*")) if templates_dir.is_dir() else [],
        "last_fire": last,
        "activation_state": "operator-owned (not tracked by Elves)",
    }


def remove(repo_root: Path | str) -> dict[str, Any]:
    directory = continuity_dir(repo_root)
    removed: list[str] = []
    cfg = config_path(repo_root)
    if cfg.is_file():
        cfg.unlink()
        removed.append(str(cfg))
    templates_dir = directory / "templates"
    if templates_dir.is_dir():
        for item in sorted(templates_dir.glob("*")):
            item.unlink()
            removed.append(str(item))
        templates_dir.rmdir()
    return {"removed": removed, "log_kept": str(directory / LOG_FILE_NAME)}


def append_log(repo_root: Path | str, record: dict[str, Any]) -> None:
    directory = continuity_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOG_FILE_NAME
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if path.stat().st_size <= LOG_MAX_BYTES:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def claim(repo_root: Path | str) -> Iterator[bool]:
    """Non-blocking single-flight claim; yields False when another fire holds it."""

    directory = continuity_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    handle = open(directory / CLAIM_FILE_NAME, "w", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
