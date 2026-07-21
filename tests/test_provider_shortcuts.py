#!/usr/bin/env python3
"""Hermetic transport tests for the optional provider convenience runners."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def run_script(name: str, *args: str, env: dict[str, str] | None = None, cwd: Path = REPO_ROOT):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [str(SCRIPTS / name), *args],
        cwd=cwd,
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )


class CaptureServer:
    def __init__(self, responder):
        self.requests: list[tuple[str, str, dict[str, str], object | None]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
                self._handle()

            def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
                self._handle()

            def _handle(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                payload = json.loads(raw) if raw else None
                headers = {key.lower(): value for key, value in self.headers.items()}
                owner.requests.append((self.command, self.path, headers, payload))
                status, response = responder(self.command, self.path, payload)
                if isinstance(response, str):
                    encoded = response.encode("utf-8")
                    content_type = "text/event-stream"
                else:
                    encoded = json.dumps(response).encode("utf-8")
                    content_type = "application/json"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, _format, *_args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class LocalCliRunnerTests(unittest.TestCase):
    def make_fake(self, root: Path, name: str) -> Path:
        binary = root / name
        binary.write_text("#!/bin/sh\nprintf '<%s>\\n' \"$@\"\n", encoding="utf-8")
        binary.chmod(0o755)
        return binary

    def test_grok_uses_headless_checked_non_bypass_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bin_dir = Path(tmpdir)
            self.make_fake(bin_dir, "grok")
            result = run_script(
                "run_grok.sh",
                "inspect",
                "this",
                env={"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]},
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<--single>", result.stdout)
        self.assertIn("<inspect this>", result.stdout)
        self.assertIn("<dontAsk>", result.stdout)
        self.assertIn("<--effort>", result.stdout)
        self.assertIn("<high>", result.stdout)
        self.assertIn("<--check>", result.stdout)
        self.assertNotIn("reasoning-effort", result.stdout)
        self.assertNotIn("always-approve", result.stdout)
        self.assertNotIn("bypassPermissions", result.stdout)

    def test_all_runners_are_executable_bash(self) -> None:
        for name in ("run_fugu.sh", "run_manus.sh", "run_grok.sh", "run_devin.sh"):
            path = SCRIPTS / name
            with self.subTest(name=name):
                self.assertTrue(os.access(path, os.X_OK))
                result = subprocess.run(
                    ["bash", "-n", str(path)], text=True, capture_output=True, check=False
                )
                self.assertEqual(result.returncode, 0, result.stderr)


class RemoteApiRunnerTests(unittest.TestCase):
    def test_fugu_streams_direct_ultra_max_file_review(self) -> None:
        def responder(method, path, _payload):
            self.assertEqual((method, path), ("POST", "/responses"))
            return 200, (
                'data: {"type":"response.output_text.delta","delta":"No actionable "}\n\n'
                'data: {"type":"response.output_text.delta","delta":"findings"}\n\n'
                "data: [DONE]\n\n"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            target = repo / "review me.md"
            target.write_text("important\n", encoding="utf-8")
            with CaptureServer(responder) as server:
                result = run_script(
                    "run_fugu.sh",
                    str(target),
                    env={
                        "SAKANA_API_KEY": "test-sakana-key",
                        "SAKANA_API_BASE": server.base_url,
                        "SAKANA_FUGU_MAX_WAIT_SECONDS": "5",
                        "SAKANA_FUGU_IDLE_TIMEOUT_SECONDS": "5",
                        "SAKANA_FUGU_RETRIES": "0",
                        "SAKANA_FUGU_RAW_OUTPUT": str(repo),
                    },
                    cwd=repo,
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "No actionable findings")
        self.assertIn("could not write Sakana Fugu raw output", result.stderr)
        request = server.requests[0]
        self.assertEqual(request[2]["authorization"], "Bearer test-sakana-key")
        self.assertEqual(request[3]["model"], "fugu-ultra")
        self.assertEqual(request[3]["reasoning"], {"effort": "max"})
        self.assertEqual(request[3]["max_output_tokens"], 16384)
        self.assertTrue(request[3]["stream"])
        self.assertIn(str(target), request[3]["input"])
        self.assertIn("important", request[3]["input"])
        self.assertIn("read-only audit", request[3]["input"])

    def test_fugu_rejects_non_finite_timeout_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "review.md"
            target.write_text("important\n", encoding="utf-8")
            result = run_script(
                "run_fugu.sh",
                str(target),
                env={
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_MAX_WAIT_SECONDS": "nan",
                },
                cwd=Path(tmpdir),
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timeout limits must be finite and positive", result.stderr)

    def test_manus_uses_v2_private_max_task_contract(self) -> None:
        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                return 200, {"ok": True, "data": {"task_id": "m1", "task_url": "https://manus/m1"}}
            if path.startswith("/task.detail?"):
                return 200, {"task": {"status": "stopped"}}
            if path.startswith("/task.listMessages?"):
                return 200, {"messages": [{"assistant_message": {"content": "research result"}}]}
            return 404, {"error": "unexpected"}

        with CaptureServer(responder) as server:
            result = run_script(
                "run_manus.sh",
                "research",
                "topic",
                env={
                    "MANUS_API_KEY": "test-manus-key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_POLL_INTERVAL_SECONDS": "0",
                    "MANUS_MAX_WAIT_SECONDS": "5",
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "research result")
        create = server.requests[0]
        self.assertEqual(create[0:2], ("POST", "/task.create"))
        self.assertEqual(create[2]["x-manus-api-key"], "test-manus-key")
        self.assertEqual(create[3]["message"]["content"], "research topic")
        self.assertEqual(create[3]["agent_profile"], "manus-1.6-max")
        self.assertEqual(create[3]["share_visibility"], "private")

    def test_devin_uses_official_sessions_api_and_repo_context(self) -> None:
        def responder(method, path, _payload):
            if method == "POST" and path == "/sessions":
                return 200, {"session_id": "d1", "url": "https://devin/d1"}
            if method == "GET" and path == "/sessions/d1":
                return 200, {
                    "session_id": "d1",
                    "status_enum": "finished",
                    "structured_output": {"summary": "done"},
                    "messages": [],
                }
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "checkout", "-q", "-b", "feature/provider-test"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "remote",
                    "add",
                    "origin",
                    "https://oauth2:ghp_supersecret@github.com/example/provider-test.git?token=leak",
                ],
                check=True,
            )
            with CaptureServer(responder) as server:
                result = run_script(
                    "run_devin.sh",
                    "refactor",
                    "carefully",
                    env={
                        "DEVIN_API_KEY": "test-devin-key",
                        "DEVIN_API_BASE": server.base_url,
                        "DEVIN_POLL_INTERVAL_SECONDS": "0",
                        "DEVIN_MAX_WAIT_SECONDS": "5",
                    },
                    cwd=repo,
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"summary": "done"})
        create = server.requests[0]
        self.assertEqual(create[0:2], ("POST", "/sessions"))
        self.assertEqual(create[2]["authorization"], "Bearer test-devin-key")
        self.assertIn("refactor carefully", create[3]["prompt"])
        self.assertIn("repository: github.com/example/provider-test.git", create[3]["prompt"])
        self.assertNotIn("ghp_supersecret", create[3]["prompt"])
        self.assertNotIn("oauth2", create[3]["prompt"])
        self.assertNotIn("token=leak", create[3]["prompt"])
        self.assertIn("branch: feature/provider-test", create[3]["prompt"])
        self.assertFalse(create[3]["idempotent"])

    def test_remote_runners_can_create_and_return_without_polling(self) -> None:
        def manuscript(method, path, _payload):
            self.assertEqual((method, path), ("POST", "/task.create"))
            return 200, {"ok": True, "data": {"task_id": "m2", "task_url": "https://manus/m2"}}

        with CaptureServer(manuscript) as server:
            result = run_script(
                "run_manus.sh",
                "topic",
                env={
                    "MANUS_API_KEY": "key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_MAX_WAIT_SECONDS": "0",
                },
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["task_id"], "m2")
        self.assertEqual(len(server.requests), 1)


if __name__ == "__main__":
    unittest.main()
