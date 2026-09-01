from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "install_doctor.py"


def load_install_doctor_module():
    spec = importlib.util.spec_from_file_location("install_doctor_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load install_doctor module for tests")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_wsl_runner(
    *,
    names: bytes | str,
    verbose: bytes | str = b"",
    quiet_returncode: int = 0,
    verbose_returncode: int = 0,
) -> mock.Mock:
    runner = mock.Mock()

    def run(argv, **_kwargs):
        if argv[-1] == "--quiet":
            return SimpleNamespace(
                returncode=quiet_returncode,
                stdout=names,
                stderr=b"quiet failure" if quiet_returncode else b"",
            )
        if argv[-1] == "--verbose":
            return SimpleNamespace(
                returncode=verbose_returncode,
                stdout=verbose,
                stderr=b"verbose failure" if verbose_returncode else b"",
            )
        raise AssertionError(f"unexpected WSL query: {argv}")

    runner.side_effect = run
    return runner


class InstallDoctorCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.install_doctor = load_install_doctor_module()

    def write_skill(self, root: Path, version: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        (root / "SKILL.md").write_text(f'---\nversion: "{version}"\n---\n')
        return root

    def test_fetch_latest_release_refreshes_stale_cache_when_active_version_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "install-doctor.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "checked_at": datetime(2026, 4, 12, 18, 0, tzinfo=timezone.utc).isoformat(),
                        "latest_version": "1.6.1",
                        "latest_url": "https://example.com/v1.6.1",
                        "source": "gh-release",
                    }
                )
            )
            gh_fetch = mock.Mock(
                return_value={
                    "tag_name": "v1.7.0",
                    "html_url": "https://github.com/aigorahub/elves/releases/tag/v1.7.0",
                }
            )

            with mock.patch.object(self.install_doctor, "CACHE_PATH", cache_path), mock.patch.object(
                self.install_doctor, "fetch_json_with_gh", gh_fetch
            ), mock.patch.object(self.install_doctor, "fetch_json_with_http", return_value=None), mock.patch.object(
                self.install_doctor, "datetime"
            ) as fake_datetime:
                fake_datetime.now.return_value = datetime(2026, 4, 12, 20, 30, tzinfo=timezone.utc)
                fake_datetime.fromisoformat.side_effect = datetime.fromisoformat
                latest_release = self.install_doctor.fetch_latest_release(24, minimum_version="1.7.0")

            self.assertEqual(latest_release["latest_version"], "1.7.0")
            gh_fetch.assert_called_once_with("repos/aigorahub/elves/releases/latest")

    def test_version_comparison_handles_v_prefix_and_numeric_segments(self) -> None:
        self.assertTrue(self.install_doctor.version_is_newer("v1.10.0", "1.9.9"))
        self.assertFalse(self.install_doctor.version_is_newer("v1.9.9", "1.10.0"))
        self.assertFalse(self.install_doctor.version_is_newer("1.10.0", "v1.10.0"))
        self.assertFalse(self.install_doctor.version_is_newer("invalid", "1.0.0"))
        self.assertFalse(self.install_doctor.version_is_newer("v1.2.beta", "1.2.0"))
        self.assertFalse(self.install_doctor.version_is_newer("1.2.1", "invalid"))

    def test_read_version_returns_frontmatter_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self.write_skill(Path(tmpdir) / "skill", "1.15.0")

            self.assertEqual(self.install_doctor.read_version(root), "1.15.0")

    def test_discover_installs_finds_global_project_local_and_legacy_installs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            active = self.write_skill(root / "repo", "1.15.0")
            claude_global = self.write_skill(root / "home" / ".claude" / "skills" / "elves", "1.14.0")
            codex_global = self.write_skill(root / "home" / ".codex" / "skills" / "elves", "1.15.0")
            codex_local = self.write_skill(root / "project" / ".codex" / "skills" / "elves", "1.13.0")
            codex_legacy = self.write_skill(root / "home" / ".agents" / "skills" / "elves", "1.12.0")
            codex_legacy_local = self.write_skill(
                root / "project" / ".agents" / "skills" / "elves",
                "1.11.0",
            )
            cwd = root / "project" / "src"
            cwd.mkdir(parents=True)

            with mock.patch.object(self.install_doctor, "ACTIVE_ROOT", active), mock.patch.object(
                self.install_doctor,
                "GLOBAL_INSTALLS",
                {"claude": claude_global, "codex": codex_global},
            ), mock.patch.object(
                self.install_doctor,
                "LOCAL_INSTALL_SUFFIXES",
                {
                    "claude": Path(".claude") / "skills" / "elves",
                    "codex": Path(".codex") / "skills" / "elves",
                },
            ), mock.patch.object(
                self.install_doctor,
                "LEGACY_INSTALLS",
                {
                    "codex": {
                        "global": codex_legacy,
                        "local_suffix": Path(".agents") / "skills" / "elves",
                    }
                },
            ):
                installs, active_install = self.install_doctor.discover_installs(cwd)

            observed = {
                (
                    install.platform,
                    install.scope,
                    install.path.resolve(),
                    install.version,
                    install.active,
                )
                for install in installs
            }
            expected = {
                ("unknown", "repo-checkout", active.resolve(), "1.15.0", True),
                ("claude", "global", claude_global.resolve(), "1.14.0", False),
                ("codex", "global", codex_global.resolve(), "1.15.0", False),
                ("codex", "project-local", codex_local.resolve(), "1.13.0", False),
                ("codex", "legacy-global", codex_legacy.resolve(), "1.12.0", False),
                (
                    "codex",
                    "legacy-project-local",
                    codex_legacy_local.resolve(),
                    "1.11.0",
                    False,
                ),
            }
            self.assertEqual(active_install.path, active)
            self.assertEqual(observed, expected)

    def test_windows_install_paths_and_omp_are_classified(self) -> None:
        self.assertEqual(
            self.install_doctor.infer_platform(
                Path(r"C:\Users\alice\.omp\agent\skills\elves")
            ),
            "omp",
        )
        self.assertEqual(
            self.install_doctor.infer_platform(
                Path(r"C:\work\repo\.codex\skills\elves")
            ),
            "codex",
        )
        with mock.patch.object(
            self.install_doctor,
            "GLOBAL_INSTALLS",
            {"omp": Path(r"C:\Users\alice\.omp\agent\skills\elves")},
        ):
            self.assertEqual(
                self.install_doctor.infer_scope(
                    Path(r"C:\Users\alice\.omp\agent\skills\elves")
                ),
                "global",
            )
        self.assertIn("omp", self.install_doctor.GLOBAL_INSTALLS)
        self.assertIn("omp", self.install_doctor.LOCAL_INSTALL_SUFFIXES)

    def test_native_windows_without_distribution_reports_install_command(self) -> None:
        runner = make_wsl_runner(names=b"")
        support = self.install_doctor.build_host_support(
            platform_name="win32",
            environ={},
            kernel_release="10.0.26100",
            wsl_runner=runner,
            probe_sandbox=False,
        )
        self.assertEqual(support["status"], "needs_wsl_distribution")
        self.assertFalse(support["supported"])
        self.assertIn("wsl --install -d Ubuntu", support["remediation"])
        runner.assert_called_once_with(
            ["wsl.exe", "--list", "--quiet"],
            capture_output=True,
            check=False,
            timeout=10,
        )

    def test_native_windows_with_wsl2_directs_execution_inside_distro(self) -> None:
        runner = make_wsl_runner(
            names="Ubuntu\r\n".encode("utf-16-le"),
            verbose=(
                "  NAME      STATE           VERSION\r\n"
                "* Ubuntu    Stopped         2\r\n"
            ).encode("utf-16-le"),
        )
        support = self.install_doctor.build_host_support(
            platform_name="win32",
            environ={},
            kernel_release="10.0.26100",
            wsl_runner=runner,
            probe_sandbox=False,
        )
        self.assertEqual(support["status"], "use_wsl2")
        self.assertFalse(support["supported"])
        self.assertEqual(support["wsl"]["distribution"], "Ubuntu")
        self.assertEqual(support["wsl"]["version"], 2)
        self.assertIn("wsl -d Ubuntu", support["remediation"])
        self.assertIn("inside", support["summary"].lower())

    def test_native_windows_wsl1_reports_conversion_command(self) -> None:
        runner = make_wsl_runner(
            names=b"Ubuntu\r\n",
            verbose=b"  NAME      STATE           VERSION\r\n* Ubuntu    Stopped         1\r\n",
        )
        support = self.install_doctor.build_host_support(
            platform_name="win32",
            environ={},
            kernel_release="10.0.26100",
            wsl_runner=runner,
            probe_sandbox=False,
        )
        self.assertEqual(support["status"], "needs_wsl2_conversion")
        self.assertFalse(support["supported"])
        self.assertIn("wsl --set-version Ubuntu 2", support["remediation"])

    def test_native_windows_unknown_wsl_generation_is_not_supported(self) -> None:
        runner = make_wsl_runner(
            names=b"Ubuntu\r\n",
            verbose=b"  NAME      STATE           VERSION\r\n  Ubuntu    Stopped         ?\r\n",
        )
        support = self.install_doctor.build_host_support(
            platform_name="win32",
            environ={},
            kernel_release="10.0.26100",
            wsl_runner=runner,
            probe_sandbox=False,
        )
        self.assertEqual(support["status"], "wsl_generation_unknown")
        self.assertFalse(support["supported"])
        self.assertIn("wsl --list --verbose", support["remediation"])

    def test_native_windows_uses_default_distro_with_localized_state(self) -> None:
        runner = make_wsl_runner(
            names=b"Ubuntu\r\nDebian\r\n",
            verbose=(
                "  NAME      ZUSTAND       VERSION\r\n"
                "  Ubuntu    Beendet       2\r\n"
                "* Debian    Angehalten    2\r\n"
            ),
        )
        support = self.install_doctor.build_host_support(
            platform_name="win32",
            environ={},
            kernel_release="10.0.26100",
            wsl_runner=runner,
            probe_sandbox=False,
        )
        self.assertEqual(support["status"], "use_wsl2")
        self.assertEqual(support["wsl"]["distribution"], "Debian")
        self.assertTrue(support["wsl"]["distributions"][1]["default"])

    def test_native_windows_ignores_docker_desktop_as_an_elves_host(self) -> None:
        runner = make_wsl_runner(
            names=b"docker-desktop\r\n",
            verbose=b"* docker-desktop    Stopped    2\r\n",
        )
        support = self.install_doctor.build_host_support(
            platform_name="win32",
            environ={},
            kernel_release="10.0.26100",
            wsl_runner=runner,
            probe_sandbox=False,
        )
        self.assertEqual(support["status"], "needs_wsl_distribution")
        self.assertEqual(support["remediation"], "wsl --install -d Ubuntu")
        self.assertTrue(support["wsl"]["distributions"][0]["managed"])
        self.assertIn("Docker Desktop", support["summary"])

    def test_native_windows_reports_failed_wsl_probe_without_claiming_no_distro(self) -> None:
        runner = make_wsl_runner(names=b"", quiet_returncode=5)
        support = self.install_doctor.build_host_support(
            platform_name="win32",
            environ={},
            kernel_release="10.0.26100",
            wsl_runner=runner,
            probe_sandbox=False,
        )
        self.assertEqual(support["status"], "wsl_probe_failed")
        self.assertNotIn("wsl --install", support["remediation"])
        self.assertIn("status 5", support["summary"])

    def test_native_windows_quotes_distribution_names_for_powershell(self) -> None:
        wsl2_runner = make_wsl_runner(
            names=b"My Ubuntu\r\n",
            verbose=b"* My Ubuntu    Stopped    2\r\n",
        )
        wsl1_runner = make_wsl_runner(
            names=b"My Ubuntu\r\n",
            verbose=b"* My Ubuntu    Stopped    1\r\n",
        )
        wsl2 = self.install_doctor.build_host_support(
            platform_name="win32",
            environ={},
            kernel_release="10.0.26100",
            wsl_runner=wsl2_runner,
            probe_sandbox=False,
        )
        wsl1 = self.install_doctor.build_host_support(
            platform_name="win32",
            environ={},
            kernel_release="10.0.26100",
            wsl_runner=wsl1_runner,
            probe_sandbox=False,
        )
        self.assertEqual(wsl2["remediation"], "wsl -d 'My Ubuntu'")
        self.assertEqual(wsl1["remediation"], "wsl --set-version 'My Ubuntu' 2")

    def test_inside_wsl2_separates_shortcut_and_council_capabilities(self) -> None:
        backend = SimpleNamespace(name="bwrap", executable=Path("/usr/bin/bwrap"))
        support = self.install_doctor.build_host_support(
            platform_name="linux",
            environ={"WSL_DISTRO_NAME": "Ubuntu"},
            kernel_release="5.15.146.1-microsoft-standard-WSL2",
            sandbox_resolver=lambda: backend,
        )
        self.assertEqual(support["status"], "supported")
        self.assertTrue(support["supported"])
        self.assertEqual(support["wsl"]["version"], 2)
        self.assertTrue(support["capabilities"]["local_provider_shortcuts"]["ready"])
        self.assertEqual(
            support["capabilities"]["local_provider_shortcuts"]["backend"],
            "bwrap",
        )
        self.assertFalse(support["capabilities"]["external_council"]["ready"])
        self.assertEqual(
            support["capabilities"]["external_council"]["reason_code"],
            "isolation_recursive_containment_unavailable",
        )

    def test_older_microsoft_standard_kernel_is_confirmed_wsl2(self) -> None:
        support = self.install_doctor.build_host_support(
            platform_name="linux",
            environ={"WSL_DISTRO_NAME": "Ubuntu"},
            kernel_release="4.19.128-microsoft-standard",
            sandbox_resolver=lambda: None,
        )
        self.assertEqual(support["status"], "supported")
        self.assertEqual(support["wsl"]["version"], 2)

    def test_inside_wsl1_and_unknown_generation_are_not_supported(self) -> None:
        wsl1 = self.install_doctor.build_host_support(
            platform_name="linux",
            environ={"WSL_DISTRO_NAME": "Ubuntu"},
            kernel_release="4.4.0-19041-Microsoft",
            probe_sandbox=False,
        )
        unknown = self.install_doctor.build_host_support(
            platform_name="linux",
            environ={"WSL_DISTRO_NAME": "Ubuntu"},
            kernel_release="custom-kernel",
            probe_sandbox=False,
        )
        self.assertEqual(wsl1["status"], "needs_wsl2_conversion")
        self.assertIn("wsl --set-version Ubuntu 2", wsl1["remediation"])
        self.assertEqual(unknown["status"], "wsl_generation_unknown")
        self.assertFalse(unknown["supported"])

    def test_inside_wsl1_quotes_distribution_name_for_powershell(self) -> None:
        support = self.install_doctor.build_host_support(
            platform_name="linux",
            environ={"WSL_DISTRO_NAME": "My Ubuntu"},
            kernel_release="4.4.0-19041-Microsoft",
            probe_sandbox=False,
        )
        self.assertEqual(
            support["remediation"],
            "wsl --set-version 'My Ubuntu' 2",
        )

    def test_non_windows_platform_does_not_report_a_windows_boundary_reason(self) -> None:
        support = self.install_doctor.build_host_support(
            platform_name="freebsd14",
            environ={},
            kernel_release="14.0",
            probe_sandbox=False,
        )
        reason = support["capabilities"]["external_council"]["reason"]
        self.assertIn("freebsd14", reason)
        self.assertNotIn("Windows", reason)

    def test_sandbox_validation_failure_becomes_unavailable_capability(self) -> None:
        from cobbler_runtime.schema import ValidationIssue

        def fail_probe():
            raise ValidationIssue("probe_failed", "fixture")

        support = self.install_doctor.build_host_support(
            platform_name="linux",
            environ={},
            kernel_release="6.8.0",
            sandbox_resolver=fail_probe,
        )
        capability = support["capabilities"]["local_provider_shortcuts"]
        self.assertFalse(capability["ready"])
        self.assertEqual(capability["reason"], "The filesystem-sandbox probe failed.")

    def test_doctor_human_and_json_outputs_include_windows_support_state(self) -> None:
        support = {
            "status": "needs_wsl_distribution",
            "supported": False,
            "summary": "Native Win32 is not supported. Install an Ubuntu WSL2 distribution.",
            "wsl": {"distribution": None, "version": None, "distributions": []},
            "remediation": "wsl --install -d Ubuntu",
            "capabilities": {
                "local_provider_shortcuts": {
                    "ready": False,
                    "backend": None,
                    "reason": "Enter WSL2 first.",
                },
                "external_council": {
                    "ready": False,
                    "reason_code": "isolation_recursive_containment_unavailable",
                    "reason": "Native Windows has no qualified boundary.",
                },
            },
        }
        active = self.install_doctor.Install(
            platform="unknown",
            scope="repo-checkout",
            path=Path("/repo"),
            version="2.35.0",
            active=True,
        )
        rendered = self.install_doctor.render_doctor(
            [active],
            {"latest_version": "2.35.0", "latest_url": None},
            [],
            support,
        )
        self.assertIn("Status: needs_wsl_distribution", rendered)
        self.assertIn("Next command: wsl --install -d Ubuntu", rendered)

        args = SimpleNamespace(
            startup=False,
            doctor=True,
            cache_hours=24,
            json=True,
        )
        stdout = io.StringIO()
        with mock.patch.object(self.install_doctor, "parse_args", return_value=args), mock.patch.object(
            self.install_doctor,
            "discover_installs",
            return_value=([active], active),
        ), mock.patch.object(
            self.install_doctor,
            "fetch_latest_release",
            return_value={"latest_version": "2.35.0", "latest_url": None},
        ), mock.patch.object(
            self.install_doctor,
            "build_host_support",
            return_value=support,
        ), redirect_stdout(stdout):
            exit_code = self.install_doctor.main()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["host_support"]["status"], "needs_wsl_distribution")
        self.assertEqual(
            payload["host_support"]["remediation"],
            "wsl --install -d Ubuntu",
        )

    def test_build_recommendations_reports_updates_mismatch_legacy_and_sync_hint(self) -> None:
        active = self.install_doctor.Install(
            platform="unknown",
            scope="repo-checkout",
            path=Path("/repo"),
            version="1.15.0",
            active=True,
        )
        installs = [
            active,
            self.install_doctor.Install(
                platform="codex",
                scope="global",
                path=Path("/home/.codex/skills/elves"),
                version="1.15.0",
            ),
            self.install_doctor.Install(
                platform="codex",
                scope="project-local",
                path=Path("/project/.codex/skills/elves"),
                version="1.14.0",
            ),
            self.install_doctor.Install(
                platform="codex",
                scope="legacy-global",
                path=Path("/home/.agents/skills/elves"),
                version="1.12.0",
            ),
        ]

        notes = self.install_doctor.build_recommendations(
            installs,
            active,
            {
                "latest_version": "1.16.0",
                "latest_url": "https://github.com/aigorahub/elves/releases/tag/v1.16.0",
            },
        )

        self.assertTrue(any("Update available: v1.15.0 -> v1.16.0" in note for note in notes))
        self.assertTrue(any("project-local install v1.14.0" in note for note in notes))
        self.assertTrue(any("Legacy codex install detected" in note for note in notes))
        self.assertTrue(any("sync_installed_skills.py --apply" in note for note in notes))

    def test_fetch_latest_release_reuses_cache_when_it_matches_active_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "install-doctor.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "checked_at": datetime(2026, 4, 12, 18, 0, tzinfo=timezone.utc).isoformat(),
                        "latest_version": "1.7.0",
                        "latest_url": "https://example.com/v1.7.0",
                        "source": "gh-release",
                    }
                )
            )
            gh_fetch = mock.Mock()

            with mock.patch.object(self.install_doctor, "CACHE_PATH", cache_path), mock.patch.object(
                self.install_doctor, "fetch_json_with_gh", gh_fetch
            ), mock.patch.object(self.install_doctor, "fetch_json_with_http", return_value=None), mock.patch.object(
                self.install_doctor, "datetime"
            ) as fake_datetime:
                fake_datetime.now.return_value = datetime(2026, 4, 12, 20, 30, tzinfo=timezone.utc)
                fake_datetime.fromisoformat.side_effect = datetime.fromisoformat
                latest_release = self.install_doctor.fetch_latest_release(24, minimum_version="1.7.0")

            self.assertEqual(latest_release["latest_version"], "1.7.0")
            gh_fetch.assert_not_called()

    def test_fetch_latest_release_reuses_recent_ahead_cache_without_refetching(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "install-doctor.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "checked_at": datetime(2026, 4, 12, 20, 0, tzinfo=timezone.utc).isoformat(),
                        "latest_version": "1.6.1",
                        "latest_url": "https://example.com/v1.6.1",
                        "source": "gh-release",
                    }
                )
            )
            gh_fetch = mock.Mock()

            with mock.patch.object(self.install_doctor, "CACHE_PATH", cache_path), mock.patch.object(
                self.install_doctor, "fetch_json_with_gh", gh_fetch
            ), mock.patch.object(self.install_doctor, "fetch_json_with_http", return_value=None), mock.patch.object(
                self.install_doctor, "datetime"
            ) as fake_datetime:
                fake_datetime.now.return_value = datetime(2026, 4, 12, 20, 30, tzinfo=timezone.utc)
                fake_datetime.fromisoformat.side_effect = datetime.fromisoformat
                latest_release = self.install_doctor.fetch_latest_release(24, minimum_version="1.7.0")

            self.assertEqual(latest_release["latest_version"], "1.6.1")
            gh_fetch.assert_not_called()

    def test_fetch_latest_release_refreshes_stale_unavailable_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "install-doctor.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "checked_at": datetime(2026, 4, 12, 18, 0, tzinfo=timezone.utc).isoformat(),
                        "latest_version": None,
                        "latest_url": None,
                        "source": "unavailable",
                    }
                )
            )
            gh_fetch = mock.Mock(
                return_value={
                    "tag_name": "v1.7.0",
                    "html_url": "https://github.com/aigorahub/elves/releases/tag/v1.7.0",
                }
            )

            with mock.patch.object(self.install_doctor, "CACHE_PATH", cache_path), mock.patch.object(
                self.install_doctor, "fetch_json_with_gh", gh_fetch
            ), mock.patch.object(self.install_doctor, "fetch_json_with_http", return_value=None), mock.patch.object(
                self.install_doctor, "datetime"
            ) as fake_datetime:
                fake_datetime.now.return_value = datetime(2026, 4, 12, 20, 30, tzinfo=timezone.utc)
                fake_datetime.fromisoformat.side_effect = datetime.fromisoformat
                latest_release = self.install_doctor.fetch_latest_release(24, minimum_version="1.7.0")

            self.assertEqual(latest_release["latest_version"], "1.7.0")
            gh_fetch.assert_called_once_with("repos/aigorahub/elves/releases/latest")


if __name__ == "__main__":
    unittest.main()
