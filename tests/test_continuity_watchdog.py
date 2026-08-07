"""Tests for the continuity resume watchdog (v2.24 B6)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime import continuity as ct  # noqa: E402
from cobbler_runtime import full_run as full_run_module  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import resume_watchdog  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )


def _feature_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "feat/x")
    _git(repo, "config", "user.email", "elves-tests@example.invalid")
    _git(repo, "config", "user.name", "Elves Tests")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _staged_session(repo: Path, head: str) -> Path:
    """Minimal plan + session accepted by the production prepare gate."""

    plan = repo / "plan.md"
    if not plan.exists():
        plan.write_text(
            "# Plan: fixture\n\n## Batches\n\n### Batch 0 [B0]: Fixture\n\n"
            "**Acceptance criteria:**\n\n- [ ] [B0-A1] fixture criterion\n\n"
            "## Master Acceptance\n\n- [ ] [M-A1] fixture master\n",
            encoding="utf-8",
        )
    session = repo / ".elves-session.json"
    session.write_text(
        json.dumps(
            {
                "run_id": "cont-fixture",
                "session_id": "cont-fixture-host",
                "plan_path": "plan.md",
                "branch": "feat/x",
                "start_head": head,
                "mode": "finite",
                "driver_authorized": False,
                "batches": [],
                "master_acceptance": [],
                "continuation_guard": {"stop_allowed": False},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "acceptance_contract.py"),
            "sync-session",
            "--write",
            "--repo-root",
            str(repo),
            "--session",
            str(session),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
        check=True,
    )
    return session


def _config_for(repo: Path, session_id: str = "cont-run") -> dict:
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        check=True,
        timeout=60,
    ).stdout.decode().strip()
    packet = repo / "packet.md"
    if not packet.exists():
        packet.write_text("fixture packet\n", encoding="utf-8")
    return {
        "repo_root": str(repo),
        "session_id": session_id,
        "branch": "feat/x",
        "start_head": head,
        "packet": str(packet),
    }


class ConfigAndTemplateTests(unittest.TestCase):
    def test_config_roundtrip_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _feature_repo(Path(tmp))
            ct.write_config(repo, _config_for(repo))
            stored = ct.read_config(repo)
            self.assertFalse(stored["auto_resume"])
            self.assertEqual(stored["interval_seconds"], 900)

    def test_invalid_config_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _feature_repo(Path(tmp))
            bad = _config_for(repo)
            bad["packet"] = ""
            with self.assertRaises(ct.ContinuityError) as ctx:
                ct.write_config(repo, bad)
            self.assertEqual(ctx.exception.code, "continuity_config_invalid")

    def test_templates_deterministic_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _feature_repo(Path(tmp))
            ct.write_config(repo, _config_for(repo))
            stored = ct.read_config(repo)
            plist_a = ct.render_launchd_plist(stored)
            plist_b = ct.render_launchd_plist(stored)
            self.assertEqual(plist_a, plist_b)
            self.assertIn("resume_watchdog.py", plist_a)
            self.assertIn("<integer>900</integer>", plist_a)
            self.assertIn("<false/>", plist_a)  # RunAtLoad off
            units = ct.render_systemd_units(stored)
            self.assertIn("OnUnitActiveSec=900s", units["timer"])
            self.assertIn("resume_watchdog.py", units["service"])
            self.assertIn("never resumes a terminal run", units["service"])

    def test_install_status_remove_idempotent_and_never_activate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _feature_repo(Path(tmp))
            first = ct.install(repo, _config_for(repo))
            second = ct.install(repo, _config_for(repo))
            self.assertEqual(first["templates"], second["templates"])
            self.assertIn("operator-owned", first["activation"]["note"])
            report = ct.status(repo)
            self.assertTrue(report["installed"])
            self.assertEqual(len(report["templates"]), 3)
            self.assertIn("operator-owned", report["activation_state"])
            removed = ct.remove(repo)
            self.assertEqual(len(removed["removed"]), 4)
            again = ct.remove(repo)
            self.assertEqual(again["removed"], [])
            self.assertFalse(ct.status(repo)["installed"])

    def test_module_never_invokes_os_managers(self) -> None:
        source = (SCRIPTS / "cobbler_runtime" / "continuity.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)


class ClaimTests(unittest.TestCase):
    def test_single_flight_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _feature_repo(Path(tmp))
            with ct.claim(repo) as held:
                self.assertTrue(held)
                with ct.claim(repo) as second:
                    self.assertFalse(second)
            with ct.claim(repo) as third:
                self.assertTrue(third)


class WatchdogSafetyTests(unittest.TestCase):
    def _terminal_fixture(self, tmp: Path) -> Path:
        repo = _feature_repo(tmp)
        worker = repo / "worker.py"
        worker.write_text("print('ok')\n", encoding="utf-8")
        (repo / "packet.md").write_text(
            "# Worker packet: fixture\n\n### Batch 0 [B0]: Fixture\n\n"
            "**Acceptance criteria:**\n\n- [ ] [B0-A1] fixture criterion\n\n"
            "## Master Acceptance\n\n- [ ] [M-A1] fixture master\n",
            encoding="utf-8",
        )
        (repo / "plan.md").write_text(
            "# Plan: fixture\n\n## Batches\n\n### Batch 0 [B0]: Fixture\n\n"
            "**Acceptance criteria:**\n\n- [ ] [B0-A1] fixture criterion\n\n"
            "## Master Acceptance\n\n- [ ] [M-A1] fixture master\n",
            encoding="utf-8",
        )
        # Production shape: run docs tracked, session + runtime state ignored,
        # start_head equal to the clean tip that carries the staged inputs.
        (repo / ".gitignore").write_text(
            ".elves/runtime/\n.elves-session.json\n", encoding="utf-8"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "fixture staging")
        bare = tmp / "origin.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", str(bare)],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            timeout=60,
        )
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "feat/x")
        config = _config_for(repo, session_id="cont-terminal")
        prep = full_run_module.prepare_full_run(
            repo,
            session_id="cont-terminal",
            branch="feat/x",
            start_head=config["start_head"],
            worktree=repo,
            packet_path=Path(config["packet"]),
            adapter="fixture",
            fixture_script=worker,
            effort="low",
            create=True,
        )
        state = full_run_module.load_state(repo, "cont-terminal")
        state.status = "complete"
        state.pid = None
        full_run_module.save_state(repo, state)
        events_path = Path(prep["events_path"])
        with events_path.open("ab") as handle:
            handle.write(
                (
                    json.dumps(
                        {
                            "timestamp": "2026-08-01T00:00:00Z",
                            "session_id": "cont-terminal",
                            "branch": "feat/x",
                            "head": state.head,
                            "batch": 0,
                            "type": "run_complete",
                            "summary": "done",
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
        config["auto_resume"] = True
        config["python"] = sys.executable
        config["session"] = str(_staged_session(repo, config["start_head"]))
        ct.write_config(repo, config)
        return repo

    def _state_snapshot(self, repo: Path, session_id: str) -> dict[str, bytes]:
        root = full_run_module.full_run_root(repo, session_id)
        return {
            str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    def test_terminal_run_refused_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._terminal_fixture(Path(tmp))
            before = self._state_snapshot(repo, "cont-terminal")
            outcome = resume_watchdog.run_once(repo, now=0.0)
            self.assertEqual(outcome["outcome"], "terminal_refused")
            self.assertEqual(
                outcome["detail"], "full_run_resume_prepare_terminal"
            )
            after = self._state_snapshot(repo, "cont-terminal")
            self.assertEqual(before, after)
            log = (ct.continuity_dir(repo) / ct.LOG_FILE_NAME).read_text(encoding="utf-8")
            self.assertIn("terminal_refused", log)

    def test_string_auto_resume_fails_closed(self) -> None:
        # Adversarial-review W-3: a hand-edited '"auto_resume": "false"' is
        # truthy in Python; the read path must refuse rather than silently
        # invert the operator's intent.
        with tempfile.TemporaryDirectory() as tmp:
            repo = _feature_repo(Path(tmp))
            ct.write_config(repo, _config_for(repo))
            cfg = ct.config_path(repo)
            data = json.loads(cfg.read_text())
            data["auto_resume"] = "false"
            cfg.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ct.ContinuityError) as ctx:
                ct.read_config(repo)
            self.assertEqual(ctx.exception.code, "continuity_config_invalid")
            outcome = resume_watchdog.main(["--repo-root", str(repo)])
            self.assertEqual(outcome, 1)

    def test_watchdog_holds_no_authority_or_grants(self) -> None:
        watchdog_source = (SCRIPTS / "resume_watchdog.py").read_text(encoding="utf-8")
        continuity_source = (SCRIPTS / "cobbler_runtime" / "continuity.py").read_text(
            encoding="utf-8"
        )
        for source in (watchdog_source, continuity_source):
            self.assertNotIn("landing_authority", source)
            self.assertNotIn("driver_authorized", source)
            self.assertNotIn("--grant", source)


if __name__ == "__main__":
    unittest.main()
