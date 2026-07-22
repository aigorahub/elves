"""Host-owned observation, candidate synthesis, promotion, and exact-HEAD waivers.

Learning state lives under gitignored ``.elves/runtime/landing-profile/``.  It never
grants merge, tag, release, protected-ref, connector, secret, or posting authority.
Only an explicit promote rewrites the tracked ``.elves/landing-profile.json``.
Executable profile shapes remain unsupported.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from cobbler_runtime.landing_profile import (
    MAX_CHANGED_PATHS,
    MAX_CHECKS,
    MAX_JSON_DEPTH,
    MAX_PATTERNS_PER_CHECK,
    MAX_PROFILE_BYTES,
    MAX_STRING_CHARS,
    PROFILE_RELATIVE_PATH,
    PROFILE_SCHEMA_VERSION,
    ProfileDiagnostic,
    _EXACT_COMMIT_RE,
    _CHECK_ID_RE,
    _condition_applies,
    _glob_work_units,
    _resolve_commit,
    _run_git,
    _safe_glob,
    _safe_string,
    load_landing_profile,
    path_matches_any,
    validate_landing_profile,
)

RUNTIME_RELATIVE_DIR = Path(".elves/runtime/landing-profile")
OBSERVATIONS_FILE = "observations.jsonl"
CANDIDATES_FILE = "candidates.json"
WAIVERS_FILE = "waivers.json"
LEARN_SCHEMA_VERSION = 1
MAX_OBSERVATIONS = 256
MAX_CANDIDATES = 64
MAX_WAIVERS = 64
MAX_NOTE_CHARS = 512
MAX_OBSERVATION_PATHS = 2_000
DEFAULT_MIN_SUPPORT = 2
MAX_RUNTIME_FILE_BYTES = 512 * 1024

_TOP_LEVEL_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")


@dataclass(frozen=True)
class LearnResult:
    """Machine-readable learning command result."""

    status: str
    green: bool
    payload: dict[str, Any]
    diagnostics: tuple[ProfileDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LEARN_SCHEMA_VERSION,
            "status": self.status,
            "green": self.green,
            "payload": self.payload,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def _diag(code: str, message: str) -> ProfileDiagnostic:
    return ProfileDiagnostic(code=code, message=message)


def _fail(code: str, message: str, **payload: Any) -> LearnResult:
    return LearnResult(
        status="invalid",
        green=False,
        payload=payload,
        diagnostics=(_diag(code, message),),
    )


def _ok(status: str, **payload: Any) -> LearnResult:
    return LearnResult(status=status, green=True, payload=payload)


def runtime_dir(repo_root: Path) -> Path:
    return Path(repo_root) / RUNTIME_RELATIVE_DIR


def _json_depth_ok(value: Any) -> bool:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            return False
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return True


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _ensure_runtime_dir(repo_root: Path) -> tuple[Path | None, ProfileDiagnostic | None]:
    root = Path(repo_root).resolve()
    path = runtime_dir(root)
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError:
        return None, _diag(
            "learn_runtime_unwritable",
            "Landing-profile learning runtime directory could not be created.",
        )
    try:
        info = path.lstat()
    except OSError:
        return None, _diag(
            "learn_runtime_unreadable",
            "Landing-profile learning runtime directory could not be inspected.",
        )
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return None, _diag(
            "learn_runtime_not_directory",
            "Landing-profile learning runtime path must be a non-symlink directory.",
        )
    return path, None


def _read_runtime_json(path: Path) -> tuple[Any | None, ProfileDiagnostic | None]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError:
        return None, _diag("learn_runtime_unreadable", "Runtime file could not be inspected.")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return None, _diag(
            "learn_runtime_not_regular",
            "Runtime files must be ordinary non-symlink files.",
        )
    if info.st_size > MAX_RUNTIME_FILE_BYTES:
        return None, _diag(
            "learn_runtime_too_large",
            f"Runtime file exceeds the {MAX_RUNTIME_FILE_BYTES}-byte limit.",
        )
    try:
        raw = path.read_bytes()
    except OSError:
        return None, _diag("learn_runtime_unreadable", "Runtime file could not be read.")
    if len(raw) > MAX_RUNTIME_FILE_BYTES:
        return None, _diag(
            "learn_runtime_too_large",
            f"Runtime file exceeds the {MAX_RUNTIME_FILE_BYTES}-byte limit.",
        )
    try:
        text = raw.decode("utf-8")
        parsed = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None, _diag("learn_runtime_invalid_json", "Runtime file must be valid UTF-8 JSON.")
    if not _json_depth_ok(parsed):
        return None, _diag(
            "learn_runtime_json_too_deep",
            f"Runtime file exceeds the maximum JSON depth of {MAX_JSON_DEPTH}.",
        )
    return parsed, None


def _atomic_write_json(path: Path, payload: Any) -> ProfileDiagnostic | None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_RUNTIME_FILE_BYTES and path.name != PROFILE_RELATIVE_PATH.name:
        # Tracked profile has its own size bound; promote uses that path separately.
        if path.name != "landing-profile.json":
            return _diag(
                "learn_runtime_too_large",
                f"Runtime write would exceed the {MAX_RUNTIME_FILE_BYTES}-byte limit.",
            )
    try:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
    except OSError:
        return _diag("learn_runtime_unwritable", "Runtime file could not be staged for write.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return _diag("learn_runtime_unwritable", "Runtime file could not be written atomically.")
    return None


def _atomic_write_profile(repo_root: Path, profile: Mapping[str, Any]) -> ProfileDiagnostic | None:
    validated, issues = validate_landing_profile(profile)
    if validated is None:
        return issues[0] if issues else _diag(
            "profile_schema_invalid",
            "Promoted profile failed schema validation.",
        )
    text = json.dumps(validated.to_dict(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_PROFILE_BYTES:
        return _diag(
            "profile_too_large",
            f"Landing profile exceeds the {MAX_PROFILE_BYTES}-byte limit.",
        )
    path = Path(repo_root) / PROFILE_RELATIVE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".landing-profile.",
            suffix=".tmp",
            dir=str(path.parent),
        )
    except OSError:
        return _diag("profile_write_failed", "Tracked landing profile could not be staged.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return _diag("profile_write_failed", "Tracked landing profile could not be written.")
    return None


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> ProfileDiagnostic | None:
    line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    encoded = line.encode("utf-8")
    try:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if path.exists():
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                return _diag(
                    "learn_runtime_not_regular",
                    "Observation log must be an ordinary non-symlink file.",
                )
            if info.st_size + len(encoded) > MAX_RUNTIME_FILE_BYTES:
                return _diag(
                    "learn_runtime_too_large",
                    f"Observation log exceeds the {MAX_RUNTIME_FILE_BYTES}-byte limit.",
                )
        with open(path, "ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        return _diag("learn_runtime_unwritable", "Observation log could not be appended.")
    return None


def _load_observations(repo_root: Path) -> tuple[list[dict[str, Any]] | None, ProfileDiagnostic | None]:
    path = runtime_dir(repo_root) / OBSERVATIONS_FILE
    try:
        info = path.lstat()
    except FileNotFoundError:
        return [], None
    except OSError:
        return None, _diag("learn_runtime_unreadable", "Observation log could not be inspected.")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return None, _diag(
            "learn_runtime_not_regular",
            "Observation log must be an ordinary non-symlink file.",
        )
    if info.st_size > MAX_RUNTIME_FILE_BYTES:
        return None, _diag(
            "learn_runtime_too_large",
            f"Observation log exceeds the {MAX_RUNTIME_FILE_BYTES}-byte limit.",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, _diag("learn_runtime_invalid_json", "Observation log must be valid UTF-8 JSONL.")
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, ValueError, RecursionError):
            return None, _diag(
                "learn_runtime_invalid_json",
                f"Observation log line {line_no} is not valid JSON.",
            )
        if not isinstance(parsed, dict) or not _json_depth_ok(parsed):
            return None, _diag(
                "learn_runtime_invalid_json",
                f"Observation log line {line_no} must be a bounded JSON object.",
            )
        records.append(parsed)
        if len(records) > MAX_OBSERVATIONS:
            return None, _diag(
                "learn_observations_too_many",
                f"Observation log exceeds the {MAX_OBSERVATIONS}-record limit.",
            )
    return records, None


def _load_candidates(repo_root: Path) -> tuple[dict[str, Any] | None, ProfileDiagnostic | None]:
    path = runtime_dir(repo_root) / CANDIDATES_FILE
    parsed, issue = _read_runtime_json(path)
    if issue is not None:
        return None, issue
    if parsed is None:
        return {
            "schema_version": LEARN_SCHEMA_VERSION,
            "candidates": [],
        }, None
    if not isinstance(parsed, dict):
        return None, _diag("learn_candidates_invalid", "Candidates file root must be an object.")
    if parsed.get("schema_version") != LEARN_SCHEMA_VERSION:
        return None, _diag(
            "learn_candidates_schema_unsupported",
            f"Candidates schema_version must be {LEARN_SCHEMA_VERSION}.",
        )
    candidates = parsed.get("candidates")
    if not isinstance(candidates, list):
        return None, _diag("learn_candidates_invalid", "Candidates must be an array.")
    if len(candidates) > MAX_CANDIDATES:
        return None, _diag(
            "learn_candidates_too_many",
            f"Candidates exceed the {MAX_CANDIDATES}-item limit.",
        )
    return {
        "schema_version": LEARN_SCHEMA_VERSION,
        "candidates": candidates,
    }, None


def _load_waivers(repo_root: Path) -> tuple[list[dict[str, Any]] | None, ProfileDiagnostic | None]:
    path = runtime_dir(repo_root) / WAIVERS_FILE
    parsed, issue = _read_runtime_json(path)
    if issue is not None:
        return None, issue
    if parsed is None:
        return [], None
    if not isinstance(parsed, dict):
        return None, _diag("learn_waivers_invalid", "Waivers file root must be an object.")
    if parsed.get("schema_version") != LEARN_SCHEMA_VERSION:
        return None, _diag(
            "learn_waivers_schema_unsupported",
            f"Waivers schema_version must be {LEARN_SCHEMA_VERSION}.",
        )
    waivers = parsed.get("waivers")
    if not isinstance(waivers, list):
        return None, _diag("learn_waivers_invalid", "Waivers must be an array.")
    if len(waivers) > MAX_WAIVERS:
        return None, _diag(
            "learn_waivers_too_many",
            f"Waivers exceed the {MAX_WAIVERS}-item limit.",
        )
    cleaned: list[dict[str, Any]] = []
    for item in waivers:
        if not isinstance(item, dict):
            return None, _diag("learn_waivers_invalid", "Each waiver must be an object.")
        cleaned.append(item)
    return cleaned, None


def _save_waivers(repo_root: Path, waivers: Sequence[Mapping[str, Any]]) -> ProfileDiagnostic | None:
    path = runtime_dir(repo_root) / WAIVERS_FILE
    return _atomic_write_json(
        path,
        {
            "schema_version": LEARN_SCHEMA_VERSION,
            "waivers": list(waivers),
        },
    )


def resolve_changed_paths(
    repo_root: Path,
    *,
    base_ref: str = "origin/main",
) -> tuple[dict[str, Any] | None, ProfileDiagnostic | None]:
    """Resolve exact HEAD/base/merge-base and bounded changed paths."""

    root = Path(repo_root).resolve()
    head = _resolve_commit(root, "HEAD")
    if head is None:
        return None, _diag(
            "profile_head_unresolved",
            "Landing profile requires HEAD to resolve to an exact commit.",
        )
    base_commit = _resolve_commit(root, base_ref)
    if base_commit is None:
        return None, _diag(
            "profile_base_unresolved",
            "Landing profile base must resolve to an exact commit.",
        )
    merge = _run_git(root, "merge-base", head, base_commit)
    merge_base = merge.output.decode("ascii", errors="ignore").strip().lower()
    if (
        merge.returncode != 0
        or merge.output_truncated
        or _EXACT_COMMIT_RE.fullmatch(merge_base) is None
    ):
        return None, _diag(
            "profile_merge_base_unresolved",
            "Landing profile merge base could not be resolved exactly.",
        )
    changed = _run_git(root, "diff", "--name-only", "-z", merge_base, head, "--")
    if changed.returncode != 0 or changed.output_truncated:
        return None, _diag(
            "profile_diff_unavailable",
            "Landing profile changed-path delta could not be read within bounds.",
        )
    try:
        changed_paths = tuple(
            sorted(
                path.decode("utf-8", errors="strict")
                for path in changed.output.split(b"\0")
                if path
            )
        )
    except UnicodeDecodeError:
        return None, _diag(
            "profile_diff_invalid_utf8",
            "Landing profile changed paths must be valid UTF-8.",
        )
    if len(changed_paths) > MAX_CHANGED_PATHS or any(
        len(path) > MAX_STRING_CHARS or path.startswith("/") or "\0" in path
        for path in changed_paths
    ):
        return None, _diag(
            "profile_diff_out_of_bounds",
            "Landing profile changed-path delta exceeds safe bounds.",
        )
    return {
        "head": head,
        "base_commit": base_commit,
        "merge_base": merge_base,
        "changed_paths": list(changed_paths),
    }, None


def _parse_explicit_proposal(
    *,
    check_id: str | None,
    when_patterns: Sequence[str] | None,
    paths: Sequence[str] | None,
    severity: str,
    description: str | None,
    kind: str,
) -> tuple[dict[str, Any] | None, ProfileDiagnostic | None]:
    if check_id is None and not when_patterns and not paths and description is None:
        return None, None
    if check_id is None:
        return None, _diag(
            "learn_proposal_incomplete",
            "Explicit proposals require --propose-id.",
        )
    if _CHECK_ID_RE.fullmatch(check_id) is None:
        return None, _diag(
            "profile_check_id_invalid",
            f"Proposal id must match {_CHECK_ID_RE.pattern!r}.",
        )
    if severity not in {"blocking", "advisory"}:
        return None, _diag(
            "profile_severity_invalid",
            "Proposal severity must be 'blocking' or 'advisory'.",
        )
    if kind not in {"path_touched", "post_merge_checklist"}:
        return None, _diag(
            "profile_check_kind_unsupported",
            "Proposal kind must be path_touched or post_merge_checklist.",
        )
    if kind == "post_merge_checklist":
        if not description:
            return None, _diag(
                "learn_proposal_incomplete",
                "post_merge_checklist proposals require --propose-description.",
            )
        text, issue = _safe_string(description, label="proposal.description")
        if issue is not None or text is None:
            return None, issue
        return {
            "id": check_id,
            "kind": "post_merge_checklist",
            "when": {"kind": "always"},
            "description": text,
            "source": "explicit",
            "severity_hint": severity,
        }, None

    if not when_patterns or not paths:
        return None, _diag(
            "learn_proposal_incomplete",
            "path_touched proposals require --propose-when and --propose-paths.",
        )
    if len(when_patterns) > MAX_PATTERNS_PER_CHECK or len(paths) > MAX_PATTERNS_PER_CHECK:
        return None, _diag(
            "profile_array_too_large",
            f"Proposal patterns exceed the {MAX_PATTERNS_PER_CHECK}-item limit.",
        )
    parsed_when: list[str] = []
    for index, pattern in enumerate(when_patterns):
        text, issue = _safe_glob(pattern, label=f"proposal.when[{index}]")
        if issue is not None or text is None:
            return None, issue
        parsed_when.append(text)
    parsed_paths: list[str] = []
    for index, pattern in enumerate(paths):
        text, issue = _safe_glob(pattern, label=f"proposal.paths[{index}]")
        if issue is not None or text is None:
            return None, issue
        parsed_paths.append(text)
    return {
        "id": check_id,
        "kind": "path_touched",
        "severity": severity,
        "when": {"kind": "any_path_glob", "patterns": parsed_when},
        "paths": parsed_paths,
        "source": "explicit",
        "severity_hint": severity,
    }, None


def observe_landing(
    repo_root: Path,
    *,
    base_ref: str = "origin/main",
    note: str | None = None,
    propose_id: str | None = None,
    propose_when: Sequence[str] | None = None,
    propose_paths: Sequence[str] | None = None,
    propose_severity: str = "advisory",
    propose_kind: str = "path_touched",
    propose_description: str | None = None,
) -> LearnResult:
    """Record one exact-HEAD observation packet. Never mutates the tracked profile."""

    root = Path(repo_root).resolve()
    directory, issue = _ensure_runtime_dir(root)
    if issue is not None or directory is None:
        return _fail(issue.code, issue.message) if issue else _fail(
            "learn_runtime_unwritable",
            "Landing-profile learning runtime directory unavailable.",
        )

    identity, issue = resolve_changed_paths(root, base_ref=base_ref)
    if issue is not None or identity is None:
        return _fail(
            issue.code if issue else "profile_head_unresolved",
            issue.message if issue else "Could not resolve repository identity.",
        )

    changed_paths = list(identity["changed_paths"])
    if len(changed_paths) > MAX_OBSERVATION_PATHS:
        changed_paths = changed_paths[:MAX_OBSERVATION_PATHS]

    note_text: str | None = None
    if note is not None:
        note_text, note_issue = _safe_string(note, label="note")
        if note_issue is not None:
            return _fail(note_issue.code, note_issue.message)

    proposal, proposal_issue = _parse_explicit_proposal(
        check_id=propose_id,
        when_patterns=propose_when,
        paths=propose_paths,
        severity=propose_severity,
        description=propose_description,
        kind=propose_kind,
    )
    if proposal_issue is not None:
        return _fail(proposal_issue.code, proposal_issue.message)

    loaded = load_landing_profile(root)
    profile_content_sha256 = loaded.content_sha256 if loaded.status == "loaded" else None

    existing, load_issue = _load_observations(root)
    if load_issue is not None or existing is None:
        return _fail(
            load_issue.code if load_issue else "learn_runtime_invalid_json",
            load_issue.message if load_issue else "Observation log unreadable.",
        )
    if len(existing) >= MAX_OBSERVATIONS:
        return _fail(
            "learn_observations_too_many",
            f"Observation log already has the maximum of {MAX_OBSERVATIONS} records.",
        )

    record = {
        "schema_version": LEARN_SCHEMA_VERSION,
        "head": identity["head"],
        "base_commit": identity["base_commit"],
        "merge_base": identity["merge_base"],
        "changed_paths": changed_paths,
        "note": note_text,
        "profile_content_sha256": profile_content_sha256,
        "explicit_proposal": proposal,
    }
    append_issue = _append_jsonl(directory / OBSERVATIONS_FILE, record)
    if append_issue is not None:
        return _fail(append_issue.code, append_issue.message)
    return _ok(
        "recorded",
        observation=record,
        observation_count=len(existing) + 1,
        path=str(RUNTIME_RELATIVE_DIR / OBSERVATIONS_FILE),
    )


def _top_level_prefix(path: str) -> str | None:
    if not path or path.startswith("/") or ".." in path.split("/"):
        return None
    segment = path.split("/", 1)[0]
    if segment in {".", ""} or not _TOP_LEVEL_SEGMENT_RE.fullmatch(segment):
        return None
    # Skip pure root files without a directory — still useful as exact path keys.
    if "/" not in path:
        if len(path) > MAX_STRING_CHARS:
            return None
        return path
    return f"{segment}/**"


def _existing_profile_ids(repo_root: Path) -> set[str]:
    loaded = load_landing_profile(repo_root)
    if loaded.status != "loaded" or loaded.profile is None:
        return set()
    validated, issues = validate_landing_profile(loaded.profile)
    if validated is None or issues:
        return set()
    return {check.id for check in validated.checks}


def _candidate_check_payload(candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    """Strip learning-only keys to a schema-v1 check object."""

    kind = candidate.get("kind")
    if kind == "path_touched":
        severity = candidate.get("severity") or candidate.get("severity_hint") or "advisory"
        when = candidate.get("when")
        paths = candidate.get("paths")
        check_id = candidate.get("id")
        if not isinstance(check_id, str) or not isinstance(when, dict) or not isinstance(paths, list):
            return None
        return {
            "id": check_id,
            "kind": "path_touched",
            "severity": severity,
            "when": when,
            "paths": paths,
        }
    if kind == "post_merge_checklist":
        check_id = candidate.get("id")
        when = candidate.get("when") or {"kind": "always"}
        description = candidate.get("description")
        if not isinstance(check_id, str) or not isinstance(when, dict) or not isinstance(description, str):
            return None
        return {
            "id": check_id,
            "kind": "post_merge_checklist",
            "when": when,
            "description": description,
        }
    return None


def propose_candidates(
    repo_root: Path,
    *,
    min_support: int = DEFAULT_MIN_SUPPORT,
) -> LearnResult:
    """Synthesize advisory candidates from observations. Never writes the tracked profile."""

    if not isinstance(min_support, int) or isinstance(min_support, bool) or min_support < 1:
        return _fail(
            "learn_min_support_invalid",
            "min_support must be a positive integer.",
        )

    root = Path(repo_root).resolve()
    directory, issue = _ensure_runtime_dir(root)
    if issue is not None or directory is None:
        return _fail(issue.code, issue.message) if issue else _fail(
            "learn_runtime_unwritable",
            "Landing-profile learning runtime directory unavailable.",
        )

    observations, load_issue = _load_observations(root)
    if load_issue is not None or observations is None:
        return _fail(
            load_issue.code if load_issue else "learn_runtime_invalid_json",
            load_issue.message if load_issue else "Observation log unreadable.",
        )

    existing_ids = _existing_profile_ids(root)
    candidates_by_id: dict[str, dict[str, Any]] = {}

    # 1) Explicit proposals win and are deterministic.
    for observation in observations:
        proposal = observation.get("explicit_proposal")
        if not isinstance(proposal, dict):
            continue
        check = _candidate_check_payload(proposal)
        if check is None:
            continue
        check_id = check["id"]
        if check_id in existing_ids:
            continue
        # Validate shape through the real schema parser.
        probe = {"schema_version": PROFILE_SCHEMA_VERSION, "checks": [check]}
        validated, issues = validate_landing_profile(probe)
        if validated is None:
            continue
        candidates_by_id[check_id] = {
            **check,
            "source": "explicit",
            "support": 1,
            "severity_hint": proposal.get("severity_hint") or check.get("severity") or "advisory",
        }

    # 2) Co-occurrence of top-level prefixes across observations.
    pair_support: dict[tuple[str, str], int] = {}
    for observation in observations:
        raw_paths = observation.get("changed_paths")
        if not isinstance(raw_paths, list):
            continue
        prefixes = sorted(
            {
                prefix
                for path in raw_paths
                if isinstance(path, str)
                for prefix in [_top_level_prefix(path)]
                if prefix is not None
            }
        )
        for left_index, left in enumerate(prefixes):
            for right in prefixes[left_index + 1 :]:
                # Propose both directions as co-change hints: when left touched, require right.
                pair_support[(left, right)] = pair_support.get((left, right), 0) + 1
                pair_support[(right, left)] = pair_support.get((right, left), 0) + 1

    for (when_pattern, path_pattern), support in sorted(pair_support.items()):
        if support < min_support:
            continue
        # Avoid proposing exact self-checks or pure root-file to same root-file noise.
        if when_pattern == path_pattern:
            continue
        slug_when = re.sub(r"[^a-z0-9]+", "-", when_pattern.lower()).strip("-")[:24]
        slug_path = re.sub(r"[^a-z0-9]+", "-", path_pattern.lower()).strip("-")[:24]
        check_id = f"cochange-{slug_when}-requires-{slug_path}"[:64]
        if _CHECK_ID_RE.fullmatch(check_id) is None or check_id in existing_ids:
            continue
        if check_id in candidates_by_id and candidates_by_id[check_id].get("source") == "explicit":
            continue
        check = {
            "id": check_id,
            "kind": "path_touched",
            "severity": "advisory",
            "when": {"kind": "any_path_glob", "patterns": [when_pattern]},
            "paths": [path_pattern],
        }
        probe = {"schema_version": PROFILE_SCHEMA_VERSION, "checks": [check]}
        validated, issues = validate_landing_profile(probe)
        if validated is None:
            continue
        prior = candidates_by_id.get(check_id)
        if prior is None or support > int(prior.get("support", 0)):
            candidates_by_id[check_id] = {
                **check,
                "source": "cooccurrence",
                "support": support,
                "severity_hint": "advisory",
            }

    candidates = sorted(candidates_by_id.values(), key=lambda item: item["id"])
    if len(candidates) > MAX_CANDIDATES:
        return _fail(
            "learn_candidates_too_many",
            f"Synthesized candidates exceed the {MAX_CANDIDATES}-item limit.",
        )

    document = {
        "schema_version": LEARN_SCHEMA_VERSION,
        "candidates": candidates,
    }
    write_issue = _atomic_write_json(directory / CANDIDATES_FILE, document)
    if write_issue is not None:
        return _fail(write_issue.code, write_issue.message)
    return _ok(
        "proposed",
        candidates=candidates,
        candidate_count=len(candidates),
        observation_count=len(observations),
        min_support=min_support,
        path=str(RUNTIME_RELATIVE_DIR / CANDIDATES_FILE),
    )


def list_candidates(repo_root: Path) -> LearnResult:
    root = Path(repo_root).resolve()
    document, issue = _load_candidates(root)
    if issue is not None or document is None:
        return _fail(
            issue.code if issue else "learn_candidates_invalid",
            issue.message if issue else "Candidates unreadable.",
        )
    return _ok(
        "listed",
        candidates=document["candidates"],
        candidate_count=len(document["candidates"]),
        path=str(RUNTIME_RELATIVE_DIR / CANDIDATES_FILE),
    )


def promote_candidate(
    repo_root: Path,
    *,
    check_id: str,
    severity: str | None = None,
) -> LearnResult:
    """Promote one candidate into the tracked landing profile. Host-only write."""

    root = Path(repo_root).resolve()
    if _CHECK_ID_RE.fullmatch(check_id) is None:
        return _fail(
            "profile_check_id_invalid",
            f"Check id must match {_CHECK_ID_RE.pattern!r}.",
        )
    document, issue = _load_candidates(root)
    if issue is not None or document is None:
        return _fail(
            issue.code if issue else "learn_candidates_invalid",
            issue.message if issue else "Candidates unreadable.",
        )
    match: dict[str, Any] | None = None
    remaining: list[dict[str, Any]] = []
    for candidate in document["candidates"]:
        if not isinstance(candidate, dict):
            return _fail("learn_candidates_invalid", "Each candidate must be an object.")
        if candidate.get("id") == check_id:
            match = candidate
        else:
            remaining.append(candidate)
    if match is None:
        return _fail(
            "learn_candidate_not_found",
            f"No candidate with id {check_id!r} is present.",
        )

    check = _candidate_check_payload(match)
    if check is None:
        return _fail(
            "learn_candidate_invalid",
            f"Candidate {check_id!r} is not a schema-v1 check shape.",
        )
    if check["kind"] == "path_touched":
        chosen_severity = severity or check.get("severity") or match.get("severity_hint") or "advisory"
        if chosen_severity not in {"blocking", "advisory"}:
            return _fail(
                "profile_severity_invalid",
                "Promote severity must be 'blocking' or 'advisory'.",
            )
        check["severity"] = chosen_severity

    loaded = load_landing_profile(root)
    if loaded.status == "invalid":
        return _fail(
            loaded.diagnostic.code if loaded.diagnostic else "profile_invalid",
            loaded.diagnostic.message if loaded.diagnostic else "Tracked profile is invalid.",
        )
    if loaded.status == "missing":
        new_profile: dict[str, Any] = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "checks": [check],
        }
    else:
        assert loaded.profile is not None
        existing, issues = validate_landing_profile(loaded.profile)
        if existing is None:
            return _fail(
                issues[0].code if issues else "profile_schema_invalid",
                issues[0].message if issues else "Tracked profile failed validation.",
            )
        if check_id in {item.id for item in existing.checks}:
            return _fail(
                "profile_check_id_duplicate",
                f"Tracked profile already contains check id {check_id!r}.",
            )
        if len(existing.checks) + 1 > MAX_CHECKS:
            return _fail(
                "profile_checks_too_large",
                f"Landing profile exceeds the {MAX_CHECKS}-check limit.",
            )
        checks = [item.to_dict() for item in existing.checks]
        checks.append(check)
        checks.sort(key=lambda item: item["id"])
        new_profile = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "checks": checks,
        }

    probe, probe_issues = validate_landing_profile(new_profile)
    if probe is None:
        return _fail(
            probe_issues[0].code if probe_issues else "profile_schema_invalid",
            probe_issues[0].message if probe_issues else "Promoted profile is invalid.",
        )

    write_issue = _atomic_write_profile(root, new_profile)
    if write_issue is not None:
        return _fail(write_issue.code, write_issue.message)

    candidates_path = runtime_dir(root) / CANDIDATES_FILE
    remaining_doc = {
        "schema_version": LEARN_SCHEMA_VERSION,
        "candidates": remaining,
    }
    # Best-effort candidate ledger update; profile write already succeeded.
    _ = _atomic_write_json(candidates_path, remaining_doc)

    return _ok(
        "promoted",
        check_id=check_id,
        check=check,
        profile_path=str(PROFILE_RELATIVE_PATH),
        remaining_candidates=len(remaining),
    )


def set_exact_head_waiver(
    repo_root: Path,
    *,
    check_id: str,
    reason: str,
    base_ref: str = "origin/main",
) -> LearnResult:
    """Record a host-owned exact-HEAD waiver for one check id."""

    root = Path(repo_root).resolve()
    if _CHECK_ID_RE.fullmatch(check_id) is None:
        return _fail(
            "profile_check_id_invalid",
            f"Check id must match {_CHECK_ID_RE.pattern!r}.",
        )
    reason_text, reason_issue = _safe_string(reason, label="reason")
    if reason_issue is not None or reason_text is None:
        return _fail(
            reason_issue.code if reason_issue else "profile_schema_invalid",
            reason_issue.message if reason_issue else "Waiver reason is required.",
        )
    if len(reason_text) > MAX_NOTE_CHARS:
        return _fail(
            "profile_string_too_long",
            f"Waiver reason exceeds the {MAX_NOTE_CHARS}-character limit.",
        )

    directory, issue = _ensure_runtime_dir(root)
    if issue is not None or directory is None:
        return _fail(issue.code, issue.message) if issue else _fail(
            "learn_runtime_unwritable",
            "Landing-profile learning runtime directory unavailable.",
        )

    identity, id_issue = resolve_changed_paths(root, base_ref=base_ref)
    if id_issue is not None or identity is None:
        return _fail(
            id_issue.code if id_issue else "profile_head_unresolved",
            id_issue.message if id_issue else "Could not resolve repository identity.",
        )

    waivers, load_issue = _load_waivers(root)
    if load_issue is not None or waivers is None:
        return _fail(
            load_issue.code if load_issue else "learn_waivers_invalid",
            load_issue.message if load_issue else "Waivers unreadable.",
        )

    head = identity["head"]
    kept = [
        item
        for item in waivers
        if not (item.get("check_id") == check_id and item.get("head") == head)
    ]
    kept.append(
        {
            "check_id": check_id,
            "head": head,
            "reason": reason_text,
        }
    )
    if len(kept) > MAX_WAIVERS:
        return _fail(
            "learn_waivers_too_many",
            f"Waivers exceed the {MAX_WAIVERS}-item limit.",
        )
    write_issue = _save_waivers(root, kept)
    if write_issue is not None:
        return _fail(write_issue.code, write_issue.message)
    return _ok(
        "waived",
        check_id=check_id,
        head=head,
        reason=reason_text,
        path=str(RUNTIME_RELATIVE_DIR / WAIVERS_FILE),
    )


def clear_exact_head_waiver(
    repo_root: Path,
    *,
    check_id: str | None = None,
    head: str | None = None,
) -> LearnResult:
    root = Path(repo_root).resolve()
    waivers, load_issue = _load_waivers(root)
    if load_issue is not None or waivers is None:
        return _fail(
            load_issue.code if load_issue else "learn_waivers_invalid",
            load_issue.message if load_issue else "Waivers unreadable.",
        )
    kept: list[dict[str, Any]] = []
    removed = 0
    for item in waivers:
        match_id = check_id is None or item.get("check_id") == check_id
        match_head = head is None or item.get("head") == head
        if match_id and match_head:
            removed += 1
            continue
        kept.append(item)
    write_issue = _save_waivers(root, kept)
    if write_issue is not None:
        return _fail(write_issue.code, write_issue.message)
    return _ok("cleared", removed=removed, remaining=len(kept))


def active_waivers_for_head(
    repo_root: Path,
    head: str,
) -> tuple[dict[str, str], tuple[ProfileDiagnostic, ...]]:
    """Return check_id -> reason for waivers bound to the exact HEAD."""

    if _EXACT_COMMIT_RE.fullmatch(head) is None:
        return {}, (_diag("profile_head_unresolved", "Waiver head must be an exact commit."),)
    waivers, issue = _load_waivers(repo_root)
    if issue is not None:
        # Fail closed for evaluation when waiver store is corrupt.
        return {}, (issue,)
    if waivers is None:
        return {}, ()
    active: dict[str, str] = {}
    for item in waivers:
        if item.get("head") != head:
            continue
        check_id = item.get("check_id")
        reason = item.get("reason")
        if not isinstance(check_id, str) or _CHECK_ID_RE.fullmatch(check_id) is None:
            return {}, (_diag("learn_waivers_invalid", "Waiver check_id is invalid."),)
        if not isinstance(reason, str) or not reason or len(reason) > MAX_NOTE_CHARS:
            return {}, (_diag("learn_waivers_invalid", "Waiver reason is invalid."),)
        active[check_id] = reason
    return active, ()
