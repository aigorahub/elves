"""Default live worker window / follow mode tests (B2)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.full_run import (  # noqa: E402
    FOLLOW_MODE_MODEL_INFERENCE,
    FOLLOW_MODE_REPLACES_TIMED_CHAT,
    await_full_run,
    follow_stream_lines,
    format_follow_stream_line,
)
from cobbler_runtime.risk_policy import progress_commit_subject_ok  # noqa: E402


class FollowModeTests(unittest.TestCase):
    def test_format_sanitized_stream_line(self) -> None:
        event = {
            "timestamp": "2026-07-14T00:00:00Z",
            "batch": 1,
            "type": "commit_pushed",
            "head": "abcdef1234567890",
            "summary": "Added landing authority module",
        }
        line = format_follow_stream_line(event, shared_oauth=False)
        self.assertIn("commit_pushed", line)
        self.assertIn("abcdef123456", line)
        self.assertIn("Added landing", line)

        oauth_line = format_follow_stream_line(event, shared_oauth=True)
        self.assertIn("commit_pushed", oauth_line)
        self.assertNotIn("Added landing", oauth_line)

    def test_follow_stream_cursor(self) -> None:
        events = [
            {"type": "heartbeat", "batch": 0, "head": "a" * 40, "timestamp": "t1"},
            {
                "type": "batch_started",
                "batch": 0,
                "head": "a" * 40,
                "timestamp": "t2",
                "summary": "start",
            },
        ]
        lines, cursor = follow_stream_lines(events, shared_oauth=False, already_seen=0)
        self.assertEqual(len(lines), 2)
        self.assertEqual(cursor, 2)
        more, cursor2 = follow_stream_lines(
            events, shared_oauth=False, already_seen=cursor
        )
        self.assertEqual(more, [])
        self.assertEqual(cursor2, 2)

    def test_follow_defaults_and_no_model_inference(self) -> None:
        self.assertFalse(FOLLOW_MODE_MODEL_INFERENCE)
        self.assertTrue(FOLLOW_MODE_REPLACES_TIMED_CHAT)

        calls = {"n": 0}
        written: list[str] = []

        def fake_monitor(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "state": "healthy",
                    "next_action": "parked_monitor",
                    "unchanged_healthy_poll_silent": True,
                    "material_transition": False,
                    "poll_after_seconds": 0.01,
                    "events_tail": [
                        {
                            "type": "heartbeat",
                            "batch": 0,
                            "head": "b" * 40,
                            "timestamp": "t",
                        }
                    ],
                }
            return {
                "state": "complete",
                "next_action": "final_readiness",
                "unchanged_healthy_poll_silent": False,
                "material_transition": True,
                "poll_after_seconds": 0.01,
                "events_tail": [
                    {
                        "type": "heartbeat",
                        "batch": 0,
                        "head": "b" * 40,
                        "timestamp": "t",
                    },
                    {
                        "type": "run_complete",
                        "batch": 5,
                        "head": "c" * 40,
                        "timestamp": "t2",
                        "summary": "done",
                    },
                ],
            }

        with mock.patch(
            "cobbler_runtime.full_run_monitor.monitor_full_run", side_effect=fake_monitor
        ), mock.patch(
            "cobbler_runtime.full_run.load_state"
        ) as load_state:
            load_state.return_value = mock.Mock(grok_auth_strategy="api_key")
            out = await_full_run(
                Path("."),
                session_id="s",
                sleep_fn=lambda _s: None,
                monotonic_fn=lambda: 0.0,
                follow=True,
                stream_writer=written.append,
            )
        self.assertTrue(out["awaited"])
        self.assertTrue(out["follow"])
        self.assertFalse(out["follow_model_inference"])
        self.assertTrue(out["follow_replaces_timed_chat"])
        self.assertFalse(out["merge_authority"])
        self.assertTrue(any("heartbeat" in line for line in written))

    def test_quiet_opt_out(self) -> None:
        with mock.patch(
            "cobbler_runtime.full_run_monitor.monitor_full_run",
            return_value={
                "state": "complete",
                "next_action": "final_readiness",
                "unchanged_healthy_poll_silent": False,
                "material_transition": True,
                "poll_after_seconds": 0.01,
            },
        ):
            out = await_full_run(
                Path("."),
                session_id="s",
                sleep_fn=lambda _s: None,
                monotonic_fn=lambda: 0.0,
                quiet=True,
            )
        self.assertFalse(out["follow"])
        self.assertEqual(out["follow_stream_lines"], [])

    def test_progress_commit_subjects_still_required(self) -> None:
        self.assertTrue(
            progress_commit_subject_ok(
                "[codex/joyful-elves-runs · Batch 0/6 · Implement] "
                "Add canonical contract and migration ledger"
            )
        )
        self.assertFalse(
            progress_commit_subject_ok(
                "[codex/joyful-elves-runs · Batch 0/6 · Implement] progress"
            )
        )


if __name__ == "__main__":
    unittest.main()
