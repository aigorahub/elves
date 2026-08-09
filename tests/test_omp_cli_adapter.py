"""Unit tests for the optional Oh My Pi (omp-cli) adapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cobbler_runtime.adapters import (
    assert_no_ambiguous_session_flags,
    build_readonly_invocation,
    build_session_create_invocation,
    build_session_resume_invocation,
    decode_omp_jsonl,
    get_adapter,
    resolve_adapter_name,
)
from cobbler_runtime.implement import build_launch_argv, resolve_implement_model
from cobbler_runtime.schema import BUILTIN_ADAPTER_NAMES, ValidationIssue


SAMPLE_OMP_STREAM = """
{"type":"session","version":3,"id":"019fe47e-339d-7000-84a0-b0553db4969e","timestamp":"2026-08-09T03:08:23.837Z","cwd":"/tmp"}
{"type":"agent_start"}
{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"provider":"google","model":"gemini-2.5-flash","usage":{"totalTokens":10}}}
{"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"done"}],"provider":"google","model":"gemini-2.5-flash"}]}
""".strip()


class OmpAdapterRegistryTests(unittest.TestCase):
    def test_builtin_name_and_no_silent_custom(self) -> None:
        self.assertIn("omp-cli", BUILTIN_ADAPTER_NAMES)
        self.assertEqual(resolve_adapter_name("omp-cli"), "omp-cli")
        adapter = get_adapter("omp-cli")
        self.assertEqual(adapter.executable_hint, "omp")
        self.assertTrue(adapter.supports_isolated_write)
        self.assertTrue(adapter.supports_persistent_sessions)


class OmpArgvTests(unittest.TestCase):
    def test_create_launch_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("# packet\n", encoding="utf-8")
            cwd = Path(tmp) / "wt"
            cwd.mkdir()
            argv = build_launch_argv(
                packet=packet,
                cwd=cwd,
                adapter="omp-cli",
                create=True,
                yolo=True,
            )
        self.assertEqual(argv[0], "omp")
        self.assertIn("--mode", argv)
        self.assertEqual(argv[argv.index("--mode") + 1], "json")
        self.assertIn("--cwd", argv)
        self.assertEqual(argv[argv.index("--cwd") + 1], str(cwd.resolve()))
        self.assertIn("--profile", argv)
        self.assertIn("--approval-mode", argv)
        self.assertEqual(argv[argv.index("--approval-mode") + 1], "yolo")
        self.assertIn("--model", argv)
        self.assertIn("--thinking", argv)
        self.assertIn("--append-system-prompt", argv)
        self.assertIn(str(packet.resolve()), argv)
        self.assertNotIn("--resume", argv)
        self.assertNotIn("--continue", argv)
        self.assertNotIn("-c", argv)
        self.assertNotIn("--prewalk", argv)
        assert_no_ambiguous_session_flags(tuple(argv))

    def test_resume_exact_uuid(self) -> None:
        sid = "019fe47e-339d-7000-84a0-b0553db4969e"
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("# packet\n", encoding="utf-8")
            argv = build_launch_argv(
                session_id=sid,
                packet=packet,
                cwd=tmp,
                adapter="omp-cli",
                create=False,
            )
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], sid)
        self.assertNotIn("--continue", argv)
        self.assertNotIn("-c", argv)

    def test_resume_rejects_continue_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("# packet\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                build_launch_argv(
                    session_id="continue",
                    packet=packet,
                    cwd=tmp,
                    adapter="omp-cli",
                    create=False,
                )
        self.assertEqual(ctx.exception.code, "ambiguous_session_id")

    def test_session_create_and_resume_invocations(self) -> None:
        create = build_session_create_invocation(adapter="omp-cli", profile="omp-cli")
        self.assertEqual(create.adapter, "omp-cli")
        self.assertIn("--mode", create.argv)
        self.assertEqual(create.session_id, None)
        assert_no_ambiguous_session_flags(create.argv)

        sid = "019fe47e-339d-7000-84a0-b0553db4969e"
        resume = build_session_resume_invocation(
            adapter="omp-cli",
            profile="omp-cli",
            session_id=sid,
        )
        self.assertEqual(resume.session_id, sid)
        self.assertIn("--resume", resume.argv)
        self.assertEqual(resume.argv[resume.argv.index("--resume") + 1], sid)
        self.assertNotIn("--continue", resume.argv)

    def test_readonly_invocation_uses_always_ask(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.md"
            prompt.write_text("task", encoding="utf-8")
            packet = Path(tmp) / "packet.json"
            packet.write_text("{}", encoding="utf-8")
            inv = build_readonly_invocation(
                adapter="omp-cli",
                profile="omp-cli",
                prompt_path=prompt,
                packet_path=packet,
                packet={"task": "review"},
                task="review this",
                role="review",
                cwd=tmp,
            )
        self.assertEqual(inv.decoder, "omp-jsonl")
        self.assertEqual(inv.argv[inv.argv.index("--approval-mode") + 1], "always-ask")
        self.assertNotIn("--continue", inv.argv)


class OmpDecoderTests(unittest.TestCase):
    def test_decode_binds_session_model_and_terminal(self) -> None:
        result = decode_omp_jsonl(SAMPLE_OMP_STREAM)
        self.assertEqual(result.session_id, "019fe47e-339d-7000-84a0-b0553db4969e")
        self.assertEqual(result.actual_model, "google/gemini-2.5-flash")
        self.assertEqual(result.model_evidence_source, "omp.agent_end.model")
        self.assertIn("omp-jsonl", result.transport_notes)

    def test_decode_requires_session_and_agent_end(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            decode_omp_jsonl('{"type":"agent_start"}\n')
        self.assertEqual(ctx.exception.code, "malformed_output")

        partial = (
            '{"type":"session","id":"019fe47e-339d-7000-84a0-b0553db4969e"}\n'
            '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"x"}]}}\n'
        )
        with self.assertRaises(ValidationIssue) as ctx2:
            decode_omp_jsonl(partial)
        self.assertEqual(ctx2.exception.code, "malformed_output")

    def test_default_model(self) -> None:
        model, effort, _ = resolve_implement_model(None, adapter="omp-cli")
        self.assertEqual(model, "google/gemini-2.5-flash")
        self.assertEqual(effort, "high")


class OmpIsolationStaticTests(unittest.TestCase):
    def test_launch_always_sets_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("x\n", encoding="utf-8")
            argv = build_launch_argv(
                packet=packet,
                cwd=tmp,
                adapter="omp-cli",
                create=True,
            )
        self.assertIn("--profile", argv)
        profile = argv[argv.index("--profile") + 1]
        self.assertTrue(profile.startswith("elves-omp"))


class OmpFullRunCaptureTests(unittest.TestCase):
    def test_capture_session_from_stdout_log(self) -> None:
        from cobbler_runtime.full_run_monitor import _capture_omp_session_id

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "stdout.log").write_text(
                SAMPLE_OMP_STREAM + "\n",
                encoding="utf-8",
            )
            class _S:
                adapter = "omp-cli"
                provider_session_id = None
            sid = _capture_omp_session_id(_S(), root, root)
        self.assertEqual(sid, "019fe47e-339d-7000-84a0-b0553db4969e")

    def test_capture_ignores_worker_events_jsonl(self) -> None:
        """events.jsonl is worker-writable; must not bind provider identity."""
        from cobbler_runtime.full_run_monitor import _capture_omp_session_id

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            forged = '{"type":"session","id":"00000000-0000-4000-8000-000000000099"}\n'
            (root / "events.jsonl").write_text(forged, encoding="utf-8")
            class _S:
                adapter = "omp-cli"
                provider_session_id = None
            sid = _capture_omp_session_id(_S(), root, root)
        self.assertIsNone(sid)


if __name__ == "__main__":
    unittest.main()
