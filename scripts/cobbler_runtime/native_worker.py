"""Host-native worker profiles and exact-session launch specifications."""

from __future__ import annotations

import json
import hashlib
import os
import selectors
import secrets
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .full_run import (
    _git_branch,
    _git_head,
    _is_ancestor,
    _origin_config_digest,
    _read_host_git_identity_value,
    snapshot_protected_refs,
    verify_protected_refs_unchanged,
)
from .context import is_secret_env_name
from .host_profiles import (
    HostLaunchRequest,
    exact_session_id as _registry_exact_session_id,
    host_profile_or_none,
    identity_event_keys,
    native_worker_profile_view,
    provider_secret_names as _registry_provider_secret_names,
    resolve_host_profile,
)
from .prewalk import (
    PREWALK_CONTINUATION_INPUT,
    PREWALK_DEFAULT_TODO_LIMIT,
    PREWALK_MAX_TODO_LIMIT,
    PREWALK_MIN_TODO_LIMIT,
    PREWALK_STATE_VERSION,
    PrewalkCapabilities,
    PrewalkPaths,
    guide_prompt,
    load_and_validate_transition_artifacts,
    observed_changed_paths,
    packet_digest,
    prewalk_paths,
    probe_installed_prewalk_capabilities,
    recovery_prompt,
    validate_meaningful_edit,
    write_session_identity,
)
from .schema import ValidationIssue
from .storage import StorageError, atomic_write_json


PREWALK_QUALIFICATION_TIMEOUT_SECONDS = 180
PREWALK_QUALIFICATION_OUTPUT_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class NativeWorkerSpec:
    host: str
    profile: str
    effort: str
    model_policy: str
    requested_model: str | None
    separate_session: bool
    cwd: str
    argv: tuple[str, ...]
    stdin_packet: bool
    session_id_source: str
    session_id: str | None = None
    resume_argv: tuple[str, ...] | None = None
    cache_handoff: bool = False
    commit_mode: str = "worker_commit"
    visibility_ready: bool = False
    visibility_mode: str = "commit_only"
    watcher_command: str | None = None
    git_write_roots: tuple[str, ...] = ()
    prompt_file_flag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["argv"] = list(self.argv)
        payload["resume_argv"] = list(self.resume_argv) if self.resume_argv else None
        payload["git_write_roots"] = list(self.git_write_roots)
        return payload


@dataclass(frozen=True)
class NativeWorkerPrewalkSpec:
    """Two explicit routes for one exact native-worker trajectory."""

    requested_mode: str
    guide: NativeWorkerSpec
    execution_effort: str
    execution_model: str
    todo_limit: int
    capabilities: PrewalkCapabilities
    instruction_fidelity: str
    execution_fixture_script: str | None = None
    forbidden_paths: tuple[str, ...] = ()

    def execution_spec(self, session_id: str) -> NativeWorkerSpec:
        return build_native_worker_spec(
            host=self.guide.host,
            worktree=Path(self.guide.cwd),
            effort=self.execution_effort,
            requested_model=self.execution_model,
            session_id=session_id,
            visibility_mode=self.guide.visibility_mode,
            watcher_command=self.guide.watcher_command,
            fixture_script=(
                Path(self.execution_fixture_script)
                if self.execution_fixture_script
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": "prewalk",
            "requested_mode": self.requested_mode,
            "guide": self.guide.to_dict(),
            "execution": {
                "host": self.guide.host,
                "effort": self.execution_effort,
                "requested_model": self.execution_model,
                "resume_input": PREWALK_CONTINUATION_INPUT,
                "resume_argv": None,
            },
            "todo_limit": self.todo_limit,
            "capabilities": self.capabilities.to_dict(),
            "instruction_fidelity": self.instruction_fidelity,
            "forbidden_paths": list(self.forbidden_paths),
        }


@dataclass(frozen=True)
class PrewalkQualificationResult:
    """One bounded provider phase used only by the live qualification canary."""

    exit_code: int
    stdout: str
    stderr_tail: str
    observed_session_ids: tuple[str, ...]
    provider_event_count: int
    timed_out: bool = False
    output_limit_exceeded: bool = False


def native_worker_profiles() -> dict[str, dict[str, Any]]:
    """Semantically matched profiles; a view of the host-profile registry."""
    return native_worker_profile_view()


# Canonical exact-session validation lives in the host-profile registry.
_exact_session_id = _registry_exact_session_id


def _git_write_roots(worktree: Path) -> tuple[str, ...]:
    """Return the least-privilege Git roots needed to commit in a linked worktree.

    A linked checkout stores its index and HEAD under ``.git/worktrees`` while
    objects and branch refs live in the common repository. Granting the common
    ``.git`` directory would also grant config, hooks, tags, and protected refs.
    Keep the write surface to the linked-worktree metadata, object store, and
    the parent directories of the exact feature ref and its reflog. Terminal
    verification still rejects any sibling-ref movement.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(worktree.resolve()),
                "rev-parse",
                "--path-format=absolute",
                "--git-dir",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ()
    if result.returncode != 0:
        return ()
    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 2:
        return ()
    workspace = worktree.resolve()
    git_dir, common_dir = (Path(row).resolve() for row in rows)
    # A standalone checkout keeps its metadata under the workspace. This helper
    # exists only for linked-worktree metadata outside the sandbox root.
    try:
        git_dir.relative_to(workspace)
        return ()
    except ValueError:
        pass
    branch_result = subprocess.run(
        ["git", "-C", str(workspace), "symbolic-ref", "--quiet", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    branch_ref = branch_result.stdout.strip()
    if branch_result.returncode != 0 or not branch_ref.startswith("refs/heads/"):
        raise ValidationIssue(
            "native_worker_feature_branch_required",
            "Commit-capable native workers require an attached feature branch",
        )
    relative_ref = Path(branch_ref.removeprefix("refs/heads/"))
    if len(relative_ref.parts) < 2 or any(part in {"", ".", ".."} for part in relative_ref.parts):
        raise ValidationIssue(
            "native_worker_branch_namespace_required",
            "Commit-capable linked workers require a namespaced feature branch",
            hint="Use a branch such as codex/<task> or claude/<task>",
        )
    ref_parent = (common_dir / "refs" / "heads" / relative_ref.parent).resolve()
    log_parent = (common_dir / "logs" / "refs" / "heads" / relative_ref.parent).resolve()
    candidates = (git_dir, common_dir / "objects", ref_parent, log_parent)
    external: list[Path] = []
    for raw_candidate in candidates:
        candidate = raw_candidate.resolve()
        if not candidate.is_dir():
            raise ValidationIssue(
                "native_worker_git_metadata_unavailable",
                "Required linked-worktree Git metadata directory is unavailable",
                path=str(candidate),
            )
        try:
            candidate.relative_to(workspace)
            continue
        except ValueError:
            pass
        if candidate == common_dir:
            raise ValidationIssue(
                "native_worker_git_authority_too_broad",
                "Native worker Git access may not include the shared common directory",
            )
        if candidate in external:
            continue
        external.append(candidate)
    return tuple(str(path) for path in external)


def build_native_worker_spec(
    *,
    host: str,
    worktree: Path,
    effort: str,
    requested_model: str | None = None,
    session_id: str | None = None,
    visibility_mode: str = "commit_only",
    watcher_command: str | None = None,
    fixture_script: Path | None = None,
) -> NativeWorkerSpec:
    host_profile = resolve_host_profile(host)
    effort_token = effort.strip().lower()
    if effort_token not in {"low", "medium", "high"}:
        raise ValidationIssue("invalid_worker_effort", f"Invalid worker effort `{effort}`")
    if not requested_model or not requested_model.strip():
        raise ValidationIssue(
            "current_worker_model_required",
            "Supervised CLI fallback requires the host to pass its observed current model",
            path="requested_model",
        )
    requested_model = requested_model.strip()
    cwd = str(worktree.resolve())
    git_write_roots = _git_write_roots(worktree)
    model_policy = "host_pinned_current_model"
    if visibility_mode not in {"commit_only", "native_host_agent_view", "follow_log"}:
        raise ValidationIssue("invalid_visibility_mode", f"Unknown visibility mode `{visibility_mode}`")
    visibility_ready = visibility_mode in {"native_host_agent_view", "follow_log"}
    if visibility_mode == "follow_log" and not watcher_command:
        raise ValidationIssue("visibility_not_bound", "Follow-log visibility requires an exact watcher command")
    plan = host_profile.launch_plan(
        HostLaunchRequest(
            effort=effort_token,
            requested_model=requested_model,
            cwd=cwd,
            git_write_roots=git_write_roots,
            session_id=session_id,
            fixture_script=fixture_script,
        )
    )
    return NativeWorkerSpec(
        host=host_profile.host,
        profile=host_profile.spec_profile,
        effort=effort_token,
        model_policy=model_policy,
        requested_model=requested_model,
        separate_session=True,
        cwd=cwd,
        argv=plan.argv,
        stdin_packet=plan.stdin_packet,
        session_id_source=plan.session_id_source,
        session_id=plan.session_id,
        resume_argv=plan.resume_argv,
        commit_mode=host_profile.commit_mode,
        visibility_ready=visibility_ready,
        visibility_mode=visibility_mode,
        watcher_command=watcher_command,
        git_write_roots=git_write_roots if host_profile.grants_git_write_roots else (),
        prompt_file_flag=plan.prompt_file_flag,
    )


def build_native_worker_prewalk_spec(
    *,
    host: str,
    worktree: Path,
    guide_effort: str,
    execution_effort: str,
    guide_model: str,
    execution_model: str,
    capabilities: PrewalkCapabilities,
    requested_mode: str = "required",
    todo_limit: int = PREWALK_DEFAULT_TODO_LIMIT,
    visibility_mode: str = "commit_only",
    watcher_command: str | None = None,
    guide_fixture_script: Path | None = None,
    execution_fixture_script: Path | None = None,
    forbidden_paths: tuple[str, ...] = (),
) -> NativeWorkerPrewalkSpec:
    """Build guide-create plus execution-resume policy for one exact session."""
    mode = requested_mode.strip().lower()
    if mode not in {"auto", "required", "experimental"}:
        raise ValidationIssue(
            "invalid_prewalk_mode",
            "Prewalk spec requires auto, required, or experimental mode",
        )
    capability_accepted = (
        capabilities.experimental_eligible()
        if mode == "experimental"
        else capabilities.qualified()
    )
    if not capability_accepted:
        code = capabilities.unavailable_reason() or "prewalk_capability_unavailable"
        raise ValidationIssue(
            code,
            (
                "Experimental prewalk transport lacks required advertised grammar"
                if mode == "experimental"
                else "Exact-session prewalk transport is not behaviorally qualified"
            ),
            hint=capabilities.evidence_source,
        )
    if not isinstance(todo_limit, int) or isinstance(todo_limit, bool) or not PREWALK_MIN_TODO_LIMIT <= todo_limit <= PREWALK_MAX_TODO_LIMIT:
        raise ValidationIssue(
            "prewalk_todo_limit_exceeded",
            f"Prewalk TODO limit must be {PREWALK_MIN_TODO_LIMIT}..{PREWALK_MAX_TODO_LIMIT}",
        )
    launch_profile = resolve_host_profile(host)
    capability_profile = host_profile_or_none(capabilities.host)
    capability_host = (
        capability_profile.capability_host if capability_profile else capabilities.host
    )
    if launch_profile.host != "fixture" and capability_host != launch_profile.capability_host:
        raise ValidationIssue("prewalk_capability_unavailable", "Prewalk capability host does not match launch host")
    if not capabilities.route_matches(
        guide_model=guide_model.strip(),
        guide_effort=guide_effort.strip().lower(),
        execution_model=execution_model.strip(),
        execution_effort=execution_effort.strip().lower(),
    ):
        raise ValidationIssue(
            "prewalk_route_change_unqualified",
            "Behavioral qualification does not match the requested guide/execution routes",
            hint=capabilities.evidence_source,
        )
    guide = build_native_worker_spec(
        host=host,
        worktree=worktree,
        effort=guide_effort,
        requested_model=guide_model,
        visibility_mode=visibility_mode,
        watcher_command=watcher_command,
        fixture_script=guide_fixture_script,
    )
    result = NativeWorkerPrewalkSpec(
        requested_mode=mode,
        guide=guide,
        execution_effort=execution_effort.strip().lower(),
        execution_model=execution_model.strip(),
        todo_limit=todo_limit,
        capabilities=capabilities,
        instruction_fidelity=capabilities.instruction_fidelity,
        execution_fixture_script=(
            str(execution_fixture_script.resolve(strict=True))
            if execution_fixture_script
            else str(guide_fixture_script.resolve(strict=True))
            if guide_fixture_script
            else None
        ),
        forbidden_paths=tuple(forbidden_paths),
    )
    result.execution_spec(guide.session_id or "prewalk-session-preview")
    return result


def _qualification_cache_root(
    *, cache_root: Path | None = None, env: dict[str, str] | None = None
) -> Path:
    if cache_root is not None:
        root = cache_root.expanduser()
    else:
        values = os.environ if env is None else env
        configured = values.get("XDG_CACHE_HOME", "").strip()
        if configured and not Path(configured).expanduser().is_absolute():
            raise ValidationIssue(
                "prewalk_capability_unavailable",
                "XDG_CACHE_HOME must be absolute for prewalk qualification evidence",
                path="XDG_CACHE_HOME",
            )
        root = (
            Path(configured).expanduser()
            if configured
            else Path(values.get("HOME", "~")).expanduser() / ".cache"
        )
    return root.resolve() / "elves" / "prewalk"


def prewalk_qualification_cache_path(
    capabilities: PrewalkCapabilities,
    *,
    guide_model: str,
    guide_effort: str,
    execution_model: str,
    execution_effort: str,
    cache_root: Path | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Return the private cache key for one installed build and route pair."""
    identity = {
        "host": capabilities.host,
        "transport": capabilities.transport,
        "installed_version": capabilities.installed_version,
        "installed_build_commit": capabilities.installed_build_commit,
        "guide": {"model": guide_model, "effort": guide_effort},
        "execution": {"model": execution_model, "effort": execution_effort},
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return _qualification_cache_root(cache_root=cache_root, env=env) / (
        f"{capabilities.host}-{digest}.json"
    )


def _terminate_canary_process(child: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _run_bounded_qualification_phase(
    *,
    spec: NativeWorkerSpec,
    input_text: str,
    child_env: dict[str, str],
    timeout_seconds: float,
) -> PrewalkQualificationResult:
    """Run one canary phase with a hard wall limit and bounded output."""
    if timeout_seconds <= 0:
        return PrewalkQualificationResult(
            exit_code=124,
            stdout="",
            stderr_tail="qualification deadline exhausted",
            observed_session_ids=(),
            provider_event_count=0,
            timed_out=True,
        )
    worktree = Path(spec.cwd).resolve()
    prompt_path: Path | None = None
    child: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    argv = list(spec.argv)
    stdin_handle = tempfile.TemporaryFile(mode="w+b")
    try:
        if spec.prompt_file_flag:
            prompt_fd, prompt_name = tempfile.mkstemp(
                prefix=".qualification-prompt-",
                suffix=".txt",
                dir=str(worktree),
                text=True,
            )
            prompt_path = Path(prompt_name)
            os.fchmod(prompt_fd, 0o600)
            with os.fdopen(prompt_fd, "w", encoding="utf-8") as handle:
                handle.write(input_text)
                handle.flush()
                os.fsync(handle.fileno())
            argv.extend((spec.prompt_file_flag, str(prompt_path)))
        else:
            stdin_handle.write(input_text.encode("utf-8"))
            stdin_handle.flush()
            stdin_handle.seek(0)
        child = subprocess.Popen(
            argv,
            cwd=str(worktree),
            env=child_env,
            stdin=subprocess.DEVNULL if spec.prompt_file_flag else stdin_handle,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            close_fds=True,
            start_new_session=True,
        )
        assert child.stdout is not None and child.stderr is not None
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ, "stdout")
        selector.register(child.stderr, selectors.EVENT_READ, "stderr")
        chunks: dict[str, bytearray] = {
            "stdout": bytearray(),
            "stderr": bytearray(),
        }
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        output_limit_exceeded = False
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _terminate_canary_process(child)
                break
            events = selector.select(timeout=min(0.2, remaining))
            for key, _ in events:
                data = os.read(key.fileobj.fileno(), 8192)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                target = chunks[str(key.data)]
                if (
                    len(chunks["stdout"])
                    + len(chunks["stderr"])
                    + len(data)
                    > PREWALK_QUALIFICATION_OUTPUT_MAX_BYTES
                ):
                    output_limit_exceeded = True
                    _terminate_canary_process(child)
                    break
                target.extend(data)
            if output_limit_exceeded:
                break
        if child.poll() is None:
            _terminate_canary_process(child)
        exit_code = child.wait()
        stdout = chunks["stdout"].decode("utf-8", errors="replace")
        stderr = chunks["stderr"].decode("utf-8", errors="replace")
        observed: list[str] = []
        provider_event_count = 0
        for line in stdout.splitlines():
            event = _parse_provider_event(line)
            if event is None:
                continue
            provider_event_count += 1
            session_id = _provider_session_id_from_event(event, host=spec.host)
            if session_id and session_id not in observed:
                observed.append(session_id)
        return PrewalkQualificationResult(
            exit_code=(
                124
                if timed_out
                else 125
                if output_limit_exceeded
                else exit_code
            ),
            stdout=stdout,
            stderr_tail=stderr[-_NATIVE_WORKER_STDERR_TAIL_CHARS:],
            observed_session_ids=tuple(observed),
            provider_event_count=provider_event_count,
            timed_out=timed_out,
            output_limit_exceeded=output_limit_exceeded,
        )
    finally:
        if selector is not None:
            selector.close()
        if child is not None:
            if child.stdout is not None:
                child.stdout.close()
            if child.stderr is not None:
                child.stderr.close()
        stdin_handle.close()
        if prompt_path is not None:
            prompt_path.unlink(missing_ok=True)


def _write_qualification_artifact(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        atomic_write_json(path, payload, mode=0o600)
    except (OSError, StorageError) as exc:
        raise ValidationIssue(
            "prewalk_capability_unavailable",
            "Unable to persist private prewalk qualification evidence",
            path=str(path),
        ) from exc


def _load_cached_qualification(
    *,
    host: str,
    path: Path,
) -> PrewalkCapabilities:
    return probe_installed_prewalk_capabilities(
        host,
        behavioral_evidence=path,
    )


@contextmanager
def _capture_qualification_failure(diagnostics: list[str]) -> Any:
    """Convert unexpected canary failures into persisted attempt evidence."""
    try:
        yield
    except Exception as exc:
        diagnostics.append(f"{type(exc).__name__}: {exc}")


def qualify_installed_prewalk_transport(
    *,
    host: str,
    guide_model: str,
    guide_effort: str,
    execution_model: str,
    execution_effort: str,
    cache_root: Path | None = None,
    timeout_seconds: int = PREWALK_QUALIFICATION_TIMEOUT_SECONDS,
    phase_runner: Any = None,
) -> PrewalkCapabilities:
    """Load matching proof or run a bounded two-turn live qualification canary.

    This function is called only for an explicit ``required`` launch. It never
    edits the target checkout. A temporary Git worktree holds one changing
    canary file whose unknown contents prove both phases used the same CWD.
    """
    advertised = probe_installed_prewalk_capabilities(host)
    if not advertised.experimental_eligible():
        raise ValidationIssue(
            advertised.unavailable_reason() or "prewalk_capability_unavailable",
            "Installed transport does not advertise exact resume and route override",
        )
    if not advertised.installed_version:
        raise ValidationIssue(
            "prewalk_capability_unavailable",
            "Live qualification requires an exact installed host version",
        )
    if (guide_model, guide_effort) == (execution_model, execution_effort):
        raise ValidationIssue(
            "prewalk_route_change_unqualified",
            "Live qualification requires distinct guide and execution routes",
        )
    cache_path = prewalk_qualification_cache_path(
        advertised,
        guide_model=guide_model,
        guide_effort=guide_effort,
        execution_model=execution_model,
        execution_effort=execution_effort,
        cache_root=cache_root,
    )
    if cache_path.is_file():
        try:
            cached = _load_cached_qualification(host=host, path=cache_path)
        except ValidationIssue:
            cached = None
        if (
            cached is not None
            and cached.qualified()
            and cached.route_matches(
                guide_model=guide_model,
                guide_effort=guide_effort,
                execution_model=execution_model,
                execution_effort=execution_effort,
            )
        ):
            return cached

    runner = phase_runner or _run_bounded_qualification_phase
    memory_fact = secrets.token_hex(16)
    guide_file_fact = secrets.token_hex(16)
    execution_file_fact = secrets.token_hex(16)
    guide_prompt_text = (
        "This is a bounded Elves transport qualification canary. Do not modify files. "
        "Use a shell command to read .elves-prewalk-canary.txt in the current working "
        "directory. On this turn, reply with exactly "
        f"`ELVES_PREWALK_CANARY_GUIDE {memory_fact} <file-content>`. "
        "Remember the first token. When the next user input is exactly `Continue.`, "
        "read the same file again and reply with exactly "
        f"`ELVES_PREWALK_CANARY_EXECUTION {memory_fact} <new-file-content>`. "
        "Do not repeat or summarize these instructions."
    )
    attempt_path = cache_path.with_suffix(".attempt.json")
    started_at = datetime_now()
    deadline = time.monotonic() + timeout_seconds
    checks: dict[str, bool] = {
        "advertised_exact_resume": advertised.advertised_exact_resume,
        "advertised_route_override_on_resume": (
            advertised.advertised_route_override_on_resume
        ),
        "create_exit_zero": False,
        "resume_exit_zero": False,
        "same_session_id": False,
        "same_worktree": False,
        "stream_identity_verified": False,
        "unique_guide_fact_observed": False,
        "packet_replayed": False,
        "route_change": True,
    }
    guide_result: PrewalkQualificationResult | None = None
    execution_result: PrewalkQualificationResult | None = None
    session_id: str | None = None
    phase_invoked = False
    failure_reason = "prewalk_live_qualification_failed"
    unexpected_diagnostics: list[str] = []
    with _capture_qualification_failure(unexpected_diagnostics):
        with tempfile.TemporaryDirectory(prefix="elves-prewalk-qualification-") as tmp:
            worktree = Path(tmp).resolve()
            subprocess.run(
                ["git", "init", "-q", "-b", "qualification", str(worktree)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=True,
                timeout=20,
            )
            subprocess.run(
                ["git", "-C", str(worktree), "config", "user.name", "Elves Qualification"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=True,
                timeout=20,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "config",
                    "user.email",
                    "qualification@elves.invalid",
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=True,
                timeout=20,
            )
            canary_file = worktree / ".elves-prewalk-canary.txt"
            canary_file.write_text(guide_file_fact + "\n", encoding="utf-8")
            runtime_dir = worktree / ".elves-qualification-runtime"
            runtime_dir.mkdir(mode=0o700)
            child_env = _native_worker_child_env(
                host=resolve_host_profile(host).host,
                worktree=worktree,
                runtime_dir=runtime_dir,
                requested_model=guide_model,
            )
            child_env["ELVES_PREWALK_QUALIFICATION"] = "1"
            guide_spec = build_native_worker_spec(
                host=host,
                worktree=worktree,
                effort=guide_effort,
                requested_model=guide_model,
            )
            phase_invoked = True
            guide_result = runner(
                spec=guide_spec,
                input_text=guide_prompt_text,
                child_env=child_env,
                timeout_seconds=max(1.0, deadline - time.monotonic()),
            )
            checks["create_exit_zero"] = guide_result.exit_code == 0
            guide_marker = (
                f"ELVES_PREWALK_CANARY_GUIDE {memory_fact} {guide_file_fact}"
            )
            checks["unique_guide_fact_observed"] = (
                guide_marker in guide_result.stdout
            )
            session_id = guide_spec.session_id or (
                guide_result.observed_session_ids[0]
                if guide_result.observed_session_ids
                else None
            )
            if session_id and (
                not guide_result.observed_session_ids
                or session_id in guide_result.observed_session_ids
            ):
                canary_file.write_text(execution_file_fact + "\n", encoding="utf-8")
                execution_spec = build_native_worker_spec(
                    host=host,
                    worktree=worktree,
                    effort=execution_effort,
                    requested_model=execution_model,
                    session_id=session_id,
                )
                execution_result = runner(
                    spec=execution_spec,
                    input_text=PREWALK_CONTINUATION_INPUT,
                    child_env=child_env,
                    timeout_seconds=max(1.0, deadline - time.monotonic()),
                )
                checks["resume_exit_zero"] = execution_result.exit_code == 0
                execution_marker = (
                    "ELVES_PREWALK_CANARY_EXECUTION "
                    f"{memory_fact} {execution_file_fact}"
                )
                checks["same_worktree"] = execution_marker in execution_result.stdout
                checks["same_session_id"] = bool(
                    session_id
                    and guide_result.observed_session_ids
                    and execution_result.observed_session_ids
                    and set(guide_result.observed_session_ids) == {session_id}
                    and set(execution_result.observed_session_ids) == {session_id}
                )
                checks["stream_identity_verified"] = bool(
                    checks["same_session_id"]
                    and guide_result.provider_event_count
                    and execution_result.provider_event_count
                )
            checks["packet_replayed"] = False

    qualified = all(
        (
            checks["advertised_exact_resume"],
            checks["advertised_route_override_on_resume"],
            checks["create_exit_zero"],
            checks["resume_exit_zero"],
            checks["same_session_id"],
            checks["same_worktree"],
            checks["stream_identity_verified"],
            checks["unique_guide_fact_observed"],
            not checks["packet_replayed"],
            checks["route_change"],
        )
    )
    from .context import redact_text

    diagnostic = redact_text(
        "\n".join(
            part
            for part in (
            execution_result.stderr_tail
            if execution_result and execution_result.exit_code != 0
            else guide_result.stderr_tail
            if guide_result and guide_result.exit_code != 0
            else "",
            *unexpected_diagnostics,
            )
            if part
        )
    ).text[-2_000:]
    attempt_payload: dict[str, Any] = {
        "artifact_type": "native_prewalk_qualification_attempt",
        "schema_version": 1,
        "host": advertised.host,
        "transport": advertised.transport,
        "installed_version": advertised.installed_version,
        "installed_build_commit": advertised.installed_build_commit,
        "started_at": started_at,
        "completed_at": datetime_now(),
        "timeout_seconds": timeout_seconds,
        "model_calls_made": phase_invoked,
        "guide_route": {"model": guide_model, "effort": guide_effort},
        "execution_route": {
            "model": execution_model,
            "effort": execution_effort,
        },
        "session_id": session_id,
        "checks": checks,
        "qualified": qualified,
        "failure_reason": None if qualified else failure_reason,
        "diagnostic": diagnostic or None,
        "guide_prompt_sha256": hashlib.sha256(
            guide_prompt_text.encode("utf-8")
        ).hexdigest(),
        "continuation_sha256": hashlib.sha256(
            PREWALK_CONTINUATION_INPUT.encode("utf-8")
        ).hexdigest(),
        "packet_sent_count": 1,
    }
    _write_qualification_artifact(attempt_path, attempt_payload)
    if not qualified or not session_id:
        raise ValidationIssue(
            failure_reason,
            "Live prewalk qualification did not prove every required transport fact",
            hint=f"Evidence: {attempt_path}",
        )

    if advertised.host == "grok":
        if not advertised.installed_build_commit:
            raise ValidationIssue(
                "prewalk_capability_unavailable",
                "Grok live qualification requires an installed build commit",
                hint=f"Attempt evidence: {attempt_path}",
            )
        success_payload: dict[str, Any] = {
            "artifact_type": "grok_prewalk_qualification_canary",
            "schema_version": 1,
            "host": "grok",
            "transport": "grok_build",
            "installed_version": advertised.installed_version,
            "installed_build_commit": advertised.installed_build_commit,
            "session_id": session_id,
            "guide_route": {"model": guide_model, "effort": guide_effort},
            "execution_route": {
                "model": execution_model,
                "effort": execution_effort,
            },
            "create_exit_code": 0,
            "resume_exit_code": 0,
            "same_session_id": True,
            "same_worktree": True,
            "stream_identity_verified": True,
            "unique_guide_fact_observed": True,
            "packet_replayed": False,
            "model_calls_made": True,
            "instruction_fidelity": "retained_safe",
        }
    else:
        success_payload = {
            "artifact_type": "native_prewalk_behavioral_qualification",
            "schema_version": 1,
            "host": advertised.host,
            "transport": advertised.transport,
            "installed_version": advertised.installed_version,
            "session_id": session_id,
            "create_exit_code": 0,
            "resume_exit_code": 0,
            "same_session_id": True,
            "same_worktree": True,
            "unique_guide_fact_observed": True,
            "packet_replayed": False,
            "stream_identity_verified": True,
            "instruction_fidelity": "retained_safe",
            "guide_route": {"model": guide_model, "effort": guide_effort},
            "execution_route": {
                "model": execution_model,
                "effort": execution_effort,
            },
            "model_calls_made": True,
            "guide_prompt_sha256": attempt_payload["guide_prompt_sha256"],
            "continuation_sha256": attempt_payload["continuation_sha256"],
        }
    _write_qualification_artifact(cache_path, success_payload)
    loaded = _load_cached_qualification(host=host, path=cache_path)
    if not loaded.qualified():
        raise ValidationIssue(
            "prewalk_live_qualification_failed",
            "Saved live qualification evidence did not revalidate",
            hint=f"Evidence: {cache_path}",
        )
    return loaded


def parse_codex_thread_id(jsonl: str) -> str:
    """Capture the exact Codex worker thread id from structured launch output."""
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            return _exact_session_id(event["thread_id"])
    raise ValidationIssue("worker_session_id_missing", "Codex output did not contain thread.started.thread_id")


_NATIVE_WORKER_STDERR_TAIL_CHARS = 2_000
_PREWALK_TRANSIENT_BACKOFF_SECONDS = (300, 600, 1_200)
_TRANSIENT_PROVIDER_MARKERS = (
    "429",
    "503",
    "connection reset",
    "network error",
    "over capacity",
    "overloaded",
    "rate limit",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "too many requests",
)


def _transient_provider_failure(text: str) -> bool:
    normalized = text.casefold()
    return any(marker in normalized for marker in _TRANSIENT_PROVIDER_MARKERS)


# Structured stdout event types that report a provider/transport error. Only
# these stdout events may contribute to transient-failure classification; task
# narration on stdout (for example a worker discussing a "timeout" bug) never
# does. Stderr lines remain in scope unconditionally.
_PROVIDER_ERROR_EVENT_TYPES = frozenset({"error", "turn.failed", "thread.error", "stream_error"})


def _parse_provider_event(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(event, dict) and isinstance(event.get("type"), str):
        return event
    return None


def _is_provider_error_event(event: dict[str, Any]) -> bool:
    return event.get("type") in _PROVIDER_ERROR_EVENT_TYPES


def _run_key(run_id: str) -> str:
    if not run_id.strip() or run_id.startswith("-"):
        raise ValidationIssue("invalid_native_worker_run_id", "An exact native worker run id is required")
    safe = "".join(ch if ch.isalnum() else "_" for ch in run_id)[:24]
    return f"{safe}-{hashlib.sha256(run_id.encode()).hexdigest()[:16]}"


def native_worker_paths(repo_root: Path, run_id: str) -> tuple[Path, Path]:
    root = repo_root.resolve() / ".elves" / "runtime" / "native-worker" / _run_key(run_id)
    return root / "state.json", root / "follow.jsonl"


def _write_private_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _process_start(pid: int) -> str | None:
    try:
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, check=False)
        return result.stdout.strip() or None
    except OSError:
        return None


def _process_identity_matches(pid_value: object, expected_start: object) -> bool | None:
    """Return exact identity match, known process loss, or unavailable identity."""
    if not pid_value:
        return None
    pid = int(pid_value)
    observed_start = _process_start(pid)
    if observed_start is not None:
        return observed_start == expected_start if expected_start else None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    return None


def _native_git_contract(worktree: Path) -> dict[str, Any]:
    """Capture the feature-only Git authority contract without a network probe."""
    branch = _git_branch(worktree)
    head = _git_head(worktree)
    if not branch or not head:
        raise ValidationIssue(
            "native_worker_feature_branch_required",
            "Native worker launch requires an attached feature branch with a valid tip",
        )
    return {
        "assigned_branch": branch,
        "start_head": head,
        "protected_refs": snapshot_protected_refs(
            worktree, feature_branch=branch, include_remote=False
        ),
        "origin_config_digest": _origin_config_digest(worktree),
    }


def _omp_provider_secret_for_model(requested_model: str | None) -> tuple[str, ...]:
    """Map a pinned omp model selector to preferred provider secret names."""
    model = (requested_model or "").strip().lower()
    if any(token in model for token in ("anthropic", "claude")):
        return ("ANTHROPIC_API_KEY",)
    if any(token in model for token in ("xai", "grok")):
        return ("XAI_API_KEY",)
    if any(token in model for token in ("gemini", "google/")):
        return ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if any(token in model for token in ("openai", "gpt-", "codex", "o1", "o3", "o4")):
        return ("OPENAI_API_KEY", "CODEX_API_KEY")
    # Unknown model: stable fallback order (still one secret only).
    return (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "XAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    )


def _native_worker_child_env(
    *, host: str, worktree: Path, runtime_dir: Path, requested_model: str | None = None
) -> dict[str, str]:
    """Project provider auth while removing ambient Git/network credentials."""
    parent = dict(os.environ)
    provider_secret_names = _registry_provider_secret_names(host)
    forbidden_exact = {
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GITLAB_TOKEN",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "GCM_INTERACTIVE",
    }
    env: dict[str, str] = {}
    omp_host = bool(
        host_profile_or_none(host) and resolve_host_profile(host).capability_host == "omp"
    )
    for name, value in parent.items():
        if name in forbidden_exact or name.startswith("GIT_"):
            continue
        if is_secret_env_name(name) and name not in provider_secret_names:
            continue
        # OMP: strip allowlisted provider secrets here; re-add exactly one below.
        if omp_host and name in provider_secret_names:
            continue
        env[name] = value
    # Each host may need only its registry-allowlisted provider auth names
    # (subscription tokens for Codex/Claude; XAI_API_KEY/GROK_AUTH_PATH for
    # Grok). No other secret-valued environment entry crosses the boundary.
    # OMP multi-provider allowlist: project exactly one credential, preferred
    # by the pinned model provider when known.
    if omp_host:
        omp_order = _omp_provider_secret_for_model(requested_model)
        selected = next((n for n in omp_order if n in provider_secret_names and parent.get(n)), None)
        if selected:
            env[selected] = parent[selected]
    else:
        for name in provider_secret_names:
            if parent.get(name):
                env[name] = parent[name]

    empty_gh = runtime_dir / "empty-gh-config"
    empty_gh.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(empty_gh, 0o700)
    false_executable = "/usr/bin/false" if Path("/usr/bin/false").exists() else "false"
    env.update(
        {
            "GH_CONFIG_DIR": str(empty_gh),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": false_executable,
            "SSH_ASKPASS": false_executable,
            "GIT_SSH_COMMAND": false_executable,
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "",
            "GIT_CONFIG_KEY_1": "remote.origin.pushurl",
            "GIT_CONFIG_VALUE_1": "disabled://native-worker-no-push",
        }
    )
    if host != "fixture":
        name = _read_host_git_identity_value(worktree, "user.name", parent_env=parent)
        email = _read_host_git_identity_value(worktree, "user.email", parent_env=parent)
        env.update(
            {
                "GIT_AUTHOR_NAME": name,
                "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_NAME": name,
                "GIT_COMMITTER_EMAIL": email,
            }
        )
    return env


def _verify_native_git_contract(worktree: Path, state: dict[str, Any]) -> list[str]:
    """Verify feature ancestry, origin config, and every protected local ref."""
    errors: list[str] = []
    branch = _git_branch(worktree)
    head = _git_head(worktree)
    expected_branch = str(state.get("assigned_branch") or "")
    start_head = str(state.get("start_head") or "")
    if branch != expected_branch:
        errors.append(
            f"assigned branch changed: expected {expected_branch or '<missing>'}, observed {branch or '<detached>'}"
        )
    if not head or not start_head or not _is_ancestor(worktree, start_head, head):
        errors.append("final feature tip is not a descendant of the registered start tip")
    if _origin_config_digest(worktree) != state.get("origin_config_digest"):
        errors.append("origin configuration changed during native worker execution")
    expected_refs = state.get("protected_refs")
    if not isinstance(expected_refs, dict):
        errors.append("protected-ref snapshot is missing")
    else:
        errors.extend(
            verify_protected_refs_unchanged(
                worktree,
                expected_refs,
                feature_branch=expected_branch,
                include_remote=False,
            )
        )
    return errors


@dataclass(frozen=True)
class _PhaseResult:
    exit_code: int
    provider_event_count: int
    stderr_tail: str | None
    runtime_seconds: float
    observed_session_ids: tuple[str, ...]
    session_mismatch: bool
    transient_transport_failure: bool


def _worktree_clean(worktree: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result.returncode == 0 and not result.stdout.strip()


# Identity is event-typed: only the documented identity/continuity events for
# each host may bind or challenge session identity. Codex publishes
# `thread.started.thread_id` at create and `turn.*` continuity events; Claude
# Code sessions are caller-preset UUIDs whose stream confirms identity via the
# `system`/`init` event; Grok Build sessions are caller-preset UUIDs whose
# terminal `end` event may confirm identity via `sessionId`. Arbitrary typed
# lines (for example a worker log event that merely mentions a `session_id`)
# must never bind or mismatch identity. The per-host event vocabulary is
# registry data: see `host_profiles.identity_event_keys`.


def _provider_session_id(line: str, host: str | None = None) -> str | None:
    event = _parse_provider_event(line)
    if event is None:
        return None
    return _provider_session_id_from_event(event, host=host)


def _provider_session_id_from_event(
    event: dict[str, Any], host: str | None = None
) -> str | None:
    event_type = str(event["type"])
    keys = identity_event_keys(host).get(event_type)
    if keys is None:
        return None
    if event_type == "system" and event.get("subtype") != "init":
        return None
    for key in keys:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            try:
                return _exact_session_id(value)
            except ValidationIssue:
                return None
    return None


def _authority_errors(worktree: Path, state: dict[str, Any]) -> list[str]:
    return (
        []
        if state.get("git_authority_mode") == "fixture"
        else _verify_native_git_contract(worktree, state)
    )


def _set_status(state: dict[str, Any], status: str) -> None:
    state["status"] = status
    if state.get("version") == PREWALK_STATE_VERSION:
        history = state.setdefault("status_history", [])
        if not history or history[-1].get("status") != status:
            history.append({"status": status, "at": datetime_now()})


def _final_head(worktree: Path) -> str | None:
    return (
        subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        ).stdout.strip()
        or None
    )


def _run_worker_phase(
    *,
    state_path: Path,
    log_path: Path,
    state: dict[str, Any],
    phase: str,
    argv: tuple[str, ...],
    input_text: str,
    child_env: dict[str, str],
    expected_session_id: str | None,
    prompt_file_flag: str | None = None,
) -> _PhaseResult:
    from .context import redact_text

    is_prewalk_run = state.get("mode") == "prewalk"
    phase_key = "prewalk" if phase.startswith("prewalk") else "execution"
    phase_state = state.get(phase_key) if is_prewalk_run else None
    if is_prewalk_run and not isinstance(phase_state, dict):
        raise ValidationIssue("prewalk_checkpoint_invalid", f"Missing `{phase_key}` phase state")
    worktree = Path(str(state["worktree"])).resolve()
    env = dict(child_env)
    env["ELVES_NATIVE_WORKER_PHASE"] = phase
    if is_prewalk_run:
        paths = state["prewalk"]["paths"]
        env.update(
            {
                "ELVES_PREWALK_RUN_ID": str(state["run_id"]),
                "ELVES_PREWALK_SESSION_ID": str(state.get("session_id") or ""),
                "ELVES_PREWALK_TODO_PATH": str(paths["todo"]),
                "ELVES_PREWALK_CHECKPOINT_PATH": str(paths["checkpoint"]),
                "ELVES_PREWALK_SESSION_PATH": str(paths["session_identity"]),
            }
        )
    provider_event_count = 0
    stderr_tail = ""
    observed_session_ids: list[str] = []
    session_mismatch = False
    transient_transport_failure = False
    child_started = time.monotonic()
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    prompt_path: Path | None = None
    effective_argv = list(argv)
    if prompt_file_flag:
        prompt_fd, prompt_name = tempfile.mkstemp(
            prefix=".prewalk-prompt-",
            suffix=".txt",
            dir=str(worktree),
            text=True,
        )
        prompt_path = Path(prompt_name)
        try:
            os.fchmod(prompt_fd, 0o600)
            with os.fdopen(prompt_fd, "w", encoding="utf-8") as prompt_handle:
                prompt_handle.write(input_text)
                prompt_handle.flush()
                os.fsync(prompt_handle.fileno())
        except BaseException:
            try:
                os.close(prompt_fd)
            except OSError:
                pass
            prompt_path.unlink(missing_ok=True)
            raise
        effective_argv.extend((prompt_file_flag, str(prompt_path)))
    try:
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as child_input, log_path.open(
            "a", encoding="utf-8"
        ) as log:
            child_input.write(input_text)
            child_input.flush()
            child_input.seek(0)
            os.chmod(log_path, 0o600)
            child = subprocess.Popen(
                effective_argv,
                cwd=str(worktree),
                env=env,
                stdin=subprocess.DEVNULL if prompt_file_flag else child_input,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                close_fds=True,
            )
            state["pid"] = child.pid
            state["pid_start"] = _process_start(child.pid)
            _set_status(state, (
                "prewalking"
                if is_prewalk_run and phase_key == "prewalk"
                else "executing"
                if is_prewalk_run
                else "running"
            ))
            phase_attempt: dict[str, Any] | None = None
            if isinstance(phase_state, dict):
                phase_state["pid"] = child.pid
                phase_state["pid_start"] = state["pid_start"]
                phase_state["started_at"] = datetime_now()
                phase_state["argv"] = effective_argv
                phase_attempt = {
                    "phase": phase,
                    "pid": child.pid,
                    "pid_start": state["pid_start"],
                    "started_at": phase_state["started_at"],
                    "argv": effective_argv,
                }
                phase_state.setdefault("attempts", []).append(phase_attempt)
            _write_private_json(state_path, state)
            selector = selectors.DefaultSelector()
            assert child.stdout is not None and child.stderr is not None
            selector.register(child.stdout, selectors.EVENT_READ, "stdout")
            selector.register(child.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                for key, _ in selector.select(timeout=0.2):
                    line = key.fileobj.readline()
                    if not line:
                        selector.unregister(key.fileobj)
                        continue
                    redacted = redact_text(line.rstrip("\n"))
                    # Transient markers classify transport health only: stderr
                    # lines and structured provider error events. Task stdout
                    # content never flips the transient classification.
                    if key.data == "stderr" and _transient_provider_failure(redacted.text):
                        transient_transport_failure = True
                    wrapper = {"stream": key.data, "line": redacted.text}
                    if is_prewalk_run:
                        wrapper["phase"] = phase
                    log.write(json.dumps(wrapper, sort_keys=True) + "\n")
                    log.flush()
                    event = _parse_provider_event(line) if key.data == "stdout" else None
                    if event is not None:
                        provider_event_count += 1
                        if _is_provider_error_event(event) and _transient_provider_failure(
                            redacted.text
                        ):
                            transient_transport_failure = True
                        observed = _provider_session_id_from_event(
                            event, host=str(state.get("host")) if state.get("host") else None
                        )
                        if observed:
                            if observed not in observed_session_ids:
                                observed_session_ids.append(observed)
                            bound_session_id = expected_session_id or state.get("session_id")
                            if bound_session_id and observed != bound_session_id:
                                session_mismatch = True
                            if not state.get("session_id"):
                                state["session_id"] = observed
                                if is_prewalk_run:
                                    write_session_identity(
                                        Path(state["prewalk"]["paths"]["session_identity"]),
                                        worktree=worktree,
                                        run_id=str(state["run_id"]),
                                        session_id=observed,
                                    )
                                _write_private_json(state_path, state)
                    elif key.data == "stderr":
                        stderr_tail = (stderr_tail + redacted.text + "\n")[
                            -_NATIVE_WORKER_STDERR_TAIL_CHARS:
                        ]
            code = child.wait()
            for stream in (child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
    finally:
        if prompt_path is not None:
            prompt_path.unlink(missing_ok=True)
    runtime_seconds = round(time.monotonic() - child_started, 3)
    if isinstance(phase_state, dict):
        phase_state["ended_at"] = datetime_now()
        phase_state["exit_code"] = code
        phase_state["provider_event_count"] = provider_event_count
        phase_state["runtime_seconds"] = runtime_seconds
        if phase_attempt is not None:
            phase_attempt.update(
                {
                    "ended_at": phase_state["ended_at"],
                    "exit_code": code,
                    "provider_event_count": provider_event_count,
                    "runtime_seconds": runtime_seconds,
                }
            )
    state["provider_event_count"] = int(state.get("provider_event_count") or 0) + provider_event_count
    # Preserve the bounded stderr tail on any failing exit, including runs
    # that emitted provider events: transport diagnostics often land on
    # stderr after the stream started.
    state["stderr_tail"] = (
        stderr_tail.rstrip("\n") if code != 0 and stderr_tail else None
    )
    _write_private_json(state_path, state)
    return _PhaseResult(
        exit_code=code,
        provider_event_count=provider_event_count,
        stderr_tail=state["stderr_tail"],
        runtime_seconds=runtime_seconds,
        observed_session_ids=tuple(observed_session_ids),
        session_mismatch=session_mismatch,
        transient_transport_failure=transient_transport_failure,
    )


def datetime_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _terminalize_native_worker(
    *,
    state_path: Path,
    state: dict[str, Any],
    worktree: Path,
    exit_code: int,
    failure_reason: str | None = None,
) -> int:
    prior_status = str(state.get("status") or "")
    # A hung git helper must never prevent the terminal state write.
    authority_timed_out = False
    try:
        errors = _authority_errors(worktree, state)
    except subprocess.TimeoutExpired:
        authority_timed_out = True
        errors = ["git authority verification timed out"]
    state["exit_code"] = exit_code
    state["authority_verified"] = not errors
    state["authority_errors"] = errors
    try:
        state["final_head"] = _final_head(worktree)
    except subprocess.TimeoutExpired:
        state["final_head"] = None
    if errors:
        _set_status(state, "failed")
        # A timed-out verification is an infrastructure failure, not evidence
        # of worker misbehavior; only a real check failure is a violation.
        state["failure_reason"] = (
            "native_worker_git_timeout"
            if authority_timed_out and len(errors) == 1
            else "native_worker_git_authority_violation"
        )
    elif failure_reason:
        _set_status(state, "failed")
        state["failure_reason"] = failure_reason
        if failure_reason.startswith("prewalk_"):
            phase = "execution" if "execution" in prior_status else "prewalk"
            if prior_status == "transition_ready":
                phase = "transition"
            state["failure"] = {
                "code": failure_reason,
                "phase": phase,
                "host": state.get("host"),
                "run_id": state.get("run_id"),
                "session_id": state.get("session_id"),
                "worktree": str(worktree),
                "suggested_recovery": (
                    "resume the exact recorded execution session; do not rerun prewalk"
                    if phase == "execution"
                    else "resume the exact recorded guide session or preserve the worktree and stop"
                ),
            }
    else:
        _set_status(state, "complete" if exit_code == 0 else "failed")
        if exit_code != 0:
            state["failure_reason"] = (
                "native_worker_child_exit_before_provider_event"
                if state.get("provider_event_count", 0) == 0
                else "native_worker_child_nonzero_exit"
            )
    _write_private_json(state_path, state)
    return exit_code if exit_code != 0 else (1 if state["status"] == "failed" else 0)


def launch_native_worker(
    *,
    repo_root: Path,
    run_id: str,
    spec: NativeWorkerSpec,
    packet: Path,
    cli_path: Path,
    prewalk_spec: NativeWorkerPrewalkSpec | None = None,
) -> dict[str, Any]:
    # A registry-gated host may use only the two-phase prewalk path. The spec
    # builder has already required either complete behavioral qualification or
    # an explicit experimental request with advertised exact-resume grammar.
    # Single-phase launch remains unavailable at this seam.
    launch_profile = resolve_host_profile(spec.host)
    if not launch_profile.launch_ready and prewalk_spec is None:
        raise ValidationIssue(
            f"{launch_profile.capability_host}_native_worker_launch_unqualified",
            f"{launch_profile.capability_host} single-phase native-worker launch is feature-gated off",
        )
    state_path, log_path = native_worker_paths(repo_root, run_id)
    if state_path.exists():
        raise ValidationIssue("native_worker_run_exists", f"Native worker run `{run_id}` already exists")
    watcher = shlex.join(
        [
            sys.executable,
            str(cli_path.resolve()),
            "native-worker",
            "follow",
            "--repo-root",
            str(repo_root.resolve()),
            "--run-id",
            run_id,
        ]
    )
    launch_spec = prewalk_spec.guide if prewalk_spec else spec
    worktree = Path(launch_spec.cwd).resolve()
    if prewalk_spec and not _worktree_clean(worktree):
        raise ValidationIssue(
            "prewalk_worktree_continuity_violation",
            "Prewalk requires a clean registered worktree at the exact starting HEAD",
            path=str(worktree),
        )
    if launch_spec.host == "fixture" and not prewalk_spec:
        git_contract = {
            "assigned_branch": None,
            "start_head": None,
            "protected_refs": {},
            "origin_config_digest": None,
        }
    else:
        git_contract = _native_git_contract(worktree)
    packet_path = packet.resolve(strict=True)
    base_state: dict[str, Any] = {
        "run_id": run_id,
        "host": launch_spec.host,
        "worktree": launch_spec.cwd,
        "argv": list(launch_spec.argv),
        "session_id": launch_spec.session_id,
        "session_id_source": launch_spec.session_id_source,
        "pid": None,
        "pid_start": None,
        "follow_log": str(log_path),
        "visibility_ready": True,
        "visibility_mode": "follow_log",
        "watcher_command": watcher,
        "exit_code": None,
        "commit_mode": launch_spec.commit_mode,
        "provider_event_count": 0,
        "stderr_tail": None,
        "git_write_roots": list(launch_spec.git_write_roots),
        "prompt_file_flag": launch_spec.prompt_file_flag,
        "git_network_push": "disabled",
        "git_authority_mode": "fixture" if launch_spec.host == "fixture" else "feature_only",
        **git_contract,
    }
    if prewalk_spec:
        paths = prewalk_paths(worktree, run_id)
        state = {
            **base_state,
            "version": PREWALK_STATE_VERSION,
            "mode": "prewalk",
            "status": "launching_prewalk",
            "status_history": [
                {"status": "staged", "at": datetime_now()},
                {"status": "launching_prewalk", "at": datetime_now()},
            ],
            "starting_worktree_clean": True,
            "packet": {
                "path": str(packet_path),
                "sha256": packet_digest(packet_path),
                "sent_count": 0,
            },
            "prewalk": {
                "model": prewalk_spec.guide.requested_model,
                "effort": prewalk_spec.guide.effort,
                "instruction_strategy": (
                    "experimental_unqualified_persisted_instruction"
                    if prewalk_spec.requested_mode == "experimental"
                    else "retained_safe_host_instruction"
                ),
                "instruction_fidelity": prewalk_spec.instruction_fidelity,
                "instruction_pruned": prewalk_spec.instruction_fidelity == "pruned",
                "todo_limit": prewalk_spec.todo_limit,
                "paths": paths.to_dict(),
                "argv": list(prewalk_spec.guide.argv),
                "prompt_file_flag": prewalk_spec.guide.prompt_file_flag,
                "fixture_script": (
                    prewalk_spec.guide.argv[1]
                    if prewalk_spec.guide.host == "fixture"
                    else None
                ),
                "recovery_attempts": 0,
            },
            "execution": {
                "model": prewalk_spec.execution_model,
                "effort": prewalk_spec.execution_effort,
                "resume_input": PREWALK_CONTINUATION_INPUT,
                "argv": None,
                "prompt_file_flag": (
                    prewalk_spec.execution_spec(
                        prewalk_spec.guide.session_id or "prewalk-session-preview"
                    ).prompt_file_flag
                ),
                "fixture_script": prewalk_spec.execution_fixture_script,
                "transient_retries": 0,
                "retry_backoff_seconds": [],
            },
            "transition": {"status": "pending"},
            "requested_prewalk_mode": prewalk_spec.requested_mode,
            "capabilities": prewalk_spec.capabilities.to_dict(),
            "forbidden_paths": list(prewalk_spec.forbidden_paths),
        }
    else:
        state = {**base_state, "version": 2, "status": "launching"}
    _write_private_json(state_path, state)
    supervisor_log = state_path.parent / "supervisor.log"
    with supervisor_log.open("a", encoding="utf-8") as supervisor_output:
        os.chmod(supervisor_log, 0o600)
        supervisor = subprocess.Popen(
            [
                sys.executable,
                str(cli_path.resolve()),
                "native-worker",
                "_supervise",
                "--repo-root",
                str(repo_root.resolve()),
                "--run-id",
                run_id,
                "--packet",
                str(packet_path),
            ],
            cwd=str(repo_root.resolve()),
            stdin=subprocess.DEVNULL,
            stdout=supervisor_output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    state["supervisor_pid"] = supervisor.pid
    state["supervisor_pid_start"] = _process_start(supervisor.pid)
    state["supervisor_log"] = str(supervisor_log)
    if not prewalk_spec:
        state["status"] = "running"
    _write_private_json(state_path, state)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        current = json.loads(state_path.read_text(encoding="utf-8"))
        current_profile = host_profile_or_none(str(current.get("host") or ""))
        identity_ready = current.get("pid") and (
            current.get("session_id")
            or not (current_profile and current_profile.identity_from_stream_required)
        )
        if identity_ready or current.get("status") in {"complete", "failed"}:
            return current
        time.sleep(0.02)
    try:
        os.killpg(supervisor.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    raise ValidationIssue(
        "native_worker_identity_timeout",
        "Native worker did not publish its exact PID/session binding before launch returned",
    )


def _supervise_single_phase(
    *,
    state_path: Path,
    log_path: Path,
    state: dict[str, Any],
    packet: Path,
    child_env: dict[str, str],
) -> int:
    packet_text = packet.read_text(encoding="utf-8")
    result = _run_worker_phase(
        state_path=state_path,
        log_path=log_path,
        state=state,
        phase="execution",
        argv=tuple(state["argv"]),
        input_text=packet_text,
        child_env=child_env,
        expected_session_id=state.get("session_id"),
        prompt_file_flag=state.get("prompt_file_flag"),
    )
    return _terminalize_native_worker(
        state_path=state_path,
        state=state,
        worktree=Path(state["worktree"]).resolve(),
        exit_code=result.exit_code,
    )


def _build_resumed_spec(
    state: dict[str, Any], *, phase: str, session_id: str
) -> NativeWorkerSpec:
    record = state["prewalk"] if phase == "prewalk" else state["execution"]
    fixture = record.get("fixture_script")
    return build_native_worker_spec(
        host=state["host"],
        worktree=Path(state["worktree"]),
        effort=record["effort"],
        requested_model=record["model"],
        session_id=session_id,
        visibility_mode="follow_log",
        watcher_command=state["watcher_command"],
        fixture_script=Path(fixture) if fixture else None,
    )


def _clean_fallback_allowed(state: dict[str, Any], worktree: Path) -> bool:
    if state.get("requested_prewalk_mode") != "auto":
        return False
    try:
        if not _worktree_clean(worktree):
            return False
        if _final_head(worktree) != str(state["start_head"]):
            return False
        if _verify_native_git_contract(worktree, state):
            return False
    except ValidationIssue:
        return False
    return True


def _guide_recovery_failure_reason(state: dict[str, Any], worktree: Path) -> str:
    try:
        head_moved = _final_head(worktree) != str(state["start_head"])
        paths = observed_changed_paths(worktree, str(state["start_head"]))
        task_edited = any(not path.startswith(".elves/") for path in paths)
        if head_moved:
            # A moved HEAD that retains task edits means the guide already
            # committed real work: a cold fresh-session fallback is forbidden.
            # A moved HEAD with no retained delta is history drift.
            return (
                "prewalk_post_edit_cold_fallback_forbidden"
                if task_edited
                else "prewalk_worktree_continuity_violation"
            )
        if _verify_native_git_contract(worktree, state):
            return "prewalk_worktree_continuity_violation"
    except ValidationIssue:
        return "prewalk_worktree_continuity_violation"
    if task_edited:
        return "prewalk_post_edit_cold_fallback_forbidden"
    return "prewalk_guide_exit_before_checkpoint"


def _run_clean_single_phase_fallback(
    *,
    state_path: Path,
    log_path: Path,
    state: dict[str, Any],
    packet_text: str,
    child_env: dict[str, str],
) -> int:
    worktree = Path(state["worktree"]).resolve()
    record = state["execution"]
    fixture = record.get("fixture_script")
    fresh = build_native_worker_spec(
        host=state["host"],
        worktree=worktree,
        effort=record["effort"],
        requested_model=record["model"],
        visibility_mode="follow_log",
        watcher_command=state["watcher_command"],
        fixture_script=Path(fixture) if fixture else None,
    )
    state["abandoned_prewalk_session_id"] = state.get("session_id")
    state["session_id"] = fresh.session_id
    state["session_id_source"] = fresh.session_id_source
    state["argv"] = list(fresh.argv)
    state["mode"] = "single_phase_fallback"
    _set_status(state, "launching_execution")
    state["transition"] = {
        "status": "clean_pre_edit_fallback",
        "fallback_reason": "prewalk_guide_exit_before_checkpoint",
        "prewalk_claimed": False,
    }
    state["packet"]["sent_count"] = int(state["packet"]["sent_count"]) + 1
    _write_private_json(state_path, state)
    result = _run_worker_phase(
        state_path=state_path,
        log_path=log_path,
        state=state,
        phase="execution",
        argv=fresh.argv,
        input_text=packet_text,
        child_env=child_env,
        expected_session_id=fresh.session_id,
        prompt_file_flag=fresh.prompt_file_flag,
    )
    return _terminalize_native_worker(
        state_path=state_path,
        state=state,
        worktree=worktree,
        exit_code=result.exit_code,
    )


def _run_execution_with_transient_retries(
    *,
    state_path: Path,
    log_path: Path,
    state: dict[str, Any],
    child_env: dict[str, str],
    session_id: str,
) -> _PhaseResult:
    """Resume execution with the canonical transport-only backoff policy.

    Fixture transport records the production delays but does not sleep. This
    keeps the deterministic lifecycle proof model-free and fast without adding
    a production override that could silently weaken provider recovery.
    """
    resumed = _build_resumed_spec(state, phase="execution", session_id=session_id)
    state["execution"]["argv"] = list(resumed.argv)
    _write_private_json(state_path, state)
    result = _run_worker_phase(
        state_path=state_path,
        log_path=log_path,
        state=state,
        phase="execution",
        argv=resumed.argv,
        input_text=PREWALK_CONTINUATION_INPUT,
        child_env=child_env,
        expected_session_id=session_id,
        prompt_file_flag=resumed.prompt_file_flag,
    )
    for retry_number, backoff_seconds in enumerate(
        _PREWALK_TRANSIENT_BACKOFF_SECONDS, start=1
    ):
        if (
            result.exit_code == 0
            or result.session_mismatch
            or not result.transient_transport_failure
        ):
            break
        state["execution"]["transient_retries"] = retry_number
        state["execution"]["retry_backoff_seconds"].append(backoff_seconds)
        state["execution"]["last_transport_failure_at"] = datetime_now()
        _set_status(state, "execution_backoff")
        _write_private_json(state_path, state)
        if state.get("host") != "fixture":
            time.sleep(backoff_seconds)
        _set_status(state, "launching_execution")
        _write_private_json(state_path, state)
        resumed = _build_resumed_spec(state, phase="execution", session_id=session_id)
        result = _run_worker_phase(
            state_path=state_path,
            log_path=log_path,
            state=state,
            phase=f"execution_retry_{retry_number}",
            argv=resumed.argv,
            input_text=PREWALK_CONTINUATION_INPUT,
            child_env=child_env,
            expected_session_id=session_id,
            prompt_file_flag=resumed.prompt_file_flag,
        )
    return result


def _supervise_prewalk(
    *,
    state_path: Path,
    log_path: Path,
    state: dict[str, Any],
    packet: Path,
    child_env: dict[str, str],
) -> int:
    worktree = Path(state["worktree"]).resolve()
    packet_info = state.get("packet")
    if not isinstance(packet_info, dict) or packet_info.get("sent_count") != 0:
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=1,
            failure_reason="prewalk_packet_replayed",
        )
    if packet_digest(packet) != packet_info.get("sha256") or str(packet.resolve()) != packet_info.get("path"):
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=1,
            failure_reason="prewalk_packet_replayed",
        )
    packet_text = packet.read_text(encoding="utf-8")
    paths = PrewalkPaths(**state["prewalk"]["paths"])
    if state.get("session_id"):
        write_session_identity(
            Path(paths.session_identity),
            worktree=worktree,
            run_id=str(state["run_id"]),
            session_id=str(state["session_id"]),
        )
    state["packet"]["sent_count"] = 1
    _write_private_json(state_path, state)
    initial = guide_prompt(
        run_id=str(state["run_id"]),
        paths=paths,
        todo_limit=int(state["prewalk"]["todo_limit"]),
    ) + packet_text
    guide = _run_worker_phase(
        state_path=state_path,
        log_path=log_path,
        state=state,
        phase="prewalk",
        argv=tuple(state["prewalk"]["argv"]),
        input_text=initial,
        child_env=child_env,
        expected_session_id=state.get("session_id"),
        prompt_file_flag=state["prewalk"].get("prompt_file_flag"),
    )
    session_id = str(state.get("session_id") or "")
    if not session_id:
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=1,
            failure_reason="prewalk_session_id_missing",
        )
    if guide.session_mismatch or (
        guide.exit_code == 0 and session_id not in guide.observed_session_ids
    ):
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=1,
            failure_reason="prewalk_session_continuity_violation",
        )
    if guide.exit_code != 0:
        state["prewalk"]["recovery_attempts"] = 1
        _set_status(state, "launching_prewalk")
        _write_private_json(state_path, state)
        resumed_guide = _build_resumed_spec(state, phase="prewalk", session_id=session_id)
        recovery = _run_worker_phase(
            state_path=state_path,
            log_path=log_path,
            state=state,
            phase="prewalk_recovery",
            argv=resumed_guide.argv,
            input_text=recovery_prompt(),
            child_env=child_env,
            expected_session_id=session_id,
            prompt_file_flag=resumed_guide.prompt_file_flag,
        )
        if recovery.session_mismatch or session_id not in recovery.observed_session_ids:
            return _terminalize_native_worker(
                state_path=state_path,
                state=state,
                worktree=worktree,
                exit_code=1,
                failure_reason="prewalk_session_continuity_violation",
            )
        if recovery.exit_code != 0:
            if _clean_fallback_allowed(state, worktree):
                return _run_clean_single_phase_fallback(
                    state_path=state_path,
                    log_path=log_path,
                    state=state,
                    packet_text=packet_text,
                    child_env=child_env,
                )
            return _terminalize_native_worker(
                state_path=state_path,
                state=state,
                worktree=worktree,
                exit_code=recovery.exit_code,
                failure_reason=_guide_recovery_failure_reason(state, worktree),
            )
    try:
        todo, checkpoint = load_and_validate_transition_artifacts(
            paths=paths,
            run_id=str(state["run_id"]),
            session_id=session_id,
            todo_limit=int(state["prewalk"]["todo_limit"]),
            worktree=worktree,
        )
        transition = validate_meaningful_edit(
            worktree=worktree,
            start_head=str(state["start_head"]),
            assigned_branch=str(state["assigned_branch"]),
            todo=todo,
            checkpoint=checkpoint,
            starting_worktree_clean=bool(state.get("starting_worktree_clean")),
            forbidden_paths=tuple(state.get("forbidden_paths") or ()),
            authority_errors=_authority_errors(worktree, state),
        )
    except ValidationIssue as issue:
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=1,
            failure_reason=issue.code,
        )
    state["transition"] = {
        "status": "validated",
        **transition.to_dict(),
        "validated_at": datetime_now(),
    }
    _set_status(state, "transition_ready")
    _write_private_json(state_path, state)
    if transition.task_complete:
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=0,
        )
    if state["packet"]["sent_count"] != 1:
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=1,
            failure_reason="prewalk_packet_replayed",
        )
    _set_status(state, "launching_execution")
    execution = _run_execution_with_transient_retries(
        state_path=state_path,
        log_path=log_path,
        state=state,
        child_env=child_env,
        session_id=session_id,
    )
    if execution.session_mismatch or session_id not in execution.observed_session_ids:
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=1,
            failure_reason="prewalk_session_continuity_violation",
        )
    if execution.exit_code != 0:
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=execution.exit_code,
            failure_reason="prewalk_execution_resume_failed",
        )
    try:
        final_todo, final_checkpoint = load_and_validate_transition_artifacts(
            paths=paths,
            run_id=str(state["run_id"]),
            session_id=session_id,
            todo_limit=int(state["prewalk"]["todo_limit"]),
            worktree=worktree,
        )
        if final_checkpoint.get("kind") != "task_complete" or any(
            item.get("status") != "complete" for item in final_todo.get("items", [])
        ):
            raise ValidationIssue(
                "prewalk_checkpoint_invalid",
                "Execution phase must finish the TODO and write task_complete checkpoint",
            )
    except ValidationIssue as issue:
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=1,
            failure_reason=issue.code,
        )
    state["transition"]["session_continuity"] = True
    state["transition"]["worktree_continuity"] = Path(state["worktree"]).resolve() == worktree
    state["transition"]["packet_sent_count"] = state["packet"]["sent_count"]
    _write_private_json(state_path, state)
    return _terminalize_native_worker(
        state_path=state_path,
        state=state,
        worktree=worktree,
        exit_code=0,
    )


def supervise_native_worker(*, repo_root: Path, run_id: str, packet: Path) -> int:
    state_path, log_path = native_worker_paths(repo_root, run_id)
    state: dict[str, Any] = {}
    for _ in range(50):
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("supervisor_pid"):
            break
        time.sleep(0.02)
    worktree = Path(str(state["worktree"])).resolve()
    phase_model = None
    if isinstance(state.get("execution"), dict):
        phase_model = state["execution"].get("model")
    if phase_model is None and isinstance(state.get("prewalk"), dict):
        phase_model = state["prewalk"].get("model")
    child_env = _native_worker_child_env(
        host=str(state.get("host") or ""),
        worktree=worktree,
        runtime_dir=state_path.parent,
        requested_model=str(phase_model) if phase_model else None,
    )
    try:
        if state.get("version") == PREWALK_STATE_VERSION and state.get("mode") == "prewalk":
            return _supervise_prewalk(
                state_path=state_path,
                log_path=log_path,
                state=state,
                packet=packet,
                child_env=child_env,
            )
        return _supervise_single_phase(
            state_path=state_path,
            log_path=log_path,
            state=state,
            packet=packet,
            child_env=child_env,
        )
    except (OSError, UnicodeError, ValidationIssue, subprocess.SubprocessError) as exc:
        if isinstance(exc, ValidationIssue):
            failure = exc.code
        elif isinstance(exc, subprocess.TimeoutExpired):
            failure = "native_worker_git_timeout"
        else:
            failure = "native_worker_supervisor_failure"
        return _terminalize_native_worker(
            state_path=state_path,
            state=state,
            worktree=worktree,
            exit_code=1,
            failure_reason=failure,
        )


def native_worker_status(repo_root: Path, run_id: str) -> dict[str, Any]:
    state_path, _ = native_worker_paths(repo_root, run_id)
    if not state_path.is_file() or stat.S_IMODE(state_path.stat().st_mode) & 0o077:
        raise ValidationIssue("native_worker_state_unavailable", "Private native worker state is missing or has unsafe permissions")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    pid = state.get("pid")
    expected_start = state.get("pid_start")
    process_identity_matches: bool | None = None
    active_statuses = {
        "running",
        "launching_prewalk",
        "prewalking",
        "transition_ready",
        "launching_execution",
        "executing",
        "execution_backoff",
    }
    child_statuses = {"running", "prewalking", "executing"}
    if state.get("status") in child_statuses:
        process_identity_matches = _process_identity_matches(pid, expected_start)
    state["process_identity_matches"] = process_identity_matches
    if state.get("status") in active_statuses:
        supervisor_pid = state.get("supervisor_pid")
        supervisor_start = state.get("supervisor_pid_start")
        supervisor_matches = _process_identity_matches(supervisor_pid, supervisor_start)
        state["supervisor_identity_matches"] = supervisor_matches
        lost_active_supervision = supervisor_matches is False and (
            state.get("status") not in child_statuses
            or process_identity_matches is False
        )
        if lost_active_supervision:
            # A fast supervisor can exit just before atomically recording its
            # terminal state. Give that final write a short grace window before
            # reporting lost supervision for child and childless active phases.
            latest = state
            for attempt in range(6):
                if attempt:
                    time.sleep(0.02)
                latest = json.loads(state_path.read_text(encoding="utf-8"))
                if latest.get("status") in {"complete", "failed"}:
                    return latest
            prior_status = str(state.get("status") or "")
            state["status"] = "failed"
            state["failure_reason"] = (
                "supervisor_and_child_identity_lost"
                if prior_status in child_statuses
                and process_identity_matches is False
                else "native_worker_supervisor_identity_lost"
            )
    return state


def follow_native_worker(repo_root: Path, run_id: str, *, wait: bool = True, output: Any = sys.stdout) -> dict[str, Any]:
    state = native_worker_status(repo_root, run_id)
    log_path = Path(state["follow_log"])
    offset = 0
    while True:
        if log_path.is_file():
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                while True:
                    position = handle.tell()
                    line = handle.readline()
                    if not line:
                        break
                    if not line.endswith("\n"):
                        # A torn tail is still being written; re-read it on the
                        # next poll instead of surfacing a partial event.
                        handle.seek(position)
                        break
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        # Skip a torn or corrupt log line without dying.
                        continue
                    if not isinstance(event, dict) or "stream" not in event or "line" not in event:
                        continue
                    label = (
                        f"{event['phase']}:{event['stream']}"
                        if event.get("phase")
                        else event["stream"]
                    )
                    output.write(f"[{label}] {event['line']}\n")
                offset = handle.tell()
        state = native_worker_status(repo_root, run_id)
        if not wait or state["status"] in {"complete", "failed"}:
            return state
        time.sleep(0.1)
