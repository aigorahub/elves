#!/usr/bin/env python3
"""Cobbler-managed Manus research orchestration.

The ordinary path creates one private Manus task. Wide and fan-out modes add a
durable, ignored manifest so Cobbler can reconcile exact item coverage and
resume without creating duplicate paid tasks.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "manus-cobbler-v1"
PROFILES = {"manus-1.6", "manus-1.6-lite", "manus-1.6-max"}
TERMINAL_STATUSES = {"stopped", "waiting", "error"}
TRANSIENT_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_ITEMS = 250
MAX_INPUT_BYTES = 1_048_576
MAX_PROMPT_BYTES = 262_144
MAX_MANIFEST_BYTES = 16_777_216
MAX_API_RESPONSE_BYTES = 16_777_216
MAX_REPORT_BYTES = 4_000
MAX_FAILED_TASK_ATTEMPTS = MAX_ITEMS * 2 + 10
MIN_INTERVAL_SECONDS = 0.1
DEFAULT_ATTACHMENT_LIMIT = 64 * 1024 * 1024
PROVIDER_ATTACHMENT_LIMIT = 512 * 1024 * 1024
SECRET_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".git-credentials",
    ".netrc",
    ".pgpass",
    "credentials",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "kubeconfig",
}
SECRET_FILE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
SECRET_PATH_PARTS = {".aws", ".docker", ".git", ".gnupg", ".kube", ".ssh"}


class ManusError(RuntimeError):
    """A bounded, user-facing Manus orchestration error."""


class ManusTimeout(ManusError):
    """The local wait budget expired while remote work may still be live."""


class ManusAuthError(ManusError):
    """The explicit provider shortcut has no usable API credential."""


@contextmanager
def _hard_wall_timeout(seconds: float):
    """Interrupt connect, send, and slow-drip body reads at one wall deadline."""
    if not hasattr(signal, "setitimer") or not hasattr(signal, "SIGALRM"):
        raise ManusError("This platform cannot enforce the required Manus wall-clock timeout.")
    if seconds <= 0:
        raise ManusTimeout("Manus orchestration exceeded the configured local wait.")
    previous_handler = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()

    def expired(_signum, _frame):
        raise ManusTimeout("Manus API request exceeded its hard wall-clock timeout.")

    signal.signal(signal.SIGALRM, expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        previous_delay, previous_interval = previous_timer
        if previous_delay > 0:
            restored_delay = previous_delay - (time.monotonic() - started)
            if restored_delay > 0:
                signal.setitimer(signal.ITIMER_REAL, restored_delay, previous_interval)


def _finite_number(name: str, default: str, *, minimum: float = 0) -> float:
    raw = os.environ.get(name, default)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ManusError(f"{name} must be numeric.") from exc
    if not math.isfinite(value) or value < minimum:
        raise ManusError(f"{name} must be finite and at least {minimum:g}.")
    return value


def _bounded_int(name: str, default: str, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ManusError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise ManusError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _bounded_sleep(seconds: float, deadline: float | None, message: str) -> None:
    if seconds <= 0:
        return
    if deadline is None:
        time.sleep(seconds)
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ManusTimeout(message)
    time.sleep(min(seconds, remaining))
    if time.monotonic() >= deadline:
        raise ManusTimeout(message)


def _bounded_text(value: Any, max_bytes: int = MAX_REPORT_BYTES) -> str:
    encoded = str(value or "").encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return encoded.decode("utf-8")
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _read_text(path: Path, label: str, limit: int = MAX_INPUT_BYTES) -> str:
    if path.is_symlink() or not path.is_file():
        raise ManusError(f"{label} must be a regular non-symlink file: {path}")
    if path.stat().st_size > limit:
        raise ManusError(f"{label} exceeds the {limit}-byte limit: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ManusError(f"Could not read {label}: {path}: {exc}") from exc


def _repo_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return Path.cwd().resolve()
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return Path.cwd().resolve()


def _default_manifest(mode: str) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return _repo_root() / ".elves" / "runtime" / "manus" / f"{stamp}-{os.getpid()}-{mode}.json"


def _runtime_manifest_path(
    raw: str | None,
    *,
    mode: str | None = None,
    must_exist: bool,
) -> Path:
    """Confine durable manifests to the ignored Elves runtime tree.

    A new orchestration must never repurpose an existing user file, and resume
    must not turn a valid-looking JSON document elsewhere in the repository
    into a mutable provider state record.
    """
    repo_root = _repo_root()
    runtime_root = repo_root / ".elves" / "runtime" / "manus"
    supplied = (
        Path(raw).expanduser()
        if raw is not None
        else _default_manifest(mode or "research")
    )
    raw_candidate = Path(os.path.abspath(os.fspath(supplied)))
    lexical_repo: Path | None = None
    # Keep the outermost match: a path inside `repo/alias -> repo` must remain
    # relative to the real repo root so `alias` is descriptor-walked/rejected.
    # This still accepts an OS-level spelling alias such as /var -> /private/var.
    for ancestor in raw_candidate.parents:
        try:
            if ancestor.resolve(strict=True) == repo_root:
                lexical_repo = ancestor
        except OSError:
            continue
    if lexical_repo is None:
        raise ManusError(
            "Manus manifests must live under "
            f"{runtime_root}; use the printed --resume path for continuation."
        )
    relative_manifest = raw_candidate.relative_to(lexical_repo)
    if relative_manifest.parts[:3] != (".elves", "runtime", "manus"):
        raise ManusError(
            "Manus manifests must live under "
            f"{runtime_root} and may not enter it through an in-repository symlink or alias; "
            "use the printed --resume path for continuation."
        )
    if len(relative_manifest.parts) < 4:
        raise ManusError("Manus manifest path must name a file inside the runtime directory.")
    candidate = repo_root.joinpath(*relative_manifest.parts)
    relative_parent = relative_manifest.parent

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current_fd = -1
    leaf_fd = -1
    try:
        current_fd = os.open(repo_root, directory_flags)
        for part in relative_parent.parts:
            if not must_exist:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd

        if must_exist:
            leaf_fd = os.open(
                candidate.name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current_fd,
            )
            if not stat.S_ISREG(os.fstat(leaf_fd).st_mode):
                raise ManusError(
                    f"Resume manifest must be a regular non-symlink file: {candidate}"
                )
        else:
            leaf_fd = os.open(
                candidate.name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=current_fd,
            )
    except ManusError:
        raise
    except FileExistsError as exc:
        raise ManusError(
            f"Refusing to overwrite an existing Manus manifest: {candidate}. "
            "Use --resume to continue it."
        ) from exc
    except OSError as exc:
        action = "read" if must_exist else "reserve"
        raise ManusError(
            f"Could not {action} Manus manifest without traversing a symlink or unsafe parent: "
            f"{candidate}"
        ) from exc
    finally:
        if leaf_fd >= 0:
            os.close(leaf_fd)
        if current_fd >= 0:
            os.close(current_fd)
    return candidate


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = int(time.time())
    encoded = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ManusError(f"Manus manifest exceeds the {MAX_MANIFEST_BYTES}-byte safety limit.")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _normalize_items(data: Any, label: str) -> list[dict[str, str]]:
    if isinstance(data, dict):
        data = data.get("items")
    if not isinstance(data, list) or not 1 <= len(data) <= MAX_ITEMS:
        raise ManusError(f"{label} must contain a JSON list of 1 to {MAX_ITEMS} items.")
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, value in enumerate(data):
        if isinstance(value, str):
            item_id, instructions = value.strip(), ""
        elif isinstance(value, dict):
            raw_id = value.get("id")
            raw_instructions = value.get("instructions", "")
            if not isinstance(raw_id, str) or not isinstance(raw_instructions, str):
                raise ManusError(f"Item {index + 1} id and instructions must be strings.")
            item_id = raw_id.strip()
            instructions = raw_instructions.strip()
        else:
            raise ManusError(
                f"Item {index + 1} must be a string or an object with id/instructions."
            )
        if not item_id or len(item_id) > 256 or any(ord(char) < 32 for char in item_id):
            raise ManusError(f"Item {index + 1} has an invalid id.")
        if item_id in seen:
            raise ManusError(f"Duplicate item id in roster: {item_id}")
        if len(instructions) > 20_000:
            raise ManusError(f"Instructions for item {item_id} exceed 20,000 characters.")
        seen.add(item_id)
        items.append({"id": item_id, "instructions": instructions})
    return items


def _load_items(path: Path) -> list[dict[str, str]]:
    raw = _read_text(path, "items file")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManusError(f"Items file must be valid JSON: {exc}") from exc
    return _normalize_items(data, "Items file")


def _validate_task_record(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ManusError(f"{label} must be an object or null.")
    task_id = value.get("id")
    if (
        not isinstance(task_id, str)
        or not task_id
        or len(task_id) > 512
        or any(ord(char) < 32 for char in task_id)
    ):
        raise ManusError(f"{label} has an invalid task id.")
    status = value.get("status")
    if not isinstance(status, str) or not status or len(status) > 64:
        raise ManusError(f"{label} has an invalid status.")


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ManusError(f"Resume manifest must be a regular non-symlink file: {path}")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ManusError("Resume manifest exceeds the bounded read limit.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManusError(f"Could not read resume manifest: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ManusError(f"Resume manifest must use schema_version {SCHEMA_VERSION}.")
    mode = data.get("mode")
    if mode not in {"wide", "fanout"}:
        raise ManusError("Resume manifest has an unsupported orchestration mode.")
    if data.get("profile") not in PROFILES:
        raise ManusError("Resume manifest has an unsupported Manus profile.")
    prompt = data.get("prompt")
    if (
        not isinstance(prompt, str)
        or not prompt
        or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES
    ):
        raise ManusError("Resume manifest has an invalid or oversized prompt.")
    data["items"] = _normalize_items(data.get("items"), "Resume manifest items")
    expected_ids = {item["id"] for item in data["items"]}
    attachments = data.get("attachments")
    if not isinstance(attachments, list):
        raise ManusError("Resume manifest attachments must be a list.")
    for index, attachment in enumerate(attachments):
        file_id = attachment.get("file_id") if isinstance(attachment, dict) else None
        if not isinstance(file_id, str) or not file_id or len(file_id) > 512:
            raise ManusError(f"Resume manifest attachment {index + 1} has an invalid file id.")
    if not isinstance(data.get("fallback_enabled"), bool) or not isinstance(
        data.get("fallback_used"), bool
    ):
        raise ManusError("Resume manifest fallback flags must be booleans.")
    _validate_task_record(data.get("main_task"), "Resume manifest main task")
    fanout = data.get("fanout_tasks")
    if not isinstance(fanout, dict) or any(item_id not in expected_ids for item_id in fanout):
        raise ManusError("Resume manifest fan-out task map contains an invalid item id.")
    for item_id, task in fanout.items():
        if task is None:
            raise ManusError(f"Resume manifest fan-out task {item_id} cannot be null.")
        _validate_task_record(task, f"Resume manifest fan-out task {item_id}")
    _validate_task_record(data.get("synthesis_task"), "Resume manifest synthesis task")
    failures = data.setdefault("failed_task_attempts", [])
    if not isinstance(failures, list) or len(failures) > MAX_FAILED_TASK_ATTEMPTS:
        raise ManusError("Resume manifest has invalid failed task attempt history.")
    for index, failure in enumerate(failures):
        if not isinstance(failure, dict) or failure.get("role") not in {
            "main",
            "fanout",
            "repair",
            "synthesis",
        }:
            raise ManusError(f"Resume manifest failed task attempt {index + 1} is invalid.")
        _validate_task_record(failure, f"Resume manifest failed task attempt {index + 1}")
        item_id = failure.get("item_id")
        if item_id is not None and item_id not in expected_ids:
            raise ManusError(
                f"Resume manifest failed task attempt {index + 1} has an invalid item id."
            )
    return data


def _validate_attachment(path_text: str, byte_limit: int) -> Path:
    candidate = Path(path_text).expanduser()
    if candidate.is_symlink():
        raise ManusError(f"Refusing to upload a symlink: {candidate}")
    path = candidate.resolve(strict=True)
    if not path.is_file():
        raise ManusError(f"Attachment is not a regular file: {path}")
    lowered_parts = {part.lower() for part in path.parts}
    if (
        path.name.lower() in SECRET_FILE_NAMES
        or path.name.lower().startswith(".env")
        or path.suffix.lower() in SECRET_FILE_SUFFIXES
        or lowered_parts.intersection(SECRET_PATH_PARTS)
    ):
        raise ManusError(f"Refusing to upload a credential-bearing path: {path}")
    if path.stat().st_size > byte_limit:
        raise ManusError(f"Attachment exceeds the {byte_limit}-byte configured limit: {path}")
    return path


def _archive_failed_task(
    manifest: dict[str, Any], role: str, task: dict[str, Any], *, item_id: str | None = None
) -> None:
    """Preserve bounded audit context before a known-failed task is replaced."""
    archived: dict[str, Any] = {
        "role": role,
        "id": str(task.get("id") or "")[:512],
        "status": str(task.get("status") or "error")[:64],
    }
    if item_id is not None:
        archived["item_id"] = item_id
    if task.get("url"):
        archived["url"] = _bounded_text(task["url"], 2_048)
    if task.get("assistant_text"):
        archived["assistant_text"] = _bounded_text(task["assistant_text"])
    if task.get("structured") is not None:
        archived["structured_excerpt"] = _bounded_text(
            json.dumps(task["structured"], ensure_ascii=False)
        )
    failures = manifest.setdefault("failed_task_attempts", [])
    failures.append(archived)
    if len(failures) > MAX_FAILED_TASK_ATTEMPTS:
        del failures[: len(failures) - MAX_FAILED_TASK_ATTEMPTS]


def _prepare_resume_task_records(manifest: dict[str, Any], *, repoll_waiting: bool) -> None:
    """Re-poll waiting work and make terminal provider errors explicitly retryable."""
    tasks = [manifest.get("main_task"), manifest.get("synthesis_task")]
    tasks.extend((manifest.get("fanout_tasks") or {}).values())
    refreshed = False
    if repoll_waiting:
        for task in tasks:
            if isinstance(task, dict) and task.get("status") == "waiting":
                task["status"] = "running"
                refreshed = True

    synthesis = manifest.get("synthesis_task")
    if isinstance(synthesis, dict) and synthesis.get("status") == "error":
        _archive_failed_task(manifest, "synthesis", synthesis)
        manifest["synthesis_task"] = None
        refreshed = True

    fanout = manifest.get("fanout_tasks") or {}
    failed_item_ids = [
        item_id
        for item_id, task in fanout.items()
        if isinstance(task, dict)
        and (
            task.get("status") == "error"
            or (task.get("status") == "stopped" and _single_result(item_id, task) is None)
        )
    ]
    for item_id in failed_item_ids:
        role = "repair" if manifest.get("mode") == "wide" else "fanout"
        _archive_failed_task(manifest, role, fanout[item_id], item_id=item_id)
        del fanout[item_id]
        refreshed = True

    main = manifest.get("main_task")
    if (
        isinstance(main, dict)
        and not manifest.get("fallback_enabled")
        and (
            main.get("status") == "error"
            or (
                main.get("status") == "stopped"
                and bool(_coverage(manifest["items"], main.get("structured"))[0]["missing"])
            )
        )
    ):
        _archive_failed_task(manifest, "main", main)
        manifest["main_task"] = None
        refreshed = True

    if refreshed:
        manifest["state"] = "running"


def _wide_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["complete", "uncertain", "failed"],
                        },
                        "report": {"type": "string"},
                    },
                    "required": ["id", "status", "report"],
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["items", "summary"],
        "additionalProperties": False,
    }


def _single_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "status": {"type": "string", "enum": ["complete", "uncertain", "failed"]},
            "report": {"type": "string"},
        },
        "required": ["id", "status", "report"],
        "additionalProperties": False,
    }


def _bounded_structured_output(value: Any) -> dict[str, Any] | None:
    """Retain only the two requested schemas within the manifest budget."""
    if not isinstance(value, dict):
        return None
    rows = value.get("items")
    if isinstance(rows, list):
        if len(rows) > MAX_ITEMS:
            return {
                "items": [],
                "summary": "Provider output exceeded the maximum roster row count.",
            }
        bounded_rows: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                bounded_rows.append({"id": "", "status": "", "report": ""})
                continue
            bounded_rows.append(
                {
                    "id": str(row.get("id") or "")[:256],
                    "status": str(row.get("status") or "")[:32],
                    "report": _bounded_text(row.get("report")),
                }
            )
        return {
            "items": bounded_rows,
            "summary": _bounded_text(value.get("summary")),
        }
    if any(key in value for key in ("id", "status", "report")):
        return {
            "id": str(value.get("id") or "")[:256],
            "status": str(value.get("status") or "")[:32],
            "report": _bounded_text(value.get("report")),
        }
    return None


class ManusClient:
    def __init__(self, *, deadline: float | None):
        self.base = os.environ.get("MANUS_API_BASE", "https://api.manus.ai/v2").rstrip("/")
        self.key = os.environ.get("MANUS_API_KEY", "")
        if not self.key:
            raise ManusAuthError("MANUS_API_KEY is unset.")
        self.request_timeout = _finite_number("MANUS_REQUEST_TIMEOUT_SECONDS", "60", minimum=0.1)
        self.retries = _bounded_int("MANUS_API_RETRIES", "3", minimum=0, maximum=10)
        self.deadline = deadline

    def _remaining_timeout(self) -> float:
        if self.deadline is None:
            return self.request_timeout
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ManusTimeout("Manus orchestration exceeded the configured local wait.")
        if remaining < 0.001:
            raise ManusTimeout("Manus orchestration exceeded the configured local wait.")
        return min(self.request_timeout, remaining)

    def request_json(self, method: str, path: str, payload: Any = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        url = self.base + path
        last_error = "unknown error"
        idempotent = method in {"GET", "HEAD", "OPTIONS"}
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(
                url,
                data=data,
                method=method,
                headers={
                    "Content-Type": "application/json",
                    "x-manus-api-key": self.key,
                },
            )
            call_timeout = self._remaining_timeout()
            call_deadline = time.monotonic() + call_timeout
            try:
                with _hard_wall_timeout(call_timeout):
                    with urllib.request.urlopen(request, timeout=call_timeout) as response:
                        body_bytes = response.read(MAX_API_RESPONSE_BYTES + 1)
                if len(body_bytes) > MAX_API_RESPONSE_BYTES:
                    raise ManusError(
                        f"Manus API response exceeds {MAX_API_RESPONSE_BYTES} bytes."
                    )
                body = body_bytes.decode("utf-8")
                decoded = json.loads(body)
                if not isinstance(decoded, dict):
                    raise ManusError("Manus API returned a non-object JSON response.")
                if decoded.get("ok") is False:
                    raise ManusError("Manus API rejected the request: " + json.dumps(decoded))
                return decoded
            except urllib.error.HTTPError as exc:
                error_remaining = call_deadline - time.monotonic()
                if error_remaining <= 0:
                    raise ManusTimeout(
                        "Manus API request exceeded its hard wall-clock timeout."
                    ) from exc
                with _hard_wall_timeout(error_remaining):
                    detail = exc.read(4096).decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {detail}"
                transient = exc.code in TRANSIENT_HTTP_STATUSES and (
                    idempotent or exc.code in {425, 429}
                )
                retry_after = exc.headers.get("Retry-After", "")
            except urllib.error.URLError as exc:
                last_error = f"connection error: {exc.reason}"
                # A connection failure after task.create or sendMessage is
                # ambiguous: Manus may have accepted the paid mutation. Never
                # retry it without a provider idempotency contract.
                transient = idempotent
                retry_after = ""
            except UnicodeError as exc:
                raise ManusError(f"Manus API returned invalid UTF-8: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise ManusError(f"Manus API returned invalid JSON: {exc}") from exc
            if not transient or attempt >= self.retries:
                break
            try:
                delay = float(retry_after) if retry_after else min(30.0, 2.0**attempt)
                if not math.isfinite(delay) or delay < 0:
                    raise ValueError
            except ValueError:
                delay = min(30.0, 2.0**attempt)
            if self.deadline is not None and time.monotonic() + delay >= self.deadline:
                raise ManusTimeout("Manus orchestration wait expired during API backoff.")
            _bounded_sleep(
                max(0.0, delay),
                self.deadline,
                "Manus orchestration wait expired during API backoff.",
            )
        raise ManusError(f"Manus API request failed: {last_error}")

    def upload_bytes(self, filename: str, content: bytes) -> dict[str, Any]:
        created = self.request_json("POST", "/file.upload", {"filename": filename})
        created_data = created.get("data") or created
        if not isinstance(created_data, dict):
            raise ManusError("Manus file.upload returned an invalid data shape.")
        file_info = created_data.get("file") or {}
        if not isinstance(file_info, dict):
            raise ManusError("Manus file.upload returned an invalid file shape.")
        file_id = str(file_info.get("id") or "")
        upload_url = str(created_data.get("upload_url") or "")
        if not file_id or not upload_url:
            raise ManusError("Manus file.upload returned no file id or upload URL.")
        upload_request = urllib.request.Request(
            upload_url,
            data=content,
            method="PUT",
            headers={"Content-Type": "application/octet-stream"},
        )
        upload_timeout = self._remaining_timeout()
        try:
            with _hard_wall_timeout(upload_timeout):
                with urllib.request.urlopen(upload_request, timeout=upload_timeout) as response:
                    upload_response = response.read(4097)
            if len(upload_response) > 4096:
                raise ManusError("Manus attachment upload response exceeds 4096 bytes.")
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise ManusError(f"Manus attachment upload failed: {exc}") from exc
        file_wait = _finite_number("MANUS_FILE_WAIT_SECONDS", "60", minimum=0)
        file_interval = _finite_number(
            "MANUS_FILE_POLL_INTERVAL_SECONDS", "1", minimum=MIN_INTERVAL_SECONDS
        )
        file_deadline = time.monotonic() + file_wait
        while True:
            detail = self.request_json(
                "GET", "/file.detail?" + urllib.parse.urlencode({"file_id": file_id})
            )
            detail_data = detail.get("data") or detail
            if not isinstance(detail_data, dict):
                raise ManusError("Manus file.detail returned an invalid data shape.")
            current = detail_data.get("file") or detail_data
            if not isinstance(current, dict):
                raise ManusError("Manus file.detail returned an invalid file shape.")
            status = str(current.get("status") or "")
            if status == "uploaded":
                return {"file_id": file_id, "filename": filename}
            if status in {"deleted", "error"}:
                raise ManusError(
                    f"Manus attachment {filename} entered {status}: "
                    f"{current.get('error_message') or ''}"
                )
            if time.monotonic() >= file_deadline:
                raise ManusTimeout(f"Manus attachment {filename} did not become ready in time.")
            deadlines = [file_deadline]
            if self.deadline is not None:
                deadlines.append(self.deadline)
            _bounded_sleep(
                file_interval,
                min(deadlines),
                f"Manus attachment {filename} did not become ready in time.",
            )

    def upload_path(self, path: Path) -> dict[str, Any]:
        uploaded = self.upload_bytes(path.name, path.read_bytes())
        uploaded["local_path"] = str(path)
        return uploaded

    def create_task(
        self,
        prompt: str,
        *,
        profile: str,
        title: str,
        attachments: list[dict[str, Any]],
        schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        content: str | list[dict[str, str]] = prompt
        if attachments:
            content = [{"type": "text", "text": prompt}]
            content.extend(
                {"type": "file", "file_id": str(attachment["file_id"])}
                for attachment in attachments
            )
        payload: dict[str, Any] = {
            "message": {"content": content},
            "agent_profile": profile,
            "hide_in_task_list": False,
            "share_visibility": "private",
            "connectors": [],
            "enable_skills": [],
            "force_skills": [],
        }
        if title:
            payload["title"] = title
        if schema is not None:
            payload["structured_output_schema"] = schema
        created = self.request_json("POST", "/task.create", payload)
        data = created.get("data") or created
        if not isinstance(data, dict):
            raise ManusError("Manus task.create returned an invalid data shape.")
        task_id = str(data.get("task_id") or "")
        if not task_id:
            raise ManusError("Manus task.create returned no task_id: " + json.dumps(created))
        return {
            "id": task_id,
            "url": str(data.get("task_url") or ""),
            "status": "running",
            "assistant_text": "",
            "structured": None,
        }

    def inspect_task(self, task: dict[str, Any]) -> dict[str, Any]:
        detail = self.request_json(
            "GET", "/task.detail?" + urllib.parse.urlencode({"task_id": task["id"]})
        )
        detail_data = detail.get("data") or detail
        if not isinstance(detail_data, dict):
            raise ManusError("Manus task.detail returned an invalid data shape.")
        payload = detail_data.get("task") or detail_data
        if not isinstance(payload, dict):
            raise ManusError("Manus task.detail returned an invalid task shape.")
        status = str(payload.get("status") or "unknown").lower()
        task["status"] = status
        if status not in TERMINAL_STATUSES:
            return task
        messages = self.request_json(
            "GET",
            "/task.listMessages?"
            + urllib.parse.urlencode(
                {"task_id": task["id"], "order": "desc", "limit": 200, "verbose": "true"}
            ),
        )
        message_data = messages.get("data") or messages
        if isinstance(message_data, dict):
            entries = message_data.get("messages", [])
        elif isinstance(message_data, list):
            entries = message_data
        else:
            entries = []
        if not isinstance(entries, list):
            entries = []
        assistant_text = ""
        structured: Any = None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            assistant = entry.get("assistant_message") or {}
            if not isinstance(assistant, dict):
                assistant = {}
            if not assistant_text and assistant.get("content"):
                assistant_text = str(assistant["content"])
            result = entry.get("structured_output_result") or {}
            if not isinstance(result, dict):
                result = {}
            if (
                structured is None
                and result.get("success")
                and result.get("value") is not None
            ):
                structured = result["value"]
        if isinstance(structured, str):
            try:
                structured = json.loads(structured)
            except json.JSONDecodeError:
                pass
        structured = _bounded_structured_output(structured)
        task["assistant_text"] = _bounded_text(assistant_text)
        task["structured"] = structured
        return task


def _task_prompt(prompt: str, items: list[dict[str, str]]) -> str:
    roster = "\n".join(
        f"- {item['id']}" + (f": {item['instructions']}" if item["instructions"] else "")
        for item in items
    )
    return f"""{prompt.strip()}

This is a Cobbler-managed, independently parallelizable research roster. Request Manus Wide
Research if it is available. Assign exactly one independent research subagent to every item below;
do not merge, omit, rename, or duplicate items. Each subagent must work only its assigned item and
return source-grounded evidence. The coordinator must verify exact roster coverage before synthesis.

Expected item roster ({len(items)} items):
{roster}

Return the requested structured output. Every item must have its exact id, status
(complete, uncertain, or failed), and a self-contained report. Mark unsupported claims uncertain;
do not fabricate evidence."""


def _fanout_prompt(prompt: str, item: dict[str, str]) -> str:
    detail = item["instructions"] or "Apply the shared research instructions to this item."
    return f"""You are one independent Manus research worker in a Cobbler-managed fan-out.

Shared research goal:
{prompt.strip()}

Your only assigned item is `{item['id']}`.
Item-specific instructions: {detail}

Do not research or synthesize other roster items. Return the requested structured output with the
exact id `{item['id']}`. Use status complete, uncertain, or failed. Provide source-grounded evidence
and mark unsupported claims uncertain rather than fabricating them."""


def _coverage(
    items: list[dict[str, str]], results: Any
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    expected = [item["id"] for item in items]
    counts = {item_id: 0 for item_id in expected}
    accepted: dict[str, dict[str, str]] = {}
    unknown: list[str] = []
    invalid: list[str] = []
    rows = results.get("items") if isinstance(results, dict) else None
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            invalid.append("non-object result")
            continue
        item_id = str(row.get("id") or "")
        status = str(row.get("status") or "")
        report = _bounded_text(row.get("report"))
        if item_id not in counts:
            unknown.append(item_id or "<empty>")
            continue
        counts[item_id] += 1
        if status not in {"complete", "uncertain", "failed"} or not report:
            invalid.append(item_id)
            continue
        if counts[item_id] == 1 and status != "failed":
            accepted[item_id] = {"id": item_id, "status": status, "report": report}
    duplicates = [item_id for item_id, count in counts.items() if count > 1]
    for item_id in duplicates:
        accepted.pop(item_id, None)
    missing = [item_id for item_id in expected if item_id not in accepted]
    return (
        {
            "expected": expected,
            "complete": [item_id for item_id in expected if item_id in accepted],
            "missing": missing,
            "duplicates": duplicates,
            "unknown": unknown,
            "invalid": invalid,
        },
        accepted,
    )


def _single_result(item_id: str, task: dict[str, Any]) -> dict[str, str] | None:
    structured = task.get("structured")
    if isinstance(structured, dict):
        returned_id = str(structured.get("id") or "")
        status = str(structured.get("status") or "")
        report = _bounded_text(structured.get("report"))
        if returned_id == item_id and status in {"complete", "uncertain"} and report:
            return {"id": item_id, "status": status, "report": report}
    assistant = _bounded_text(task.get("assistant_text"))
    if task.get("status") == "stopped" and assistant:
        return {"id": item_id, "status": "uncertain", "report": assistant}
    return None


def _wait_tasks(client: ManusClient, tasks: list[dict[str, Any]], interval: float) -> None:
    while True:
        pending = [task for task in tasks if task.get("status") not in TERMINAL_STATUSES]
        if not pending:
            return
        for task in pending:
            client.inspect_task(task)
        if any(task.get("status") not in TERMINAL_STATUSES for task in tasks):
            if client.deadline is not None and time.monotonic() >= client.deadline:
                raise ManusTimeout("Manus orchestration exceeded the configured local wait.")
            _bounded_sleep(
                interval,
                client.deadline,
                "Manus orchestration exceeded the configured local wait.",
            )


def _rate_limited_create_pause(
    last_created: float, interval: float, deadline: float | None
) -> float:
    if last_created:
        remaining = interval - (time.monotonic() - last_created)
        if remaining > 0:
            _bounded_sleep(
                remaining,
                deadline,
                "Manus orchestration exceeded the configured local wait while rate limiting.",
            )
    return time.monotonic()


def _print_task(task: dict[str, Any], label: str) -> None:
    print(f"{label}: {task['id']}", file=sys.stderr, flush=True)
    if task.get("url"):
        print(f"Task URL: {task['url']}", file=sys.stderr, flush=True)


def _ordinary(
    args: argparse.Namespace,
    client: ManusClient,
    prompt: str,
    attachments: list[dict[str, Any]],
    interval: float,
    max_wait: float,
) -> int:
    task = client.create_task(
        prompt,
        profile=args.profile,
        title=args.title or "",
        attachments=attachments,
        schema=None,
    )
    _print_task(task, "Manus task initiated")
    if max_wait == 0:
        print(json.dumps({"task_id": task["id"], "task_url": task["url"]}, ensure_ascii=False))
        return 0
    _wait_tasks(client, [task], interval)
    if task.get("assistant_text"):
        print(task["assistant_text"])
    print(f"Manus task status: {task['status']}", file=sys.stderr)
    return 0 if task["status"] == "stopped" else 3 if task["status"] == "waiting" else 1


def _manifest_result(
    manifest: dict[str, Any], accepted: dict[str, dict[str, str]]
) -> dict[str, Any]:
    synthesis = manifest.get("synthesis_task") or {}
    structured = synthesis.get("structured")
    if isinstance(structured, dict):
        synthesis_coverage, _ = _coverage(manifest["items"], structured)
        if not any(
            synthesis_coverage[key]
            for key in ("missing", "duplicates", "unknown", "invalid")
        ):
            return structured
    main = manifest.get("main_task") or {}
    main_structured = main.get("structured")
    coverage = manifest["coverage"]
    if (
        isinstance(main_structured, dict)
        and not manifest.get("fallback_used")
        and not any(coverage[key] for key in ("duplicates", "unknown", "invalid"))
    ):
        return main_structured
    return {
        "items": [
            accepted[item_id]
            for item_id in manifest["coverage"]["expected"]
            if item_id in accepted
        ],
        "summary": str(synthesis.get("assistant_text") or main.get("assistant_text") or ""),
    }


def _orchestrate(
    client: ManusClient,
    manifest: dict[str, Any],
    manifest_path: Path,
    interval: float,
    max_wait: float,
    create_interval: float,
) -> int:
    items = manifest["items"]
    prompt = manifest["prompt"]
    attachments = manifest.get("attachments") or []
    mode = manifest["mode"]

    if mode == "wide" and not manifest.get("main_task"):
        task = client.create_task(
            _task_prompt(prompt, items),
            profile=manifest["profile"],
            title=manifest.get("title") or "Manus Wide Research",
            attachments=attachments,
            schema=_wide_schema(),
        )
        manifest["main_task"] = task
        manifest["state"] = "running"
        _atomic_write_json(manifest_path, manifest)
        _print_task(task, "Manus Wide Research task initiated")

    if mode == "fanout":
        fanout = manifest.setdefault("fanout_tasks", {})
        last_created = 0.0
        for item in items:
            if item["id"] in fanout:
                continue
            last_created = _rate_limited_create_pause(
                last_created, create_interval, client.deadline
            )
            task = client.create_task(
                _fanout_prompt(prompt, item),
                profile=manifest["profile"],
                title=f"Manus research: {item['id']}",
                attachments=attachments,
                schema=_single_schema(),
            )
            fanout[item["id"]] = task
            _atomic_write_json(manifest_path, manifest)
            _print_task(task, f"Manus fan-out item {item['id']}")

    if max_wait == 0:
        manifest["state"] = "running"
        _atomic_write_json(manifest_path, manifest)
        print(
            json.dumps(
                {
                    "manifest": str(manifest_path),
                    "state": manifest["state"],
                    "main_task": manifest.get("main_task"),
                    "fanout_task_count": len(manifest.get("fanout_tasks") or {}),
                },
                ensure_ascii=False,
            )
        )
        return 0

    accepted: dict[str, dict[str, str]] = {}
    if mode == "wide":
        main = manifest["main_task"]
        if main.get("status") not in TERMINAL_STATUSES:
            _wait_tasks(client, [main], interval)
            _atomic_write_json(manifest_path, manifest)
        if main.get("status") == "waiting":
            manifest["state"] = "waiting"
            _atomic_write_json(manifest_path, manifest)
            print(
                json.dumps(
                    {"manifest": str(manifest_path), "state": "waiting"},
                    ensure_ascii=False,
                )
            )
            return 3
        coverage, accepted = _coverage(items, main.get("structured"))
        manifest["coverage"] = coverage
    else:
        fanout = manifest.get("fanout_tasks") or {}
        _wait_tasks(client, list(fanout.values()), interval)
        for item in items:
            result = _single_result(item["id"], fanout[item["id"]])
            if result is not None:
                accepted[item["id"]] = result
        expected = [item["id"] for item in items]
        manifest["coverage"] = {
            "expected": expected,
            "complete": [item_id for item_id in expected if item_id in accepted],
            "missing": [item_id for item_id in expected if item_id not in accepted],
            "duplicates": [],
            "unknown": [],
            "invalid": [],
        }
        _atomic_write_json(manifest_path, manifest)

    missing = list(manifest["coverage"]["missing"])
    if mode == "wide" and missing and manifest.get("fallback_enabled"):
        manifest["fallback_used"] = True
        fanout = manifest.setdefault("fanout_tasks", {})
        item_by_id = {item["id"]: item for item in items}
        last_created = 0.0
        for item_id in missing:
            if item_id in fanout:
                continue
            last_created = _rate_limited_create_pause(
                last_created, create_interval, client.deadline
            )
            item = item_by_id[item_id]
            fanout[item_id] = client.create_task(
                _fanout_prompt(prompt, item),
                profile=manifest["profile"],
                title=f"Manus coverage repair: {item_id}",
                attachments=attachments,
                schema=_single_schema(),
            )
            _atomic_write_json(manifest_path, manifest)
            _print_task(fanout[item_id], f"Manus coverage repair {item_id}")
        _wait_tasks(client, [fanout[item_id] for item_id in missing], interval)
        for item_id in missing:
            result = _single_result(item_id, fanout[item_id])
            if result is not None:
                accepted[item_id] = result
        expected = manifest["coverage"]["expected"]
        manifest["coverage"]["complete"] = [item_id for item_id in expected if item_id in accepted]
        manifest["coverage"]["missing"] = [
            item_id for item_id in expected if item_id not in accepted
        ]
        manifest["coverage"]["duplicates"] = []
        _atomic_write_json(manifest_path, manifest)

    if manifest["coverage"]["missing"]:
        fanout = manifest.get("fanout_tasks") or {}
        waiting = [
            item_id
            for item_id in manifest["coverage"]["missing"]
            if isinstance(fanout.get(item_id), dict)
            and fanout[item_id].get("status") == "waiting"
        ]
        if waiting:
            manifest["state"] = "waiting"
            _atomic_write_json(manifest_path, manifest)
            print(
                json.dumps(
                    {
                        "manifest": str(manifest_path),
                        "state": "waiting",
                        "waiting": waiting,
                        "coverage": manifest["coverage"],
                    },
                    ensure_ascii=False,
                )
            )
            return 3
        manifest["state"] = "incomplete"
        _atomic_write_json(manifest_path, manifest)
        print(
            json.dumps(
                {"manifest": str(manifest_path), "coverage": manifest["coverage"]},
                ensure_ascii=False,
            )
        )
        return 4

    if (mode == "fanout" or manifest.get("fallback_used")) and not manifest.get("synthesis_task"):
        result_bytes = json.dumps(
            {"expected": manifest["coverage"]["expected"], "results": accepted},
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        synthesis_file = client.upload_bytes("cobbler-manus-results.json", result_bytes)
        manifest.setdefault("generated_files", []).append(synthesis_file)
        synthesis_prompt = (
            "Synthesize the attached Cobbler-validated per-item research for this goal:\n\n"
            f"{prompt}\n\n"
            "Do not perform a new fan-out. Preserve every exact item id and material uncertainty. "
            "Return the requested structured output with one row per expected item."
        )
        _rate_limited_create_pause(time.monotonic(), create_interval, client.deadline)
        manifest["synthesis_task"] = client.create_task(
            synthesis_prompt,
            profile=manifest["profile"],
            title=manifest.get("title") or "Manus research synthesis",
            attachments=[synthesis_file],
            schema=_wide_schema(),
        )
        _print_task(manifest["synthesis_task"], "Manus synthesis task initiated")
        _atomic_write_json(manifest_path, manifest)

    synthesis = manifest.get("synthesis_task")
    if synthesis and synthesis.get("status") not in TERMINAL_STATUSES:
        _wait_tasks(client, [synthesis], interval)
        _atomic_write_json(manifest_path, manifest)
    if synthesis and synthesis.get("status") != "stopped":
        manifest["state"] = synthesis.get("status") or "error"
        _atomic_write_json(manifest_path, manifest)
        if manifest["state"] == "waiting":
            print(
                json.dumps(
                    {"manifest": str(manifest_path), "state": "waiting"},
                    ensure_ascii=False,
                )
            )
            return 3
        print(json.dumps(_manifest_result(manifest, accepted), ensure_ascii=False, indent=2))
        print(
            f"Validated per-item results were emitted; resume failed synthesis with: "
            f"run_manus.sh --resume {manifest_path}",
            file=sys.stderr,
        )
        return 1

    manifest["state"] = "complete"
    _atomic_write_json(manifest_path, manifest)
    print(json.dumps(_manifest_result(manifest, accepted), ensure_ascii=False, indent=2))
    print(f"Manus orchestration manifest: {manifest_path}", file=sys.stderr)
    return 0


def _run_orchestration(
    client: ManusClient,
    manifest: dict[str, Any],
    manifest_path: Path,
    interval: float,
    max_wait: float,
    create_interval: float,
) -> int:
    try:
        return _orchestrate(
            client,
            manifest,
            manifest_path,
            interval,
            max_wait,
            create_interval,
        )
    except ManusTimeout:
        manifest["state"] = "timed_out"
        _atomic_write_json(manifest_path, manifest)
        print(f"Resume with: run_manus.sh --resume {manifest_path}", file=sys.stderr)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_manus.sh",
        description="Private Manus research with optional Cobbler-managed Wide Research.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--wide", action="store_true", help="request native Wide Research")
    mode.add_argument(
        "--fanout", action="store_true", help="create one deterministic task per item"
    )
    parser.add_argument("--resume", metavar="MANIFEST", help="resume a Wide/fan-out manifest")
    parser.add_argument(
        "--items-file",
        metavar="JSON",
        help="JSON roster of strings or id/instructions objects",
    )
    parser.add_argument(
        "--prompt-file",
        metavar="PATH",
        help="read the shared research prompt from a UTF-8 file",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        metavar="PATH",
        help="upload an explicit source attachment",
    )
    parser.add_argument(
        "--manifest",
        metavar="PATH",
        help="override the ignored orchestration manifest path",
    )
    parser.add_argument("--title", default="", help="Manus task title")
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="do not fan out missing Wide Research items",
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), help="override the Manus profile")
    parser.add_argument("topic", nargs="*", help="research topic or shared orchestration goal")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    max_wait = _finite_number("MANUS_MAX_WAIT_SECONDS", "1800", minimum=0)
    interval = _finite_number(
        "MANUS_POLL_INTERVAL_SECONDS", "15", minimum=MIN_INTERVAL_SECONDS
    )
    create_interval = _finite_number(
        "MANUS_CREATE_INTERVAL_SECONDS", "6.1", minimum=MIN_INTERVAL_SECONDS
    )
    attachment_limit = _bounded_int(
        "MANUS_MAX_ATTACHMENT_BYTES",
        str(DEFAULT_ATTACHMENT_LIMIT),
        minimum=1,
        maximum=PROVIDER_ATTACHMENT_LIMIT,
    )
    deadline = None if max_wait == 0 else time.monotonic() + max_wait

    if args.resume:
        if (
            args.wide
            or args.fanout
            or args.items_file
            or args.prompt_file
            or args.file
            or args.manifest
            or args.title
            or args.no_fallback
            or args.profile is not None
            or args.topic
        ):
            raise ManusError("--resume cannot be combined with new-run arguments.")
        manifest_path = _runtime_manifest_path(args.resume, must_exist=True)
        manifest = _load_manifest(manifest_path)
        _prepare_resume_task_records(manifest, repoll_waiting=max_wait != 0)
        client = ManusClient(deadline=deadline)
        return _run_orchestration(
            client, manifest, manifest_path, interval, max_wait, create_interval
        )

    args.profile = args.profile or os.environ.get("MANUS_AGENT_PROFILE", "manus-1.6-max")
    if args.profile not in PROFILES:
        raise ManusError(
            "MANUS_AGENT_PROFILE must be manus-1.6, manus-1.6-lite, or manus-1.6-max."
        )

    if args.prompt_file and args.topic:
        raise ManusError("Use either --prompt-file or positional topic text, not both.")
    prompt = (
        _read_text(
            Path(args.prompt_file).expanduser(),
            "prompt file",
            limit=MAX_PROMPT_BYTES,
        )
        if args.prompt_file
        else " ".join(args.topic)
    ).strip()
    if not prompt:
        raise ManusError("A research topic or --prompt-file is required.")
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ManusError(f"Research prompt exceeds the {MAX_PROMPT_BYTES}-byte limit.")

    if not args.wide and not args.fanout:
        if args.items_file or args.manifest or args.no_fallback:
            raise ManusError("Roster, manifest, and fallback options require --wide or --fanout.")
        client = ManusClient(deadline=deadline)
        attachments = [
            client.upload_path(_validate_attachment(path_text, attachment_limit))
            for path_text in args.file
        ]
        return _ordinary(args, client, prompt, attachments, interval, max_wait)

    if not args.items_file:
        raise ManusError("--wide and --fanout require --items-file.")
    items = _load_items(Path(args.items_file).expanduser())
    mode = "wide" if args.wide else "fanout"
    validated_attachments = [
        _validate_attachment(path_text, attachment_limit) for path_text in args.file
    ]
    manifest_path = _runtime_manifest_path(
        args.manifest,
        mode=mode,
        must_exist=False,
    )
    client = ManusClient(deadline=deadline)
    attachments = [client.upload_path(path) for path in validated_attachments]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "state": "staging",
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "profile": args.profile,
        "title": args.title,
        "prompt": prompt,
        "items": items,
        "attachments": attachments,
        "fallback_enabled": mode == "wide" and not args.no_fallback,
        "fallback_used": False,
        "main_task": None,
        "fanout_tasks": {},
        "synthesis_task": None,
        "failed_task_attempts": [],
        "coverage": {
            "expected": [item["id"] for item in items],
            "complete": [],
            "missing": [item["id"] for item in items],
            "duplicates": [],
            "unknown": [],
            "invalid": [],
        },
    }
    _atomic_write_json(manifest_path, manifest)
    print(f"Manus orchestration manifest: {manifest_path}", file=sys.stderr)
    return _run_orchestration(
        client, manifest, manifest_path, interval, max_wait, create_interval
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ManusTimeout as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(124) from exc
    except ManusAuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (ManusError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
