from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_SCRIPT = REPO_ROOT / "scripts" / "preflight.sh"


class PreflightScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()

    def write_executable(self, name: str, body: str) -> Path:
        path = self.bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def write_fake_gh(self) -> None:
        self.write_executable(
            "gh",
            """#!/usr/bin/env bash
if [ "$1 $2" = "auth status" ]; then
  printf 'Logged in to github.com account test-user\\n'
  exit 0
fi
if [ "$1" = "api" ] && [ "$2" = "repos/aigorahub/elves/releases/latest" ]; then
  printf '{"tag_name":"v1.15.0","html_url":"https://example.com/v1.15.0"}\\n'
  exit 0
fi
printf 'unexpected gh invocation: %s\\n' "$*" >&2
exit 1
""",
        )

    def base_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("ELVES_") or key.startswith("GIT_"):
                env.pop(key)
        env.update(
            {
                "PATH": f"{self.bin_dir}:{env.get('PATH', '')}",
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_CACHE_HOME": str(self.root / "cache"),
                "TMPDIR": str(self.root),
                "GIT_CONFIG_NOSYSTEM": "1",
            }
        )
        return env

    def env(self) -> dict[str, str]:
        env = self.base_env()
        env.update(
            {
                "OPENAI_CODEX": "1",
                "CI": "true",
                "DEBIAN_FRONTEND": "noninteractive",
                "HOMEBREW_NO_AUTO_UPDATE": "1",
                "NEXT_TELEMETRY_DISABLED": "1",
                "NUXT_TELEMETRY_DISABLED": "1",
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "NPM_CONFIG_YES": "true",
            }
        )
        return env

    def run_git(self, cwd: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=self.base_env(),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def create_repo(self, with_remote: bool) -> Path:
        repo = self.root / "repo"
        repo.mkdir()
        self.run_git(repo, "init", "-b", "main")
        (repo / ".gitignore").write_text(".playwright-mcp/\ndocs/audit/\n.elves/\n")
        (repo / "README.md").write_text("test repo\n")
        self.run_git(repo, "add", ".")
        self.run_git(
            repo,
            "-c",
            "user.name=Elves Test",
            "-c",
            "user.email=elves@example.com",
            "commit",
            "-m",
            "initial",
        )
        if with_remote:
            remote = self.root / "remote.git"
            self.run_git(self.root, "init", "--bare", str(remote))
            self.run_git(repo, "remote", "add", "origin", str(remote))
            self.run_git(repo, "push", "-u", "origin", "main")
        return repo

    def run_preflight(
        self,
        repo: Path,
        *,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = self.env()
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["bash", str(PREFLIGHT_SCRIPT)],
            cwd=repo,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_preflight_args(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(PREFLIGHT_SCRIPT), *args],
            cwd=repo,
            env=self.env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_preflight_passes_in_minimal_launch_ready_repo(self) -> None:
        self.write_fake_gh()
        repo = self.create_repo(with_remote=True)

        result = self.run_preflight(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Remote origin:", result.stdout)
        self.assertIn("gh authenticated", result.stdout)
        self.assertIn("Can push to origin/main", result.stdout)
        self.assertIn("All known ephemeral directories are gitignored", result.stdout)
        self.assertIn("Sleep Prevention", result.stdout)
        self.assertIn("Project Type Detection", result.stdout)
        self.assertNotIn("Recommended dedicated worktree", result.stdout)

    def test_preflight_tolerates_gh_auth_status_as_wording(self) -> None:
        self.write_executable(
            "gh",
            """#!/usr/bin/env bash
if [ "$1 $2" = "auth status" ]; then
  printf 'Logged in to github.com as alt-user (keyring)\\n'
  exit 0
fi
if [ "$1" = "api" ] && [ "$2" = "repos/aigorahub/elves/releases/latest" ]; then
  printf '{"tag_name":"v1.15.0","html_url":"https://example.com/v1.15.0"}\\n'
  exit 0
fi
printf 'unexpected gh invocation: %s\\n' "$*" >&2
exit 1
""",
        )
        repo = self.create_repo(with_remote=True)

        result = self.run_preflight(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("gh authenticated as alt-user", result.stdout)
        self.assertIn("Push Access", result.stdout)
        self.assertIn("Sleep Prevention", result.stdout)

    def test_preflight_fails_when_origin_remote_is_missing(self) -> None:
        self.write_fake_gh()
        repo = self.create_repo(with_remote=False)

        result = self.run_preflight(repo)

        self.assertEqual(result.returncode, 1)
        self.assertIn("No git remote 'origin' found", result.stdout)
        self.assertIn("Elves Preflight Summary", result.stdout)

    def test_push_diagnostic_redacts_secret_and_credentialed_url(self) -> None:
        self.write_fake_gh()
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)
        push_secret = "push-diagnostic-secret-123456789"
        push_password = "push-password-123456"
        self.write_executable(
            "git",
            f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "push" ] && [ "${{2:-}}" = "--dry-run" ]; then
  printf '%s\n' 'fatal: unable to access https://push-user:{push_password}@example.test/repo token={push_secret}' >&2
  exit 1
fi
exec {shlex.quote(str(real_git))} "$@"
""",
        )
        repo = self.create_repo(with_remote=True)

        result = self.run_preflight(repo)

        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, combined)
        self.assertIn("Push dry-run failed", result.stdout)
        self.assertNotIn(push_secret, combined)
        self.assertNotIn(push_password, combined)
        self.assertIn("[REDACTED]", result.stdout)

    def test_preflight_reports_feature_branch_ahead_of_base_without_unpushed_label(self) -> None:
        self.write_fake_gh()
        repo = self.create_repo(with_remote=True)
        self.run_git(repo, "checkout", "-b", "feature/ahead")
        (repo / "feature.txt").write_text("feature branch work\n")
        self.run_git(repo, "add", "feature.txt")
        self.run_git(
            repo,
            "-c",
            "user.name=Elves Test",
            "-c",
            "user.email=elves@example.com",
            "commit",
            "-m",
            "feature work",
        )

        result = self.run_preflight(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "Branch has 1 commit(s) not in origin/main (expected on feature/PR branches)",
            result.stdout,
        )
        self.assertNotIn("(unpushed)", result.stdout)

    def test_preflight_rejects_malformed_plan_acceptance_before_launch(self) -> None:
        self.write_fake_gh()
        repo = self.create_repo(with_remote=True)
        plan = repo / "plan.md"
        plan.write_text(
            """\
# Plan

## Batch 0: Staging

**Acceptance criteria:**

- [ ] B0-A1 Missing separator.

## Master Acceptance

- [ ] [M-A1] Master criterion.
"""
        )

        result = self.run_preflight(
            repo,
            env_overrides={"ELVES_PLAN_PATH": str(plan)},
        )

        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, combined)
        self.assertIn("Plan/session Acceptance staging contract failed", result.stdout)
        self.assertIn("acceptance_row_syntax", result.stdout)
        self.assertIn("- [ ] B0-A1: <criterion>", result.stdout)
        self.assertIn("- [ ] [B0-A1] <criterion>", result.stdout)

    def test_preflight_rejects_session_criterion_drift_before_launch(self) -> None:
        self.write_fake_gh()
        repo = self.create_repo(with_remote=True)
        plan = repo / "plan.md"
        plan.write_text(
            """\
# Plan

## Batch 0: Staging

**Acceptance criteria:**

- [ ] [B0-A1] Authoritative criterion.

## Master Acceptance

- [ ] M-A1: Master criterion.
"""
        )
        session = repo / "session.json"
        session.write_text(
            """\
{
  "plan_path": "plan.md",
  "batches": [
    {
      "id": "B0",
      "status": "pending",
      "acceptance": [
        {
          "id": "B0-A1",
          "criterion": "Hand-copied criterion drifted.",
          "met": false,
          "evidence": ""
        }
      ]
    }
  ],
  "master_acceptance": [
    {
      "id": "M-A1",
      "criterion": "Master criterion.",
      "met": false,
      "evidence": ""
    }
  ]
}
"""
        )

        result = self.run_preflight(
            repo,
            env_overrides={"ELVES_SESSION_PATH": str(session)},
        )

        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, combined)
        self.assertIn("Plan/session Acceptance staging contract failed", result.stdout)
        self.assertIn("acceptance_criterion_mismatch", result.stdout)
        self.assertIn("B0-A1", result.stdout)
        self.assertIn("Authoritative criterion.", result.stdout)
        self.assertIn("Hand-copied criterion drifted.", result.stdout)

    def test_preflight_worktree_helper_dispatches_before_full_checklist(self) -> None:
        repo = self.create_repo(with_remote=True)

        result = self.run_preflight_args(
            repo,
            "--dry-run",
            "--create-worktree",
            "codex/wrapper-example",
            "--base",
            "origin/main",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Dry run: would create dedicated worktree", result.stdout)
        self.assertIn("branch: codex/wrapper-example", result.stdout)
        self.assertNotIn("GitHub CLI (gh)", result.stdout)
        self.assertFalse((self.root / "repo-wrapper-example").exists())

    def test_preflight_worktree_helper_can_create_via_wrapper(self) -> None:
        repo = self.create_repo(with_remote=True)

        result = self.run_preflight_args(
            repo,
            "--create-worktree",
            "codex/wrapper-create",
            "--base",
            "origin/main",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        created = self.root / "repo-wrapper-create"
        self.assertTrue(created.exists())
        self.assertIn("Created dedicated worktree", result.stdout)
        self.assertIn("branch: codex/wrapper-create", result.stdout)
        self.assertNotIn("GitHub CLI (gh)", result.stdout)
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=created,
            env=self.base_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        self.assertEqual(branch, "codex/wrapper-create")

    def test_preflight_gc_worktrees_flag_dispatches_report_before_full_checklist(self) -> None:
        repo = self.create_repo(with_remote=True)

        result = self.run_preflight_args(repo, "--gc-worktrees")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Worktree gc report", result.stdout)
        self.assertIn("mode: report (read-only; pass --apply to remove candidates)", result.stdout)
        self.assertNotIn("GitHub CLI (gh)", result.stdout)

    def test_preflight_does_not_run_browser_or_e2e_gates(self) -> None:
        self.write_fake_gh()
        repo = self.create_repo(with_remote=True)
        (repo / "package.json").write_text(
            '{"name":"preflight-browser","scripts":{"e2e":"npx playwright test"}}\n'
        )
        (repo / "playwright.config.ts").write_text("export default {};\n")
        (repo / "Makefile").write_text("e2e:\n\ttouch e2e.ran\n")
        self.run_git(repo, "add", "package.json", "playwright.config.ts", "Makefile")
        self.run_git(
            repo,
            "-c",
            "user.name=Elves Test",
            "-c",
            "user.email=elves@example.com",
            "commit",
            "-m",
            "add browser fixtures",
        )
        invocation_log = self.root / "browser-invocations.log"
        self.write_executable(
            "node",
            """#!/usr/bin/env bash
exit 1
""",
        )
        self.write_executable(
            "npx",
            f"""#!/usr/bin/env bash
printf 'npx %s\\n' "$*" >> {invocation_log}
exit 0
""",
        )
        self.write_executable(
            "npm",
            f"""#!/usr/bin/env bash
printf 'npm %s\\n' "$*" >> {invocation_log}
exit 0
""",
        )
        self.write_executable(
            "playwright",
            f"""#!/usr/bin/env bash
printf 'playwright %s\\n' "$*" >> {invocation_log}
exit 0
""",
        )

        result = self.run_preflight(repo)

        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertNotIn("npx playwright", combined)
        self.assertNotIn("npm run e2e", combined)
        self.assertNotIn("make e2e", combined)
        self.assertFalse((repo / "e2e.ran").exists())
        if invocation_log.exists():
            logged = invocation_log.read_text()
            self.assertNotIn("playwright", logged)
            self.assertNotIn("e2e", logged)
        source = PREFLIGHT_SCRIPT.read_text()
        self.assertNotIn("playwright_config_present", source)
        self.assertNotIn("npx playwright test", source)

    def test_preflight_gc_worktrees_apply_removes_merged_worktree_via_wrapper(self) -> None:
        repo = self.create_repo(with_remote=True)
        worktree = self.root / "repo-wrapper-merged"
        self.run_git(repo, "worktree", "add", "-b", "codex/wrapper-merged", str(worktree), "main")
        (worktree / "wrapper.txt").write_text("wrapper gc work\n")
        self.run_git(worktree, "add", "wrapper.txt")
        self.run_git(
            worktree,
            "-c",
            "user.name=Elves Test",
            "-c",
            "user.email=elves@example.com",
            "commit",
            "-m",
            "wrapper gc work",
        )
        self.run_git(worktree, "push", "-u", "origin", "codex/wrapper-merged")
        self.run_git(repo, "push", "origin", "codex/wrapper-merged:main")
        self.run_git(repo, "fetch", "origin")
        self.run_git(repo, "merge", "--ff-only", "origin/main")

        result = self.run_preflight_args(repo, "--gc-worktrees", "--apply")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("removed worktree", result.stdout)
        self.assertNotIn("GitHub CLI (gh)", result.stdout)
        self.assertFalse(worktree.exists())


if __name__ == "__main__":
    unittest.main()
