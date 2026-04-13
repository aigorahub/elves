from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
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


class InstallDoctorCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.install_doctor = load_install_doctor_module()

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
