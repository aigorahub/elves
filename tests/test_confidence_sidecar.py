"""Tests for native confidence sidecar and calibration store."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cobbler_runtime import confidence_sidecar as cs


class ConfidenceSidecarTests(unittest.TestCase):
    def test_parse_and_roundtrip_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            parsed = cs.parse_confidence_trailer(
                "msg\n\nConfidence: medium — unsure: bounds in queue.py; importer\n"
            )
            self.assertIsNotNone(parsed)
            assert parsed is not None
            path = cs.write_confidence_sidecar(repo, key="B3", payload=parsed)
            self.assertTrue(path.is_file())
            loaded = cs.read_confidence_sidecar(repo, "B3")
            self.assertEqual(loaded["confidence"], "medium")
            self.assertEqual(loaded["authority"], "triage_only")
            self.assertEqual(len(loaded["unsure_about"]), 2)

    def test_calibration_append_and_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            cs.append_calibration_record(
                repo,
                run_id="run-1",
                host="claude",
                provider="native",
                model="opus",
                effort="high",
                confidence="high",
                outcome="terminal_blocker_product",
            )
            cs.append_calibration_record(
                repo,
                run_id="run-2",
                host="claude",
                provider="native",
                model="opus",
                effort="high",
                confidence=None,
                outcome="landed_clean",
            )
            rows = cs.load_calibration_records(repo)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["outcome"], "terminal_blocker_product")
            self.assertEqual(rows[1]["confidence"], "missing")
            with self.assertRaises(ValueError):
                cs.append_calibration_record(
                    repo,
                    run_id="x",
                    host="h",
                    provider="p",
                    model="m",
                    effort="e",
                    confidence="high",
                    outcome="not-a-category",
                )

    def test_calibration_enforces_record_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with mock.patch.object(cs, "MAX_CALIBRATION_RECORDS", 3):
                with mock.patch.object(cs, "MAX_CALIBRATION_FILE_BYTES", 10**6):
                    for i in range(5):
                        cs.append_calibration_record(
                            repo,
                            run_id=f"run-{i}",
                            host="claude",
                            provider="native",
                            model="m",
                            effort="high",
                            confidence="low",
                            outcome="landed_clean",
                        )
                    rows = cs.load_calibration_records(repo)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["run_id"], "run-2")
            self.assertEqual(rows[-1]["run_id"], "run-4")

    def test_calibration_skips_malformed_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            path = cs.calibration_path(repo)
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            path.write_text(
                '{"schema_version":1,"run_id":"a","outcome":"landed_clean",'
                '"confidence":"high","host":"h","provider":"p","model":"m",'
                '"effort":"e","ts":"t"}\n'
                "not-json\n",
                encoding="utf-8",
            )
            cs.append_calibration_record(
                repo,
                run_id="b",
                host="h",
                provider="p",
                model="m",
                effort="e",
                confidence="medium",
                outcome="abandoned",
            )
            rows = cs.load_calibration_records(repo)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["run_id"], "a")
            self.assertEqual(rows[1]["run_id"], "b")

    def test_record_terminal_calibration_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            first = cs.record_terminal_calibration(
                repo,
                run_id="run-x",
                adapter="claude",
                model="opus",
                effort="high",
                status="complete",
                confidence="high",
            )
            second = cs.record_terminal_calibration(
                repo,
                run_id="run-x",
                adapter="claude",
                model="opus",
                effort="high",
                status="complete",
                confidence="low",
            )
            self.assertTrue(first)
            self.assertFalse(second)
            rows = cs.load_calibration_records(repo)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["confidence"], "high")

    def test_outcome_category_maps_infra_blockers(self) -> None:
        self.assertEqual(
            cs.outcome_category_for_status(
                "blocked", blocker="credential context unverified"
            ),
            "terminal_blocker_infra",
        )
        self.assertEqual(
            cs.outcome_category_for_status("blocked", blocker="acceptance failed"),
            "terminal_blocker_product",
        )
        self.assertEqual(cs.outcome_category_for_status("complete"), "landed_clean")
        self.assertEqual(cs.outcome_category_for_status("stopped"), "abandoned")

    def test_write_sidecars_from_report_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            paths = cs.write_sidecars_from_report(
                repo,
                {
                    "batches": [
                        {
                            "id": "B1",
                            "confidence": "low",
                            "unsure_about": ["queue race"],
                        },
                        {"id": "B2", "status": "complete"},
                    ]
                },
            )
            self.assertEqual(len(paths), 1)
            loaded = cs.read_confidence_sidecar(repo, "B1")
            self.assertEqual(loaded["confidence"], "low")
            commit_paths = cs.write_sidecars_from_commit_messages(
                repo,
                [
                    {
                        "sha": "abc123",
                        "subject": "B1 done\n\nConfidence: high — unsure: none",
                    }
                ],
            )
            self.assertEqual(len(commit_paths), 1)
            trend = cs.calibration_trend_summary(repo)
            self.assertEqual(trend["authority"], "triage_only")
            self.assertEqual(trend["sample_size"], 0)


if __name__ == "__main__":
    unittest.main()
