"""Tests for the observed-usage ledger (v2.24 B3)."""

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

from cobbler_runtime import confidence_sidecar as cs  # noqa: E402
from cobbler_runtime import usage_ledger as ul  # noqa: E402
from cobbler_runtime.host_profiles import HOST_PROFILES  # noqa: E402


class AggregateTests(unittest.TestCase):
    def test_totals_and_completeness_complete(self) -> None:
        block = ul.aggregate(
            [
                {"route": "claude@low", "payload": {"input_tokens": 100, "output_tokens": 40}},
                {"route": "codex@medium", "payload": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.25}},
            ]
        )
        self.assertEqual(block["completeness"], "complete")
        self.assertEqual(block["total"]["input_tokens"], 110)
        self.assertEqual(block["total"]["output_tokens"], 45)
        self.assertEqual(block["total"]["cost_usd"], 0.25)

    def test_unobserved_route_yields_partial_never_zero(self) -> None:
        block = ul.aggregate(
            [
                {"route": "claude@low", "payload": {"input_tokens": 100, "output_tokens": 40}},
                {"route": "grok@high", "payload": {}},
            ]
        )
        self.assertEqual(block["completeness"], "partial")
        grok = next(e for e in block["by_route"] if e["route"] == "grok@high")
        self.assertFalse(grok["observed"])
        self.assertNotIn("input_tokens", grok)

    def test_all_unobserved_is_literal_unobserved(self) -> None:
        block = ul.aggregate([{"route": "grok@high", "payload": {}}])
        self.assertEqual(block["completeness"], "unobserved")
        self.assertEqual(block["total"], "unobserved")
        empty = ul.aggregate([])
        self.assertEqual(empty["completeness"], "unobserved")
        self.assertEqual(empty["total"], "unobserved")

    def test_cache_read_fields_are_structurally_excluded(self) -> None:
        block = ul.aggregate(
            [
                {
                    "route": "claude@low",
                    "payload": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 999_999,
                        "cache_creation_input_tokens": 888_888,
                    },
                }
            ]
        )
        self.assertEqual(ul.ceiling_basis_tokens(block), 15)


class CeilingTests(unittest.TestCase):
    def _block(self) -> dict:
        return ul.aggregate(
            [{"route": "claude@low", "payload": {"input_tokens": 700, "output_tokens": 300}}]
        )

    def test_no_ceiling(self) -> None:
        result = ul.ceiling_check(self._block(), None)
        self.assertEqual(result["status"], "no_ceiling")

    def test_under_and_crossed_checkpoint_never_stop(self) -> None:
        under = ul.ceiling_check(self._block(), 2000)
        self.assertEqual(under["status"], "under")
        crossed = ul.ceiling_check(self._block(), 1000)
        self.assertEqual(crossed["status"], "crossed")
        self.assertEqual(crossed["classification"], "usage_ceiling_checkpoint")
        self.assertIn("never a stop", crossed["note"])
        self.assertNotIn("stop_required", crossed)

    def test_unobserved_basis_never_a_number(self) -> None:
        block = ul.aggregate([{"route": "grok@high", "payload": {}}])
        result = ul.ceiling_check(block, 1000)
        self.assertEqual(result["status"], "under")
        self.assertIsNone(result["basis_tokens"])

    def test_invalid_ceiling_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ul.ceiling_check(self._block(), 0)


class SessionAndRenderTests(unittest.TestCase):
    def test_write_session_block_is_additive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.json"
            session.write_text(
                json.dumps({"run_id": "r1", "branch": "b", "batches": []}, indent=2) + "\n"
            )
            block = ul.aggregate(
                [{"route": "claude@low", "payload": {"input_tokens": 1, "output_tokens": 2}}]
            )
            ul.write_session_block(session, block)
            data = json.loads(session.read_text())
            self.assertEqual(data["run_id"], "r1")
            self.assertEqual(data["branch"], "b")
            self.assertEqual(data["batches"], [])
            self.assertEqual(data["usage_observed"]["completeness"], "complete")

    def test_budget_lines_render_unobserved_literally(self) -> None:
        block = ul.aggregate([{"route": "grok@high", "payload": {}}])
        lines = ul.session_budget_lines(block, None)
        self.assertIn("unobserved", lines[0])
        self.assertIn("observed ≠ billed", lines[0])
        with_ceiling = ul.session_budget_lines(block, 500_000)
        self.assertIn("never a stop", with_ceiling[1])

    def test_panel_renders_data_and_omits_unobserved(self) -> None:
        observed = ul.aggregate(
            [{"route": "claude<script>", "payload": {"input_tokens": 3, "output_tokens": 4}}]
        )
        html_out = ul.report_panel_html(observed)
        self.assertIn("Observed usage", html_out)
        self.assertIn("claude&lt;script&gt;", html_out)
        self.assertNotIn("<script>", html_out)
        empty = ul.aggregate([])
        self.assertEqual(ul.report_panel_html(empty), "")


class CalibrationUsageFieldTests(unittest.TestCase):
    def test_optional_usage_field_roundtrip_and_absence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            cs.append_calibration_record(
                repo,
                run_id="r-old",
                host="claude",
                provider="native",
                model="m",
                effort="low",
                confidence="high",
                outcome="landed_clean",
            )
            cs.append_calibration_record(
                repo,
                run_id="r-new",
                host="claude",
                provider="native",
                model="m",
                effort="low",
                confidence="high",
                outcome="landed_clean",
                usage={"input_tokens": 10, "output_tokens": 5, "cache_read": 99, "bogus": -1},
            )
            rows = cs.load_calibration_records(repo)
            self.assertEqual(len(rows), 2)
            old = next(r for r in rows if r["run_id"] == "r-old")
            new = next(r for r in rows if r["run_id"] == "r-new")
            self.assertNotIn("usage", old)
            self.assertEqual(new["usage"], {"input_tokens": 10, "output_tokens": 5})


class HostProfileUsageCapabilityTests(unittest.TestCase):
    def test_every_profile_declares_reports_usage(self) -> None:
        for profile in HOST_PROFILES:
            self.assertTrue(profile.reports_usage, profile.host)


class RoutingUnaffectedTests(unittest.TestCase):
    def test_route_worker_identical_with_and_without_usage_block(self) -> None:
        def run_route(cwd: Path) -> str:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "cobbler_agents.py"),
                    "route-worker",
                    "--host",
                    "claude",
                    "--execution-reasoning",
                    "high",
                    "--review-risk",
                    "standard",
                    "--provider",
                    "native",
                    "--repo-root",
                    str(cwd),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            return completed.stdout.decode()

        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain"
            plain.mkdir()
            with_usage = Path(tmp) / "with-usage"
            with_usage.mkdir()
            session = with_usage / ".elves-session.json"
            session.write_text(json.dumps({"run_id": "r", "batches": []}))
            ul.write_session_block(
                session,
                ul.aggregate(
                    [{"route": "claude@low", "payload": {"input_tokens": 1_000_000}}]
                ),
            )
            self.assertEqual(run_route(plain), run_route(with_usage))


if __name__ == "__main__":
    unittest.main()
