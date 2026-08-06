"""Tests for worktree fingerprinting and the futile re-drive guard (v2.24 B1)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime import worktree_fingerprint as wf  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )


def _make_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "elves-tests@example.invalid")
    _git(repo, "config", "user.name", "Elves Tests")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


class FingerprintCaptureTests(unittest.TestCase):
    def test_mtime_only_change_is_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            first = wf.capture(repo)
            self.assertIsNone(first.error)
            os.utime(repo / "a.txt", (1_000_000_000, 1_000_000_000))
            second = wf.capture(repo)
            self.assertEqual(wf.compare(first, second), "identical")

    def test_tracked_content_change_is_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            first = wf.capture(repo)
            (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
            second = wf.capture(repo)
            self.assertEqual(wf.compare(first, second), "changed")

    def test_untracked_and_symlink_changes_are_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            first = wf.capture(repo)
            (repo / "new.txt").write_text("fresh\n", encoding="utf-8")
            second = wf.capture(repo)
            self.assertEqual(wf.compare(first, second), "changed")

            os.symlink("a.txt", repo / "link")
            third = wf.capture(repo)
            self.assertEqual(wf.compare(second, third), "changed")
            os.remove(repo / "link")
            os.symlink("new.txt", repo / "link")
            fourth = wf.capture(repo)
            self.assertEqual(wf.compare(third, fourth), "changed")

    def test_runtime_churn_is_invisible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            first = wf.capture(repo)
            runtime = repo / ".elves" / "runtime" / "anything"
            runtime.mkdir(parents=True)
            (runtime / "noise.json").write_text("{}\n", encoding="utf-8")
            second = wf.capture(repo)
            self.assertEqual(wf.compare(first, second), "identical")

    def test_capture_error_is_unavailable_never_futile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            good = wf.capture(repo)
            broken = wf.capture(Path(tmp) / "does-not-exist")
            self.assertIsNotNone(broken.error)
            self.assertEqual(wf.compare(good, broken), "unavailable")

    def test_over_cap_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            (repo / "big.bin").write_bytes(b"x" * 4096)
            capped = wf.capture(repo, byte_cap=64)
            self.assertTrue(capped.over_cap)
            self.assertEqual(wf.compare(capped, capped), "unavailable")


class RedriveGuardTests(unittest.TestCase):
    def test_futile_flow_charges_budget_and_escalates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            wf.record_failure(repo, batch="B3", failure_class="substantive")
            decision = wf.evaluate_redrive(
                repo, batch="B3", failure_class="substantive", budget=3
            )
            self.assertEqual(decision.classification, wf.FUTILE_CLASSIFICATION)
            self.assertEqual(decision.attempts_used, 1)
            self.assertTrue(decision.relaunch_identical_forbidden)
            self.assertTrue(decision.escalation_required)
            self.assertIn("workspace unchanged", decision.gap_packet_line)
            self.assertIn(wf.FUTILE_CLASSIFICATION, decision.log_snippet)

            events = (
                (repo / ".elves" / "runtime" / "redrive" / wf.EVENTS_FILE_NAME)
                .read_text(encoding="utf-8")
                .strip()
                .splitlines()
            )
            kinds = [json.loads(line)["event"] for line in events]
            self.assertIn("failure_recorded", kinds)
            self.assertIn("redrive_evaluated", kinds)

    def test_changed_tree_allows_redrive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            wf.record_failure(repo, batch="B3", failure_class="substantive")
            (repo / "a.txt").write_text("one\nfixed\n", encoding="utf-8")
            decision = wf.evaluate_redrive(
                repo, batch="B3", failure_class="substantive", budget=3
            )
            self.assertEqual(decision.classification, "redrive_allowed:changed")
            self.assertFalse(decision.relaunch_identical_forbidden)
            self.assertFalse(decision.escalation_required)
            self.assertIn("workspace changed", decision.gap_packet_line)

    def test_different_failure_class_is_not_futile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            wf.record_failure(repo, batch="B2", failure_class="substantive:wrong-direction")
            decision = wf.evaluate_redrive(
                repo, batch="B2", failure_class="substantive:red-gates", budget=3
            )
            self.assertEqual(decision.classification, "redrive_allowed:identical")
            self.assertFalse(decision.relaunch_identical_forbidden)

    def test_unavailable_fingerprint_never_futile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            wf.record_failure(repo, batch="B4", failure_class="substantive")
            broken = wf.capture(Path(tmp) / "missing")
            decision = wf.evaluate_redrive(
                repo,
                batch="B4",
                failure_class="substantive",
                budget=3,
                fingerprint=broken,
            )
            self.assertEqual(decision.classification, "redrive_allowed:unavailable")
            self.assertFalse(decision.relaunch_identical_forbidden)

    def test_budget_exhaustion_escalates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            wf.record_failure(repo, batch="B5", failure_class="substantive")
            for round_number in range(2):
                (repo / "a.txt").write_text(f"round {round_number}\n", encoding="utf-8")
                decision = wf.evaluate_redrive(
                    repo, batch="B5", failure_class="substantive", budget=2
                )
            self.assertEqual(decision.attempts_used, 2)
            self.assertTrue(decision.escalation_required)
            self.assertEqual(decision.budget_remaining, 0)

    def test_status_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            before = wf.guard_status(repo, batch="B9")
            self.assertEqual(before["attempts_used"], 0)
            self.assertFalse(before["has_prior_failure"])
            wf.record_failure(repo, batch="B9", failure_class="substantive")
            after = wf.guard_status(repo, batch="B9")
            self.assertTrue(after["has_prior_failure"])
            self.assertEqual(after["attempts_used"], 0)


class RedriveCliTests(unittest.TestCase):
    def _run_cli(self, repo: Path, *args: str) -> dict:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "cobbler_agents.py"),
                "redrive",
                *args,
                "--repo-root",
                str(repo),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=completed.stderr.decode("utf-8", "replace"),
        )
        return json.loads(completed.stdout.decode("utf-8"))

    def test_cli_record_then_evaluate_futile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            recorded = self._run_cli(repo, "record-failure", "--batch", "B1")
            self.assertTrue(recorded["recorded"])
            decision = self._run_cli(
                repo, "evaluate", "--batch", "B1", "--budget", "3"
            )
            self.assertEqual(decision["classification"], wf.FUTILE_CLASSIFICATION)
            self.assertTrue(decision["relaunch_identical_forbidden"])
            status = self._run_cli(repo, "status", "--batch", "B1")
            self.assertEqual(status["attempts_used"], 1)


if __name__ == "__main__":
    unittest.main()
