"""Real Git worktrees exercise persistent writer lifecycle and integration."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cobbler_runtime.parallel_lanes import LaneSupervisor
from cobbler_runtime.schema import ValidationIssue
from cobbler_runtime import team_lanes as tl


class WriterLanesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git(self.repo, "init", "-b", "feature/team")
        self.git(self.repo, "config", "user.name", "Test")
        self.git(self.repo, "config", "user.email", "test@example.com")
        self.git(self.repo, "config", "commit.gpgsign", "false")
        self.commit(self.repo, "README.md", "base\n")
        self.actor = tl.identity("driver-session", "codex", "model-a")
        self.worker = tl.identity("writer-session", "claude", "model-b")
        self.path = self.root / "lanes.sqlite"
        self.store = tl.LaneStore(self.path)
        self.store.initialize(repo=self.repo, run_id="run-one", driver=self.actor)

    def git(self, path, *args):
        result = subprocess.run(["git", "-C", str(path), *args], text=True,
                                capture_output=True, check=True)
        return result.stdout.strip()

    def commit(self, path, name, content):
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.git(path, "add", "--", name)
        self.git(path, "commit", "-m", "Change " + name)
        return self.git(path, "rev-parse", "HEAD")

    def register(self, lid="L1", owns=None, deps=None):
        worker = dict(self.worker, session="writer-" + lid)
        path = self.root / lid
        branch = "writer/" + lid
        self.git(self.repo, "worktree", "add", "-b", branch, str(path))
        self.store.register(actor=self.actor, lane_id=lid, worktree=path, branch=branch,
                            worker=worker, owns=owns or [lid + "/"], depends_on=deps)
        return path, worker

    def completed(self, lid="L1", owns=None, deps=None):
        path, worker = self.register(lid, owns, deps)
        self.store.start(actor=self.actor, lane_id=lid, worker=worker)
        head = self.commit(path, lid + "/result.txt", lid + " done\n")
        self.store.complete(actor=self.actor, lane_id=lid, worker=worker, result_head=head)
        return path, worker, head

    def link_session(self):
        exclude = self.repo / ".git/info/exclude"
        exclude.write_text(exclude.read_text() + "\n.elves/\n")
        self.session_path = self.repo / ".elves/session.json"
        self.session_path.parent.mkdir(exist_ok=True)
        driver = {"session_id": self.actor["session"], "kind": self.actor["kind"], "model": self.actor["model"]}
        session = {"run_id": "run-one", "worktree_path": str(self.repo),
                   "team": {"version": 1, "driver": driver, "contributors": [{**driver, "role": "lead"}], "helpers": {}}}
        self.session_path.write_text(json.dumps(session))
        self.path = self.root / "linked.sqlite"
        self.store = tl.LaneStore(self.path)
        self.store.initialize(repo=self.repo, run_id="run-one", driver=self.actor, session_path=self.session_path)
        return json.loads(self.session_path.read_text())

    def assertIssue(self, code, function, **kwargs):
        with self.assertRaises(ValidationIssue) as caught:
            function(**kwargs)
        self.assertEqual(caught.exception.code, code)

    def reserve(self, lid="L1"):
        original = tl._git

        def interrupted(path, *args, **kwargs):
            if args[0] == "merge":
                raise RuntimeError("Simulated process interruption")
            return original(path, *args, **kwargs)

        with patch.object(tl, "_git", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                self.store.integrate(actor=self.actor, lane_id=lid)

    def test_pending_survives_restart_and_keeps_run_active(self):
        self.register()
        state = tl.LaneStore(self.path).status()
        self.assertEqual(state["pending"], ["L1"])
        self.assertFalse(state["all_terminal"])
        self.assertFalse(state["all_integrated"])
        self.assertFalse(state["launch_authorized"])
        self.assertEqual(state["lanes"]["L1"]["identity"]["model"], "model-b")

    def test_legacy_pending_and_empty_are_not_terminal_or_integrable(self):
        supervisor = LaneSupervisor()
        self.assertFalse(supervisor.reconcile()["all_terminal"])
        self.assertFalse(supervisor.reconcile()["ok_to_integrate"])
        supervisor.register("L1")
        self.assertFalse(supervisor.reconcile()["all_terminal"])
        supervisor.register("L2")
        supervisor.mark_completed("L1")
        self.assertFalse(supervisor.reconcile()["all_terminal"])
        supervisor.mark_completed("L2")
        self.assertTrue(supervisor.reconcile()["all_terminal"])
        self.assertTrue(supervisor.reconcile()["ok_to_integrate"])

    def test_exact_session_kind_model_required_for_restart(self):
        _, worker = self.register()
        self.store.start(actor=self.actor, lane_id="L1", worker=worker)
        restarted = tl.LaneStore(self.path)
        for key in worker:
            self.assertIssue("team_lanes_identity_mismatch", restarted.start,
                             actor=self.actor, lane_id="L1", worker={**worker, key: "different"})
        resumed = restarted.start(actor=self.actor, lane_id="L1", worker=worker)
        self.assertTrue(resumed["resume_only"])
        self.assertFalse(resumed["launch_authorized"])

    def test_helper_cannot_register_recursive_helper(self):
        _, worker = self.register()
        self.assertIssue("team_lanes_driver_required", self.store.register,
                         actor=worker, lane_id="L2", worktree=self.repo, branch="any",
                         worker=tl.identity("third", "other", "model-c"), owns=["b/"])

    def test_overlap_and_unknown_dependencies_rejected(self):
        self.register(owns=["src/"])
        with self.assertRaises(ValidationIssue) as caught:
            self.register("L2", owns=["src/nested/"])
        self.assertEqual(caught.exception.code, "parallel_lanes_surface_overlap")
        with self.assertRaises(ValidationIssue) as caught:
            self.register("L3", deps=["L999"])
        self.assertEqual(caught.exception.code, "team_lanes_dependency_unknown")

    def test_sequential_dependencies_require_integrated_base(self):
        self.completed()
        path, worker = self.register("L2", deps=["L1"])
        self.assertIssue("team_lanes_dependency_unmet", self.store.start,
                         actor=self.actor, lane_id="L2", worker=worker)
        self.store.integrate(actor=self.actor, lane_id="L1")
        self.assertIssue("team_lanes_dependency_unmet", self.store.start,
                         actor=self.actor, lane_id="L2", worker=worker)
        self.git(path, "merge", "--ff-only", "feature/team")
        self.store.start(actor=self.actor, lane_id="L2", worker=worker)
        head = self.commit(path, "L2/next.txt", "next\n")
        self.store.complete(actor=self.actor, lane_id="L2", worker=worker, result_head=head)
        state = self.store.integrate(actor=self.actor, lane_id="L2")
        self.assertTrue(state["all_integrated"])

    def test_completed_result_is_not_terminal_until_integration(self):
        self.completed()
        state = self.store.status()
        self.assertEqual(state["completed"], ["L1"])
        self.assertFalse(state["all_terminal"])
        result = self.store.integrate(actor=self.actor, lane_id="L1")
        self.assertTrue(result["all_terminal"])
        self.assertTrue(result["all_integrated"])
        self.assertEqual((self.repo / "L1/result.txt").read_text(), "L1 done\n")
        self.assertEqual(len(self.git(self.repo, "show", "-s", "--format=%P").split()), 2)

    def test_concurrent_results_integrate_with_disjoint_paths(self):
        self.completed()
        self.completed("L2")
        self.store.integrate(actor=self.actor, lane_id="L1")
        state = self.store.integrate(actor=self.actor, lane_id="L2")
        self.assertTrue(state["all_integrated"])

    def test_duplicate_integration_is_rejected(self):
        self.completed()
        self.store.integrate(actor=self.actor, lane_id="L1")
        self.assertIssue("team_lanes_integration_state", self.store.integrate,
                         actor=self.actor, lane_id="L1")

    def test_actual_ancestry_detects_unrecorded_integration(self):
        _, _, head = self.completed()
        self.git(self.repo, "merge", "--no-ff", "--no-edit", head)
        self.assertIssue("team_lanes_already_integrated", self.store.gate,
                         actor=self.actor, lane_id="L1")

    def test_branch_drift_after_completion_blocks_gate(self):
        path, _, _ = self.completed()
        self.commit(path, "L1/extra.txt", "drift\n")
        self.assertIssue("team_lanes_branch_drift", self.store.gate,
                         actor=self.actor, lane_id="L1")

    def test_changed_branch_binding_blocks_gate(self):
        path, _, _ = self.completed()
        self.git(path, "switch", "-c", "other-branch")
        self.assertIssue("team_lanes_branch_drift", self.store.gate,
                         actor=self.actor, lane_id="L1")

    def test_actual_driver_overlap_blocks_gate(self):
        self.completed()
        self.commit(self.repo, "L1/driver.txt", "overlap\n")
        self.assertIssue("team_lanes_integration_overlap", self.store.gate,
                         actor=self.actor, lane_id="L1")

    def test_staged_and_untracked_files_block_integration(self):
        path, _, _ = self.completed()
        for target in (path, self.repo):
            with self.subTest(target=target):
                dirty = target / "untracked.txt"
                dirty.write_text("dirty\n")
                self.assertIssue("team_lanes_dirty_worktree", self.store.gate,
                                 actor=self.actor, lane_id="L1")
                self.git(target, "add", "untracked.txt")
                self.assertIssue("team_lanes_dirty_worktree", self.store.gate,
                                 actor=self.actor, lane_id="L1")
                self.git(target, "reset", "HEAD", "--", "untracked.txt")
                dirty.unlink()

    def test_ownership_checks_history_even_when_outside_edit_is_reverted(self):
        path, worker = self.register()
        self.store.start(actor=self.actor, lane_id="L1", worker=worker)
        self.commit(path, "README.md", "outside\n")
        self.commit(path, "README.md", "base\n")
        head = self.commit(path, "L1/result.txt", "owned\n")
        self.assertIssue("team_lanes_ownership_violation", self.store.complete,
                         actor=self.actor, lane_id="L1", worker=worker, result_head=head)

    def test_reservation_survives_restart_and_requires_explicit_reconciliation(self):
        self.completed()
        self.reserve()
        restarted = tl.LaneStore(self.path)
        self.assertEqual(restarted.status()["integrating"], ["L1"])
        self.assertFalse(restarted.status()["all_terminal"])
        self.assertIssue("team_lanes_integration_state", restarted.integrate,
                         actor=self.actor, lane_id="L1")
        state = restarted.reconcile(actor=self.actor, lane_id="L1", outcome="not-applied")
        self.assertEqual(state["completed"], ["L1"])
        self.assertTrue(restarted.integrate(actor=self.actor, lane_id="L1")["all_integrated"])

    def test_reservation_blocks_other_integrations(self):
        self.completed()
        self.completed("L2")
        self.reserve()
        self.assertIssue("team_lanes_integration_pending", self.store.integrate,
                         actor=self.actor, lane_id="L2")

    def test_driver_branch_is_rechecked_after_reservation(self):
        self.completed()
        original = self.store._save

        def change_branch(db, state):
            original(db, state)
            if state["lanes"]["L1"]["status"] == "integrating":
                self.git(self.repo, "switch", "-c", "wrong-branch")

        with patch.object(self.store, "_save", side_effect=change_branch):
            self.assertIssue("team_lanes_branch_drift", self.store.integrate,
                             actor=self.actor, lane_id="L1")
        self.assertEqual(self.store.status()["integrating"], ["L1"])
        self.assertFalse((self.repo / "L1/result.txt").exists())

    def test_reconcile_adopts_only_reserved_parents_and_tree(self):
        _, _, head = self.completed()
        self.reserve()
        self.git(self.repo, "merge", "--no-ff", "--no-edit", head)
        state = tl.LaneStore(self.path).reconcile(actor=self.actor, lane_id="L1", outcome="integrated")
        self.assertTrue(state["all_integrated"])

    def test_reconcile_rejects_ambiguous_modified_merge(self):
        _, _, head = self.completed()
        self.reserve()
        self.git(self.repo, "merge", "--no-ff", "--no-edit", head)
        self.commit(self.repo, "unrelated.txt", "later\n")
        for outcome in ("integrated", "not-applied"):
            self.assertIssue("team_lanes_reconcile_ambiguous", self.store.reconcile,
                             actor=self.actor, lane_id="L1", outcome=outcome)
        self.assertEqual(self.store.status()["integrating"], ["L1"])

    def test_driver_required_for_state_mutations(self):
        self.completed()
        self.assertIssue("team_lanes_driver_required", self.store.integrate,
                         actor=self.worker, lane_id="L1")

    def test_protected_main_cannot_be_driver(self):
        self.git(self.repo, "switch", "-c", "main")
        self.assertIssue("team_lanes_protected_branch", tl.LaneStore(self.root / "other.sqlite").initialize,
                         repo=self.repo, run_id="bad", driver=self.actor)

    def test_configured_default_branch_cannot_be_driver(self):
        self.git(self.repo, "config", "init.defaultBranch", "trunk")
        self.git(self.repo, "switch", "-c", "trunk")
        self.assertIssue("team_lanes_protected_branch", tl.LaneStore(self.root / "other.sqlite").initialize,
                         repo=self.repo, run_id="bad", driver=self.actor)

    def test_existing_database_cannot_be_reinitialized(self):
        self.assertIssue("team_lanes_already_initialized", self.store.initialize,
                         repo=self.repo, run_id="other", driver=self.actor)
        self.assertEqual(self.store.status()["run_id"], "run-one")

    def test_cancel_pending_retains_failure_reason(self):
        self.register()
        state = self.store.stop(actor=self.actor, lane_id="L1", reason="User cancelled", cancelled=True)
        self.assertTrue(state["all_terminal"])
        self.assertFalse(state["all_integrated"])
        self.assertEqual(state["lanes"]["L1"]["reason"], "User cancelled")

    def test_linked_session_records_all_writer_contributors_before_launch(self):
        self.link_session()
        _, worker = self.register()
        session = json.loads(self.session_path.read_text())
        self.assertEqual(session["team_lanes"], {"state_path": str(self.path), "run_id": "run-one"})
        self.assertIn({"session_id": worker["session"], "kind": worker["kind"],
                       "model": worker["model"], "role": "implementer"}, session["team"]["contributors"])

    def test_linked_readiness_uses_real_integration_and_blocks_pending(self):
        self.link_session()
        self.completed()
        session = json.loads(self.session_path.read_text())
        self.assertIssue("team_lanes_not_ready", tl.readiness_check,
                         session=session, head=self.git(self.repo, "rev-parse", "HEAD"))
        self.store.integrate(actor=self.actor, lane_id="L1")
        tl.readiness_check(session, self.git(self.repo, "rev-parse", "HEAD"))
        self.register("L2")
        session = json.loads(self.session_path.read_text())
        self.assertIssue("team_lanes_not_ready", tl.readiness_check,
                         session=session, head=self.git(self.repo, "rev-parse", "HEAD"))

    def test_linked_readiness_rejects_removed_contributor(self):
        self.link_session()
        self.completed()
        self.store.integrate(actor=self.actor, lane_id="L1")
        session = json.loads(self.session_path.read_text())
        session["team"]["contributors"] = session["team"]["contributors"][:1]
        self.assertIssue("team_lanes_contributor_missing", tl.readiness_check,
                         session=session, head=self.git(self.repo, "rev-parse", "HEAD"))
        self.session_path.write_text(json.dumps(session))
        self.assertIssue("team_lanes_contributor_missing", tl.readiness_check,
                         session=session, head=self.git(self.repo, "rev-parse", "HEAD"))

    def test_failed_lane_requires_explicit_resolution_before_readiness(self):
        self.link_session()
        self.register()
        self.store.stop(actor=self.actor, lane_id="L1", reason="Worker failed")
        session = json.loads(self.session_path.read_text())
        self.assertIssue("team_lanes_not_ready", tl.readiness_check,
                         session=session, head=self.git(self.repo, "rev-parse", "HEAD"))
        self.store.stop(actor=self.actor, lane_id="L1", reason="User cancelled this item", cancelled=True)
        tl.readiness_check(session, self.git(self.repo, "rev-parse", "HEAD"))

    def test_linked_session_identity_drift_blocks_mutations(self):
        self.link_session()
        _, worker = self.register()
        session = json.loads(self.session_path.read_text())
        session["team"]["driver"]["model"] = "different"
        self.session_path.write_text(json.dumps(session))
        self.assertIssue("team_lanes_identity_mismatch", self.store.start,
                         actor=self.actor, lane_id="L1", worker=worker)

    def test_standalone_readiness_remains_neutral(self):
        tl.readiness_check({"run_id": "standalone"}, "not-needed")

    def test_empty_linked_ledger_requires_explicit_abandonment(self):
        session = self.link_session()
        self.assertFalse(self.store.status()["all_terminal"])
        head = self.git(self.repo, "rev-parse", "HEAD")
        self.assertIssue("team_lanes_not_ready", tl.readiness_check, session=session, head=head)
        self.assertIssue("team_lanes_reason_required", self.store.abandon, actor=self.actor, reason="")
        result = self.store.abandon(actor=self.actor, reason="Driver chose the serial path")
        self.assertTrue(result["ready"])
        self.assertTrue(result["all_terminal"])
        self.assertFalse(result["all_integrated"])
        tl.readiness_check(session, head)
        self.assertEqual(tl.LaneStore(self.path).status()["disposition"]["reason"], "Driver chose the serial path")
        with self.assertRaises(ValidationIssue) as caught:
            self.register()
        self.assertEqual(caught.exception.code, "team_lanes_run_abandoned")

    def test_abandon_cannot_hide_registered_writers(self):
        self.register()
        self.assertIssue("team_lanes_abandon_invalid", self.store.abandon,
                         actor=self.actor, reason="Switch to serial")

    def test_public_cli_abandons_empty_ledger(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/cobbler_agents.py"), "team-lanes", "abandon",
             "--state", str(self.path), "--actor-session", self.actor["session"],
             "--actor-kind", self.actor["kind"], "--actor-model", self.actor["model"],
             "--reason", "Use the serial driver"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["result"]["ready"])

    def test_linked_session_must_stay_inside_worktree_without_symlinks(self):
        self.link_session()
        outside = self.root / "outside-session.json"
        original = self.session_path.read_text()
        outside.write_text(original)
        candidates = [outside]
        linked = self.session_path.parent / "linked.json"
        linked.symlink_to(outside)
        candidates.append(linked)
        directory = self.session_path.parent / "linked-dir"
        directory.symlink_to(self.root, target_is_directory=True)
        candidates.append(directory / "outside-session.json")
        for index, candidate in enumerate(candidates):
            with self.subTest(path=candidate):
                self.assertIssue("team_lanes_session_path", tl.LaneStore(self.root / f"bad-{index}.sqlite").initialize,
                                 repo=self.repo, run_id="run-one", driver=self.actor, session_path=candidate)
        self.assertEqual(outside.read_text(), original)

    def test_linked_transactions_share_reentrant_canonical_session_lock(self):
        from cobbler_runtime.teams import session_lock
        self.link_session()
        with session_lock(self.session_path):
            self.register()
            self.assertEqual(self.store.status()["pending"], ["L1"])

    def test_lane_registration_waits_for_team_session_writer_and_retains_both_contributors(self):
        self.link_session()
        worker_path = self.root / "L1"
        self.git(self.repo, "worktree", "add", "-b", "writer/L1", str(worker_path))
        ready = self.root / "session-lock-held"
        release = self.root / "release-session-lock"
        attempted = self.root / "writer-lock-requested"
        helper_script = '''import json, sys, time
from pathlib import Path
from cobbler_runtime.teams import contributor, session_lock
from cobbler_runtime.storage import atomic_write_json
session_path, ready, release = map(Path, sys.argv[1:])
with session_lock(session_path):
    session = json.loads(session_path.read_text())
    ready.write_text("locked")
    deadline = time.monotonic() + 15
    while not release.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Test release did not arrive")
        time.sleep(0.01)
    contributor(session, {"session_id":"brainstorm-helper", "kind":"grok", "model":"model-c"}, "proposer")
    atomic_write_json(session_path, session)
'''
        writer_script = '''import sys
from pathlib import Path
from contextlib import contextmanager
from cobbler_runtime import teams
from cobbler_agents import main
original = teams.session_lock
@contextmanager
def traced_lock(path):
    Path(sys.argv[1]).write_text("requested")
    with original(path):
        yield
teams.session_lock = traced_lock
raise SystemExit(main(sys.argv[2:]))
'''
        env = {**os.environ, "PYTHONPATH": str(ROOT / "scripts")}
        helper = subprocess.Popen([sys.executable, "-c", helper_script, str(self.session_path), str(ready), str(release)],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        writer = None
        try:
            import time
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline and helper.poll() is None:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            writer = subprocess.Popen(
                [sys.executable, "-c", writer_script, str(attempted), "team-lanes", "register",
                 "--state", str(self.path), "--actor-session", self.actor["session"],
                 "--actor-kind", self.actor["kind"], "--actor-model", self.actor["model"],
                 "--lane", "L1", "--worktree", str(worker_path), "--branch", "writer/L1",
                 "--session", "writer-L1", "--kind", "claude", "--model", "model-b", "--owns", "src/"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            # Prove the writer waits on the canonical lock instead of reading
            # and overwriting the helper's in-flight JSON session update.
            deadline = time.monotonic() + 10
            while not attempted.exists() and time.monotonic() < deadline and writer.poll() is None:
                time.sleep(0.01)
            self.assertTrue(attempted.exists(), "Lane CLI did not enter the canonical session lock")
            with self.assertRaises(subprocess.TimeoutExpired):
                writer.communicate(timeout=0.1)
            release.write_text("release")
            helper_output = helper.communicate(timeout=15)
            writer_output = writer.communicate(timeout=15)
            self.assertEqual(helper.returncode, 0, helper_output)
            self.assertEqual(writer.returncode, 0, writer_output)
            contributors = json.loads(self.session_path.read_text())["team"]["contributors"]
            self.assertEqual({row["session_id"] for row in contributors},
                             {self.actor["session"], "brainstorm-helper", "writer-L1"})
        finally:
            release.touch()
            for process in (helper, writer):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_parser_and_error_envelopes(self):
        parser = argparse.ArgumentParser()
        tl.add_parser(parser.add_subparsers())
        args = parser.parse_args(["team-lanes", "status", "--state", str(self.path), "--json"])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(args.func(args), 0)
        self.assertEqual(json.loads(output.getvalue())["result"]["run_id"], "run-one")
        args.state = self.root / "absent.sqlite"
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(args.func(args), 1)
        self.assertEqual(json.loads(output.getvalue())["issues"][0]["code"], "team_lanes_state_missing")

    def test_public_cli(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/cobbler_agents.py"),
                                 "team-lanes", "status", "--state", str(self.path), "--json"],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"]["run_id"], "run-one")

    def test_database_serializes_competing_ownership_registration(self):
        processes = []
        for lid in ("L1", "L2"):
            path = self.root / lid
            branch = "writer/" + lid
            self.git(self.repo, "worktree", "add", "-b", branch, str(path))
            processes.append(subprocess.Popen(
                [sys.executable, str(ROOT / "scripts/cobbler_agents.py"), "team-lanes", "register",
                 "--state", str(self.path), "--actor-session", self.actor["session"],
                 "--actor-kind", self.actor["kind"], "--actor-model", self.actor["model"],
                 "--lane", lid, "--worktree", str(path), "--branch", branch,
                 "--session", "writer-" + lid, "--kind", "claude", "--model", "model-b", "--owns", "src/"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        try:
            results = [process.communicate(timeout=30) for process in processes]
            self.assertEqual(sorted(process.returncode for process in processes), [0, 1], results)
            payloads = [json.loads(result[0]) for result in results]
            failure = next(payload for payload in payloads if not payload["ok"])
            self.assertEqual(failure["issues"][0]["code"], "parallel_lanes_surface_overlap")
            self.assertEqual(len(self.store.status()["lanes"]), 1)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
