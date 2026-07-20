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

exec python3 - "$TASK_DESCRIPTION" <<'PY'
import json
import os
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
if max_wait < 0 or interval < 0:
    raise SystemExit("Error: Devin wait settings must be non-negative.")

def git_value(*args):
    result = subprocess.run(
        ["git", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""

branch = git_value("branch", "--show-current")
origin = git_value("remote", "get-url", "origin")
context = []
if origin:
    context.append(f"repository: {origin}")
if branch:
    context.append(f"branch: {branch}")
prompt = task
if context:
    prompt += "\n\nWork context supplied by Elves: " + "; ".join(context) + "."

def request(method, path, payload=None):
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
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Devin API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Devin API connection error: {exc.reason}") from exc

created = request("POST", "/sessions", {"prompt": prompt, "idempotent": False, "unlisted": False})
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

deadline = time.monotonic() + max_wait
while time.monotonic() < deadline:
    detail = request("GET", "/sessions/" + urllib.parse.quote(session_id, safe=""))
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
    time.sleep(interval)

print(f"Devin session is still running after {max_wait}s: {session_id} {session_url}".rstrip(), file=sys.stderr)
raise SystemExit(124)
PY
