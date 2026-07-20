#!/bin/bash
# Bounded autonomous web research through the Manus v2 task API.
set -euo pipefail

RESEARCH_TOPIC="$*"
if [ -z "$RESEARCH_TOPIC" ]; then
  echo "Usage: run_manus.sh <research topic>" >&2
  exit 2
fi
if [ -z "${MANUS_API_KEY:-}" ]; then
  echo "Error: MANUS_API_KEY is unset." >&2
  exit 1
fi

exec python3 - "$RESEARCH_TOPIC" <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

topic = sys.argv[1]
base = os.environ.get("MANUS_API_BASE", "https://api.manus.ai/v2").rstrip("/")
profile = os.environ.get("MANUS_AGENT_PROFILE", "manus-1.6-max")
if profile not in {"manus-1.6", "manus-1.6-lite", "manus-1.6-max"}:
    raise SystemExit("Error: MANUS_AGENT_PROFILE must be manus-1.6, manus-1.6-lite, or manus-1.6-max.")

try:
    max_wait = int(os.environ.get("MANUS_MAX_WAIT_SECONDS", "1800"))
    interval = float(os.environ.get("MANUS_POLL_INTERVAL_SECONDS", "15"))
except ValueError as exc:
    raise SystemExit("Error: Manus wait settings must be numeric.") from exc
if max_wait < 0 or interval < 0:
    raise SystemExit("Error: Manus wait settings must be non-negative.")

def request(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "x-manus-api-key": os.environ["MANUS_API_KEY"],
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Manus API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Manus API connection error: {exc.reason}") from exc

created = request(
    "POST",
    "/task.create",
    {
        "message": {"content": topic},
        "agent_profile": profile,
        "hide_in_task_list": False,
        "share_visibility": "private",
    },
)
if created.get("ok") is False:
    raise SystemExit("Manus task creation failed: " + json.dumps(created, ensure_ascii=False))
created_data = created.get("data") or created
task_id = created_data.get("task_id")
task_url = created_data.get("task_url") or ""
if not task_id:
    raise SystemExit("Manus task creation returned no task_id: " + json.dumps(created, ensure_ascii=False))
print(f"Manus task initiated: {task_id}", file=sys.stderr, flush=True)
if task_url:
    print(f"Task URL: {task_url}", file=sys.stderr, flush=True)
if max_wait == 0:
    print(json.dumps({"task_id": task_id, "task_url": task_url}, ensure_ascii=False))
    raise SystemExit(0)

deadline = time.monotonic() + max_wait
while time.monotonic() < deadline:
    detail = request("GET", "/task.detail?" + urllib.parse.urlencode({"task_id": task_id}))
    task = detail.get("task") or detail.get("data") or detail
    status = str(task.get("status", "unknown"))
    if status in {"stopped", "waiting", "error"}:
        messages = request(
            "GET",
            "/task.listMessages?" + urllib.parse.urlencode(
                {"task_id": task_id, "order": "asc", "limit": 200, "verbose": "true"}
            ),
        )
        texts = []
        for message in messages.get("messages", messages.get("data", [])) or []:
            assistant = message.get("assistant_message") or {}
            if assistant.get("content"):
                texts.append(str(assistant["content"]))
        if texts:
            print(texts[-1])
        print(f"Manus task status: {status}", file=sys.stderr)
        raise SystemExit(0 if status == "stopped" else 3 if status == "waiting" else 1)
    time.sleep(interval)

print(f"Manus task is still running after {max_wait}s: {task_id} {task_url}".rstrip(), file=sys.stderr)
raise SystemExit(124)
PY
