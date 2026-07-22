"""Observation, candidate synthesis, promotion, and exact-HEAD waiver tests."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CLI = SCRIPTS / "landing_profile.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.landing_profile import evaluate_landing_profile  # noqa: E402
from cobbler_runtime.landing_profile_learn import (  # noqa: E402
    list_candidates,
    observe_landing,
    promote_candidate,
    propose_candidates,
    set_exact_head_waiver,
)


def always() -> dict[str, str]:
    return {"kind": "always"}


def path_check(
    *,
    check_id: str = "path-check",
    severity: str = "blocking",
    when: dict | None = None,
    paths: list[str] | None = None,
) -> dict:
    return {
        "id": check_id,
        "kind": "path_touched",
        "severity": severity,
        "when": when or always(),
        "paths": paths or ["scripts/**"],
    }


def profile(*checks: dict) -> dict:
    return {"schema_version": 1, "checks": list(checks)}


class LandingProfileLearningTests(unittest.TestCase):
    def _run(self, root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()

    def _repo(
        self,
        raw: str,
        *,
        raw_profile: dict | None = None,
        files: dict[str, str] | None = None,
    ) -> tuple[Path, str]:
        root = Path(raw)
        self._run(root, "init", "-q", "-b", "feature")
        self._run(root, "config", "user.email", "tests@example.invalid")
        self._run(root, "config", "user.name", "Elves Tests")
        (root / "README.md").write_text("base\n", encoding="utf-8")
        self._run(root, "add", "README.md")
        self._run(root, "commit", "-qm", "base")
        base = self._run(root, "rev-parse", "HEAD")

        if raw_profile is not None:
            profile_path = root / ".elves" / "landing-profile.json"
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.write_text(
                json.dumps(raw_profile, indent=2) + "\n",
                encoding="utf-8",
            )
            self._run(root, "add", ".elves/landing-profile.json")

        for relative, content in (files or {"scripts/feature.py": "changed\n"}).items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self._run(root, "add", relative)

        self._run(root, "commit", "-qm", "feature")
        return root, base

    def test_observe_records_runtime_packet_without_touching_tracked_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, files={"scripts/a.py": "a\n", "docs/x.md": "x\n"})
            before = list((root / ".elves").rglob("*")) if (root / ".elves").exists() else []
            result = observe_landing(
                root,
                base_ref=base,
                note="landed with docs",
                propose_id="docs-with-scripts",
                propose_when=["scripts/**"],
                propose_paths=["docs/**"],
                propose_severity="advisory",
            )

            self.assertTrue(result.green)
            self.assertEqual(result.status, "recorded")
            observation_path = root / ".elves/runtime/landing-profile/observations.jsonl"
            self.assertTrue(observation_path.is_file())
            self.assertFalse((root / ".elves/landing-profile.json").exists())
            line = observation_path.read_text(encoding="utf-8").strip()
            packet = json.loads(line)
            self.assertEqual(packet["note"], "landed with docs")
            self.assertEqual(packet["explicit_proposal"]["id"], "docs-with-scripts")
            self.assertIn("scripts/a.py", packet["changed_paths"])
            # No unexpected tracked profile write from observe.
            self.assertEqual(
                [path for path in (root / ".elves").rglob("*") if path.is_file() and "runtime" not in path.parts],
                before if before else [],
            )

    def test_propose_and_promote_write_tracked_profile_only_on_promote(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(
                raw,
                raw_profile=profile(path_check(check_id="existing", paths=["README.md"])),
                files={"scripts/a.py": "a\n", "docs/x.md": "x\n"},
            )
            observe_landing(
                root,
                base_ref=base,
                propose_id="docs-with-scripts",
                propose_when=["scripts/**"],
                propose_paths=["docs/**"],
                propose_severity="advisory",
            )
            proposed = propose_candidates(root, min_support=1)
            self.assertTrue(proposed.green)
            listed = list_candidates(root)
            ids = {item["id"] for item in listed.payload["candidates"]}
            self.assertIn("docs-with-scripts", ids)

            # Propose must not rewrite tracked profile.
            tracked_before = (root / ".elves/landing-profile.json").read_text(encoding="utf-8")
            propose_candidates(root, min_support=1)
            self.assertEqual(
                (root / ".elves/landing-profile.json").read_text(encoding="utf-8"),
                tracked_before,
            )

            promoted = promote_candidate(root, check_id="docs-with-scripts", severity="blocking")
            self.assertTrue(promoted.green)
            tracked = json.loads((root / ".elves/landing-profile.json").read_text(encoding="utf-8"))
            self.assertEqual(tracked["schema_version"], 1)
            ids = [check["id"] for check in tracked["checks"]]
            self.assertIn("docs-with-scripts", ids)
            self.assertIn("existing", ids)
            match = next(check for check in tracked["checks"] if check["id"] == "docs-with-scripts")
            self.assertEqual(match["severity"], "blocking")
            self.assertEqual(match["kind"], "path_touched")

            # Candidate removed after promote.
            remaining = list_candidates(root)
            self.assertNotIn(
                "docs-with-scripts",
                {item["id"] for item in remaining.payload["candidates"]},
            )

            # Duplicate promote fails closed.
            again = promote_candidate(root, check_id="docs-with-scripts")
            self.assertFalse(again.green)

    def test_cooccurrence_requires_min_support_and_never_executable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(
                raw,
                files={"scripts/a.py": "a\n", "docs/x.md": "x\n"},
            )
            observe_landing(root, base_ref=base)
            # One observation is not enough for default min_support=2.
            weak = propose_candidates(root, min_support=2)
            self.assertTrue(weak.green)
            self.assertEqual(weak.payload["candidate_count"], 0)

            # Second observation with same co-change prefixes.
            (root / "scripts/b.py").write_text("b\n", encoding="utf-8")
            (root / "docs/y.md").write_text("y\n", encoding="utf-8")
            self._run(root, "add", "scripts/b.py", "docs/y.md")
            self._run(root, "commit", "-qm", "second")
            observe_landing(root, base_ref=base)
            strong = propose_candidates(root, min_support=2)
            self.assertTrue(strong.green)
            self.assertGreaterEqual(strong.payload["candidate_count"], 1)
            for candidate in strong.payload["candidates"]:
                self.assertEqual(candidate["kind"], "path_touched")
                self.assertNotIn("argv", candidate)
                self.assertNotIn("command", candidate)
                self.assertEqual(candidate["source"], "cooccurrence")

    def test_exact_head_waiver_clears_blocking_failure_and_binds_digest(self) -> None:
        raw_profile = profile(
            path_check(
                check_id="docs-required",
                severity="blocking",
                when={"kind": "any_path_glob", "patterns": ["scripts/**"]},
                paths=["docs/**"],
            )
        )
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(
                raw,
                raw_profile=raw_profile,
                files={"scripts/only.py": "x\n"},
            )
            failed = evaluate_landing_profile(root, base_ref=base)
            self.assertFalse(failed.green)
            self.assertEqual(failed.checks[0].status, "failed")
            failed_digest = failed.digest

            waived = set_exact_head_waiver(
                root,
                check_id="docs-required",
                reason="temporary docs lag on this head only",
                base_ref=base,
            )
            self.assertTrue(waived.green)
            result = evaluate_landing_profile(root, base_ref=base)
            self.assertTrue(result.green)
            self.assertEqual(result.checks[0].status, "waived")
            self.assertEqual(result.checks[0].code, "exact_head_waiver")
            self.assertNotEqual(result.digest, failed_digest)

            # Moving HEAD invalidates the waiver.
            (root / "scripts/more.py").write_text("y\n", encoding="utf-8")
            self._run(root, "add", "scripts/more.py")
            self._run(root, "commit", "-qm", "move-head")
            moved = evaluate_landing_profile(root, base_ref=base)
            self.assertFalse(moved.green)
            self.assertEqual(moved.checks[0].status, "failed")

    def test_cli_observe_propose_promote_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(
                raw,
                files={"scripts/a.py": "a\n", "docs/x.md": "x\n"},
            )
            observe = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "observe",
                    "--repo-root",
                    str(root),
                    "--base",
                    base,
                    "--propose-id",
                    "docs-with-scripts",
                    "--propose-when",
                    "scripts/**",
                    "--propose-paths",
                    "docs/**",
                    "--json",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(observe.returncode, 0, observe.stderr)
            propose = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "propose",
                    "--repo-root",
                    str(root),
                    "--min-support",
                    "1",
                    "--json",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(propose.returncode, 0, propose.stderr)
            promote = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "promote",
                    "--repo-root",
                    str(root),
                    "--id",
                    "docs-with-scripts",
                    "--severity",
                    "advisory",
                    "--json",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(promote.returncode, 0, promote.stderr)
            tracked = json.loads((root / ".elves/landing-profile.json").read_text(encoding="utf-8"))
            self.assertEqual(tracked["checks"][0]["id"], "docs-with-scripts")


if __name__ == "__main__":
    unittest.main()
