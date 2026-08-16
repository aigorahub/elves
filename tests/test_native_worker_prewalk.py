from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.prewalk import (  # noqa: E402
    GROK_PREWALK_QUALIFICATION_ARTIFACT_TYPE,
    PREWALK_CONTINUATION_INPUT,
    advertised_prewalk_capabilities,
    experimental_prewalk_capabilities,
    fixture_prewalk_capabilities,
    guide_prompt,
    load_and_validate_transition_artifacts,
    load_grok_prewalk_qualification,
    load_prewalk_capability_evidence,
    prewalk_paths,
    probe_installed_prewalk_capabilities,
    validate_checkpoint_artifact,
    validate_meaningful_edit,
    validate_todo_artifact,
)
from cobbler_runtime.native_worker import (  # noqa: E402
    PrewalkQualificationResult,
    build_native_worker_prewalk_spec,
    native_worker_paths,
    native_worker_status,
    prewalk_qualification_cache_path,
    qualify_installed_prewalk_transport,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _todo(*, run_id: str = "run-1", session_id: str = "session-1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "created_at": _now(),
        "updated_at": _now(),
        "items": [
            {
                "id": "PW-01",
                "description": "Start the implementation",
                "acceptance": "The first task behavior changes",
                "validation": "python3 -m unittest tests.test_example",
                "status": "complete",
            },
            {
                "id": "PW-02",
                "description": "Finish the implementation",
                "acceptance": "The full behavior is present",
                "validation": "python3 scripts/verify_repo.py --version Unreleased",
                "status": "in_progress",
            },
        ],
    }


def _checkpoint(
    *,
    run_id: str = "run-1",
    session_id: str = "session-1",
    path: str = "src/example.py",
    kind: str = "first_meaningful_edit",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "kind": kind,
        "todo_id": "PW-01",
        "changed_paths": [path],
        "summary": "Started the task behavior",
        "validation_attempted": [{"command": "python3 -m unittest tests.test_example", "exit_code": 1}],
        "ready_for_execution_model": True,
        "created_at": _now(),
    }


class PrewalkArtifactTests(unittest.TestCase):
    def test_valid_bounded_todo_and_checkpoint(self) -> None:
        todo = validate_todo_artifact(_todo(), run_id="run-1", session_id="session-1")
        checkpoint = validate_checkpoint_artifact(
            _checkpoint(), run_id="run-1", session_id="session-1", todo=todo
        )
        self.assertEqual(checkpoint["todo_id"], "PW-01")
        self.assertEqual(PREWALK_CONTINUATION_INPUT, "Continue.")

    def test_todo_rejects_empty_duplicate_reordered_and_missing_validation(self) -> None:
        mutations = []
        empty = _todo()
        empty["items"] = []
        mutations.append(empty)
        duplicate = _todo()
        duplicate["items"][1]["id"] = "PW-01"  # type: ignore[index]
        mutations.append(duplicate)
        reordered = _todo()
        reordered["items"][0]["id"] = "PW-02"  # type: ignore[index]
        mutations.append(reordered)
        missing = _todo()
        missing["items"][0]["validation"] = ""  # type: ignore[index]
        mutations.append(missing)
        for data in mutations:
            with self.subTest(data=data), self.assertRaises(ValidationIssue) as caught:
                validate_todo_artifact(data, run_id="run-1", session_id="session-1")
            self.assertEqual(caught.exception.code, "prewalk_todo_invalid")

    def test_todo_rejects_limit_and_multiple_in_progress(self) -> None:
        too_many = _todo()
        too_many["items"] = [
            {
                "id": f"PW-{index:02d}",
                "description": f"item {index}",
                "acceptance": "observable",
                "validation": "test command",
                "status": "pending",
            }
            for index in range(1, 11)
        ]
        with self.assertRaises(ValidationIssue) as caught:
            validate_todo_artifact(too_many, run_id="run-1", session_id="session-1", todo_limit=5)
        self.assertEqual(caught.exception.code, "prewalk_todo_limit_exceeded")
        multiple = _todo()
        multiple["items"][0]["status"] = "in_progress"  # type: ignore[index]
        with self.assertRaises(ValidationIssue) as caught:
            validate_todo_artifact(multiple, run_id="run-1", session_id="session-1")
        self.assertEqual(caught.exception.code, "prewalk_todo_invalid")

    def test_all_complete_requires_task_complete_checkpoint(self) -> None:
        data = _todo()
        data["items"][1]["status"] = "complete"  # type: ignore[index]
        with self.assertRaises(ValidationIssue):
            validate_todo_artifact(data, run_id="run-1", session_id="session-1")
        todo = validate_todo_artifact(
            data, run_id="run-1", session_id="session-1", allow_all_complete=True
        )
        checkpoint = _checkpoint(kind="task_complete")
        self.assertEqual(
            validate_checkpoint_artifact(
                checkpoint, run_id="run-1", session_id="session-1", todo=todo
            )["kind"],
            "task_complete",
        )

    def test_checkpoint_rejects_identity_and_unsafe_path(self) -> None:
        todo = validate_todo_artifact(_todo(), run_id="run-1", session_id="session-1")
        mismatch = _checkpoint(session_id="other")
        with self.assertRaises(ValidationIssue) as caught:
            validate_checkpoint_artifact(
                mismatch, run_id="run-1", session_id="session-1", todo=todo
            )
        self.assertEqual(caught.exception.code, "prewalk_checkpoint_invalid")
        escape = _checkpoint(path="../outside.py")
        with self.assertRaises(ValidationIssue) as caught:
            validate_checkpoint_artifact(
                escape, run_id="run-1", session_id="session-1", todo=todo
            )
        self.assertEqual(caught.exception.code, "prewalk_checkpoint_invalid")

    def test_artifact_loader_rejects_paths_outside_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = prewalk_paths(root, "run-1")
            escaped = deepcopy(paths)
            object.__setattr__(escaped, "todo", str(root / "outside.json"))
            with self.assertRaises(ValidationIssue) as caught:
                load_and_validate_transition_artifacts(
                    paths=escaped,
                    run_id="run-1",
                    session_id="session-1",
                    todo_limit=10,
                    worktree=root,
                )
            self.assertEqual(caught.exception.code, "prewalk_checkpoint_missing")

    def test_runtime_paths_reject_symlinked_worktree_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / ".elves").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValidationIssue) as caught:
                prewalk_paths(root, "run-1")
            self.assertEqual(
                caught.exception.code, "prewalk_worktree_continuity_violation"
            )

    def test_prompt_names_artifacts_and_minimal_later_input(self) -> None:
        paths = prewalk_paths(REPO_ROOT, "prompt-run")
        text = guide_prompt(run_id="prompt-run", paths=paths, todo_limit=10)
        self.assertIn(paths.todo, text)
        self.assertIn(paths.checkpoint, text)
        self.assertIn("sent exactly once", text)
        self.assertIn("only `Continue.`", text)


class MeaningfulEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", "-b", "feat/prewalk", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Elves Test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "elves@example.invalid"], check=True)
        (self.root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "base"], check=True)
        self.start = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.todo = validate_todo_artifact(_todo(), run_id="run-1", session_id="session-1")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _validate(self, path: str, **kwargs):
        checkpoint = validate_checkpoint_artifact(
            _checkpoint(path=path), run_id="run-1", session_id="session-1", todo=self.todo
        )
        return validate_meaningful_edit(
            worktree=self.root,
            start_head=self.start,
            assigned_branch="feat/prewalk",
            todo=self.todo,
            checkpoint=checkpoint,
            starting_worktree_clean=True,
            **kwargs,
        )

    def test_accepts_source_test_first_and_product_documentation_edits(self) -> None:
        for path in ("src/example.py", "tests/test_example.py", "docs/operator.md"):
            with self.subTest(path=path):
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("first task edit\n", encoding="utf-8")
                result = self._validate(path)
                self.assertIn(path, result.changed_paths)
                self.assertEqual(len(result.diff_sha256), 64)
                target.unlink()
                parent = target.parent
                if parent != self.root:
                    parent.rmdir()

    def test_accepts_expected_failing_validation_without_judging_correctness(self) -> None:
        target = self.root / "tests" / "test_regression.py"
        target.parent.mkdir()
        target.write_text("raise AssertionError('reproduced')\n", encoding="utf-8")
        result = self._validate("tests/test_regression.py")
        self.assertTrue(result.meaningful_edit_valid)

    def test_rejects_empty_runtime_only_and_plan_only_deltas(self) -> None:
        with self.assertRaises(ValidationIssue) as caught:
            self._validate("src/example.py")
        self.assertEqual(caught.exception.code, "prewalk_meaningful_edit_missing")
        for path in (
            ".elves/runtime/prewalk/run/todo.json",
            ".elves-session.json",
            "docs/plans/task.md",
            "docs/elves/learnings.md",
            "docs/elves/execution-log-task.md",
        ):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("staging only\n", encoding="utf-8")
        with self.assertRaises(ValidationIssue) as caught:
            self._validate("docs/plans/task.md")
        self.assertEqual(caught.exception.code, "prewalk_changed_path_forbidden")

    def test_rejects_changed_symlink_that_resolves_outside_worktree(self) -> None:
        outside = self.root.parent / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        target = self.root / "src" / "escape.txt"
        target.parent.mkdir()
        target.symlink_to(outside)
        with self.assertRaises(ValidationIssue) as caught:
            self._validate("src/escape.txt")
        self.assertEqual(caught.exception.code, "prewalk_changed_path_forbidden")

    def test_rejects_mixed_product_and_driver_owned_run_memory_edits(self) -> None:
        product = self.root / "src" / "example.py"
        product.parent.mkdir()
        product.write_text("edit\n", encoding="utf-8")
        for path in (".elves-session.json", "docs/plans/active-run.md"):
            with self.subTest(path=path):
                memory = self.root / path
                memory.parent.mkdir(parents=True, exist_ok=True)
                memory.write_text("driver memory\n", encoding="utf-8")
                with self.assertRaises(ValidationIssue) as caught:
                    self._validate("src/example.py")
                self.assertEqual(
                    caught.exception.code, "prewalk_changed_path_forbidden"
                )
                memory.unlink()

    def test_rejects_forbidden_surface_and_authority_errors(self) -> None:
        target = self.root / "src" / "example.py"
        target.parent.mkdir()
        target.write_text("edit\n", encoding="utf-8")
        with self.assertRaises(ValidationIssue) as caught:
            self._validate("src/example.py", forbidden_paths=("src/",))
        self.assertEqual(caught.exception.code, "prewalk_changed_path_forbidden")
        with self.assertRaises(ValidationIssue) as caught:
            self._validate("src/example.py", authority_errors=("protected ref moved",))
        self.assertEqual(caught.exception.code, "prewalk_changed_path_forbidden")

    def test_rejects_wrong_worktree_branch_and_dirty_start(self) -> None:
        target = self.root / "src" / "example.py"
        target.parent.mkdir()
        target.write_text("edit\n", encoding="utf-8")
        for changes in (
            {"assigned_branch": "other/branch"},
            {"starting_worktree_clean": False},
            {"worktree": self.root / "src"},
        ):
            checkpoint = validate_checkpoint_artifact(
                _checkpoint(), run_id="run-1", session_id="session-1", todo=self.todo
            )
            params = {
                "worktree": self.root,
                "start_head": self.start,
                "assigned_branch": "feat/prewalk",
                "todo": self.todo,
                "checkpoint": checkpoint,
                "starting_worktree_clean": True,
            }
            params.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationIssue) as caught:
                validate_meaningful_edit(**params)
            self.assertEqual(caught.exception.code, "prewalk_worktree_continuity_violation")


class CapabilityEvidenceTests(unittest.TestCase):
    def test_versioned_installed_help_fixtures_prove_advertised_grammar_only(self) -> None:
        fixtures = REPO_ROOT / "tests" / "fixtures"
        codex = advertised_prewalk_capabilities(
            host="codex",
            version="0.144.1",
            create_help=(fixtures / "codex-0.144.1-exec-help.txt").read_text(),
            resume_help=(
                fixtures / "codex-0.144.1-exec-resume-help.txt"
            ).read_text(),
        )
        claude_help = (fixtures / "claude-2.1.207-help.txt").read_text()
        claude = advertised_prewalk_capabilities(
            host="claude",
            version="2.1.207",
            create_help=claude_help,
            resume_help=claude_help,
        )
        for capabilities in (codex, claude):
            self.assertTrue(capabilities.advertised_exact_resume)
            self.assertTrue(capabilities.advertised_route_override_on_resume)
            self.assertFalse(capabilities.behaviorally_verified_session_continuity)
            self.assertFalse(capabilities.model_calls_made)
            self.assertFalse(capabilities.qualified())

    def test_help_is_advertised_only_not_behavioral_proof(self) -> None:
        codex = advertised_prewalk_capabilities(
            host="codex",
            version="0.144.1",
            create_help="--model -c model_reasoning_effort resume",
            resume_help="Usage: resume SESSION_ID --model -c model_reasoning_effort",
        )
        claude = advertised_prewalk_capabilities(
            host="claude",
            version="2.1.207",
            create_help="--session-id --model --effort --resume",
            resume_help="--resume --model --effort",
        )
        for caps in (codex, claude):
            self.assertTrue(caps.advertised_exact_resume)
            self.assertTrue(caps.advertised_route_override_on_resume)
            self.assertFalse(caps.behaviorally_verified_session_continuity)
            self.assertFalse(caps.qualified())
            self.assertEqual(caps.instruction_fidelity, "unsupported")

    def test_explicit_experimental_mode_binds_advertised_route_without_claiming_qualification(
        self,
    ) -> None:
        advertised = advertised_prewalk_capabilities(
            host="codex",
            version="0.144.1",
            create_help="--model -c model_reasoning_effort resume",
            resume_help="Usage: resume SESSION_ID --model -c model_reasoning_effort",
        )
        experimental = experimental_prewalk_capabilities(
            advertised,
            guide_model="guide-model",
            guide_effort="high",
            execution_model="execution-model",
            execution_effort="medium",
        )
        self.assertTrue(experimental.experimental_eligible())
        self.assertFalse(experimental.qualified())
        self.assertEqual(
            experimental.evidence_source, "explicit_experimental_request"
        )
        self.assertTrue(
            experimental.route_matches(
                guide_model="guide-model",
                guide_effort="high",
                execution_model="execution-model",
                execution_effort="medium",
            )
        )

    def test_explicit_experimental_mode_rejects_identical_routes(self) -> None:
        advertised = advertised_prewalk_capabilities(
            host="codex",
            version="0.144.1",
            create_help="--model -c model_reasoning_effort resume",
            resume_help="Usage: resume SESSION_ID --model -c model_reasoning_effort",
        )
        with self.assertRaises(ValidationIssue) as caught:
            experimental_prewalk_capabilities(
                advertised,
                guide_model="same-model",
                guide_effort="high",
                execution_model="same-model",
                execution_effort="high",
            )
        self.assertEqual(
            caught.exception.code, "prewalk_route_change_unqualified"
        )

    def test_bounded_behavioral_artifact_qualifies_retained_safe_continuity(self) -> None:
        advertised = advertised_prewalk_capabilities(
            host="codex",
            version="0.144.1",
            create_help="--model -c model_reasoning_effort resume",
            resume_help="Usage: resume SESSION_ID --model -c model_reasoning_effort",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qualification.json"
            payload = {
                "artifact_type": "native_prewalk_behavioral_qualification",
                "schema_version": 1,
                "host": "codex",
                "transport": "codex_exec",
                "installed_version": "0.144.1",
                "session_id": "exact-session-1",
                "create_exit_code": 0,
                "resume_exit_code": 0,
                "same_session_id": True,
                "same_worktree": True,
                "unique_guide_fact_observed": True,
                "packet_replayed": False,
                "stream_identity_verified": True,
                "instruction_fidelity": "retained_safe",
                "guide_route": {"model": "guide-model", "effort": "high"},
                "execution_route": {"model": "execution-model", "effort": "low"},
                "model_calls_made": True,
                "guide_prompt_sha256": hashlib.sha256(b"guide").hexdigest(),
                "continuation_sha256": hashlib.sha256(b"Continue.").hexdigest(),
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            path.chmod(0o600)
            qualified = load_prewalk_capability_evidence(
                path,
                host="codex",
                installed_version="0.144.1",
                advertised=advertised,
            )
            payload["model_calls_made"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValidationIssue) as caught:
                load_prewalk_capability_evidence(
                    path,
                    host="codex",
                    installed_version="0.144.1",
                    advertised=advertised,
                )
            self.assertEqual(caught.exception.code, "prewalk_capability_unavailable")
            payload["model_calls_made"] = True
            payload["continuation_sha256"] = hashlib.sha256(b"Keep going").hexdigest()
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValidationIssue) as caught:
                load_prewalk_capability_evidence(
                    path,
                    host="codex",
                    installed_version="0.144.1",
                    advertised=advertised,
                )
            self.assertEqual(caught.exception.code, "prewalk_capability_unavailable")
            payload["continuation_sha256"] = hashlib.sha256(b"Continue.").hexdigest()
            payload["installed_version"] = None
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValidationIssue) as caught:
                load_prewalk_capability_evidence(
                    path,
                    host="codex",
                    installed_version=None,
                    advertised=advertised,
                )
            self.assertEqual(caught.exception.code, "prewalk_capability_unavailable")
        self.assertTrue(qualified.qualified())
        self.assertFalse(qualified.behaviorally_verified_instruction_pruning)
        self.assertEqual(qualified.instruction_fidelity, "retained_safe")
        self.assertTrue(qualified.model_calls_made)
        self.assertTrue(
            qualified.route_matches(
                guide_model="guide-model",
                guide_effort="high",
                execution_model="execution-model",
                execution_effort="low",
            )
        )
        # The proof binds the execution route: another guide model reuses it,
        # another execution model does not.
        self.assertTrue(
            qualified.route_matches(
                guide_model="other-guide",
                guide_effort="medium",
                execution_model="execution-model",
                execution_effort="low",
            )
        )
        self.assertFalse(
            qualified.route_matches(
                guide_model="guide-model",
                guide_effort="high",
                execution_model="other-execution-model",
                execution_effort="low",
            )
        )
        self.assertFalse(
            qualified.route_matches(
                guide_model="guide-model",
                guide_effort="high",
                execution_model="execution-model",
                execution_effort="medium",
            )
        )
        for fidelity in ("pruned", "turn_scoped", "unsupported"):
            with self.subTest(fidelity=fidelity):
                unavailable = replace(qualified, instruction_fidelity=fidelity)
                self.assertFalse(unavailable.qualified())
                self.assertEqual(
                    unavailable.unavailable_reason(),
                    "prewalk_instruction_pruning_unqualified",
                )
        # Another guide model builds on the same proof; another execution
        # model has no proof and fails closed.
        build_native_worker_prewalk_spec(
            host="codex",
            worktree=REPO_ROOT,
            guide_effort="high",
            execution_effort="low",
            guide_model="other-guide",
            execution_model="execution-model",
            capabilities=qualified,
            requested_mode="required",
        )
        with self.assertRaises(ValidationIssue) as caught:
            build_native_worker_prewalk_spec(
                host="codex",
                worktree=REPO_ROOT,
                guide_effort="high",
                execution_effort="low",
                guide_model="guide-model",
                execution_model="other-execution-model",
                capabilities=qualified,
                requested_mode="required",
            )
        self.assertEqual(caught.exception.code, "prewalk_route_change_unqualified")

    def test_failed_help_commands_cannot_advertise_or_qualify_prewalk(self) -> None:
        def failed_runner(argv, **_kwargs):
            return subprocess.CompletedProcess(
                argv,
                1,
                "Usage: resume SESSION_ID --session-id --resume --model --effort -c",
                "",
            )

        with mock.patch(
            "cobbler_runtime.prewalk.shutil.which", return_value="/usr/bin/codex"
        ):
            capabilities = probe_installed_prewalk_capabilities(
                "codex", runner=failed_runner
            )
        self.assertFalse(capabilities.advertised_exact_resume)
        self.assertFalse(capabilities.advertised_route_override_on_resume)
        self.assertFalse(capabilities.qualified())


class FdBoundEvidenceLoaderTests(unittest.TestCase):
    """B5: load_prewalk_capability_evidence uses the shared fd-bound reader."""

    def _payload(self) -> dict:
        return {
            "artifact_type": "native_prewalk_behavioral_qualification",
            "schema_version": 1,
            "host": "codex",
            "transport": "codex_exec",
            "installed_version": "0.144.1",
            "session_id": "exact-session-1",
            "create_exit_code": 0,
            "resume_exit_code": 0,
            "same_session_id": True,
            "same_worktree": True,
            "unique_guide_fact_observed": True,
            "packet_replayed": False,
            "stream_identity_verified": True,
            "instruction_fidelity": "retained_safe",
            "guide_route": {"model": "guide-model", "effort": "high"},
            "execution_route": {"model": "execution-model", "effort": "low"},
            "model_calls_made": True,
            "guide_prompt_sha256": hashlib.sha256(b"guide").hexdigest(),
            "continuation_sha256": hashlib.sha256(b"Continue.").hexdigest(),
        }

    def _advertised(self):
        return advertised_prewalk_capabilities(
            host="codex",
            version="0.144.1",
            create_help="--model -c model_reasoning_effort resume",
            resume_help="Usage: resume SESSION_ID --model -c model_reasoning_effort",
        )

    def test_symlinked_and_irregular_evidence_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "qualification.json"
            real.write_text(json.dumps(self._payload()), encoding="utf-8")
            real.chmod(0o600)
            # The regular file itself still loads.
            loaded = load_prewalk_capability_evidence(
                real,
                host="codex",
                installed_version="0.144.1",
                advertised=self._advertised(),
            )
            self.assertTrue(loaded.qualified())

            link = root / "qualification-link.json"
            link.symlink_to(real)
            with self.assertRaises(ValidationIssue) as caught:
                load_prewalk_capability_evidence(
                    link,
                    host="codex",
                    installed_version="0.144.1",
                    advertised=self._advertised(),
                )
            self.assertEqual(
                caught.exception.code, "prewalk_capability_unavailable"
            )
            self.assertIn("non-symlink", caught.exception.message)

            writable = root / "writable.json"
            writable.write_text(json.dumps(self._payload()), encoding="utf-8")
            writable.chmod(0o666)
            with self.assertRaises(ValidationIssue) as caught:
                load_prewalk_capability_evidence(
                    writable,
                    host="codex",
                    installed_version="0.144.1",
                    advertised=self._advertised(),
                )
            self.assertEqual(
                caught.exception.code, "prewalk_capability_unavailable"
            )
            self.assertIn("writable", caught.exception.message)

            missing = root / "absent.json"
            with self.assertRaises(ValidationIssue) as caught:
                load_prewalk_capability_evidence(
                    missing,
                    host="codex",
                    installed_version="0.144.1",
                    advertised=self._advertised(),
                )
            self.assertEqual(
                caught.exception.code, "prewalk_capability_unavailable"
            )


class GrokPrewalkStaticProbeTests(unittest.TestCase):
    """B3-A1: fixture-backed grok advertised grammar with zero model calls."""

    def _help_text(self) -> str:
        return (
            REPO_ROOT / "tests" / "fixtures" / "grok-0.2.102-help.txt"
        ).read_text(encoding="utf-8")

    def test_current_version_fixture_advertises_exact_resume_and_route_override(self) -> None:
        help_text = self._help_text()
        capabilities = advertised_prewalk_capabilities(
            host="grok",
            version="0.2.102",
            create_help=help_text,
            resume_help=help_text,
        )
        self.assertEqual(capabilities.host, "grok")
        self.assertEqual(capabilities.transport, "grok_build")
        self.assertTrue(capabilities.advertised_exact_resume)
        self.assertTrue(capabilities.advertised_route_override_on_resume)
        self.assertFalse(capabilities.behaviorally_verified_session_continuity)
        self.assertFalse(capabilities.qualified())
        self.assertEqual(capabilities.instruction_fidelity, "unsupported")
        self.assertEqual(capabilities.evidence_source, "installed_help_only")
        self.assertFalse(capabilities.model_calls_made)

    def test_installed_probe_reads_help_and_version_only(self) -> None:
        help_text = self._help_text()
        calls: list[tuple[str, ...]] = []

        def runner(argv, **_kwargs):
            calls.append(tuple(argv))
            if "--version" in argv:
                return subprocess.CompletedProcess(argv, 0, "grok 0.2.102", "")
            return subprocess.CompletedProcess(argv, 0, help_text, "")

        with mock.patch(
            "cobbler_runtime.prewalk.shutil.which", return_value="/usr/bin/grok"
        ):
            capabilities = probe_installed_prewalk_capabilities("grok", runner=runner)
        self.assertEqual(capabilities.installed_version, "0.2.102")
        self.assertTrue(capabilities.advertised_exact_resume)
        self.assertTrue(capabilities.advertised_route_override_on_resume)
        self.assertFalse(capabilities.qualified())
        self.assertFalse(capabilities.model_calls_made)
        # Zero model calls: the probe may only read `--version` and `--help`.
        self.assertTrue(calls)
        for argv in calls:
            self.assertIn(argv[1:], {("--version",), ("--help",)}, argv)

    def test_missing_grok_binary_reports_concrete_reason_not_a_traceback(self) -> None:
        with mock.patch("cobbler_runtime.prewalk.shutil.which", return_value=None):
            capabilities = probe_installed_prewalk_capabilities("grok")
        self.assertEqual(capabilities.host, "grok")
        self.assertEqual(capabilities.transport, "grok_build")
        self.assertEqual(capabilities.evidence_source, "installed_binary_missing")
        self.assertFalse(capabilities.qualified())
        self.assertIsNotNone(capabilities.unavailable_reason())

    def test_cli_prewalk_capabilities_host_grok_is_end_to_end_and_model_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            # An empty PATH entry guarantees no installed grok is discovered:
            # the CLI must report a concrete unavailable reason, never error.
            env["PATH"] = str(Path(tmp) / "empty-path")
            (Path(tmp) / "empty-path").mkdir()
            env["XDG_CONFIG_HOME"] = tmp
            cli = REPO_ROOT / "scripts" / "cobbler_agents.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "native-worker",
                    "prewalk-capabilities",
                    "--host",
                    "grok",
                    "--json",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["model_calls_made"])
            capabilities = payload["prewalk_capabilities"]
            self.assertEqual(capabilities["host"], "grok")
            self.assertEqual(capabilities["transport"], "grok_build")
            self.assertEqual(
                capabilities["evidence_source"], "installed_binary_missing"
            )
            self.assertFalse(capabilities["qualified"])
            self.assertIsNotNone(capabilities["unavailable_reason"])


GOLDEN_GROK_SESSION = "3f2b9a54-6a1d-4a8e-9c7b-2d5e8f1a0b4c"


def write_grok_qualification_artifact(
    root: Path,
    *,
    mutation: dict[str, object] | None = None,
    remove: tuple[str, ...] = (),
    name: str = "grok-prewalk-qualification.json",
    mode: int = 0o600,
) -> Path:
    payload: dict[str, object] = {
        "artifact_type": GROK_PREWALK_QUALIFICATION_ARTIFACT_TYPE,
        "schema_version": 1,
        "host": "grok",
        "transport": "grok_build",
        "installed_version": "0.2.102",
        "installed_build_commit": "c1b5909ec707",
        "session_id": GOLDEN_GROK_SESSION,
        "guide_route": {"model": "guide-model", "effort": "high"},
        "execution_route": {"model": "grok-4.5", "effort": "high"},
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
    payload.update(mutation or {})
    for key in remove:
        payload.pop(key, None)
    path = root / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(mode)
    return path


class GrokPrewalkQualificationLoaderTests(unittest.TestCase):
    """B3-A2: golden artifact accepted; every single-field mutation rejected."""

    def test_golden_artifact_loads_qualified_retained_safe_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_grok_qualification_artifact(Path(tmp))
            capabilities = load_grok_prewalk_qualification(
                path,
                installed_version="0.2.102",
                installed_build_commit="C1B5909EC707",
            )
        self.assertEqual(capabilities.host, "grok")
        self.assertEqual(capabilities.transport, "grok_build")
        self.assertEqual(capabilities.installed_version, "0.2.102")
        self.assertTrue(capabilities.qualified())
        self.assertEqual(capabilities.instruction_fidelity, "retained_safe")
        self.assertFalse(capabilities.behaviorally_verified_instruction_pruning)
        self.assertTrue(capabilities.model_calls_made)
        # The loader must never emit a fixture token: the evidence source is
        # always the resolved artifact path (the routing gate rejects
        # deterministic_fixture with qualification_fixture_evidence_forbidden).
        self.assertEqual(capabilities.evidence_source, str(path.resolve()))
        self.assertNotEqual(capabilities.evidence_source, "deterministic_fixture")
        self.assertEqual(capabilities.qualified_guide_model, "guide-model")
        self.assertEqual(capabilities.qualified_guide_effort, "high")
        self.assertEqual(
            capabilities.qualified_execution_model, "grok-4.5"
        )
        self.assertEqual(capabilities.qualified_execution_effort, "high")
        self.assertTrue(
            capabilities.route_matches(
                guide_model="guide-model",
                guide_effort="high",
                execution_model="grok-4.5",
                execution_effort="high",
            )
        )
        self.assertTrue(
            capabilities.route_matches(
                guide_model="other-guide",
                guide_effort="high",
                execution_model="grok-4.5",
                execution_effort="high",
            )
        )
        self.assertFalse(
            capabilities.route_matches(
                guide_model="guide-model",
                guide_effort="high",
                execution_model="grok-4.6",
                execution_effort="high",
            )
        )

    def test_non_activating_fidelities_load_as_recorded_but_unqualified(self) -> None:
        for fidelity in ("pruned", "turn_scoped"):
            with self.subTest(fidelity=fidelity), tempfile.TemporaryDirectory() as tmp:
                path = write_grok_qualification_artifact(
                    Path(tmp), mutation={"instruction_fidelity": fidelity}
                )
                capabilities = load_grok_prewalk_qualification(path)
                self.assertEqual(capabilities.instruction_fidelity, fidelity)
                self.assertFalse(capabilities.qualified())
                self.assertEqual(
                    capabilities.unavailable_reason(),
                    "prewalk_instruction_pruning_unqualified",
                )
                self.assertEqual(
                    capabilities.behaviorally_verified_instruction_pruning,
                    fidelity == "pruned",
                )

    def test_each_single_field_mutation_is_rejected_with_a_stable_code(self) -> None:
        cases: list[tuple[dict[str, object] | None, tuple[str, ...], str]] = [
            ({"host": "claude"}, (), "prewalk_capability_unavailable"),
            ({"transport": "claude_code"}, (), "prewalk_capability_unavailable"),
            (
                {"artifact_type": "native_prewalk_behavioral_qualification"},
                (),
                "prewalk_capability_unavailable",
            ),
            ({"schema_version": 2}, (), "prewalk_capability_unavailable"),
            ({"schema_version": True}, (), "prewalk_capability_unavailable"),
            ({"schema_version": "1"}, (), "prewalk_capability_unavailable"),
            (
                {"artifact_type": "GROK_PREWALK_QUALIFICATION_CANARY"},
                (),
                "prewalk_capability_unavailable",
            ),
            (
                {"session_id": f"urn:uuid:{GOLDEN_GROK_SESSION}"},
                (),
                "prewalk_session_id_missing",
            ),
            ({"installed_version": "0.2.101"}, (), "prewalk_capability_unavailable"),
            (
                {"installed_build_commit": "not-a-commit"},
                (),
                "prewalk_capability_unavailable",
            ),
            ({"session_id": "not-a-uuid"}, (), "prewalk_session_id_missing"),
            (
                {"session_id": GOLDEN_GROK_SESSION.upper()},
                (),
                "prewalk_session_id_missing",
            ),
            (None, ("guide_route",), "prewalk_capability_unavailable"),
            (None, ("execution_route",), "prewalk_capability_unavailable"),
            (
                {"guide_route": {"model": "guide-model", "effort": "extreme"}},
                (),
                "prewalk_route_change_unqualified",
            ),
            ({"create_exit_code": 1}, (), "prewalk_capability_unavailable"),
            ({"create_exit_code": False}, (), "prewalk_capability_unavailable"),
            ({"resume_exit_code": 1}, (), "prewalk_capability_unavailable"),
            ({"same_session_id": False}, (), "prewalk_capability_unavailable"),
            ({"same_worktree": False}, (), "prewalk_capability_unavailable"),
            (
                {"stream_identity_verified": False},
                (),
                "prewalk_capability_unavailable",
            ),
            (
                {"unique_guide_fact_observed": False},
                (),
                "prewalk_capability_unavailable",
            ),
            ({"packet_replayed": True}, (), "prewalk_capability_unavailable"),
            ({"model_calls_made": False}, (), "prewalk_capability_unavailable"),
            (
                {"instruction_fidelity": "unsupported"},
                (),
                "prewalk_instruction_pruning_unqualified",
            ),
            (
                {"unexpected_extra_field": True},
                (),
                "prewalk_capability_unavailable",
            ),
        ]
        for mutation, remove, expected_code in cases:
            with self.subTest(mutation=mutation, remove=remove):
                with tempfile.TemporaryDirectory() as tmp:
                    path = write_grok_qualification_artifact(
                        Path(tmp), mutation=mutation, remove=remove
                    )
                    with self.assertRaises(ValidationIssue) as caught:
                        load_grok_prewalk_qualification(
                            path,
                            installed_version="0.2.102",
                            installed_build_commit="c1b5909ec707",
                        )
                self.assertEqual(caught.exception.code, expected_code)

    def test_unsafe_files_are_rejected_before_any_field_is_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            golden = write_grok_qualification_artifact(root)
            symlink = root / "qualification-symlink.json"
            symlink.symlink_to(golden)
            with self.assertRaises(ValidationIssue) as caught:
                load_grok_prewalk_qualification(symlink)
            self.assertEqual(caught.exception.code, "prewalk_capability_unavailable")
            writable = write_grok_qualification_artifact(
                root, name="group-writable.json", mode=0o664
            )
            with self.assertRaises(ValidationIssue) as caught:
                load_grok_prewalk_qualification(writable)
            self.assertEqual(caught.exception.code, "prewalk_capability_unavailable")
            oversized = root / "oversized.json"
            oversized.write_text(
                golden.read_text(encoding="utf-8") + " " * (64 * 1024),
                encoding="utf-8",
            )
            oversized.chmod(0o600)
            with self.assertRaises(ValidationIssue) as caught:
                load_grok_prewalk_qualification(oversized)
            self.assertEqual(caught.exception.code, "prewalk_capability_unavailable")
            with self.assertRaises(ValidationIssue) as caught:
                load_grok_prewalk_qualification(root / "absent.json")
            self.assertEqual(caught.exception.code, "prewalk_capability_unavailable")

    def test_probe_binds_the_artifact_to_the_installed_version(self) -> None:
        help_text = (
            REPO_ROOT / "tests" / "fixtures" / "grok-0.2.102-help.txt"
        ).read_text(encoding="utf-8")

        def runner_for(version: str):
            def runner(argv, **_kwargs):
                if "--version" in argv:
                    return subprocess.CompletedProcess(argv, 0, f"grok {version}", "")
                return subprocess.CompletedProcess(argv, 0, help_text, "")

            return runner

        with tempfile.TemporaryDirectory() as tmp:
            path = write_grok_qualification_artifact(Path(tmp))
            with mock.patch(
                "cobbler_runtime.prewalk.shutil.which", return_value="/usr/bin/grok"
            ):
                qualified = probe_installed_prewalk_capabilities(
                    "grok",
                    behavioral_evidence=path,
                    runner=runner_for("0.2.102"),
                )
                self.assertTrue(qualified.qualified())
                self.assertEqual(qualified.evidence_source, str(path.resolve()))
                with self.assertRaises(ValidationIssue) as caught:
                    probe_installed_prewalk_capabilities(
                        "grok",
                        behavioral_evidence=path,
                        runner=runner_for("0.2.101"),
                    )
        self.assertEqual(caught.exception.code, "prewalk_capability_unavailable")
        self.assertEqual(caught.exception.path, "installed_version")

    def test_probe_binds_the_artifact_to_the_installed_build_commit(self) -> None:
        help_text = (
            REPO_ROOT / "tests" / "fixtures" / "grok-0.2.102-help.txt"
        ).read_text(encoding="utf-8")

        def runner_for(version_line: str):
            def runner(argv, **_kwargs):
                if "--version" in argv:
                    return subprocess.CompletedProcess(argv, 0, version_line, "")
                return subprocess.CompletedProcess(argv, 0, help_text, "")

            return runner

        with tempfile.TemporaryDirectory() as tmp:
            path = write_grok_qualification_artifact(Path(tmp))
            with mock.patch(
                "cobbler_runtime.prewalk.shutil.which", return_value="/usr/bin/grok"
            ):
                bound = probe_installed_prewalk_capabilities(
                    "grok",
                    behavioral_evidence=path,
                    runner=runner_for("grok 0.2.102 (c1b5909ec707)"),
                )
                self.assertTrue(bound.qualified())
                with self.assertRaises(ValidationIssue) as caught:
                    probe_installed_prewalk_capabilities(
                        "grok",
                        behavioral_evidence=path,
                        runner=runner_for("grok 0.2.102 (deadbeef1234)"),
                    )
        self.assertEqual(caught.exception.code, "prewalk_capability_unavailable")
        self.assertEqual(caught.exception.path, "installed_build_commit")


class NativeTransportParityTests(unittest.TestCase):
    def _spec(self, host: str):
        return build_native_worker_prewalk_spec(
            host=host,
            worktree=REPO_ROOT,
            guide_effort="high",
            execution_effort="low",
            guide_model="guide-model",
            execution_model="execution-model",
            capabilities=fixture_prewalk_capabilities(host),
            requested_mode="required",
        )

    def test_codex_create_and_exact_resume_pin_distinct_routes(self) -> None:
        prewalk = self._spec("codex")
        self.assertIn("-C", prewalk.guide.argv)
        self.assertIn("guide-model", prewalk.guide.argv)
        self.assertIn('model_reasoning_effort="high"', prewalk.guide.argv)
        resumed = prewalk.execution_spec("thread-exact-123")
        self.assertIn("execution-model", resumed.argv)
        self.assertIn('model_reasoning_effort="low"', resumed.argv)
        self.assertIn("resume", resumed.argv)
        self.assertEqual(resumed.argv[resumed.argv.index("resume") + 1], "thread-exact-123")
        self.assertNotIn("--last", resumed.argv)
        self.assertLess(resumed.argv.index("--sandbox"), resumed.argv.index("resume"))
        for root in resumed.git_write_roots:
            self.assertLess(resumed.argv.index(root), resumed.argv.index("resume"))
        self.assertEqual(resumed.cwd, str(REPO_ROOT.resolve()))

    def test_claude_create_and_exact_resume_pin_distinct_routes(self) -> None:
        prewalk = self._spec("claude")
        self.assertIn("--session-id", prewalk.guide.argv)
        self.assertIn("guide-model", prewalk.guide.argv)
        self.assertEqual(prewalk.guide.argv[prewalk.guide.argv.index("--effort") + 1], "high")
        exact = prewalk.guide.session_id
        self.assertIsNotNone(exact)
        resumed = prewalk.execution_spec(exact or "")
        self.assertIn("--resume", resumed.argv)
        self.assertEqual(resumed.argv[resumed.argv.index("--resume") + 1], exact)
        self.assertIn("execution-model", resumed.argv)
        self.assertEqual(resumed.argv[resumed.argv.index("--effort") + 1], "low")
        self.assertNotIn("--continue", resumed.argv)
        self.assertIn("--safe-mode", resumed.argv)
        self.assertIn("--verbose", resumed.argv)
        self.assertEqual(resumed.argv[resumed.argv.index("--permission-mode") + 1], "auto")

    def test_shared_semantic_contract_is_table_driven_for_both_hosts(self) -> None:
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                prewalk = self._spec(host)
                session_id = prewalk.guide.session_id or "captured-thread-id"
                resumed = prewalk.execution_spec(session_id)
                self.assertTrue(prewalk.guide.separate_session)
                self.assertEqual(prewalk.guide.cwd, resumed.cwd)
                self.assertEqual(resumed.session_id, session_id)
                self.assertEqual(prewalk.guide.requested_model, "guide-model")
                self.assertEqual(resumed.requested_model, "execution-model")
                self.assertFalse(prewalk.guide.cache_handoff)
                self.assertFalse(resumed.cache_handoff)
                self.assertEqual(prewalk.capabilities.instruction_fidelity, "retained_safe")
                self.assertTrue(prewalk.capabilities.stream_identity_verified)


class PrewalkSupervisorLifecycleTests(unittest.TestCase):
    def _repo(self, root: Path) -> tuple[Path, Path]:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "feat/prewalk", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Elves Test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "elves@example.invalid"], check=True)
        (repo / ".gitignore").write_text(".elves/\n", encoding="utf-8")
        (repo / "product.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore", "product.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
        packet = repo / ".elves" / "runtime" / "packet.md"
        packet.parent.mkdir(parents=True)
        packet.write_text("packet body\n", encoding="utf-8")
        return repo, packet

    def _fixtures(self, root: Path) -> tuple[Path, Path]:
        fixture_root = root / "fixtures"
        fixture_root.mkdir()
        guide = fixture_root / "guide.py"
        execution = fixture_root / "execution.py"
        guide.write_text(
            "from datetime import datetime, timezone\n"
            "import json, os, pathlib, sys\n"
            "scenario = os.environ.get('PW_FIXTURE_SCENARIO', 'success')\n"
            "record = pathlib.Path(os.environ['PW_FIXTURE_RECORD_DIR'])\n"
            "record.mkdir(parents=True, exist_ok=True)\n"
            "received = sys.stdin.read()\n"
            "identity = json.loads(pathlib.Path(os.environ['ELVES_PREWALK_SESSION_PATH']).read_text())\n"
            "sid = identity['session_id']\n"
            "phase = os.environ['ELVES_NATIVE_WORKER_PHASE']\n"
            "guide_record = {'packet_count': received.count('packet body\\n'), 'phase': phase}\n"
            "(record / 'guide.json').write_text(json.dumps(guide_record))\n"
            "(record / ('guide-' + phase + '.json')).write_text(json.dumps(guide_record))\n"
            "if scenario != 'guide_no_id' and not (scenario == 'recovery_no_initial_id' and phase == 'prewalk'):\n"
            "    event = {'type':'system','subtype':'init','session_id':sid} if scenario == 'claude_session_id' else {'type':'thread.started','thread_id':sid}\n"
            "    print(json.dumps(event), flush=True)\n"
            "if scenario == 'guide_mismatch': print(json.dumps({'type':'turn.started','session_id':'different-session'}), flush=True)\n"
            "if scenario == 'clean_branch_drift':\n"
            "    if phase == 'prewalk':\n"
            "        import subprocess\n"
            "        subprocess.run(['git', 'switch', '-q', '-c', 'drift/clean-fallback'], check=True)\n"
            "    raise SystemExit(7)\n"
            "if scenario == 'clean_head_drift':\n"
            "    if phase == 'prewalk':\n"
            "        import subprocess\n"
            "        pathlib.Path('product.txt').write_text('temporary committed edit\\n')\n"
            "        subprocess.run(['git', 'add', 'product.txt'], check=True)\n"
            "        subprocess.run(['git', 'commit', '-qm', 'temporary edit'], check=True)\n"
            "        pathlib.Path('product.txt').write_text('base\\n')\n"
            "        subprocess.run(['git', 'add', 'product.txt'], check=True)\n"
            "        subprocess.run(['git', 'commit', '-qm', 'restore content'], check=True)\n"
            "    raise SystemExit(7)\n"
            "if scenario == 'recovery_no_initial_id' and phase == 'prewalk': raise SystemExit(7)\n"
            "if scenario == 'recovery_success' and phase == 'prewalk': raise SystemExit(7)\n"
            "if scenario == 'clean_fallback': raise SystemExit(7)\n"
            "if scenario == 'post_edit_failure':\n"
            "    pathlib.Path('product.txt').write_text('uncheckpointed guide edit\\n')\n"
            "    raise SystemExit(7)\n"
            "if scenario == 'missing': raise SystemExit(0)\n"
            "pathlib.Path('product.txt').write_text('guide edit\\n')\n"
            "now = datetime.now(timezone.utc).isoformat()\n"
            "all_complete = scenario == 'tiny'\n"
            "todo = {'schema_version':1,'run_id':os.environ['ELVES_PREWALK_RUN_ID'],'session_id':sid,'created_at':now,'updated_at':now,'items':[{'id':'PW-01','description':'make first edit','acceptance':'product changed','validation':'inspect product.txt','status':'complete'}]}\n"
            "if not all_complete: todo['items'].append({'id':'PW-02','description':'finish task','acceptance':'execution completed','validation':'inspect final product.txt','status':'in_progress'})\n"
            "pathlib.Path(os.environ['ELVES_PREWALK_TODO_PATH']).write_text(json.dumps(todo))\n"
            "checkpoint = {'schema_version':1,'run_id':os.environ['ELVES_PREWALK_RUN_ID'],'session_id':sid,'kind':'task_complete' if all_complete else 'first_meaningful_edit','todo_id':'PW-01','changed_paths':['product.txt'],'summary':'first task edit','validation_attempted':[{'command':'inspect product.txt','exit_code':0}],'ready_for_execution_model':True,'created_at':now}\n"
            "pathlib.Path(os.environ['ELVES_PREWALK_CHECKPOINT_PATH']).write_text(json.dumps(checkpoint))\n"
            "if scenario == 'malformed': pathlib.Path(os.environ['ELVES_PREWALK_TODO_PATH']).write_text('{')\n"
            "if scenario == 'branch_drift':\n"
            "    import subprocess\n"
            "    subprocess.run(['git', 'switch', '-q', '-c', 'drift/prewalk'], check=True)\n",
            encoding="utf-8",
        )
        execution.write_text(
            "from datetime import datetime, timezone\n"
            "import json, os, pathlib, sys\n"
            "scenario = os.environ.get('PW_FIXTURE_SCENARIO', 'success')\n"
            "record = pathlib.Path(os.environ['PW_FIXTURE_RECORD_DIR'])\n"
            "received = sys.stdin.read()\n"
            "count_path = record / 'execution-count.txt'\n"
            "attempt = int(count_path.read_text()) + 1 if count_path.exists() else 1\n"
            "count_path.write_text(str(attempt))\n"
            "(record / 'execution.json').write_text(json.dumps({'input': received, 'phase': os.environ['ELVES_NATIVE_WORKER_PHASE']}))\n"
            "(record / ('execution-' + str(attempt) + '.json')).write_text(json.dumps({'input': received, 'phase': os.environ['ELVES_NATIVE_WORKER_PHASE']}))\n"
            "if scenario == 'clean_fallback':\n"
            "    pathlib.Path('product.txt').write_text('single phase fallback edit\\n')\n"
            "    raise SystemExit(0)\n"
            "identity = json.loads(pathlib.Path(os.environ['ELVES_PREWALK_SESSION_PATH']).read_text())\n"
            "sid = 'different-session' if scenario == 'mismatch' else identity['session_id']\n"
            "if scenario != 'execution_no_id':\n"
            "    event = {'type':'system','subtype':'init','session_id':sid} if scenario == 'claude_session_id' else {'type':'thread.started','thread_id':sid}\n"
            "    print(json.dumps(event), flush=True)\n"
            "if scenario == 'transient_recovery' and attempt == 1:\n"
            "    print('provider overloaded: 503 temporarily unavailable', file=sys.stderr, flush=True)\n"
            "    raise SystemExit(7)\n"
            "if scenario == 'execution_fail': raise SystemExit(7)\n"
            "todo_path = pathlib.Path(os.environ['ELVES_PREWALK_TODO_PATH'])\n"
            "todo = json.loads(todo_path.read_text())\n"
            "for item in todo['items']: item['status'] = 'complete'\n"
            "todo['updated_at'] = datetime.now(timezone.utc).isoformat()\n"
            "todo_path.write_text(json.dumps(todo))\n"
            "pathlib.Path('product.txt').write_text('guide edit\\nexecution edit\\n')\n"
            "checkpoint = {'schema_version':1,'run_id':os.environ['ELVES_PREWALK_RUN_ID'],'session_id':identity['session_id'],'kind':'task_complete','todo_id':'PW-01','changed_paths':['product.txt'],'summary':'task complete','validation_attempted':[{'command':'inspect final product.txt','exit_code':0}],'ready_for_execution_model':True,'created_at':datetime.now(timezone.utc).isoformat()}\n"
            "pathlib.Path(os.environ['ELVES_PREWALK_CHECKPOINT_PATH']).write_text(json.dumps(checkpoint))\n",
            encoding="utf-8",
        )
        return guide, execution

    def _launch(
        self,
        *,
        scenario: str = "success",
        mode: str = "required",
        forbidden_paths: tuple[str, ...] = (),
    ) -> tuple[dict[str, object], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        repo, packet = self._repo(root)
        guide, execution = self._fixtures(root)
        record = root / "record"
        env = os.environ.copy()
        env["PW_FIXTURE_SCENARIO"] = scenario
        env["PW_FIXTURE_RECORD_DIR"] = str(record)
        cli = REPO_ROOT / "scripts" / "cobbler_agents.py"
        run_id = f"lifecycle-{scenario}"
        command = [
            sys.executable,
            str(cli),
            "native-worker",
            "launch",
            "--host",
            "fixture",
            "--worktree",
            str(repo),
            "--prewalk",
            mode,
            "--guide-model",
            "guide-model",
            "--guide-effort",
            "high",
            "--execution-model",
            "execution-model",
            "--execution-effort",
            "low",
            "--fixture-script",
            str(guide),
            "--execution-fixture-script",
            str(execution),
            "--repo-root",
            str(repo),
            "--run-id",
            run_id,
            "--packet",
            str(packet),
            "--json",
        ]
        for path in forbidden_paths:
            command.extend(("--forbidden-path", path))
        launched = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
        self.assertEqual(launched.returncode, 0, launched.stderr or launched.stdout)
        state: dict[str, object] = json.loads(launched.stdout)["worker"]
        for _ in range(100):
            status = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "native-worker",
                    "status",
                    "--repo-root",
                    str(repo),
                    "--run-id",
                    run_id,
                    "--json",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            state = json.loads(status.stdout)["worker"]
            if state["status"] in {"complete", "failed"}:
                break
            time.sleep(0.05)
        return state, repo, record

    def test_two_phase_fixture_preserves_trajectory_and_one_follow_stream(self) -> None:
        state, _repo, record = self._launch()
        supervisor_log = Path(state["supervisor_log"]).read_text(encoding="utf-8")
        self.assertEqual(state["status"], "complete", supervisor_log)
        self.assertEqual(state["version"], 3)
        self.assertEqual(state["mode"], "prewalk")
        self.assertEqual(state["packet"]["sent_count"], 1)
        self.assertEqual(state["execution"]["resume_input"], "Continue.")
        self.assertTrue(state["transition"]["session_continuity"])
        self.assertTrue(state["transition"]["worktree_continuity"])
        self.assertEqual(state["transition"]["packet_sent_count"], 1)
        guide_record = json.loads((record / "guide.json").read_text())
        execution_record = json.loads((record / "execution.json").read_text())
        self.assertEqual(guide_record["packet_count"], 1)
        self.assertEqual(execution_record["input"], "Continue.")
        self.assertEqual(guide_record["phase"], "prewalk")
        self.assertEqual(execution_record["phase"], "execution")
        statuses = [entry["status"] for entry in state["status_history"]]
        for expected in (
            "staged",
            "launching_prewalk",
            "prewalking",
            "transition_ready",
            "launching_execution",
            "executing",
            "complete",
        ):
            self.assertIn(expected, statuses)
        follow = Path(state["follow_log"]).read_text(encoding="utf-8")
        self.assertIn('"phase": "prewalk"', follow)
        self.assertIn('"phase": "execution"', follow)

    def test_claude_stream_session_id_preserves_the_same_trajectory(self) -> None:
        state, _repo, record = self._launch(scenario="claude_session_id")
        self.assertEqual(state["status"], "complete")
        self.assertTrue(state["transition"]["session_continuity"])
        self.assertEqual(state["packet"]["sent_count"], 1)
        execution_record = json.loads((record / "execution.json").read_text())
        self.assertEqual(execution_record["input"], "Continue.")

    def test_atomic_task_completes_without_execution_turn(self) -> None:
        state, _repo, record = self._launch(scenario="tiny")
        self.assertEqual(state["status"], "complete")
        self.assertTrue(state["transition"]["task_complete"])
        self.assertFalse((record / "execution.json").exists())
        statuses = [entry["status"] for entry in state["status_history"]]
        self.assertNotIn("executing", statuses)

    def test_missing_transition_artifacts_fail_before_execution(self) -> None:
        state, _repo, record = self._launch(scenario="missing")
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["failure_reason"], "prewalk_checkpoint_missing")
        self.assertFalse((record / "execution.json").exists())

    def test_guide_recovery_resumes_exact_session_without_replaying_packet(self) -> None:
        state, _repo, record = self._launch(scenario="recovery_success")
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["prewalk"]["recovery_attempts"], 1)
        self.assertEqual(state["packet"]["sent_count"], 1)
        initial = json.loads((record / "guide-prewalk.json").read_text())
        recovery = json.loads((record / "guide-prewalk_recovery.json").read_text())
        self.assertEqual(initial["packet_count"], 1)
        self.assertEqual(recovery["packet_count"], 0)
        recovered_without_initial_event, _repo, _record = self._launch(
            scenario="recovery_no_initial_id"
        )
        self.assertEqual(recovered_without_initial_event["status"], "complete")
        self.assertEqual(
            recovered_without_initial_event["prewalk"]["recovery_attempts"], 1
        )

    def test_auto_fallback_is_explicitly_fresh_and_only_allowed_while_clean(self) -> None:
        state, repo, record = self._launch(scenario="clean_fallback", mode="auto")
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["mode"], "single_phase_fallback")
        self.assertFalse(state["transition"]["prewalk_claimed"])
        self.assertEqual(state["packet"]["sent_count"], 2)
        self.assertNotEqual(state["abandoned_prewalk_session_id"], state["session_id"])
        execution = json.loads((record / "execution.json").read_text())
        self.assertEqual(execution["input"], "packet body\n")
        self.assertEqual((repo / "product.txt").read_text(), "single phase fallback edit\n")

    def test_post_edit_cold_fallback_is_forbidden_and_preserves_edit(self) -> None:
        state, repo, record = self._launch(scenario="post_edit_failure", mode="auto")
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["failure_reason"], "prewalk_post_edit_cold_fallback_forbidden")
        self.assertEqual(state["packet"]["sent_count"], 1)
        self.assertFalse((record / "execution.json").exists())
        self.assertEqual((repo / "product.txt").read_text(), "uncheckpointed guide edit\n")

    def test_clean_auto_fallback_rejects_branch_and_head_authority_drift(self) -> None:
        for scenario in ("clean_branch_drift", "clean_head_drift"):
            with self.subTest(scenario=scenario):
                state, _repo, record = self._launch(scenario=scenario, mode="auto")
                self.assertEqual(state["status"], "failed")
                self.assertEqual(
                    state["failure_reason"],
                    "prewalk_worktree_continuity_violation",
                )
                self.assertEqual(state["packet"]["sent_count"], 1)
                self.assertFalse((record / "execution.json").exists())

    def test_malformed_forbidden_and_branch_drift_transitions_fail_closed(self) -> None:
        malformed, _repo, _record = self._launch(scenario="malformed")
        self.assertEqual(malformed["failure_reason"], "prewalk_todo_invalid")
        forbidden, _repo, _record = self._launch(forbidden_paths=("product.txt",))
        self.assertEqual(forbidden["failure_reason"], "prewalk_changed_path_forbidden")
        drifted, _repo, _record = self._launch(scenario="branch_drift")
        self.assertEqual(drifted["failure_reason"], "prewalk_worktree_continuity_violation")

    def test_session_mismatch_and_execution_failure_fail_closed(self) -> None:
        guide_no_id, _repo, _record = self._launch(scenario="guide_no_id")
        self.assertEqual(
            guide_no_id["failure_reason"],
            "prewalk_session_continuity_violation",
        )
        execution_no_id, _repo, _record = self._launch(scenario="execution_no_id")
        self.assertEqual(
            execution_no_id["failure_reason"],
            "prewalk_session_continuity_violation",
        )
        guide_mismatch, _repo, guide_record = self._launch(scenario="guide_mismatch")
        self.assertEqual(guide_mismatch["status"], "failed")
        self.assertEqual(
            guide_mismatch["failure_reason"],
            "prewalk_session_continuity_violation",
        )
        self.assertFalse((guide_record / "execution.json").exists())
        mismatch, _repo, _record = self._launch(scenario="mismatch")
        self.assertEqual(mismatch["status"], "failed")
        self.assertEqual(mismatch["failure_reason"], "prewalk_session_continuity_violation")
        failed, _repo, record = self._launch(scenario="execution_fail")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_reason"], "prewalk_execution_resume_failed")
        self.assertTrue((record / "execution.json").is_file())
        self.assertEqual(failed["packet"]["sent_count"], 1)

    def test_transient_execution_failure_backs_off_and_resumes_same_route(self) -> None:
        state, _repo, record = self._launch(scenario="transient_recovery")
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["execution"]["transient_retries"], 1)
        self.assertEqual(state["execution"]["retry_backoff_seconds"], [300])
        self.assertEqual(len(state["execution"]["attempts"]), 2)
        self.assertEqual(state["execution"]["attempts"][0]["phase"], "execution")
        self.assertEqual(
            state["execution"]["attempts"][1]["phase"], "execution_retry_1"
        )
        first = json.loads((record / "execution-1.json").read_text())
        second = json.loads((record / "execution-2.json").read_text())
        self.assertEqual(first["input"], "Continue.")
        self.assertEqual(second["input"], "Continue.")
        self.assertEqual(state["packet"]["sent_count"], 1)
        statuses = [entry["status"] for entry in state["status_history"]]
        self.assertIn("execution_backoff", statuses)

    def test_orphaned_childless_backoff_state_fails_status_instead_of_hanging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path, _log_path = native_worker_paths(repo, "orphaned-backoff")
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps(
                    {
                        "status": "execution_backoff",
                        "pid": None,
                        "pid_start": None,
                        "supervisor_pid": 999_999_999,
                        "supervisor_pid_start": "not-running",
                    }
                ),
                encoding="utf-8",
            )
            state_path.chmod(0o600)
            state = native_worker_status(repo, "orphaned-backoff")
            self.assertEqual(state["status"], "failed")
            self.assertEqual(
                state["failure_reason"],
                "native_worker_supervisor_identity_lost",
            )

    def test_live_child_is_not_reported_terminal_when_supervisor_is_lost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path, _log_path = native_worker_paths(repo, "orphaned-live-child")
            state_path.parent.mkdir(parents=True)
            process_start = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(os.getpid())],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            state_path.write_text(
                json.dumps(
                    {
                        "status": "executing",
                        "pid": os.getpid(),
                        "pid_start": process_start,
                        "supervisor_pid": 999_999_999,
                        "supervisor_pid_start": "not-running",
                    }
                ),
                encoding="utf-8",
            )
            state_path.chmod(0o600)
            state = native_worker_status(repo, "orphaned-live-child")
            self.assertEqual(state["status"], "executing")
            self.assertTrue(state["process_identity_matches"])
            self.assertFalse(state["supervisor_identity_matches"])

class AutomaticPrewalkQualificationTests(unittest.TestCase):
    def _advertised(self):
        return advertised_prewalk_capabilities(
            host="codex",
            version="9.9.9",
            create_help="--model -c model_reasoning_effort resume",
            resume_help="Usage: resume SESSION_ID --model -c model_reasoning_effort",
        )

    def _probe(self, advertised):
        def probe(host, *, behavioral_evidence=None, **_kwargs):
            self.assertEqual(host, "codex")
            if behavioral_evidence is None:
                return advertised
            return load_prewalk_capability_evidence(
                Path(behavioral_evidence),
                host="codex",
                installed_version="9.9.9",
                advertised=advertised,
            )

        return probe

    def test_required_canary_proves_and_reuses_matching_private_evidence(self) -> None:
        advertised = self._advertised()
        state: dict[str, str] = {}
        calls: list[str] = []

        def phase_runner(*, spec, input_text, **_kwargs):
            calls.append(input_text)
            canary_value = (
                Path(spec.cwd) / ".elves-prewalk-canary.txt"
            ).read_text(encoding="utf-8").strip()
            if input_text != PREWALK_CONTINUATION_INPUT:
                memory = re.search(
                    r"ELVES_PREWALK_CANARY_GUIDE ([0-9a-f]+)",
                    input_text,
                ).group(1)
                state["memory"] = memory
                marker = (
                    f"ELVES_PREWALK_CANARY_GUIDE {memory} {canary_value}"
                )
                event = {
                    "type": "thread.started",
                    "thread_id": "qualification-session",
                }
            else:
                marker = (
                    "ELVES_PREWALK_CANARY_EXECUTION "
                    f"{state['memory']} {canary_value}"
                )
                event = {
                    "type": "turn.started",
                    "thread_id": "qualification-session",
                }
            return PrewalkQualificationResult(
                exit_code=0,
                stdout=json.dumps(event) + "\n" + marker + "\n",
                stderr_tail="",
                observed_session_ids=("qualification-session",),
                provider_event_count=1,
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "cobbler_runtime.native_worker.probe_installed_prewalk_capabilities",
            side_effect=self._probe(advertised),
        ):
            cache_root = Path(tmp)
            qualified = qualify_installed_prewalk_transport(
                host="codex",
                guide_model="guide-model",
                guide_effort="high",
                execution_model="execution-model",
                execution_effort="medium",
                cache_root=cache_root,
                phase_runner=phase_runner,
            )
            self.assertTrue(qualified.qualified())
            self.assertEqual(calls[-1], PREWALK_CONTINUATION_INPUT)
            self.assertEqual(len(calls), 2)
            cache_path = prewalk_qualification_cache_path(
                advertised,
                execution_model="execution-model",
                execution_effort="medium",
                cache_root=cache_root,
            )
            self.assertTrue(cache_path.is_file())
            self.assertEqual(cache_path.stat().st_mode & 0o777, 0o600)

            reused = qualify_installed_prewalk_transport(
                host="codex",
                guide_model="guide-model",
                guide_effort="high",
                execution_model="execution-model",
                execution_effort="medium",
                cache_root=cache_root,
                phase_runner=lambda **_kwargs: self.fail(
                    "matching evidence should avoid a second live canary"
                ),
            )
            self.assertTrue(reused.qualified())
            self.assertEqual(len(calls), 2)

            # A different guide route reuses the same cached proof: the canary
            # binds the execution route, so no second canary is spent.
            other_guide = qualify_installed_prewalk_transport(
                host="codex",
                guide_model="other-guide-model",
                guide_effort="low",
                execution_model="execution-model",
                execution_effort="medium",
                cache_root=cache_root,
                phase_runner=lambda **_kwargs: self.fail(
                    "a guide-route change must reuse the execution-route proof"
                ),
            )
            self.assertTrue(other_guide.qualified())
            self.assertEqual(len(calls), 2)

    def test_required_canary_failure_stops_with_private_attempt_evidence(self) -> None:
        advertised = self._advertised()

        def phase_runner(**_kwargs):
            return PrewalkQualificationResult(
                exit_code=0,
                stdout=(
                    json.dumps(
                        {
                            "type": "thread.started",
                            "thread_id": "qualification-session",
                        }
                    )
                    + "\nwrong output\n"
                ),
                stderr_tail="",
                observed_session_ids=("qualification-session",),
                provider_event_count=1,
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "cobbler_runtime.native_worker.probe_installed_prewalk_capabilities",
            side_effect=self._probe(advertised),
        ):
            with self.assertRaises(ValidationIssue) as caught:
                qualify_installed_prewalk_transport(
                    host="codex",
                    guide_model="guide-model",
                    guide_effort="high",
                    execution_model="execution-model",
                    execution_effort="medium",
                    cache_root=Path(tmp),
                    phase_runner=phase_runner,
                )
            self.assertEqual(
                caught.exception.code, "prewalk_live_qualification_failed"
            )
            evidence = Path(caught.exception.hint.split("Evidence: ", 1)[1])
            self.assertTrue(evidence.is_file())
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertFalse(payload["qualified"])
            self.assertFalse(payload["checks"]["unique_guide_fact_observed"])
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)

    def test_required_canary_runtime_error_stops_with_attempt_evidence(self) -> None:
        advertised = self._advertised()

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "cobbler_runtime.native_worker.probe_installed_prewalk_capabilities",
            side_effect=self._probe(advertised),
        ):
            with self.assertRaises(ValidationIssue) as caught:
                qualify_installed_prewalk_transport(
                    host="codex",
                    guide_model="guide-model",
                    guide_effort="high",
                    execution_model="execution-model",
                    execution_effort="medium",
                    cache_root=Path(tmp),
                    phase_runner=lambda **_kwargs: (_ for _ in ()).throw(
                        OSError("provider process failed")
                    ),
                )
            self.assertEqual(
                caught.exception.code, "prewalk_live_qualification_failed"
            )
            evidence = Path(caught.exception.hint.split("Evidence: ", 1)[1])
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertFalse(payload["qualified"])
            self.assertTrue(payload["model_calls_made"])
            self.assertIn("provider process failed", payload["diagnostic"])


if __name__ == "__main__":
    unittest.main()
