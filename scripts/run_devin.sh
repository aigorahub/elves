#!/bin/bash
# Bounded remote developer task through the official Devin v1 sessions API.
set -euo pipefail

TASK_DESCRIPTION="$*"
if [ -z "$TASK_DESCRIPTION" ]; then
  echo "Usage: run_devin.sh <instructions>" >&2
  exit 2
fi
if [ -z "${DEVIN_API_KEY:-}" ]; then
  echo "Error: DEVIN_API_KEY is unset." >&2
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "run_devin.sh requires Python >= 3.10 (repo floor); found $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" >&2
  exit 2
fi
exec python3 - "$TASK_DESCRIPTION" <<'PY'
import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

task = sys.argv[1]
base = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai/v1").rstrip("/")
try:
    max_wait = int(os.environ.get("DEVIN_MAX_WAIT_SECONDS", "1800"))
    interval = float(os.environ.get("DEVIN_POLL_INTERVAL_SECONDS", "15"))
except ValueError as exc:
    raise SystemExit("Error: Devin wait settings must be numeric.") from exc
if max_wait < 0 or not math.isfinite(interval) or interval < 0.1:
    raise SystemExit(
        "Error: Devin max wait must be non-negative and poll interval must be finite and "
        "at least 0.1 seconds."
    )

def git_value(*args):
    result = subprocess.run(
        ["git", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def provider_safe_remote(value):
    """Return host/path context without forwarding URL credentials or local paths."""
    remote = str(value or "").strip()
    if not remote:
        return ""
    try:
        if "://" in remote:
            parsed = urllib.parse.urlsplit(remote)
            host = parsed.hostname or ""
            if not host:
                return ""
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            if parsed.port is not None:
                host += f":{parsed.port}"
            return host + (parsed.path or "")
        if "@" in remote:
            host_path = remote.rsplit("@", 1)[1]
            return host_path if ":" in host_path else ""
    except ValueError:
        return ""
    return ""


branch = git_value("branch", "--show-current")
origin = provider_safe_remote(git_value("remote", "get-url", "origin"))
context = []
if origin:
    context.append(f"repository: {origin}")
if branch:
    context.append(f"branch: {branch}")
prompt = task
if context:
    prompt += "\n\nWork context supplied by Elves: " + "; ".join(context) + "."

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class hard_wall_timeout:
    """Interrupt connect, send, and slow-drip body reads at one wall deadline."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.previous_handler = None
        self.previous_timer = (0.0, 0.0)
        self.started = 0.0

    def __enter__(self):
        if not hasattr(signal, "setitimer") or not hasattr(signal, "SIGALRM"):
            raise SystemExit(
                "Error: this platform cannot enforce the required Devin wall-clock timeout."
            )
        if self.seconds <= 0:
            raise TimeoutError("Devin API request timed out")
        self.previous_handler = signal.getsignal(signal.SIGALRM)
        self.started = time.monotonic()

        def expired(_signum, _frame):
            raise TimeoutError("Devin API request timed out")

        signal.signal(signal.SIGALRM, expired)
        self.previous_timer = signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return self

    def __exit__(self, _type, _value, _traceback):
        signal.setitimer(signal.ITIMER_REAL, 0)
        assert self.previous_handler is not None
        signal.signal(signal.SIGALRM, self.previous_handler)
        previous_delay, previous_interval = self.previous_timer
        if previous_delay > 0:
            restored_delay = previous_delay - (time.monotonic() - self.started)
            if restored_delay > 0:
                signal.setitimer(signal.ITIMER_REAL, restored_delay, previous_interval)
        return False


def request(method, path, payload=None, *, timeout=60.0):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {os.environ['DEVIN_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    call_deadline = time.monotonic() + timeout
    try:
        with hard_wall_timeout(timeout):
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body_bytes = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body_bytes) > MAX_RESPONSE_BYTES:
                    raise SystemExit(
                        f"Devin API response exceeds {MAX_RESPONSE_BYTES} bytes."
                    )
                return json.loads(body_bytes.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        remaining = call_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Devin API request timed out") from exc
        with hard_wall_timeout(remaining):
            body = exc.read(4096).decode("utf-8", errors="replace")
        raise SystemExit(f"Devin API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise TimeoutError("Devin API request timed out") from exc
        raise SystemExit(f"Devin API connection error: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise TimeoutError("Devin API request timed out") from exc

deadline = None if max_wait == 0 else time.monotonic() + max_wait
create_timeout = 60.0
if deadline is not None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        print(f"Devin session creation timed out after {max_wait}s.", file=sys.stderr)
        raise SystemExit(124)
    create_timeout = min(60.0, remaining)
try:
    created = request(
        "POST",
        "/sessions",
        {
            "prompt": prompt,
            "idempotent": False,
            "unlisted": False,
            "secret_ids": [],
            "knowledge_ids": [],
        },
        timeout=create_timeout,
    )
except TimeoutError:
    print(f"Devin session creation timed out after {max_wait}s.", file=sys.stderr)
    raise SystemExit(124)
session_id = created.get("session_id")
session_url = created.get("url") or ""
if not session_id:
    raise SystemExit("Devin session creation returned no session_id: " + json.dumps(created))
print(f"Devin session initiated: {session_id}", file=sys.stderr, flush=True)
if session_url:
    print(f"Session URL: {session_url}", file=sys.stderr, flush=True)
if max_wait == 0:
    print(json.dumps({"session_id": session_id, "url": session_url}))
    raise SystemExit(0)

assert deadline is not None
while time.monotonic() < deadline:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        break
    try:
        detail = request(
            "GET",
            "/sessions/" + urllib.parse.quote(session_id, safe=""),
            timeout=min(60.0, remaining),
        )
    except TimeoutError:
        break
    status = str(detail.get("status_enum") or detail.get("status") or "unknown").lower()
    if status in {"finished", "blocked", "expired", "error", "failed"}:
        output = detail.get("structured_output")
        if output is not None:
            print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            messages = detail.get("messages") or []
            if messages:
                print(json.dumps(messages[-1], indent=2, ensure_ascii=False))
        pull_request = detail.get("pull_request") or {}
        if pull_request.get("url"):
            print("Pull request: " + str(pull_request["url"]), file=sys.stderr)
        print(f"Devin session status: {status}", file=sys.stderr)
        raise SystemExit(0 if status == "finished" else 3 if status == "blocked" else 1)
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(min(interval, remaining))

print(f"Devin session is still running after {max_wait}s: {session_id} {session_url}".rstrip(), file=sys.stderr)
raise SystemExit(124)
PY
