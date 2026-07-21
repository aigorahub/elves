#!/bin/bash
# Focused, read-only file review through Sakana's streamed Fugu Ultra API.
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "Usage: run_fugu.sh <file>" >&2
  exit 2
fi
if [ -z "${SAKANA_API_KEY:-}" ]; then
  echo "Error: SAKANA_API_KEY is unset." >&2
  exit 1
fi
if [ ! -f "$1" ]; then
  echo "Error: review target is not a regular file: $1" >&2
  exit 2
fi

TARGET_DIR=$(cd "$(dirname "$1")" && pwd -P)
TARGET_FILE="$TARGET_DIR/$(basename "$1")"

exec python3 - "$TARGET_FILE" <<'PY'
import json
import math
import os
from pathlib import Path
import signal
import socket
import sys
import time
import urllib.error
import urllib.request


target = Path(sys.argv[1])
base = (
    os.environ.get("SAKANA_API_BASE")
    or os.environ.get("SAKANA_BASE_URL")
    or "https://api.sakana.ai/v1"
).rstrip("/")
effort = os.environ.get("SAKANA_FUGU_REASONING_EFFORT", "max").strip().lower()
if effort not in {"high", "xhigh", "max"}:
    raise SystemExit("Error: SAKANA_FUGU_REASONING_EFFORT must be high, xhigh, or max.")

try:
    max_output_tokens = int(os.environ.get("SAKANA_FUGU_MAX_OUTPUT_TOKENS", "16384"))
    max_input_bytes = int(os.environ.get("SAKANA_FUGU_MAX_INPUT_BYTES", "262144"))
    max_wait = float(os.environ.get("SAKANA_FUGU_MAX_WAIT_SECONDS", "1800"))
    idle_timeout = float(os.environ.get("SAKANA_FUGU_IDLE_TIMEOUT_SECONDS", "600"))
    retries = int(os.environ.get("SAKANA_FUGU_RETRIES", "2"))
except ValueError as exc:
    raise SystemExit("Error: Sakana Fugu limits must be numeric.") from exc
if max_output_tokens < 2048:
    raise SystemExit("Error: SAKANA_FUGU_MAX_OUTPUT_TOKENS must be at least 2048 for Fugu Ultra.")
if (
    max_input_bytes <= 0
    or not math.isfinite(max_wait)
    or not math.isfinite(idle_timeout)
    or max_wait <= 0
    or idle_timeout <= 0
):
    raise SystemExit("Error: Sakana Fugu input and timeout limits must be finite and positive.")
if retries < 0:
    raise SystemExit("Error: SAKANA_FUGU_RETRIES must be zero or greater.")

try:
    raw_content = target.read_bytes()
except OSError as exc:
    raise SystemExit(f"Error: could not read review target: {exc}") from exc
if len(raw_content) > max_input_bytes:
    raise SystemExit(
        f"Error: review target is {len(raw_content)} bytes; narrow it below {max_input_bytes} bytes."
    )
try:
    content = raw_content.decode("utf-8")
except UnicodeDecodeError as exc:
    raise SystemExit("Error: Fugu review target must be UTF-8 text.") from exc

prompt = f"""Perform a focused, independent review of the exact file below.

This is a read-only audit. Report only actionable findings, ordered P0 through P3. For every
finding, cite the target file and exact line(s), explain a concrete failure scenario, and state the
smallest safe repair. Do not restate the file. If there are no actionable findings, say exactly
"No actionable findings" and then list only residual verification risks.

Target: {target}

<review-target>
{content}
</review-target>
"""
body = {
    "model": "fugu-ultra",
    "input": prompt,
    "reasoning": {"effort": effort},
    "max_output_tokens": max_output_tokens,
    "temperature": 0,
    "stream": True,
}
headers = {
    "Authorization": f"Bearer {os.environ['SAKANA_API_KEY']}",
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
}
transient_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
deadline = time.monotonic() + max_wait
raw_output = os.environ.get("SAKANA_FUGU_RAW_OUTPUT", "").strip()

if not all(hasattr(signal, name) for name in ("SIGALRM", "ITIMER_REAL", "setitimer")):
    raise SystemExit("Error: this platform cannot enforce the Sakana Fugu wall-clock limit.")


def wall_clock_timeout(_signum, _frame):
    raise TimeoutError(f"Sakana Fugu review exceeded {max_wait:g}s")


signal.signal(signal.SIGALRM, wall_clock_timeout)


def persist_raw(events):
    if not raw_output:
        return
    try:
        raw_path = Path(raw_output).expanduser()
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Warning: could not write Sakana Fugu raw output: {exc}", file=sys.stderr)


class StreamEventError(RuntimeError):
    def __init__(self, message, events):
        super().__init__(message)
        self.events = list(events)


def extract_text(event):
    if not isinstance(event, dict):
        return ""
    event_type = str(event.get("type") or "")
    if isinstance(event.get("delta"), str) and (
        not event_type or event_type == "response.output_text.delta"
    ):
        return event["delta"]
    if isinstance(event.get("output_text"), str):
        return event["output_text"]
    return ""


def stream_once():
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(f"Sakana Fugu review exceeded {max_wait:g}s")
    request = urllib.request.Request(
        base + "/responses",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    chunks = []
    raw_events = []
    data_lines = []

    def consume_event():
        if not data_lines:
            return False
        encoded = "\n".join(data_lines).strip()
        data_lines.clear()
        if not encoded:
            return False
        if encoded == "[DONE]":
            return True
        try:
            event = json.loads(encoded)
        except json.JSONDecodeError:
            raw_events.append(encoded)
            return False
        raw_events.append(event)
        if str(event.get("type") or "") in {"error", "response.error"}:
            detail = json.dumps(event, ensure_ascii=False)[:2048]
            raise StreamEventError(
                f"Sakana Fugu stream returned an error event: {detail}", raw_events
            )
        text = extract_text(event)
        if text:
            chunks.append(text)
        return False

    timeout = min(idle_timeout, max(1.0, remaining))
    signal.setitimer(signal.ITIMER_REAL, max(0.001, remaining))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Sakana Fugu review exceeded {max_wait:g}s")
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    if consume_event():
                        break
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            if data_lines:
                consume_event()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return "".join(chunks).strip(), raw_events


last_error = None
for attempt in range(retries + 1):
    try:
        text, events = stream_once()
        if not text:
            persist_raw(events)
            raise RuntimeError(
                "Sakana Fugu Ultra returned no visible review text; retry the compact prompt at high effort."
            )
        print(text)
        persist_raw(events)
        raise SystemExit(0)
    except urllib.error.HTTPError as exc:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = "<error body not read: total wait expired>"
        else:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, remaining))
            try:
                detail = exc.read(4096).decode("utf-8", errors="replace")
            except (OSError, TimeoutError, socket.timeout) as body_exc:
                detail = f"<error body unavailable: {body_exc}>"
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
        last_error = RuntimeError(f"Sakana API error {exc.code}: {detail}")
        persist_raw([{"type": "http_error", "status": exc.code, "body": detail}])
        transient = exc.code in transient_statuses
    except (urllib.error.URLError, TimeoutError, socket.timeout, RuntimeError) as exc:
        last_error = exc
        if isinstance(exc, StreamEventError):
            persist_raw(exc.events)
        transient = isinstance(exc, (urllib.error.URLError, TimeoutError, socket.timeout))
    if not transient or attempt >= retries or time.monotonic() >= deadline:
        break
    delay = min(30.0, 2.0 * (2**attempt), max(0.0, deadline - time.monotonic()))
    print(
        f"Sakana Fugu transient failure; retrying in {delay:g}s ({attempt + 1}/{retries}).",
        file=sys.stderr,
    )
    time.sleep(delay)

raise SystemExit(f"Error: Sakana Fugu review failed: {last_error}")
PY
