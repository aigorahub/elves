from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
CLI = SCRIPTS / "cobbler_agents.py"


def _ensure_import_path() -> None:
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


_ensure_import_path()

from cobbler_runtime.adapters import (  # noqa: E402
    AMBIGUOUS_SESSION_FLAG_PATTERNS,
    assert_no_ambiguous_session_flags,
    build_session_create_invocation,
    build_session_resume_invocation,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402
from cobbler_runtime.sessions import (  # noqa: E402
    CreationMethod,
    SessionLifecycle,
    SessionRegistry,
    assert_grok_worktree_isolation,
    compute_context_digest,
    evaluate_session_continuity,
    grok_headless_worktree_resume_supported,
    parse_grok_child_summary,
    parse_usage_payload,
    register_grok_child,
    transition_lifecycle,
)
from cobbler_runtime.storage import StorageError, record_filename  # noqa: E402


class LifecycleTests(unittest.TestCase):
    def test_valid_and_invalid_transitions(self) -> None:
        self.assertEqual(
            transition_lifecycle(SessionLifecycle.NEW, SessionLifecycle.ACTIVE),
            SessionLifecycle.ACTIVE,
        )
        self.assertEqual(
            transition_lifecycle(SessionLifecycle.ACTIVE, SessionLifecycle.REHYDRATION_REQUIRED),
            SessionLifecycle.REHYDRATION_REQUIRED,
        )
        with self.assertRaises(ValidationIssue) as ctx:
            transition_lifecycle(SessionLifecycle.CLOSED, SessionLifecycle.ACTIVE)
        self.assertEqual(ctx.exception.code, "invalid_lifecycle_transition")
        with self.assertRaises(ValidationIssue):
            transition_lifecycle(SessionLifecycle.DRIFTED, SessionLifecycle.ACTIVE)


class DigestAndContinuityTests(unittest.TestCase):
    def test_digest_changes_when_plan_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan.md"
            plan.write_text("batch 1\n", encoding="utf-8")
            d1 = compute_context_digest(
                session_id="s1",
                harness="claude-code",
                profile="claude-code",
                role="planning",
                requested_model="m",
                actual_model="m",
                parent_id=None,
                cwd=str(root),
                worktree=None,
                source_head="abc",
                plan_path=plan,
            )
            plan.write_text("batch 1\nbatch 2\n", encoding="utf-8")
            d2 = compute_context_digest(
                session_id="s1",
                harness="claude-code",
                profile="claude-code",
                role="planning",
                requested_model="m",
                actual_model="m",
                parent_id=None,
                cwd=str(root),
                worktree=None,
                source_head="abc",
                plan_path=plan,
            )
        self.assertNotEqual(d1.digest, d2.digest)
        self.assertIn("plan_sha256", d1.components)

    def test_expected_head_change_requests_rehydration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            rec = reg.create(
                session_id="sess-1",
                harness="claude-code",
                profile="claude-code",
                role="review",
                actual_model="model-a",
                cwd=str(Path(tmp)),
                source_head="head-old",
            )
            rec = reg.activate("sess-1")
            digest = compute_context_digest(
                session_id=rec.session_id,
                harness=rec.harness,
                profile=rec.profile,
                role=rec.role,
                requested_model=rec.requested_model,
                actual_model=rec.actual_model,
                parent_id=rec.parent_id,
                cwd=rec.cwd,
                worktree=rec.worktree,
                source_head="head-new",
            )
            result = evaluate_session_continuity(
                rec,
                observed_model=rec.actual_model,
                observed_cwd=rec.cwd,
                observed_worktree=None,
                observed_parent_id=None,
                observed_head="head-new",
                current_digest=digest,
            )
        self.assertTrue(result.ok)
        self.assertTrue(result.expected_change)
        self.assertIsNotNone(result.rehydration)
        self.assertFalse(result.write_reuse_blocked)

    def test_model_or_cwd_drift_blocks_write_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            rec = reg.create(
                session_id="sess-2",
                harness="grok-build",
                profile="grok-build",
                role="implement",
                actual_model="grok-model",
                cwd="/work/a",
                source_head="h1",
            )
            digest = compute_context_digest(
                session_id=rec.session_id,
                harness=rec.harness,
                profile=rec.profile,
                role=rec.role,
                requested_model=None,
                actual_model="other-model",
                parent_id=None,
                cwd="/work/b",
                worktree=None,
                source_head="h1",
            )
            result = evaluate_session_continuity(
                rec,
                observed_model="other-model",
                observed_cwd="/work/b",
                observed_worktree=None,
                observed_parent_id=None,
                observed_head="h1",
                current_digest=digest,
            )
        self.assertFalse(result.ok)
        self.assertTrue(result.write_reuse_blocked)
        self.assertTrue(any("actual_model" in r for r in result.reasons))
        self.assertTrue(any("cwd" in r for r in result.reasons))


class RegistryLifecycleTests(unittest.TestCase):
    def test_explicit_cas_rejects_caller_revision_mismatch_and_increments_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            current = reg.create(
                session_id="cas-explicit",
                harness="grok-build",
                profile="grok-build-write",
                role="implement",
            )
            stale = type(current).from_dict(current.to_dict())
            stale.revision = 0
            with self.assertRaises(ValidationIssue) as ctx:
                reg.save(stale, expected_revision=current.revision)
            self.assertEqual(ctx.exception.code, "session_revision_conflict")
            fresh = reg.get("cas-explicit")
            prior = fresh.revision
            saved = reg.save(fresh, expected_revision=prior)
            self.assertEqual(saved.revision, prior + 1)

    def test_revision_zero_cannot_overwrite_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            current = reg.create(
                session_id="cas-zero",
                harness="grok-build",
                profile="grok-build-write",
                role="implement",
            )
            stale = type(current).from_dict(current.to_dict())
            stale.revision = 0
            with self.assertRaises(ValidationIssue) as ctx:
                reg.save(stale)
            self.assertEqual(ctx.exception.code, "session_revision_conflict")

    def test_exact_create_resume_and_closed_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            rec = reg.create(
                session_id="exact-1",
                harness="claude-code",
                profile="claude-code",
                role="planning",
                requested_model="m1",
                actual_model="m1",
                cwd=str(Path(tmp) / "wt"),
                source_head="abc",
            )
            self.assertEqual(rec.lifecycle, SessionLifecycle.NEW)
            rec = reg.activate("exact-1")
            self.assertEqual(rec.lifecycle, SessionLifecycle.ACTIVE)
            updated, drift = reg.resume_exact(
                "exact-1",
                observed_model="m1",
                observed_cwd=str(Path(tmp) / "wt"),
                observed_head="abc",
            )
            self.assertTrue(drift.ok)
            self.assertEqual(updated.resume_method, "exact_id")
            reg.close("exact-1")
            with self.assertRaises(ValidationIssue) as ctx:
                reg.resume_exact(
                    "exact-1",
                    observed_model="m1",
                    observed_cwd=str(Path(tmp) / "wt"),
                )
            self.assertEqual(ctx.exception.code, "session_closed")

    def test_missing_session_and_stale_rehydration_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            with self.assertRaises(ValidationIssue) as ctx:
                reg.get("no-such-session")
            self.assertEqual(ctx.exception.code, "session_not_found")

            plan = Path(tmp) / "plan.md"
            plan.write_text("v1\n", encoding="utf-8")
            reg.create(
                session_id="s-rehyd",
                harness="codex-fugu",
                profile="codex-fugu",
                role="review",
                actual_model="fugu",
                cwd=str(tmp),
                source_head="h1",
                plan_path=plan,
            )
            reg.activate("s-rehyd")
            original = reg.get("s-rehyd")
            original_digest = original.context_digest
            plan.write_text("v2\n", encoding="utf-8")
            rec, drift = reg.resume_exact(
                "s-rehyd",
                observed_model="fugu",
                observed_cwd=str(tmp),
                observed_head="h1",
                plan_path=plan,
            )
            self.assertTrue(drift.expected_change)
            self.assertEqual(rec.lifecycle, SessionLifecycle.REHYDRATION_REQUIRED)
            # Active digest must stay frozen until rehydration proof.
            self.assertEqual(rec.context_digest, original_digest)
            self.assertIsNotNone(rec.pending_context_digest)
            self.assertNotEqual(rec.pending_context_digest, original_digest)

    def test_resume_cannot_activate_until_rehydration_proof_matches_pending_digest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            plan = Path(tmp) / "plan.md"
            plan.write_text("v1\n", encoding="utf-8")
            reg.create(
                session_id="proof-1",
                harness="claude-code",
                profile="claude-code",
                role="review",
                actual_model="m",
                cwd=str(tmp),
                source_head="h1",
                plan_path=plan,
            )
            reg.activate("proof-1")
            before = reg.get("proof-1")
            plan.write_text("v2\n", encoding="utf-8")
            rec, drift = reg.resume_exact(
                "proof-1",
                observed_model="m",
                observed_cwd=str(tmp),
                observed_head="h1",
                plan_path=plan,
            )
            self.assertEqual(rec.lifecycle, SessionLifecycle.REHYDRATION_REQUIRED)
            self.assertEqual(rec.context_digest, before.context_digest)
            pending = rec.pending_context_digest
            self.assertTrue(pending)
            self.assertNotEqual(pending, before.context_digest)

            # Wrong model while rehydration is pending blocks write reuse.
            rec_bad, drift_bad = reg.resume_exact(
                "proof-1",
                observed_model="wrong-model",
                observed_cwd=str(tmp),
                observed_head="h1",
                plan_path=plan,
            )
            self.assertTrue(drift_bad.write_reuse_blocked)
            self.assertEqual(rec_bad.lifecycle, SessionLifecycle.DRIFTED)
            self.assertEqual(rec_bad.context_digest, before.context_digest)

            # Fresh session for the successful proof path.
            plan.write_text("v1\n", encoding="utf-8")
            reg.create(
                session_id="proof-2",
                harness="claude-code",
                profile="claude-code",
                role="review",
                actual_model="m",
                cwd=str(tmp),
                source_head="h1",
                plan_path=plan,
            )
            reg.activate("proof-2")
            plan.write_text("v2\n", encoding="utf-8")
            rec2, _ = reg.resume_exact(
                "proof-2",
                observed_model="m",
                observed_cwd=str(tmp),
                observed_head="h1",
                plan_path=plan,
            )
            pending2 = rec2.pending_context_digest
            self.assertEqual(rec2.lifecycle, SessionLifecycle.REHYDRATION_REQUIRED)
            # Second exact resume with matching pending digest promotes to active.
            rec3, drift3 = reg.resume_exact(
                "proof-2",
                observed_model="m",
                observed_cwd=str(tmp),
                observed_head="h1",
                plan_path=plan,
            )
            self.assertTrue(drift3.ok or drift3.expected_change)
            self.assertEqual(rec3.lifecycle, SessionLifecycle.ACTIVE)
            self.assertEqual(rec3.context_digest, pending2)
            self.assertIsNone(rec3.pending_context_digest)
            self.assertEqual(rec3.resume_method, "exact_id_rehydrated")

    def test_readonly_list_does_not_create_runtime_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = SessionRegistry.open_readonly(root)
            sessions = reg.list_sessions()
            self.assertEqual(sessions, [])
            self.assertFalse((root / ".elves" / "runtime" / "sessions").exists())

    def test_malformed_session_record_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            reg.create(
                session_id="good",
                harness="claude-code",
                profile="claude-code",
                role="review",
                actual_model="m",
                cwd=str(tmp),
                source_head="h",
            )
            bad = reg.root / "broken.json"
            bad.write_text("{not-json", encoding="utf-8")
            records = reg.list_sessions()
            self.assertEqual(len(records), 1)
            self.assertEqual(len(reg.malformed_records), 1)
            with self.assertRaises(ValidationIssue) as ctx:
                reg.list_sessions_strict()
            self.assertEqual(ctx.exception.code, "session_record_malformed")

    def test_parent_child_validation_on_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            reg.create(
                session_id="child-1",
                harness="grok-build",
                profile="grok-build",
                role="implement",
                actual_model="m",
                parent_id="parent-1",
                cwd=str(tmp),
                source_head="h",
                creation_method=CreationMethod.FORK_CHILD,
            )
            reg.activate("child-1")
            rec, drift = reg.resume_exact(
                "child-1",
                observed_model="m",
                observed_cwd=str(tmp),
                observed_parent_id="wrong-parent",
                observed_head="h",
            )
            self.assertTrue(drift.write_reuse_blocked)
            self.assertEqual(rec.lifecycle, SessionLifecycle.DRIFTED)
            self.assertTrue(rec.write_reuse_blocked)


class RegistryStorageContainmentTests(unittest.TestCase):
    @staticmethod
    def _create(registry: SessionRegistry, session_id: str) -> None:
        registry.create(
            session_id=session_id,
            harness="grok-build",
            profile="grok-build",
            role="implementer",
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
                SessionRegistry(repo)
            self.assertEqual(ctx.exception.code, "symlink_component")
            self.assertFalse((outside / "runtime").exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged\n")

    def test_record_index_and_lock_symlink_leaves_fail_without_target_mutation(self) -> None:
        for leaf_kind in ("record", "index", "lock"):
            with self.subTest(leaf_kind=leaf_kind), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                repo = base / "repo"
                outside = base / "outside"
                repo.mkdir()
                outside.mkdir()
                registry = SessionRegistry(repo)
                session_id = f"unsafe-{leaf_kind}"
                record_path = registry.root / record_filename(session_id, prefix="sess")
                leaf_path = {
                    "record": record_path,
                    "index": registry.root / "index.json",
                    "lock": registry.root / "store.lock",
                }[leaf_kind]
                target = outside / f"{leaf_kind}.json"
                original = '{"sentinel": "unchanged"}\n'
                target.write_text(original, encoding="utf-8")
                leaf_path.symlink_to(target)

                with self.assertRaises(StorageError):
                    self._create(registry, session_id)
                self.assertEqual(target.read_text(encoding="utf-8"), original)
                if leaf_kind != "record":
                    self.assertFalse(record_path.exists())


class SessionListCliTests(unittest.TestCase):
    @staticmethod
    def _invoke(root: Path, *, json_output: bool = True) -> subprocess.CompletedProcess[str]:
        argv = [
            sys.executable,
            str(CLI),
            "session",
            "list",
            "--repo-root",
            str(root),
        ]
        if json_output:
            argv.append("--json")
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _invoke_action(
        root: Path,
        action: str,
        *,
        session_id: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = [sys.executable, str(CLI)]
        if action == "doctor":
            argv.extend(["doctor", "--repo-root", str(root), "--json"])
        else:
            argv.extend(["session", action, "--repo-root", str(root), "--json"])
            if session_id is not None:
                argv.extend(["--session-id", session_id])
        return subprocess.run(argv, capture_output=True, text=True, check=False)

    @staticmethod
    def _regular_files(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }

    def test_valid_list_preserves_read_only_output_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = SessionRegistry(root)
            registry.create(
                session_id="valid-list",
                harness="claude-code",
                profile="claude-code",
                role="review",
            )
            before = self._regular_files(root)

            result = self._invoke(root)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["read_only"])
            self.assertFalse(payload["mutated_repo"])
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["sessions"][0]["session_id"], "valid-list")
            self.assertEqual(self._regular_files(root), before)

    def test_malformed_record_returns_structured_exit_one_without_mutation(self) -> None:
        malformed_payloads = (
            "{not-json",
            '{"usage": []}',
            '{"session_id":"bad","harness":"x","profile":"x","revision":1e100000}',
        )
        for malformed in malformed_payloads:
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                registry = SessionRegistry(root)
                registry.create(
                    session_id="good-list",
                    harness="claude-code",
                    profile="claude-code",
                    role="review",
                )
                (registry.root / "broken.json").write_text(
                    malformed,
                    encoding="utf-8",
                )
                before = self._regular_files(root)

                result = self._invoke(root)

                self.assertEqual(result.returncode, 1, result.stderr)
                payload = json.loads(result.stdout)
                self.assertFalse(payload["ok"])
                self.assertTrue(payload["read_only"])
                self.assertFalse(payload["mutated_repo"])
                self.assertEqual(payload["sessions"], [])
                self.assertEqual(payload["count"], 0)
                self.assertEqual(
                    payload["issues"][0]["code"],
                    "session_record_malformed",
                )
                self.assertEqual(self._regular_files(root), before)

    def test_malformed_values_never_leak_from_list_probe_or_doctor(self) -> None:
        mutations = {
            "lifecycle": "super-secret-value-123456789",
            "usage": "opaque-legacy-credential-987654321",
        }
        for field_name, sentinel in mutations.items():
            with self.subTest(field_name=field_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                session_id = f"malformed-{field_name}"
                registry = SessionRegistry(root)
                registry.create(
                    session_id=session_id,
                    harness="claude-code",
                    profile="claude-code",
                    role="review",
                )
                record_path = registry._record_path(session_id)
                payload = json.loads(record_path.read_text(encoding="utf-8"))
                payload[field_name] = sentinel
                record_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                before = self._regular_files(root)

                for action in ("list", "probe", "doctor"):
                    with self.subTest(action=action):
                        result = self._invoke_action(
                            root,
                            action,
                            session_id=session_id if action == "probe" else None,
                        )
                        self.assertEqual(result.returncode, 1, result.stderr)
                        response = json.loads(result.stdout)
                        self.assertFalse(response["ok"])
                        surfaced = result.stdout + result.stderr
                        self.assertNotIn(sentinel, surfaced)
                        self.assertNotIn("Traceback", surfaced)
                        self.assertIn(
                            response["issues"][0]["code"],
                            {"session_record_malformed"},
                        )
                self.assertEqual(self._regular_files(root), before)

    def test_listing_binds_filenames_and_rejects_duplicate_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_id = "bound-session-record"
            registry = SessionRegistry(root)
            registry.create(
                session_id=session_id,
                harness="codex",
                profile="codex",
                role="review",
            )
            canonical = registry._record_path(session_id)
            misnamed = registry.root / "attacker.json"
            canonical.rename(misnamed)
            with self.assertRaises(ValidationIssue) as ctx:
                registry.list_sessions_strict()
            self.assertEqual(ctx.exception.code, "session_record_malformed")
            misnamed.rename(canonical)

            legacy = registry._legacy_record_path(session_id)
            legacy.write_bytes(canonical.read_bytes())
            with self.assertRaises(ValidationIssue) as ctx:
                registry.list_sessions_strict()
            self.assertEqual(ctx.exception.code, "session_record_malformed")
            with self.assertRaises(ValidationIssue) as ctx:
                registry.get(session_id)
            self.assertEqual(ctx.exception.code, "session_record_ambiguous")

    def test_empty_enums_and_boolean_revision_are_not_defaulted(self) -> None:
        for field_name, bad_value in (
            ("creation_method", ""),
            ("lifecycle", ""),
            ("revision", False),
        ):
            with self.subTest(field_name=field_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                session_id = f"strict-{field_name}"
                registry = SessionRegistry(root)
                registry.create(
                    session_id=session_id,
                    harness="codex",
                    profile="codex",
                    role="review",
                )
                path = registry._record_path(session_id)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload[field_name] = bad_value
                path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                with self.assertRaises(ValidationIssue) as ctx:
                    registry.list_sessions_strict()
                self.assertEqual(ctx.exception.code, "session_record_malformed")

    def test_malformed_nested_usage_is_rejected_without_leak_or_mutation(self) -> None:
        cases = (
            {"input_tokens": []},
            {
                "quota_known": "false",
                "remaining_quota": "opaque-usage-sentinel-123456789",
            },
            {"cost_usd": float("inf")},
            {"quota_known": True, "remaining_quota": None},
        )
        for index, malformed_usage in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                session_id = f"strict-usage-{index}"
                registry = SessionRegistry(root)
                registry.create(
                    session_id=session_id,
                    harness="codex",
                    profile="codex",
                    role="review",
                )
                path = registry._record_path(session_id)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["usage"] = malformed_usage
                path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                before = self._regular_files(root)

                for action in ("list", "probe", "doctor"):
                    result = self._invoke_action(
                        root,
                        action,
                        session_id=session_id if action == "probe" else None,
                    )
                    self.assertEqual(result.returncode, 1, result.stderr)
                    response = json.loads(result.stdout)
                    self.assertFalse(response["ok"])
                    self.assertEqual(
                        response["issues"][0]["code"],
                        "session_record_malformed",
                    )
                    self.assertNotIn("opaque-usage-sentinel", result.stdout)
                    self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertEqual(self._regular_files(root), before)

    def test_legacy_session_is_readable_but_cannot_gain_write_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_id = "legacy-read-only-session"
            registry = SessionRegistry(root)
            registry.create(
                session_id=session_id,
                harness="claude-code",
                profile="claude-code",
                role="review",
            )
            canonical = registry._record_path(session_id)
            legacy = registry._legacy_record_path(session_id)
            canonical.rename(legacy)
            before = self._regular_files(root)

            with mock.patch.object(
                registry,
                "_load_exact_record",
                wraps=registry._load_exact_record,
            ) as load_exact:
                record, storage_kind = registry.get_with_storage_kind(session_id)
            self.assertEqual(record.session_id, session_id)
            self.assertEqual(storage_kind, "legacy")
            load_exact.assert_called_once_with(session_id)
            with self.assertRaises(ValidationIssue) as ctx:
                registry.activate(session_id)
            self.assertEqual(ctx.exception.code, "session_legacy_read_only")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "session",
                    "resume",
                    "--repo-root",
                    str(root),
                    "--session-id",
                    session_id,
                    "--require-write",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            response = json.loads(result.stdout)
            self.assertEqual(
                response["issues"][0]["code"],
                "session_legacy_read_only",
            )
            self.assertEqual(self._regular_files(root), before)
            self.assertFalse(canonical.exists())
            self.assertTrue(legacy.is_file())

    def test_unsafe_store_returns_structured_exit_one_without_following_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            (root / ".elves").symlink_to(outside, target_is_directory=True)

            result = self._invoke(root)

            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["mutated_repo"])
            self.assertEqual(payload["issues"][0]["code"], "storage_symlink_component")
            self.assertTrue((root / ".elves").is_symlink())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged\n")
            self.assertFalse((outside / "runtime").exists())


class UsageLedgerTests(unittest.TestCase):
    def test_unknown_quota_not_zero(self) -> None:
        usage = parse_usage_payload(
            {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01}
        )
        self.assertEqual(usage.input_tokens, 10)
        self.assertEqual(usage.output_tokens, 5)
        self.assertEqual(usage.total_tokens, 15)
        self.assertEqual(usage.cost_usd, 0.01)
        self.assertFalse(usage.quota_known)
        self.assertEqual(usage.to_dict()["remaining_quota"], "unknown")
        self.assertNotEqual(usage.to_dict()["remaining_quota"], 0)

    def test_quota_known_only_when_explicit(self) -> None:
        usage = parse_usage_payload(
            {"input_tokens": 1, "remaining_quota": 99, "quota_known": True}
        )
        self.assertTrue(usage.quota_known)
        self.assertEqual(usage.remaining_quota, 99)
        # Token counts alone never imply known quota.
        usage2 = parse_usage_payload({"total_tokens": 1000, "remaining_quota": 0})
        self.assertFalse(usage2.quota_known)
        self.assertEqual(usage2.remaining_quota, "unknown")
        usage3 = parse_usage_payload(
            {
                "input_tokens": [],
                "remaining_quota": 0,
                "quota_known": "false",
            }
        )
        self.assertIsNone(usage3.input_tokens)
        self.assertFalse(usage3.quota_known)
        self.assertEqual(usage3.remaining_quota, "unknown")


class GrokLineageTests(unittest.TestCase):
    def test_discover_and_register_child_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = SessionRegistry(Path(tmp))
            summary = parse_grok_child_summary(
                {
                    "child_id": "child-uuid-2",
                    "parent_id": "parent-uuid-1",
                    "model": "grok-model",
                    "cwd": str(Path(tmp) / "worktree"),
                    "head": "deadbeef",
                    "worktree": str(Path(tmp) / "worktree"),
                }
            )
            rec = register_grok_child(
                reg,
                summary=summary,
                profile="grok-build",
                role="implement",
                expected_parent_id="parent-uuid-1",
                expected_model="grok-model",
                expected_cwd=str(Path(tmp) / "worktree"),
                expected_head="deadbeef",
            )
            self.assertEqual(rec.session_id, "child-uuid-2")
            self.assertEqual(rec.parent_id, "parent-uuid-1")
            self.assertEqual(rec.creation_method, CreationMethod.FORK_CHILD)
            self.assertNotEqual(rec.session_id, rec.parent_id)

    def test_same_uuid_lineage_rejected(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            parse_grok_child_summary(
                {"child_id": "same", "parent_id": "same", "model": "m", "cwd": "/x", "head": "h"}
            )
        self.assertEqual(ctx.exception.code, "grok_lineage_same_uuid")

    def test_child_registration_requires_observed_model_cwd_worktree_and_head(self) -> None:
        base = {
            "child_id": "child-uuid",
            "parent_id": "parent-uuid",
            "model": "grok-model",
            "cwd": "/verified/worktree",
            "worktree": "/verified/worktree",
            "head": "a" * 40,
        }
        for missing in ("model", "cwd", "worktree", "head"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                payload = dict(base)
                payload.pop(missing)
                summary = parse_grok_child_summary(payload)
                with self.assertRaises(ValidationIssue):
                    register_grok_child(
                        SessionRegistry(Path(tmp)),
                        summary=summary,
                        profile="grok-build-write",
                        role="implement",
                        expected_parent_id="parent-uuid",
                        expected_model="grok-model",
                        expected_cwd="/verified/worktree",
                        expected_head="a" * 40,
                    )


class WriteResumeCliTests(unittest.TestCase):
    def _invoke(
        self,
        root: Path,
        *extra: str,
        adapter: str = "grok-build",
        model: str = "grok-model",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "session",
                "resume",
                "--repo-root",
                str(root),
                "--json",
                "--session-id",
                "22222222-2222-2222-2222-222222222222",
                "--adapter",
                adapter,
                "--model",
                model,
                "--cwd",
                str(root),
                "--worktree",
                str(root),
                "--parent-id",
                "parent-1",
                "--source-head",
                "a" * 40,
                "--require-write",
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_write_resume_uses_guarded_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = SessionRegistry(root)
            registry.create(
                session_id="22222222-2222-2222-2222-222222222222",
                harness="codex-fugu",
                profile="codex-fugu",
                role="implement",
                actual_model="fugu",
                parent_id="parent-1",
                cwd=str(root),
                worktree=str(root),
                source_head="a" * 40,
            )
            registry.activate("22222222-2222-2222-2222-222222222222")
            result = self._invoke(
                root,
                "--profile",
                "codex-fugu",
                adapter="codex-fugu",
                model="fugu",
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["issues"][0]["code"],
                "fugu_implementation_route_blocked",
            )

    def test_write_resume_requires_observed_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = SessionRegistry(root)
            registry.create(
                session_id="22222222-2222-2222-2222-222222222222",
                harness="grok-build",
                profile="grok-build-write",
                role="implement",
                actual_model="grok-model",
                parent_id="parent-1",
                cwd=str(root),
                worktree=str(root),
                source_head="a" * 40,
            )
            registry.activate("22222222-2222-2222-2222-222222222222")
            result = self._invoke(root)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertIn("profile", payload["issues"][0]["message"])

    def test_write_resume_blocks_expected_head_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = SessionRegistry(root)
            registry.create(
                session_id="22222222-2222-2222-2222-222222222222",
                harness="grok-build",
                profile="grok-build-write",
                role="implement",
                actual_model="grok-model",
                parent_id="parent-1",
                cwd=str(root),
                worktree=str(root),
                source_head="b" * 40,
            )
            registry.activate("22222222-2222-2222-2222-222222222222")
            result = self._invoke(root, "--profile", "grok-build-write")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["issues"][0]["code"], "session_write_reuse_unqualified"
            )

    def test_write_resume_recomputes_canonical_disk_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan.md"
            plan.write_text("stable\n", encoding="utf-8")
            registry = SessionRegistry(root)
            registry.create(
                session_id="22222222-2222-2222-2222-222222222222",
                harness="grok-build",
                profile="grok-build-write",
                role="implement",
                actual_model="grok-model",
                parent_id="parent-1",
                cwd=str(root),
                worktree=str(root),
                source_head="a" * 40,
                plan_path=plan,
            )
            registry.activate("22222222-2222-2222-2222-222222222222")
            exact = self._invoke(root, "--profile", "grok-build-write")
            self.assertEqual(exact.returncode, 0, exact.stdout)
            plan.write_text("changed on disk\n", encoding="utf-8")
            drifted = self._invoke(root, "--profile", "grok-build-write")
            self.assertNotEqual(drifted.returncode, 0, drifted.stdout)
            payload = json.loads(drifted.stdout)
            self.assertIn("canonical on-disk context digest changed", payload["issues"][0]["message"])

    def test_headless_worktree_resume_broken_on_0_2_93(self) -> None:
        self.assertFalse(grok_headless_worktree_resume_supported("0.2.93"))
        with self.assertRaises(ValidationIssue) as ctx:
            assert_grok_worktree_isolation(
                version="0.2.93",
                cwd_verified=True,
                worktree_registered=True,
                used_headless_worktree_resume=True,
            )
        self.assertEqual(ctx.exception.code, "grok_headless_worktree_resume_broken")

    def test_fail_closed_without_cwd_worktree_verification(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            assert_grok_worktree_isolation(
                version="0.3.0",
                cwd_verified=False,
                worktree_registered=False,
                used_headless_worktree_resume=False,
            )
        self.assertEqual(ctx.exception.code, "grok_worktree_unverified")


class SessionCommandBuilderTests(unittest.TestCase):
    def test_exact_create_and_resume_forbid_ambiguous_flags(self) -> None:
        adapters = ("claude-code", "grok-build", "codex-fugu", "custom-cli")
        forbidden_substrings = ("--continue", "--last")
        for adapter in adapters:
            with self.subTest(adapter=adapter, op="create"):
                inv = build_session_create_invocation(
                    adapter=adapter,
                    profile=adapter,
                    executable="tool" if adapter == "custom-cli" else None,
                    requested_model=("fugu" if adapter == "codex-fugu" else "example-model"),
                )
                joined = " ".join(inv.argv)
                for token in forbidden_substrings:
                    self.assertNotIn(token, inv.argv)
                    self.assertNotIn(token, joined)
                if adapter == "codex-fugu":
                    sandbox = inv.argv.index("--sandbox")
                    self.assertEqual(inv.argv[sandbox + 1], "read-only")
                if adapter == "claude-code":
                    self.assertIn("--permission-mode", inv.argv)
                    self.assertEqual(
                        inv.argv[inv.argv.index("--permission-mode") + 1],
                        "plan",
                    )
                assert_no_ambiguous_session_flags(inv.argv)
            with self.subTest(adapter=adapter, op="resume"):
                session_id = (
                    "11111111-1111-1111-1111-111111111111"
                    if adapter == "grok-build"
                    else "exact-session-id-123"
                )
                inv = build_session_resume_invocation(
                    adapter=adapter,
                    profile=adapter,
                    session_id=session_id,
                    executable="tool" if adapter == "custom-cli" else None,
                    requested_model=("fugu" if adapter == "codex-fugu" else "example-model"),
                    cwd="/verified/worktree",
                )
                joined = " ".join(inv.argv)
                self.assertIn(session_id, joined)
                for token in forbidden_substrings:
                    self.assertNotIn(token, inv.argv)
                if adapter == "codex-fugu":
                    sandbox = inv.argv.index("--sandbox")
                    self.assertEqual(inv.argv[sandbox + 1], "read-only")
                    self.assertLess(sandbox, inv.argv.index("resume"))
                    self.assertEqual(inv.argv[-2:], ("resume", session_id))
                if adapter == "claude-code":
                    self.assertIn("--permission-mode", inv.argv)
                    self.assertEqual(
                        inv.argv[inv.argv.index("--permission-mode") + 1],
                        "plan",
                    )
                # Bare --resume without id is forbidden; exact --resume <id> is required.
                assert_no_ambiguous_session_flags(inv.argv)
                # Ensure we never emit continue/last patterns from the corpus.
                self.assertTrue(AMBIGUOUS_SESSION_FLAG_PATTERNS)

    def test_bare_resume_without_id_is_rejected(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            assert_no_ambiguous_session_flags(["claude", "--resume"])
        self.assertEqual(ctx.exception.code, "ambiguous_session_flag")
        with self.assertRaises(ValidationIssue):
            assert_no_ambiguous_session_flags(["claude", "--continue"])
        with self.assertRaises(ValidationIssue):
            assert_no_ambiguous_session_flags(["claude", "--last"])

    def test_resume_requires_exact_session_id(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            build_session_resume_invocation(
                adapter="claude-code",
                profile="claude-code",
                session_id="",
            )
        self.assertEqual(ctx.exception.code, "missing_session_id")

    def test_claude_and_fugu_preserve_exact_ids_in_argv(self) -> None:
        for adapter in ("claude-code", "codex-fugu"):
            inv = build_session_resume_invocation(
                adapter=adapter,
                profile=adapter,
                session_id="preserve-me-uuid",
                requested_model=("fugu" if adapter == "codex-fugu" else "model-x"),
            )
            self.assertIn("preserve-me-uuid", inv.argv)
            self.assertIn("fugu" if adapter == "codex-fugu" else "model-x", inv.argv)

    def test_provider_allocated_create_ids_are_not_fabricated(self) -> None:
        for adapter in ("opencode-cli", "antigravity-cli"):
            with self.subTest(adapter=adapter):
                inv = build_session_create_invocation(
                    adapter=adapter,
                    profile=adapter,
                    executable="opencode" if adapter == "opencode-cli" else "agy",
                )
                self.assertIsNone(inv.session_id)
                self.assertIn("authoritative", inv.notes)

    def test_host_allocated_gemini_create_id_is_passed_exactly(self) -> None:
        inv = build_session_create_invocation(
            adapter="gemini-cli",
            profile="gemini-cli",
            executable="gemini",
        )
        self.assertIsNotNone(inv.session_id)
        self.assertIn("--session-id", inv.argv)
        self.assertIn(inv.session_id or "", inv.argv)

    def test_host_allocated_grok_create_id_uses_supported_session_flag(self) -> None:
        inv = build_session_create_invocation(
            adapter="grok-build",
            profile="grok-build",
            executable="grok",
        )
        self.assertIsNotNone(inv.session_id)
        self.assertIn("--session-id", inv.argv)
        self.assertIn(inv.session_id or "", inv.argv)
        self.assertNotIn("--new-session", inv.argv)

    def test_grok_resume_rejects_non_uuid_identity(self) -> None:
        with self.assertRaises(ValidationIssue) as caught:
            build_session_resume_invocation(
                adapter="grok-build",
                profile="grok-build",
                session_id="not-a-uuid",
            )
        self.assertEqual(caught.exception.code, "invalid_grok_session_uuid")


class DoctorSessionFieldsTests(unittest.TestCase):
    def test_doctor_json_separates_discovery_and_session_fields(self) -> None:
        from cobbler_runtime.capabilities import doctor_inventory

        inv = doctor_inventory(
            profiles={
                "host-native": __import__(
                    "cobbler_runtime.adapters", fromlist=["default_profiles"]
                ).default_profiles()["host-native"],
                "grok-build": __import__(
                    "cobbler_runtime.adapters", fromlist=["default_profiles"]
                ).default_profiles()["grok-build"],
            }
        )
        self.assertIn("adapters", inv)
        grok = inv["adapters"]["grok-build"]
        for key in (
            "executable",
            "version",
            "auth",
            "discovered_models",
            "qualification_freshness",
            "session_support",
        ):
            self.assertIn(key, grok)
        self.assertIn("remaining_quota", grok)
        self.assertEqual(grok["remaining_quota"], "unknown")


if __name__ == "__main__":
    unittest.main()
