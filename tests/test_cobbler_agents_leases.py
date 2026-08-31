from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def _ensure_import_path() -> None:
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


_ensure_import_path()

from cobbler_runtime.adapters import (  # noqa: E402
    build_write_resume_invocation,
    grok_write_profile,
    workspace_sandbox_write_profile,
)
from cobbler_runtime.audit import (  # noqa: E402
    audit_lease_turn,
    build_audit_evidence,
    export_binary_patches,
    host_apply_check,
    host_import_patches,
    list_commit_chain,
    normalize_worker_credential_grant_names,
    pre_turn_snapshots,
    snapshot_config,
    verify_patch_manifest,
)
from cobbler_runtime.leases import (  # noqa: E402
    host_qualification_evidence,
    LeaseState,
    LeaseStore,
    WriterLease,
    build_write_task_packet,
    is_path_allowed,
    preflight_worker_checkout,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402
from cobbler_runtime.storage import StorageError, record_filename  # noqa: E402


def _run(cwd: Path, args: list[str]) -> None:
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _run(path, ["git", "init"])
    _run(path, ["git", "config", "user.email", "lease@example.test"])
    _run(path, ["git", "config", "user.name", "Lease Test"])
    (path / ".gitignore").write_text(".elves/\n", encoding="utf-8")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    _run(path, ["git", "add", "-A"])
    _run(path, ["git", "commit", "-m", "base"])
    return _git(path, "rev-parse", "HEAD")


def _detached_worktree(main: Path, worktree: Path, head: str) -> None:
    _run(main, ["git", "worktree", "add", "--detach", str(worktree), head])



def _register_session(
    host: Path,
    session_id: str,
    *,
    worker: Path,
    head: str,
    adapter: str = "grok-build",
    profile: str | None = None,
) -> None:
    """Register an exact session so lease qualification can require it."""
    from cobbler_runtime.sessions import SessionRecord, SessionRegistry

    reg = SessionRegistry(host)
    rec = SessionRecord(
        session_id=session_id,
        harness=adapter,
        profile=profile or ("grok-build-write" if adapter == "grok-build" else adapter),
        role="implementer",
        actual_model="grok-4.5",
        requested_model="grok-4.5",
        cwd=str(Path(worker).resolve()),
        worktree=str(Path(worker).resolve()),
        parent_id="host-parent",
        source_head=head,
    )
    try:
        reg.save(rec)
        reg.activate(session_id)
    except Exception:
        # Idempotent for tests that register twice.
        try:
            existing = reg.get(session_id)
            if existing.lifecycle.value == "new":
                reg.activate(session_id)
        except Exception:
            raise


def _qual(
    worker,
    head,
    session_id="sess",
    adapter="grok-build",
    sandbox="devbox",
    profile=None,
    version="0.2.93",
    **overrides,
):
    evidence = host_qualification_evidence(
        adapter=adapter,
        model="grok-4.5",
        profile=profile or ("grok-build-write" if adapter == "grok-build" else adapter),
        version=version,
        sandbox=sandbox,
        worktree=str(Path(worker).resolve()),
        cwd=str(Path(worker).resolve()),
        parent="host-parent",
        source_head=head,
        session_id=session_id,
    )
    evidence.update(overrides)
    return evidence


def _audit_evidence(audit, *, pre_snapshots: dict | None = None) -> dict:
    return build_audit_evidence(audit, pre_snapshots=pre_snapshots)


def _prove_worker_handoff(
    store: LeaseStore,
    lease_id: str,
    *,
    host: Path,
    patch_dir: Path,
) -> tuple[WriterLease, list[Path], dict]:
    audit = audit_lease_turn(store.get(lease_id))
    if not audit.ok:
        raise AssertionError(audit.reasons)
    store.mark_auditing(lease_id)
    store.mark_audited_pass(lease_id, evidence=_audit_evidence(audit))
    lease = store.get(lease_id)
    patches = export_binary_patches(
        lease,
        output_dir=patch_dir,
        chain=audit.commit_chain,
        audit_evidence=_audit_evidence(audit),
    )
    checked = host_apply_check(
        host,
        patches,
        base_head=lease.base_head,
        lease=lease,
        manifest_dir=patch_dir,
    )
    store.mark_exported(lease_id, str(patch_dir))
    lease = store.mark_apply_checked(lease_id, evidence=checked)
    return lease, patches, checked


class RunGitTimeoutTests(unittest.TestCase):
    """B5: run_git enforces a bounded default so a hung git cannot stall."""

    def test_default_timeout_matches_supervisor_hardening(self) -> None:
        from cobbler_runtime import leases as leases_module

        self.assertEqual(leases_module.DEFAULT_GIT_TIMEOUT_SECONDS, 30.0)
        with mock.patch.object(
            leases_module.subprocess,
            "run",
            return_value=mock.Mock(returncode=0, stdout="", stderr=""),
        ) as run_mock:
            leases_module.run_git(Path("/tmp"), ["status"], check=False)
        self.assertEqual(
            run_mock.call_args.kwargs["timeout"],
            leases_module.DEFAULT_GIT_TIMEOUT_SECONDS,
        )
        # An explicit override still wins.
        with mock.patch.object(
            leases_module.subprocess,
            "run",
            return_value=mock.Mock(returncode=0, stdout="", stderr=""),
        ) as run_mock:
            leases_module.run_git(
                Path("/tmp"), ["ls-remote"], check=False, timeout=15
            )
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 15)

    def test_hung_git_surfaces_timeout_expired(self) -> None:
        from cobbler_runtime import leases as leases_module

        with mock.patch.object(
            leases_module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30.0),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                leases_module.run_git(Path("/tmp"), ["fetch"], check=False)


class PathScopeTests(unittest.TestCase):
    def test_forbidden_and_allowed_paths(self) -> None:
        from cobbler_runtime.leases import WriterLease, normalize_repo_rel_path

        lease = WriterLease(
            lease_id="L",
            host_checkout="/host",
            worker_checkout="/worker",
            session_id="s",
            base_head="h",
            adapter="grok-build",
            profile="p",
            allowed_paths=["src/", "scripts/"],
        )
        self.assertTrue(is_path_allowed("src/app.py", lease))
        self.assertTrue(is_path_allowed("./scripts/x.py", lease))
        self.assertFalse(is_path_allowed(".elves/session.json", lease))
        self.assertFalse(is_path_allowed(".elves/secret.json", lease))
        self.assertFalse(is_path_allowed(".elves-session.json", lease))
        self.assertFalse(is_path_allowed("docs/elves/log.md", lease))
        self.assertFalse(is_path_allowed("other/x.py", lease))
        self.assertFalse(is_path_allowed("../escape.py", lease))
        self.assertFalse(is_path_allowed("/abs/path.py", lease))
        # Empty allow-list fails closed.

        empty = WriterLease(
            lease_id="E",
            host_checkout="/host",
            worker_checkout="/worker",
            session_id="s",
            base_head="h",
            adapter="grok-build",
            profile="p",
            allowed_paths=[],
        )
        self.assertFalse(is_path_allowed("src/app.py", empty))
        self.assertFalse(is_path_allowed(".elves/secret.json", empty))
        # lstrip("./") would have turned this into elves/ and escaped; must stay blocked.
        sneaky = WriterLease(
            lease_id="S",
            host_checkout="/host",
            worker_checkout="/worker",
            session_id="s",
            base_head="h",
            adapter="grok-build",
            profile="p",
            allowed_paths=["elves/"],
        )
        self.assertFalse(is_path_allowed(".elves/secret.json", sneaky))
        self.assertEqual(normalize_repo_rel_path(".elves/secret.json"), ".elves/secret.json")
        self.assertEqual(normalize_repo_rel_path("./src/app.py"), "src/app.py")

    def test_worker_credential_grant_names_reject_values_paths_and_controls(self) -> None:
        for malformed in ("XAI_API_KEY=value", "../XAI_API_KEY", "/tmp/token"):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValidationIssue) as ctx:
                    normalize_worker_credential_grant_names([malformed])
                self.assertEqual(ctx.exception.code, "credential_grant_name_invalid")
        with self.assertRaises(ValidationIssue) as ctx:
            normalize_worker_credential_grant_names(["HOME"])
        self.assertEqual(
            ctx.exception.code,
            "worker_isolation_control_grant_forbidden",
        )
        self.assertEqual(
            normalize_worker_credential_grant_names(
                ["XAI_API_KEY", "OPENROUTER_API_KEY", "XAI_API_KEY"]
            ),
            ["OPENROUTER_API_KEY", "XAI_API_KEY"],
        )


class LeaseExclusivityTests(unittest.TestCase):
    def test_host_and_worker_checkout_must_be_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host = Path(tmp) / "host"
            head = _init_repo(host)
            with self.assertRaises(ValidationIssue) as ctx:
                LeaseStore(host).prepare(
                    lease_id="same-checkout",
                    host_checkout=host,
                    worker_checkout=host,
                    session_id="session",
                    base_head=head,
                    adapter="grok-build",
                    profile="grok-build-write",
                    allowed_paths=["src/"],
                    qualification_evidence={},
                )
            self.assertEqual(ctx.exception.code, "worker_checkout_not_isolated")

    def test_second_live_lease_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess-1", worker=worker, head=head)
            store.prepare(
                lease_id="lease-1",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess-1",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head, session_id="sess-1", adapter="grok-build"),
            )
            with self.assertRaises(ValidationIssue) as ctx:
                _register_session(host, "sess-2", worker=worker, head=head)
                store.prepare(
                    lease_id="lease-2",
                    host_checkout=host,
                    worker_checkout=worker,
                    session_id="sess-2",
                    base_head=head,
                    adapter="grok-build",
                    profile="grok-build-write",
                qualification_evidence=_qual(worker, head, session_id="sess-2", adapter="grok-build"),
                )
            self.assertEqual(ctx.exception.code, "lease_exclusivity")


class QualificationIdentityTests(unittest.TestCase):
    def test_registered_identity_mismatches_and_stale_evidence_fail_closed(self) -> None:
        cases = {
            "model": "other-model",
            "profile": "other-profile",
            "parent": "other-parent",
            "source_head": "0" * 40,
            "cwd": "/tmp/not-the-worker",
            "worktree": "/tmp/not-the-worker",
            "version": "0.0.0",
            "preference_declared": True,
            "observed_at": (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat(),
        }
        for field_name, bad_value in cases.items():
            with self.subTest(field=field_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                host = root / "host"
                worker = root / "worker"
                head = _init_repo(host)
                _detached_worktree(host, worker, head)
                _register_session(host, "sess", worker=worker, head=head)
                evidence = _qual(worker, head, **{field_name: bad_value})
                with self.assertRaises(ValidationIssue):
                    LeaseStore(host).prepare(
                        lease_id=f"lease-{field_name}",
                        host_checkout=host,
                        worker_checkout=worker,
                        session_id="sess",
                        base_head=head,
                        adapter="grok-build",
                        profile="grok-build-write",
                        allowed_paths=["src/"],
                        grok_version="0.2.93",
                        qualification_evidence=evidence,
                    )

    def test_dirty_and_branch_attached_and_head_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)

            # Dirty
            (worker / "src" / "app.py").write_text("dirty\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                preflight_worker_checkout(
                    worker_checkout=worker,
                    base_head=head,
                )
            self.assertEqual(ctx.exception.code, "worker_dirty")

            # Reset dirty via checkout of file
            _run(worker, ["git", "checkout", "--", "src/app.py"])

            # HEAD mismatch
            with self.assertRaises(ValidationIssue) as ctx:
                preflight_worker_checkout(
                    worker_checkout=worker,
                    base_head="0" * 40,
                )
            self.assertEqual(ctx.exception.code, "worker_head_mismatch")

            # Branch-attached main checkout fails detached requirement
            with self.assertRaises(ValidationIssue) as ctx:
                preflight_worker_checkout(
                    worker_checkout=host,
                    base_head=head,
                    require_detached=True,
                    require_registered=True,
                )
            self.assertEqual(ctx.exception.code, "worker_not_detached")

    def test_write_packet_denies_push_pr_run_memory(self) -> None:
        lease = LeaseStore.__new__(LeaseStore)  # unused
        from cobbler_runtime.leases import WriterLease

        wl = WriterLease(
            lease_id="L",
            host_checkout="/h",
            worker_checkout="/w",
            session_id="s",
            base_head="abc",
            adapter="grok-build",
            profile="p",
        )
        packet = build_write_task_packet(wl, task="implement batch")
        self.assertTrue(packet["denials"]["push"])
        self.assertTrue(packet["denials"]["pr"])
        self.assertTrue(packet["denials"]["run_memory"])
        self.assertTrue(packet["denials"]["branch"])
        self.assertIn("detached_commits_permitted", packet)


class AuditAndPatchTests(unittest.TestCase):
    def test_intermediate_binary_secret_removed_at_tip_still_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-intermediate-binary-secret",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            sentinel = "opaque-intermediate-binary-secret-771199"
            blob = worker / "src" / "payload.bin"
            blob.write_bytes(b"\x00binary-prefix\xff" + sentinel.encode("utf-8"))
            _run(worker, ["git", "add", "--", "src/payload.bin"])
            _run(worker, ["git", "commit", "-m", "introduce binary", "--", "src/payload.bin"])
            blob.write_bytes(b"\x00safe-final-binary\xff")
            _run(worker, ["git", "add", "--", "src/payload.bin"])
            _run(worker, ["git", "commit", "-m", "remove binary", "--", "src/payload.bin"])

            audit = audit_lease_turn(
                store.get(lease.lease_id),
                exact_secret_values={sentinel},
            )

            self.assertFalse(audit.ok)
            self.assertIn("changed_blob_content", " ".join(audit.reasons))
            self.assertNotIn(sentinel, json.dumps(audit.to_dict(), sort_keys=True))

    def test_post_audit_common_config_symlink_with_identical_bytes_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-post-audit-config-symlink",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            evidence = _audit_evidence(audit)
            store.mark_audited_pass(lease.lease_id, evidence=evidence)
            lease = store.get(lease.lease_id)

            config = host / ".git" / "config"
            backup = host / ".git" / "config.audit-backup"
            outside = root / "identical-config"
            outside.write_bytes(config.read_bytes())
            config.rename(backup)
            config.symlink_to(outside)
            try:
                with self.assertRaises(ValidationIssue) as ctx:
                    export_binary_patches(
                        lease,
                        output_dir=root / "patches",
                        chain=audit.commit_chain,
                        audit_evidence=evidence,
                    )
                self.assertEqual(ctx.exception.code, "git_surface_unsafe")
                self.assertFalse((root / "patches").exists())
            finally:
                config.unlink()
                backup.rename(config)

    def test_post_audit_fsmonitor_is_rejected_before_any_git_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-fsmonitor-order",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            store.mark_audited_pass(lease.lease_id, evidence=_audit_evidence(audit))
            marker = root / "fsmonitor-ran"
            monitor = root / "fsmonitor.sh"
            monitor.write_text(
                f"#!/bin/sh\ntouch {marker}\nexit 0\n",
                encoding="utf-8",
            )
            monitor.chmod(0o700)
            _run(host, ["git", "config", "core.fsmonitor", str(monitor)])

            with mock.patch(
                "cobbler_runtime.leases._git_head",
                side_effect=AssertionError("Git ran before descriptor rejection"),
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    store._read_verified_audit_evidence(store.get(lease.lease_id))
            self.assertEqual(ctx.exception.code, "audit_evidence_git_surfaces_mismatch")
            self.assertFalse(marker.exists())

    def test_post_audit_hidden_index_flag_invalidates_sealed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-post-audit-hidden-index",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            store.mark_audited_pass(lease.lease_id, evidence=_audit_evidence(audit))

            _run(worker, ["git", "update-index", "--skip-worktree", "src/app.py"])
            (worker / "src" / "app.py").write_text(
                "post-audit hidden dirty content\n",
                encoding="utf-8",
            )
            self.assertEqual(_git(worker, "status", "--porcelain"), "")
            with self.assertRaises(ValidationIssue) as ctx:
                store._read_verified_audit_evidence(store.get(lease.lease_id))
            self.assertEqual(ctx.exception.code, "git_index_flags_unsafe")

    def test_swapped_git_locator_filter_is_rejected_before_filter_executes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            (host / ".gitattributes").write_text("*.txt filter=evil\n", encoding="utf-8")
            (host / "payload.txt").write_text("base\n", encoding="utf-8")
            _run(host, ["git", "add", "-A"])
            _run(host, ["git", "commit", "-m", "trusted attribute fixture"])
            head = _git(host, "rev-parse", "HEAD")
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-locator-filter",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            pre = pre_turn_snapshots(worker)

            alternate = root / "alternate"
            alternate_head = _init_repo(alternate)
            self.assertTrue(alternate_head)
            marker = root / "filter-ran"
            clean_filter = root / "clean-filter.sh"
            clean_filter.write_text(
                f"#!/bin/sh\ntouch {marker}\ncat\n",
                encoding="utf-8",
            )
            clean_filter.chmod(0o700)
            _run(alternate, ["git", "config", "filter.evil.clean", str(clean_filter)])
            _run(alternate, ["git", "config", "filter.evil.smudge", "cat"])
            dot_git = worker / ".git"
            original_locator = dot_git.read_bytes()
            dot_git.write_text(f"gitdir: {alternate / '.git'}\n", encoding="utf-8")
            try:
                with mock.patch(
                    "cobbler_runtime.audit._safe_git_head",
                    side_effect=AssertionError("Git ran after locator swap"),
                ):
                    with self.assertRaises(ValidationIssue) as ctx:
                        audit_lease_turn(
                            store.get(lease.lease_id),
                            pre_refs_digest=pre["refs_digest"],
                            pre_remotes=pre["remotes"],
                            pre_config=pre["config"],
                            pre_hooks=pre["hooks"],
                            pre_common_config=pre["common_config"],
                            pre_common_hooks=pre["common_hooks"],
                            pre_ref_storage=pre["ref_storage"],
                            pre_git_dir=pre["git_dir"],
                            pre_git_common_dir=pre["git_common_dir"],
                            pre_authority=pre["authority"],
                            pre_static_control=pre["static_control"],
                        )
                self.assertIn(
                    ctx.exception.code,
                    {"git_surface_unsafe", "audit_pre_git_surface_mismatch"},
                )
                self.assertFalse(marker.exists())
            finally:
                dot_git.write_bytes(original_locator)

    def test_git_config_parser_rejects_case_varied_command_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            _init_repo(repo)
            config = repo / ".git" / "config"
            baseline = config.read_text(encoding="utf-8")
            cases = (
                '[FiLtEr "ev\\"il"] # trailing comment\nclean = /tmp/never\n',
                '[DiFf "ev\\"il"] ; trailing comment\ntextconv = /tmp/never\n',
            )
            for index, stanza in enumerate(cases):
                with self.subTest(index=index):
                    config.write_text(baseline + "\n" + stanza, encoding="utf-8")
                    with self.assertRaises(ValidationIssue) as ctx:
                        snapshot_config(repo / ".git")
                    self.assertEqual(ctx.exception.code, "git_surface_unsafe")

    def test_export_write_and_first_unlink_failure_is_fail_closed_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-export-double-failure",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            evidence = _audit_evidence(audit)
            store.mark_audited_pass(lease.lease_id, evidence=evidence)
            lease = store.get(lease.lease_id)
            patch_dir = root / "patches"
            real_unlink = os.unlink
            unlink_calls = 0

            def fail_first_unlink(path, *args, **kwargs):
                nonlocal unlink_calls
                unlink_calls += 1
                if unlink_calls == 1:
                    raise OSError("synthetic first unlink failure")
                return real_unlink(path, *args, **kwargs)

            with mock.patch(
                "cobbler_runtime.audit.os.write",
                side_effect=OSError("synthetic write failure"),
            ), mock.patch(
                "cobbler_runtime.audit.os.unlink",
                side_effect=fail_first_unlink,
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    export_binary_patches(
                        lease,
                        output_dir=patch_dir,
                        chain=audit.commit_chain,
                        audit_evidence=evidence,
                    )
            self.assertEqual(ctx.exception.code, "export_cleanup_failed")
            self.assertGreaterEqual(unlink_calls, 2)
            self.assertEqual(list(patch_dir.iterdir()), [])

    def test_interrupted_export_removes_untracked_partial_leaf(self) -> None:
        from cobbler_runtime import audit as audit_module

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "patches"
            output.mkdir()
            directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with mock.patch(
                    "cobbler_runtime.audit.os.write",
                    side_effect=KeyboardInterrupt,
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        audit_module._write_export_file(
                            directory_fd,
                            "0001-interrupted.patch",
                            b"partial",
                        )
                self.assertEqual(list(output.iterdir()), [])
            finally:
                os.close(directory_fd)

    def test_export_failure_removes_every_created_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-export-cleanup",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            evidence = _audit_evidence(audit)
            store.mark_audited_pass(lease.lease_id, evidence=evidence)
            lease = store.get(lease.lease_id)
            patch_dir = root / "patches"

            from cobbler_runtime import audit as audit_module

            real_write = audit_module._write_export_file

            def fail_manifest(directory_fd, name, data):
                if name == "chain.json":
                    raise ValidationIssue("synthetic_manifest_failure", "synthetic")
                return real_write(directory_fd, name, data)

            with mock.patch(
                "cobbler_runtime.audit._write_export_file",
                side_effect=fail_manifest,
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    export_binary_patches(
                        lease,
                        output_dir=patch_dir,
                        chain=audit.commit_chain,
                        audit_evidence=evidence,
                    )
            self.assertEqual(ctx.exception.code, "synthetic_manifest_failure")
            self.assertTrue(patch_dir.is_dir())
            self.assertEqual(list(patch_dir.iterdir()), [])

    def test_real_host_import_uses_retained_bundle_and_proves_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-real-import",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "first worker change", "--", "src/app.py"])
            (worker / "src" / "extra.py").write_text("value = 2\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/extra.py"])
            _run(worker, ["git", "commit", "-m", "second worker change", "--", "src/extra.py"])
            lease, _patches, checked = _prove_worker_handoff(
                store,
                lease.lease_id,
                host=host,
                patch_dir=root / "patches",
            )

            imported = host_import_patches(
                lease,
                manifest_dir=Path(lease.exported_patch_dir or ""),
            )

            self.assertTrue(imported["ok"])
            self.assertTrue(imported["mutated_repo"])
            self.assertEqual(imported["resulting_tree"], checked["expected_worker_tree"])
            self.assertEqual(_git(host, "write-tree"), checked["expected_worker_tree"])
            self.assertEqual(_git(host, "rev-parse", "HEAD"), head)
            self.assertIn("src/extra.py", _git(host, "status", "--porcelain"))

    def test_untrusted_audit_rejects_in_repo_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-symlink",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "link.py").symlink_to("app.py")
            _run(worker, ["git", "add", "--", "src/link.py"])
            _run(worker, ["git", "commit", "-m", "add in-repo symlink", "--", "src/link.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertFalse(audit.ok)
            self.assertEqual(audit.symlink_escapes, ["src/link.py"])
            self.assertTrue(any("symlink paths are forbidden" in reason for reason in audit.reasons))

    def test_untrusted_audit_rejects_command_bearing_attributes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-attributes",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / ".gitattributes").write_text(
                "*.py FILTER=worker-command\n",
                encoding="utf-8",
            )
            _run(worker, ["git", "add", "--", "src/.gitattributes"])
            _run(worker, ["git", "commit", "-m", "add filter attribute", "--", "src/.gitattributes"])

            audit = audit_lease_turn(store.get(lease.lease_id))

            self.assertFalse(audit.ok)
            self.assertTrue(any(".gitattributes" in reason for reason in audit.reasons))

    def test_untrusted_audit_rejects_gitlink_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-gitlink",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            _run(
                worker,
                [
                    "git",
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"160000,{head},src/vendor",
                ],
            )
            _run(worker, ["git", "commit", "-m", "add gitlink"])

            audit = audit_lease_turn(store.get(lease.lease_id))

            self.assertFalse(audit.ok)
            self.assertTrue(any("submodule controls" in reason for reason in audit.reasons))

    def test_lease_revision_zero_cannot_overwrite_existing_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-cas-zero",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            stale = WriterLease.from_dict(lease.to_dict())
            stale.revision = 0
            with self.assertRaises(ValidationIssue) as ctx:
                store.save(stale)
            self.assertEqual(ctx.exception.code, "lease_revision_conflict")

            stale = WriterLease.from_dict(lease.to_dict())
            stale.revision = 0
            with self.assertRaises(ValidationIssue) as ctx:
                store.save(stale, expected_revision=lease.revision)
            self.assertEqual(ctx.exception.code, "lease_revision_conflict")

    def test_terminal_lease_id_is_immutable_and_cannot_be_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            kwargs = dict(
                lease_id="lease-terminal-id",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.prepare(**kwargs)
            store.close("lease-terminal-id")
            with self.assertRaises(ValidationIssue) as ctx:
                store.prepare(**kwargs)
            self.assertEqual(ctx.exception.code, "lease_id_immutable")

    def test_lease_prepare_rejects_active_session_with_pending_rehydration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            _register_session(host, "sess", worker=worker, head=head)
            from cobbler_runtime.sessions import SessionRegistry

            registry = SessionRegistry(host)
            session = registry.get("sess")
            session.pending_context_digest = "pending"
            registry.save(session)
            with self.assertRaises(ValidationIssue) as ctx:
                LeaseStore(host).prepare(
                    lease_id="lease-pending",
                    host_checkout=host,
                    worker_checkout=worker,
                    session_id="sess",
                    base_head=head,
                    adapter="grok-build",
                    profile="grok-build-write",
                    allowed_paths=["src/"],
                    qualification_evidence=_qual(worker, head),
                )
            self.assertEqual(ctx.exception.code, "write_qualification_session_blocked")

    def test_allowed_detached_chain_export_and_apply_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-ok",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head, session_id="sess", adapter="grok-build"),
            )
            store.activate("lease-ok")
            pre = pre_turn_snapshots(worker)

            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(
                worker,
                [
                    "git",
                    "commit",
                    "-m",
                    "[grok-worker · Batch 4/6 · Implement] Update app",
                    "--",
                    "src/app.py",
                ],
            )
            # Commit two depends on commit one. A non-cumulative checker would
            # incorrectly accept both independently; reversed order must fail.
            (worker / "src" / "app.py").write_text("print('v3')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(
                worker,
                [
                    "git",
                    "commit",
                    "-m",
                    "[grok-worker · Batch 4/6 · Implement] Refine app",
                    "--",
                    "src/app.py",
                ],
            )

            lease = store.get("lease-ok")
            audit = audit_lease_turn(
                lease,
                pre_refs_digest=pre["refs_digest"],
                pre_remotes=pre["remotes"],
                pre_config=pre["config"],
                pre_hooks=pre["hooks"],
                process_baseline=["pid-1"],
                process_observed=["pid-1"],
            )
            self.assertTrue(audit.ok, audit.reasons)
            self.assertEqual(len(audit.commit_chain), 2)
            self.assertEqual(audit.commit_chain[0].parents[0], head)

            store.mark_auditing("lease-ok")
            store.mark_audited_pass(
                "lease-ok",
                evidence=_audit_evidence(audit),
            )
            lease = store.get("lease-ok")
            patch_dir = root / "patches"
            patches = export_binary_patches(
                lease,
                output_dir=patch_dir,
                chain=audit.commit_chain,
                audit_evidence=audit.to_dict(),
            )
            self.assertGreaterEqual(len(patches), 2)
            self.assertTrue((patch_dir / "chain.json").is_file())
            self.assertEqual(verify_patch_manifest(lease, output_dir=patch_dir), patches)

            # Host still at base; apply-check should pass without committing.
            checked = host_apply_check(
                host,
                patches,
                base_head=head,
                lease=lease,
                manifest_dir=patch_dir,
            )
            self.assertTrue(checked["ok"])
            self.assertTrue(checked["manifest_verified"])
            self.assertTrue(checked["disposable"])
            self.assertEqual(_git(host, "rev-parse", "HEAD"), head)
            self.assertEqual(_git(host, "status", "--porcelain"), "")
            with self.assertRaises(ValidationIssue) as ctx:
                host_apply_check(host, list(reversed(patches)), base_head=head)
            self.assertEqual(ctx.exception.code, "apply_check_failed")
            store.mark_exported(lease.lease_id, str(patch_dir))
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_apply_checked(lease.lease_id)
            self.assertEqual(ctx.exception.code, "apply_check_evidence_required")
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_apply_checked(lease.lease_id, evidence=dict(checked))
            self.assertEqual(ctx.exception.code, "apply_check_evidence_unverified")
            original_note = checked["note"]
            checked["note"] = "forged after check"
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_apply_checked(lease.lease_id, evidence=checked)
            self.assertEqual(ctx.exception.code, "apply_check_evidence_unverified")
            checked["note"] = original_note
            applied_lease = store.mark_apply_checked(lease.lease_id, evidence=checked)
            self.assertEqual(applied_lease.state, LeaseState.APPLY_CHECKED)
            self.assertEqual(len(applied_lease.apply_check_evidence_digest or ""), 64)
            self.assertTrue(
                (store.snapshot_dir(lease.lease_id) / "apply_check_evidence.json").is_file()
            )

            first_patch = patches[0]
            original_patch = first_patch.read_bytes()
            first_patch.write_bytes(original_patch + b"\n# tampered\n")
            with self.assertRaises(ValidationIssue) as ctx:
                verify_patch_manifest(lease, output_dir=patch_dir)
            self.assertEqual(ctx.exception.code, "patch_manifest_patch_digest_mismatch")
            first_patch.write_bytes(original_patch)

            extra = patch_dir / "unexpected.txt"
            extra.write_text("extra\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                verify_patch_manifest(lease, output_dir=patch_dir)
            self.assertEqual(ctx.exception.code, "patch_manifest_extra_or_missing_files")
            extra.unlink()

            manifest_path = patch_dir / "chain.json"
            original_manifest = manifest_path.read_text(encoding="utf-8")
            manifest = json.loads(original_manifest)
            manifest["patches"] = list(reversed(manifest["patches"]))
            canonical = {
                key: value
                for key, value in manifest.items()
                if key != "manifest_digest"
            }
            manifest["manifest_digest"] = hashlib.sha256(
                json.dumps(
                    canonical,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValidationIssue) as ctx:
                verify_patch_manifest(lease, output_dir=patch_dir)
            self.assertEqual(ctx.exception.code, "patch_manifest_order_mismatch")
            manifest_path.write_text(original_manifest, encoding="utf-8")

    def test_mark_audited_pass_rejects_forged_chain_and_dirty_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-forged-audit",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)

            forged = _audit_evidence(audit)
            forged["commit_chain"] = []
            canonical = {
                key: value
                for key, value in forged.items()
                if key != "evidence_digest"
            }
            forged["evidence_digest"] = hashlib.sha256(
                json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_audited_pass(lease.lease_id, evidence=forged)
            self.assertEqual(ctx.exception.code, "audit_evidence_unverified")
            self.assertFalse(
                (store.snapshot_dir(lease.lease_id) / "audit_evidence.json").exists()
            )

            (worker / "src" / "app.py").write_text("dirty\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_audited_pass(
                    lease.lease_id,
                    evidence=_audit_evidence(audit),
                )
            self.assertEqual(ctx.exception.code, "audit_evidence_worker_dirty")

            _run(worker, ["git", "checkout", "--", "src/app.py"])
            (worker / "src" / "app.py").write_text("print('v3')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "later change", "--", "src/app.py"])
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_audited_pass(
                    lease.lease_id,
                    evidence=_audit_evidence(audit),
                )
            # Detached HEAD is a descriptor-bound control surface, so the
            # post-audit mutation is rejected before any Git HEAD query runs.
            self.assertEqual(ctx.exception.code, "audit_evidence_git_surfaces_mismatch")

    def test_mark_audited_pass_rejects_rehashed_false_out_of_scope_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-false-verdict",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "README.md").write_text("outside lease scope\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "README.md"])
            _run(worker, ["git", "commit", "-m", "out of scope", "--", "README.md"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertFalse(audit.ok)
            self.assertEqual(audit.out_of_scope_paths, ["README.md"])
            store.mark_auditing(lease.lease_id)

            forged = audit.to_dict()
            forged["ok"] = True
            forged["reasons"] = []
            forged["out_of_scope_paths"] = []
            canonical = {
                key: value
                for key, value in forged.items()
                if key != "evidence_digest"
            }
            forged["evidence_digest"] = hashlib.sha256(
                json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_audited_pass(lease.lease_id, evidence=forged)
            self.assertEqual(ctx.exception.code, "audit_evidence_unverified")
            self.assertEqual(store.get(lease.lease_id).state, LeaseState.AUDITING)

            with self.assertRaises(ValidationIssue) as ctx:
                build_audit_evidence(audit)
            self.assertEqual(ctx.exception.code, "audit_evidence_not_ok")
            audit.ok = True
            with self.assertRaises(ValidationIssue) as ctx:
                build_audit_evidence(audit)
            self.assertEqual(ctx.exception.code, "audit_result_unverified")

    def test_audit_evidence_redacts_exact_values_from_pre_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-exact-pre-snapshot",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)

            sentinel = "opaque-pre-snapshot-grant-991177"
            evidence = build_audit_evidence(
                audit,
                pre_snapshots={
                    "ordinary": f"prefix:{sentinel}:suffix",
                    f"key-{sentinel}": {"nested": sentinel},
                },
                exact_secret_values={sentinel},
            )
            rendered = json.dumps(evidence, sort_keys=True)
            self.assertNotIn(sentinel, rendered)
            self.assertIn("[REDACTED:exact_grant]", rendered)

    def test_export_and_apply_promotions_reverify_real_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-proof-reverify",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            store.mark_audited_pass(
                lease.lease_id,
                evidence=_audit_evidence(audit),
            )
            lease = store.get(lease.lease_id)

            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_exported(lease.lease_id, str(root / "missing-patches"))
            self.assertEqual(ctx.exception.code, "patch_manifest_dir_missing")
            self.assertEqual(store.get(lease.lease_id).state, LeaseState.AUDITED_PASS)

            patch_dir = root / "patches"
            patches = export_binary_patches(
                lease,
                output_dir=patch_dir,
                chain=audit.commit_chain,
                audit_evidence=_audit_evidence(audit),
            )
            checked = host_apply_check(
                host,
                patches,
                base_head=head,
                lease=lease,
                manifest_dir=patch_dir,
            )
            store.mark_exported(lease.lease_id, str(patch_dir))
            patches[0].write_bytes(patches[0].read_bytes() + b"\n# tampered\n")
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_apply_checked(lease.lease_id, evidence=checked)
            self.assertEqual(ctx.exception.code, "patch_manifest_patch_digest_mismatch")
            self.assertEqual(store.get(lease.lease_id).state, LeaseState.EXPORTED)

    def test_apply_check_rejects_rehashed_patch_with_wrong_candidate_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-rehashed-wrong-tree",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            evidence = _audit_evidence(audit)
            store.mark_audited_pass(lease.lease_id, evidence=evidence)
            lease = store.get(lease.lease_id)
            patch_dir = root / "patches"
            patches = export_binary_patches(
                lease,
                output_dir=patch_dir,
                chain=audit.commit_chain,
                audit_evidence=evidence,
            )

            patch = patches[0]
            original = patch.read_bytes()
            altered = original.replace(b"+print('v2')", b"+print('attacker')")
            self.assertNotEqual(original, altered)
            patch.write_bytes(altered)
            manifest_path = patch_dir / "chain.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            altered_digest = hashlib.sha256(altered).hexdigest()
            manifest["patch_digests"][patch.name] = altered_digest
            manifest["audited_patch_transport_digests"][0]["sha256"] = altered_digest
            canonical = {
                key: value for key, value in manifest.items() if key != "manifest_digest"
            }
            manifest["manifest_digest"] = hashlib.sha256(
                json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValidationIssue) as ctx:
                verify_patch_manifest(lease, output_dir=patch_dir)
            self.assertEqual(
                ctx.exception.code,
                "patch_manifest_transport_authority_mismatch",
            )
            with self.assertRaises(ValidationIssue) as ctx:
                host_apply_check(
                    host,
                    patches,
                    base_head=head,
                    lease=lease,
                    manifest_dir=patch_dir,
                )
            self.assertEqual(
                ctx.exception.code,
                "patch_manifest_transport_authority_mismatch",
            )

    def test_export_rejects_post_audit_format_signature_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-format-signature-race",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            evidence = _audit_evidence(audit)
            store.mark_audited_pass(lease.lease_id, evidence=evidence)
            lease = store.get(lease.lease_id)
            patch_dir = root / "patches"
            sentinel = "opaque-format-signature-attack-771199"

            from cobbler_runtime import audit as audit_module

            real_format = audit_module._format_patch_bytes
            injected = False

            def inject_signature_then_format(
                repo,
                sha,
                *,
                git_dir=None,
                common_dir=None,
            ):
                nonlocal injected
                self.assertIsNotNone(git_dir)
                self.assertIsNotNone(common_dir)
                if not injected:
                    _run(repo, ["git", "config", "format.signature", sentinel])
                    injected = True
                return real_format(
                    repo,
                    sha,
                    git_dir=git_dir,
                    common_dir=common_dir,
                )

            with mock.patch(
                "cobbler_runtime.audit._format_patch_bytes",
                side_effect=inject_signature_then_format,
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    export_binary_patches(
                        lease,
                        output_dir=patch_dir,
                        chain=audit.commit_chain,
                        audit_evidence=evidence,
                    )
            self.assertEqual(ctx.exception.code, "patch_transport_digest_mismatch")
            self.assertTrue(injected)
            self.assertFalse(patch_dir.exists())
            self.assertNotIn(sentinel, str(ctx.exception))

    def test_apply_consumes_retained_bytes_after_post_read_path_swap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-apply-path-swap",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            evidence = _audit_evidence(audit)
            store.mark_audited_pass(lease.lease_id, evidence=evidence)
            lease = store.get(lease.lease_id)
            patch_dir = root / "patches"
            patches = export_binary_patches(
                lease,
                output_dir=patch_dir,
                chain=audit.commit_chain,
                audit_evidence=evidence,
            )
            victim = root / "victim.patch"
            victim.write_bytes(b"malicious but never consumed\n")
            displaced = root / "audited.patch"

            from cobbler_runtime import audit as audit_module

            real_verify = audit_module._read_verified_patch_bundle
            swapped = False

            def verify_then_swap(*args, **kwargs):
                nonlocal swapped
                verified = real_verify(*args, **kwargs)
                if not swapped:
                    first_path = verified.paths[0]
                    first_path.rename(displaced)
                    first_path.symlink_to(victim)
                    swapped = True
                return verified

            with mock.patch(
                "cobbler_runtime.audit._read_verified_patch_bundle",
                side_effect=verify_then_swap,
            ):
                checked = host_apply_check(
                    host,
                    patches,
                    base_head=head,
                    lease=lease,
                    manifest_dir=patch_dir,
                )
            self.assertTrue(checked["ok"])
            self.assertTrue(swapped)
            self.assertEqual(victim.read_bytes(), b"malicious but never consumed\n")

    def test_patch_export_rejects_leaf_and_ancestor_symlinks_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-export-symlink",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            evidence = _audit_evidence(audit)
            store.mark_audited_pass(lease.lease_id, evidence=evidence)
            lease = store.get(lease.lease_id)

            outside_leaf = root / "outside-leaf"
            outside_leaf.mkdir()
            leaf_alias = root / "leaf-alias"
            leaf_alias.symlink_to(outside_leaf, target_is_directory=True)
            with self.assertRaises(ValidationIssue) as ctx:
                export_binary_patches(
                    lease,
                    output_dir=leaf_alias,
                    chain=audit.commit_chain,
                    audit_evidence=evidence,
                )
            self.assertEqual(ctx.exception.code, "export_dir_symlink")
            self.assertEqual(list(outside_leaf.iterdir()), [])

            outside_parent = root / "outside-parent"
            outside_parent.mkdir()
            parent_alias = root / "parent-alias"
            parent_alias.symlink_to(outside_parent, target_is_directory=True)
            with self.assertRaises(ValidationIssue) as ctx:
                export_binary_patches(
                    lease,
                    output_dir=parent_alias / "patches",
                    chain=audit.commit_chain,
                    audit_evidence=evidence,
                )
            self.assertEqual(ctx.exception.code, "export_dir_unsafe")
            self.assertFalse((outside_parent / "patches").exists())

    def test_patch_export_directory_swap_never_writes_through_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-export-dir-swap",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            evidence = _audit_evidence(audit)
            store.mark_audited_pass(lease.lease_id, evidence=evidence)
            lease = store.get(lease.lease_id)

            patch_dir = root / "patches"
            displaced = root / "displaced-patches"
            victim = root / "victim"
            victim.mkdir()
            from cobbler_runtime import audit as audit_module

            real_write = audit_module._write_export_file
            swapped = False

            def swap_then_write(dir_fd, name, data):
                nonlocal swapped
                if not swapped:
                    patch_dir.rename(displaced)
                    patch_dir.symlink_to(victim, target_is_directory=True)
                    swapped = True
                return real_write(dir_fd, name, data)

            with mock.patch(
                "cobbler_runtime.audit._write_export_file",
                side_effect=swap_then_write,
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    export_binary_patches(
                        lease,
                        output_dir=patch_dir,
                        chain=audit.commit_chain,
                        audit_evidence=evidence,
                    )
            self.assertEqual(ctx.exception.code, "export_dir_identity_changed")
            self.assertTrue(swapped)
            self.assertEqual(list(displaced.iterdir()), [])
            self.assertEqual(list(victim.iterdir()), [])

    def test_disposable_apply_check_fails_closed_when_cleanup_leaves_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host = Path(tmp) / "host"
            head = _init_repo(host)
            residue: list[Path] = []

            def leave_residue(path, *args, **kwargs):
                del args, kwargs
                residue.append(Path(path))

            with mock.patch(
                "cobbler_runtime.audit.shutil.rmtree",
                side_effect=leave_residue,
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    host_apply_check(host, [], base_head=head)
            self.assertEqual(ctx.exception.code, "host_disposable_cleanup_failed")
            self.assertTrue(residue)
            for path in residue:
                shutil.rmtree(path, ignore_errors=True)

    def test_out_of_scope_elves_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-bad-path",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head, session_id="sess", adapter="grok-build"),
            )
            store.activate(lease.lease_id)
            elves = worker / ".elves"
            elves.mkdir()
            (elves / "secret.json").write_text("{}\n", encoding="utf-8")
            _run(worker, ["git", "add", "-f", "--", ".elves/secret.json"])
            _run(worker, ["git", "commit", "-m", "bad elves edit", "--", ".elves/secret.json"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertFalse(audit.ok)
            self.assertTrue(any("out-of-scope" in r for r in audit.reasons))

    def test_unexpected_merge_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-merge",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head, session_id="sess", adapter="grok-build"),
            )
            # Create two divergent commits and merge
            _run(worker, ["git", "checkout", "-b", "side-a"])
            (worker / "src" / "a.py").write_text("a\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/a.py"])
            _run(worker, ["git", "commit", "-m", "a", "--", "src/a.py"])
            _run(worker, ["git", "checkout", "-b", "side-b", head])
            (worker / "src" / "b.py").write_text("b\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/b.py"])
            _run(worker, ["git", "commit", "-m", "b", "--", "src/b.py"])
            _run(worker, ["git", "merge", "--no-ff", "side-a", "-m", "merge sides"])
            # Detach at merge tip for audit
            tip = _git(worker, "rev-parse", "HEAD")
            _run(worker, ["git", "checkout", "--detach", tip])
            # Update lease base is still original head - chain will fail merge parent
            lease = store.get(lease.lease_id)
            lease.base_head = head
            store.save(lease)
            with self.assertRaises(ValidationIssue) as ctx:
                list_commit_chain(worker, head, tip)
            self.assertIn(ctx.exception.code, {"unexpected_merge_or_root", "commit_chain_not_descendant", "chain_parent_mismatch"})

    def test_new_ref_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-ref",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head, session_id="sess", adapter="grok-build"),
            )
            pre = pre_turn_snapshots(worker)
            (worker / "src" / "app.py").write_text("v\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "ok", "--", "src/app.py"])
            _run(worker, ["git", "tag", "evil-tag"])
            audit = audit_lease_turn(
                store.get(lease.lease_id),
                pre_refs_digest=pre["refs_digest"],
            )
            self.assertFalse(audit.ok)
            self.assertTrue(audit.refs_changed)

    def test_push_attempt_and_process_leak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-push",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head, session_id="sess", adapter="grok-build"),
            )
            audit = audit_lease_turn(
                store.get(lease.lease_id),
                observed_commands=["git push origin HEAD"],
                process_baseline=["worker-main"],
                process_observed=["worker-main", "lingering-paid-job"],
            )
            self.assertFalse(audit.ok)
            self.assertTrue(any("forbidden" in r for r in audit.reasons))
            self.assertTrue(any("process leak" in r for r in audit.reasons))

    def test_dirty_index_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-dirty",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head, session_id="sess", adapter="grok-build"),
            )
            (worker / "src" / "app.py").write_text("staged?\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertFalse(audit.ok)
            self.assertTrue(audit.staged)

    def test_hidden_index_flags_cannot_mask_dirty_tracked_content(self) -> None:
        for update_flag in ("--skip-worktree", "--assume-unchanged"):
            with self.subTest(update_flag=update_flag), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                host = root / "host"
                worker = root / "worker"
                head = _init_repo(host)
                _detached_worktree(host, worker, head)
                store = LeaseStore(host)
                _register_session(host, "sess", worker=worker, head=head)
                lease = store.prepare(
                    lease_id="lease-hidden-" + update_flag.removeprefix("--"),
                    host_checkout=host,
                    worker_checkout=worker,
                    session_id="sess",
                    base_head=head,
                    adapter="grok-build",
                    profile="grok-build-write",
                    allowed_paths=["src/"],
                    qualification_evidence=_qual(
                        worker,
                        head,
                        session_id="sess",
                        adapter="grok-build",
                    ),
                )
                store.activate(lease.lease_id)
                _run(worker, ["git", "update-index", update_flag, "src/app.py"])
                (worker / "src" / "app.py").write_text(
                    "hidden dirty content\n",
                    encoding="utf-8",
                )
                self.assertEqual(_git(worker, "status", "--porcelain"), "")

                with self.assertRaises(ValidationIssue) as ctx:
                    audit_lease_turn(store.get(lease.lease_id))
                self.assertEqual(ctx.exception.code, "git_index_flags_unsafe")

    def test_workspace_sandbox_rejects_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head, profile="workspace")
            # Unsupported sandbox_profile cannot qualify or enable detached commits.
            with self.assertRaises(ValidationIssue) as ctx:
                store.prepare(
                    lease_id="lease-workspace",
                    host_checkout=host,
                    worker_checkout=worker,
                    session_id="sess",
                    base_head=head,
                    adapter="grok-build",
                    profile="workspace",
                    sandbox_profile="workspace",
                    allowed_paths=["src/"],
                    qualification_evidence=_qual(
                        worker,
                        head,
                        session_id="sess",
                        adapter="grok-build",
                        sandbox="workspace",
                        profile="workspace",
                    ),
                )
            self.assertIn("sandbox", ctx.exception.message.lower())
            # Evidence/profile mismatch fails closed.
            with self.assertRaises(ValidationIssue):
                store.prepare(
                    lease_id="lease-workspace-mismatch",
                    host_checkout=host,
                    worker_checkout=worker,
                    session_id="sess",
                    base_head=head,
                    adapter="grok-build",
                    profile="workspace",
                    sandbox_profile="workspace",
                    allowed_paths=["src/"],
                    qualification_evidence=_qual(
                        worker,
                        head,
                        session_id="sess",
                        adapter="grok-build",
                        sandbox="devbox",
                        profile="workspace",
                    ),
                )
            # Explicit detached_commits_permitted=False with supported sandbox.
            lease = store.prepare(
                lease_id="lease-no-detach",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="workspace",
                sandbox_profile="devbox",
                allowed_paths=["src/"],
                detached_commits_permitted=False,
                qualification_evidence=_qual(
                    worker,
                    head,
                    session_id="sess",
                    adapter="grok-build",
                    sandbox="devbox",
                    profile="workspace",
                ),
            )
            self.assertFalse(lease.detached_commits_permitted)
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("x\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "should fail policy", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertFalse(audit.ok)
            self.assertTrue(any("detached_commits_permitted" in r for r in audit.reasons))

    def test_cleanup_refresh_after_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-refresh",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head, session_id="sess", adapter="grok-build"),
            )
            store.activate(lease.lease_id)
            # Worker produces the audited tree; host independently imports the
            # same tree before integration can be claimed.
            (worker / "src" / "app.py").write_text("host v2\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker change", "--", "src/app.py"])
            audit = audit_lease_turn(store.get(lease.lease_id))
            self.assertTrue(audit.ok, audit.reasons)
            store.mark_auditing(lease.lease_id)
            store.mark_audited_pass(
                lease.lease_id,
                evidence=_audit_evidence(audit),
            )
            audited_lease = store.get(lease.lease_id)
            patch_dir = root / "patches"
            patches = export_binary_patches(
                audited_lease,
                output_dir=patch_dir,
                chain=audit.commit_chain,
                audit_evidence=_audit_evidence(audit),
            )
            checked = host_apply_check(
                host,
                patches,
                base_head=head,
                lease=audited_lease,
                manifest_dir=patch_dir,
            )
            store.mark_exported(lease.lease_id, str(patch_dir))
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_integrated(lease.lease_id, new_tip=head)
            self.assertEqual(ctx.exception.code, "integrate_requires_apply_checked")
            store.mark_apply_checked(lease.lease_id, evidence=checked)
            with self.assertRaises(ValidationIssue) as ctx:
                store.refresh_worker_to_tip(lease.lease_id, new_tip=head)
            self.assertEqual(ctx.exception.code, "invalid_lease_state")
            (host / "src" / "app.py").write_text("host v2\n", encoding="utf-8")
            _run(host, ["git", "add", "--", "src/app.py"])
            _run(host, ["git", "commit", "-m", "host integrate", "--", "src/app.py"])
            new_tip = _git(host, "rev-parse", "HEAD")
            (worker / "src" / "app.py").write_text("dirty\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue):
                store.mark_integrated(lease.lease_id, new_tip=new_tip)
            self.assertEqual(store.get(lease.lease_id).state, LeaseState.APPLY_CHECKED)
            _run(worker, ["git", "checkout", "--", "src/app.py"])
            store.mark_integrated(lease.lease_id, new_tip=new_tip)
            with self.assertRaises(ValidationIssue) as ctx:
                store.refresh_worker_to_tip(lease.lease_id, new_tip=head)
            self.assertEqual(ctx.exception.code, "refresh_tip_mismatch")
            result = store.refresh_worker_to_tip(lease.lease_id, new_tip=new_tip)
            self.assertEqual(result["worker_tip"], new_tip)
            self.assertEqual(_git(worker, "rev-parse", "HEAD"), new_tip)

    def test_mark_integrated_rejects_host_tree_that_differs_from_audited_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-tree-mismatch",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("worker tree\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker tree", "--", "src/app.py"])
            _prove_worker_handoff(
                store,
                lease.lease_id,
                host=host,
                patch_dir=root / "patches",
            )
            (host / "src" / "app.py").write_text("different host tree\n", encoding="utf-8")
            _run(host, ["git", "add", "--", "src/app.py"])
            _run(host, ["git", "commit", "-m", "wrong import", "--", "src/app.py"])
            host_tip = _git(host, "rev-parse", "HEAD")
            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_integrated(lease.lease_id, new_tip=host_tip)
            self.assertEqual(ctx.exception.code, "integration_tree_mismatch")
            self.assertEqual(store.get(lease.lease_id).state, LeaseState.APPLY_CHECKED)

    def test_mark_integrated_cannot_be_forged_with_replacement_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            _register_session(host, "sess", worker=worker, head=head)
            lease = store.prepare(
                lease_id="lease-replacement-forgery",
                host_checkout=host,
                worker_checkout=worker,
                session_id="sess",
                base_head=head,
                adapter="grok-build",
                profile="grok-build-write",
                allowed_paths=["src/"],
                qualification_evidence=_qual(worker, head),
            )
            store.activate(lease.lease_id)
            (worker / "src" / "app.py").write_text("audited worker tree\n", encoding="utf-8")
            _run(worker, ["git", "add", "--", "src/app.py"])
            _run(worker, ["git", "commit", "-m", "worker tree", "--", "src/app.py"])
            proved_lease, _patches, _checked = _prove_worker_handoff(
                store,
                lease.lease_id,
                host=host,
                patch_dir=root / "patches",
            )
            audited_tip = str(proved_lease.worker_tip)
            (host / "src" / "app.py").write_text("wrong raw host tree\n", encoding="utf-8")
            _run(host, ["git", "add", "--", "src/app.py"])
            _run(host, ["git", "commit", "-m", "wrong host integration", "--", "src/app.py"])
            wrong_tip = _git(host, "rev-parse", "HEAD")
            _run(host, ["git", "replace", wrong_tip, audited_tip])
            _run(host, ["git", "reset", "--hard", wrong_tip])

            raw_env = dict(os.environ)
            raw_env["GIT_NO_REPLACE_OBJECTS"] = "1"
            raw_host_tree = subprocess.run(
                ["git", "rev-parse", f"{wrong_tip}^{{tree}}"],
                cwd=str(host),
                check=True,
                capture_output=True,
                text=True,
                env=raw_env,
            ).stdout.strip()
            raw_worker_tree = subprocess.run(
                ["git", "rev-parse", f"{audited_tip}^{{tree}}"],
                cwd=str(worker),
                check=True,
                capture_output=True,
                text=True,
                env=raw_env,
            ).stdout.strip()
            self.assertNotEqual(raw_host_tree, raw_worker_tree)

            with self.assertRaises(ValidationIssue) as ctx:
                store.mark_integrated(lease.lease_id, new_tip=wrong_tip)
            self.assertIn(
                ctx.exception.code,
                {"host_dirty_on_integrate", "integration_tree_mismatch"},
            )
            self.assertEqual(store.get(lease.lease_id).state, LeaseState.APPLY_CHECKED)


class LeaseStorageContainmentTests(unittest.TestCase):
    @staticmethod
    def _lease(lease_id: str) -> WriterLease:
        return WriterLease(
            lease_id=lease_id,
            host_checkout="/host",
            worker_checkout="/worker",
            session_id="session",
            base_head="a" * 40,
            adapter="grok-build",
            profile="grok-build-write",
        )

    def test_symlinked_elves_ancestor_fails_before_outside_directory_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            outside = base / "outside"
            repo.mkdir()
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            (repo / ".elves").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(StorageError) as ctx:
                LeaseStore(repo)
            self.assertEqual(ctx.exception.code, "symlink_component")
            self.assertFalse((outside / "runtime").exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged\n")

    def test_record_and_lock_symlink_leaves_do_not_mutate_outside_targets(self) -> None:
        for leaf_kind in ("record", "lock"):
            with self.subTest(leaf_kind=leaf_kind), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                repo = base / "repo"
                outside = base / "outside"
                repo.mkdir()
                outside.mkdir()
                store = LeaseStore(repo)
                lease_id = f"unsafe-{leaf_kind}"
                record_path = store.root / record_filename(lease_id, prefix="lease")
                leaf_path = (
                    record_path if leaf_kind == "record" else store.root / "store.lock"
                )
                target = outside / f"{leaf_kind}.json"
                original = '{"sentinel": "unchanged"}\n'
                target.write_text(original, encoding="utf-8")
                leaf_path.symlink_to(target)

                with self.assertRaises((StorageError, ValidationIssue)):
                    store.save(self._lease(lease_id))
                self.assertEqual(target.read_text(encoding="utf-8"), original)
                if leaf_kind == "lock":
                    self.assertFalse(record_path.exists())


class GrokWriteProfileTests(unittest.TestCase):
    def test_write_resume_rejects_fugu_adapter_and_model(self) -> None:
        for adapter, executable, model in (
            ("CoDeX-FuGu", None, None),
            ("claude-code", "Claude-Fugu", None),
            ("claude-code", "claude", "fugu[1m]"),
        ):
            with self.subTest(adapter=adapter, executable=executable, model=model):
                with self.assertRaises(ValidationIssue) as raised:
                    build_write_resume_invocation(
                        adapter=adapter,
                        session_id="exact-session",
                        cwd="/verified/worktree",
                        executable=executable,
                        requested_model=model,
                    )
                self.assertEqual(
                    raised.exception.code,
                    "fugu_implementation_route_blocked",
                )
        with mock.patch.dict(
            os.environ,
            {"ANTHROPIC_BASE_URL": "https://api.sakana.ai"},
        ):
            with self.assertRaises(ValidationIssue) as endpoint:
                build_write_resume_invocation(
                    adapter="claude-code",
                    session_id="exact-session",
                    cwd="/verified/worktree",
                    executable="claude",
                    requested_model="current-model",
                )
        self.assertEqual(
            endpoint.exception.code,
            "fugu_implementation_route_blocked",
        )

    def test_headless_worktree_resume_forbidden(self) -> None:
        profile = grok_write_profile("0.2.93")
        self.assertTrue(profile.forbid_headless_worktree_resume)
        self.assertTrue(profile.qualified)
        with self.assertRaises(ValidationIssue) as ctx:
            build_write_resume_invocation(
                adapter="grok-build",
                session_id="child-id",
                cwd="/verified/worktree",
                version="0.2.93",
                use_headless_worktree_resume=True,
            )
        self.assertEqual(ctx.exception.code, "grok_headless_worktree_resume_forbidden")

    def test_write_resume_requires_cwd_and_exact_id(self) -> None:
        session_id = "11111111-1111-4111-8111-111111111111"
        inv = build_write_resume_invocation(
            adapter="grok-build",
            session_id=session_id,
            cwd="/verified/worktree",
            version="0.2.93",
        )
        self.assertIn(session_id, inv.argv)
        self.assertIn("/verified/worktree", inv.argv)
        self.assertNotIn("--worktree", inv.argv)
        with self.assertRaises(ValidationIssue):
            build_write_resume_invocation(
                adapter="grok-build",
                session_id=session_id,
                cwd="",
                version="0.2.93",
            )

    def test_workspace_sandbox_not_commit_capable(self) -> None:
        profile = workspace_sandbox_write_profile()
        self.assertFalse(profile.qualified)
        self.assertFalse(profile.detached_commits_permitted)


class UnqualifiedWriteTests(unittest.TestCase):
    def test_writer_lease_rejects_fugu_before_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValidationIssue) as raised:
                LeaseStore(root).prepare(
                    lease_id="fugu-lease",
                    host_checkout=root / "host",
                    worker_checkout=root / "worker",
                    session_id="session",
                    base_head="0" * 40,
                    adapter="CLAUDE-FUGU",
                    profile="claude-fugu",
                )
            self.assertEqual(
                raised.exception.code,
                "fugu_implementation_route_blocked",
            )

    def test_unqualified_profile_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "host"
            worker = root / "worker"
            head = _init_repo(host)
            _detached_worktree(host, worker, head)
            store = LeaseStore(host)
            with self.assertRaises(ValidationIssue) as ctx:
                _register_session(host, "sess", worker=worker, head=head)
                store.prepare(
                    lease_id="lease-unqual",
                    host_checkout=host,
                    worker_checkout=worker,
                    session_id="sess",
                    base_head=head,
                    adapter="grok-build",
                    profile="unqualified",
                    write_profile_qualified=False,
                qualification_evidence=_qual(worker, head, session_id="sess", adapter="grok-build"),
                )
            self.assertEqual(ctx.exception.code, "write_profile_unqualified")


if __name__ == "__main__":
    unittest.main()
