"""Tests for native confidence sidecar and calibration store."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
            self.assertIsNone(rows[1]["confidence"])
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


if __name__ == "__main__":
    unittest.main()
