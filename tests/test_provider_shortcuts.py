#!/usr/bin/env python3
"""Hermetic transport tests for the optional provider convenience runners."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.isolation import detect_fs_sandbox_backend  # noqa: E402


HAS_FS_SANDBOX = detect_fs_sandbox_backend() is not None


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

            def do_PUT(self):  # noqa: N802 - BaseHTTPRequestHandler API
                self._handle()

            def _handle(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    payload = raw
                headers = {key.lower(): value for key, value in self.headers.items()}
                owner.requests.append((self.command, self.path, headers, payload))
                response_spec = responder(self.command, self.path, payload)
                if len(response_spec) == 3:
                    status, response, extra_headers = response_spec
                else:
                    status, response = response_spec
                    extra_headers = {}
                if isinstance(response, str):
                    encoded = response.encode("utf-8")
                    content_type = "text/event-stream"
                else:
                    encoded = json.dumps(response).encode("utf-8")
                    content_type = "application/json"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(encoded)))
                for name, value in extra_headers.items():
                    self.send_header(name, value)
                self.end_headers()
                try:
                    self.wfile.write(encoded)
                except BrokenPipeError:
                    pass

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
        binary.write_text(
            "#!/bin/sh\n"
            "printf 'unrelated-secret=<%s>\\n' \"${AWS_SECRET_ACCESS_KEY:-}\"\n"
            "printf '<%s>\\n' \"$@\"\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_capture_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "printf 'cwd=<%s>\\n' \"$PWD\"\n"
            "printf 'notice=<%s> update=<%s>\\n' \"$CODEX_FUGU_NO_NOTICE\" \"$CODEX_FUGU_NO_UPDATE\"\n"
            "printf 'unrelated-secret=<%s>\\n' \"${AWS_SECRET_ACCESS_KEY:-}\"\n"
            "printf 'arg=<%s>\\n' \"$@\"\n"
            "if [ -f _elves_review/change-context.txt ]; then\n"
            "  while IFS= read -r line || [ -n \"$line\" ]; do\n"
            "    printf 'evidence=<%s>\\n' \"$line\"\n"
            "  done < _elves_review/change-context.txt\n"
            "fi\n"
            "while IFS= read -r line || [ -n \"$line\" ]; do \n"
            "  printf 'prompt=<%s>\\n' \"$line\"\n"
            "done\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_defaults_to_project_aware_regular_high_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            nested = repo / "nested"
            nested.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "review",
                "the auth flow",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                    "AWS_SECRET_ACCESS_KEY": "must-not-cross",
                },
                cwd=nested,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"cwd=<.*elves-iso-[^>]+/snapshot>")
        self.assertIn("unrelated-secret=<>", result.stdout)
        self.assertIn("notice=<1> update=<1>", result.stdout)
        self.assertIn("arg=<--no-update>", result.stdout)
        self.assertIn("arg=<--model>\narg=<fugu>", result.stdout)
        self.assertIn('arg=<model_reasoning_effort="high">', result.stdout)
        self.assertIn("arg=<--sandbox>\narg=<read-only>", result.stdout)
        self.assertIn("arg=<--ask-for-approval>\narg=<never>", result.stdout)
        self.assertRegex(result.stdout, r"arg=<--cd>\narg=<.*elves-iso-[^>]+/snapshot>")
        self.assertIn("arg=<exec>", result.stdout)
        self.assertIn("arg=<--ephemeral>", result.stdout)
        self.assertIn("arg=<->", result.stdout)
        self.assertIn("prompt=<Review task: review the auth flow>", result.stdout)
        self.assertIn("prompt=<do not ask the caller to paste files", result.stdout)
        self.assertNotIn("arg=<fugu-ultra>", result.stdout)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_profiles_select_regular_deep_or_ultra_high(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            env = {
                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                "SAKANA_API_KEY": "test-sakana-key",
            }
            deep = run_script("run_fugu.sh", "--deep", "review parser", env=env, cwd=repo)
            ultra = run_script("run_fugu.sh", "--ultra", "review parser", env=env, cwd=repo)

        self.assertEqual(deep.returncode, 0, deep.stderr)
        self.assertIn("arg=<--model>\narg=<fugu>", deep.stdout)
        self.assertIn('arg=<model_reasoning_effort="xhigh">', deep.stdout)
        self.assertEqual(ultra.returncode, 0, ultra.stderr)
        self.assertIn("arg=<--model>\narg=<fugu-ultra>", ultra.stdout)
        self.assertIn('arg=<model_reasoning_effort="high">', ultra.stdout)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_diff_evidence_omits_snapshot_excluded_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            safe = repo / "safe.txt"
            excluded = repo / ".env"
            safe.write_text("safe baseline\n", encoding="utf-8")
            excluded.write_text("SECRET_BASELINE_MUST_NOT_CROSS\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "safe.txt", ".env"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "baseline"], check=True)
            safe.write_text("SAFE_DIFF_MARKER\n", encoding="utf-8")
            excluded.write_text("SECRET_DIFF_MARKER_MUST_NOT_CROSS\n", encoding="utf-8")
            result = run_script(
                "run_fugu.sh",
                "review filtered changes",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SAFE_DIFF_MARKER", result.stdout)
        self.assertNotIn("SECRET_BASELINE_MUST_NOT_CROSS", result.stdout)
        self.assertNotIn("SECRET_DIFF_MARKER_MUST_NOT_CROSS", result.stdout)
        self.assertNotIn("diff --git a/.env", result.stdout)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_legacy_file_is_focus_hint_not_copied_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            target = repo / "review me.md"
            target.write_text("SENSITIVE_SENTINEL_MUST_NOT_BE_COPIED\n", encoding="utf-8")
            result = run_script(
                "run_fugu.sh",
                str(target),
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(
            result.stdout,
            r"prompt=<Review task: Review .*elves-iso-[^>]+/snapshot/review me\.md",
        )
        self.assertNotIn("SENSITIVE_SENTINEL_MUST_NOT_BE_COPIED", result.stdout)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_enforces_finite_hard_wall_clock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            sleeper = bin_dir / "codex-fugu"
            sleeper.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
            sleeper.chmod(0o755)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            env = {
                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                "SAKANA_API_KEY": "test-sakana-key",
                "SAKANA_FUGU_MAX_WAIT_SECONDS": "0.05",
            }
            started = time.monotonic()
            timed_out = run_script("run_fugu.sh", "review", env=env, cwd=repo)
            elapsed = time.monotonic() - started
            env["SAKANA_FUGU_MAX_WAIT_SECONDS"] = "nan"
            non_finite = run_script("run_fugu.sh", "review", env=env, cwd=repo)

        self.assertEqual(timed_out.returncode, 124, timed_out.stderr)
        self.assertLess(elapsed, 2)
        self.assertIn("terminating it", timed_out.stderr)
        self.assertNotEqual(non_finite.returncode, 0)
        self.assertIn("must be finite and positive", non_finite.stderr)

    def test_grok_uses_headless_checked_non_bypass_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bin_dir = Path(tmpdir)
            self.make_fake(bin_dir, "grok")
            result = run_script(
                "run_grok.sh",
                "inspect",
                "this",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "XAI_API_KEY": "test-xai-key",
                    "AWS_SECRET_ACCESS_KEY": "must-not-cross",
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unrelated-secret=<>", result.stdout)
        self.assertIn("<--single=inspect this>", result.stdout)
        self.assertIn("<dontAsk>", result.stdout)
        self.assertIn("<--effort>", result.stdout)
        self.assertIn("<high>", result.stdout)
        self.assertIn("<--check>", result.stdout)
        self.assertIn("<--sandbox>", result.stdout)
        self.assertIn("<elves-shortcut>", result.stdout)
        self.assertNotIn("reasoning-effort", result.stdout)
        self.assertNotIn("always-approve", result.stdout)
        self.assertNotIn("bypassPermissions", result.stdout)

    def test_grok_shared_oauth_fails_closed_before_provider_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fake(bin_dir, "grok")
            host_home = root / "host-home"
            auth_dir = host_home / ".grok"
            auth_dir.mkdir(parents=True)
            auth_path = auth_dir / "auth.json"
            auth_path.write_text(
                json.dumps({"account": {"refresh_token": "provider-refresh-secret"}}),
                encoding="utf-8",
            )
            auth_path.chmod(0o600)
            result = run_script(
                "run_grok.sh",
                "inspect oauth isolation",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "HOME": str(host_home),
                    "GROK_HOME": "",
                    "GROK_AUTH_PATH": "",
                    "XAI_API_KEY": "",
                    "GROK_CODE_XAI_API_KEY": "",
                },
            )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("requires an explicit XAI_API_KEY", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("provider-refresh-secret", result.stdout)

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
                    "MANUS_POLL_INTERVAL_SECONDS": "0.1",
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
        self.assertEqual(create[3]["connectors"], [])
        self.assertEqual(create[3]["enable_skills"], [])
        self.assertEqual(create[3]["force_skills"], [])

    def test_manus_wide_reconciles_roster_and_uploads_explicit_files(self) -> None:
        reports = {
            "paper-a": {"id": "paper-a", "status": "complete", "report": "A evidence"},
            "paper-b": {"id": "paper-b", "status": "uncertain", "report": "B evidence"},
        }
        server: CaptureServer

        def responder(method, path, payload):
            if method == "POST" and path == "/file.upload":
                return 200, {
                    "ok": True,
                    "data": {
                        "file": {"id": "source-file"},
                        "upload_url": server.base_url + "/upload/source-file",
                    },
                }
            if method == "PUT" and path == "/upload/source-file":
                return 200, {}
            if path.startswith("/file.detail?"):
                return 200, {"data": {"file": {"id": "source-file", "status": "uploaded"}}}
            if method == "POST" and path == "/task.create":
                return 200, {"ok": True, "data": {"task_id": "wide-1"}}
            if path.startswith("/task.detail?"):
                return 200, {"data": {"task": {"status": "stopped"}}}
            if path.startswith("/task.listMessages?"):
                return 200, {
                    "messages": [
                        {
                            "structured_output_result": {
                                "success": True,
                                "value": {
                                    "items": list(reports.values()),
                                    "summary": "wide complete",
                                },
                            }
                        }
                    ]
                }
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text(json.dumps({"items": list(reports)}), encoding="utf-8")
            source_path = root / "source.pdf"
            source_path.write_bytes(b"paper source bytes")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            server = CaptureServer(responder)
            with server:
                result = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--items-file",
                    str(items_path),
                    "--file",
                    str(source_path),
                    "--manifest",
                    str(manifest_path),
                    "audit",
                    "these papers",
                    env={
                        "MANUS_API_KEY": "wide-key",
                        "MANUS_API_BASE": server.base_url,
                        "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                        "MANUS_FILE_POLL_INTERVAL_SECONDS": "0.1",
                        "MANUS_MAX_WAIT_SECONDS": "5",
                    },
                    cwd=root,
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["summary"], "wide complete")
        self.assertEqual(manifest["state"], "complete")
        self.assertFalse(manifest["fallback_used"])
        self.assertEqual(manifest["coverage"]["complete"], list(reports))
        uploads = [request for request in server.requests if request[0] == "PUT"]
        self.assertEqual(uploads[0][3], b"paper source bytes")
        self.assertNotIn("x-manus-api-key", uploads[0][2])
        creates = [request for request in server.requests if request[1] == "/task.create"]
        self.assertEqual(len(creates), 1)
        payload = creates[0][3]
        self.assertEqual(payload["share_visibility"], "private")
        self.assertEqual(payload["agent_profile"], "manus-1.6-max")
        self.assertEqual(payload["connectors"], [])
        self.assertEqual(payload["enable_skills"], [])
        self.assertEqual(payload["force_skills"], [])
        self.assertIn("structured_output_schema", payload)
        self.assertEqual(
            payload["message"]["content"][1],
            {"type": "file", "file_id": "source-file"},
        )
        self.assertIn(
            "exactly one independent research subagent",
            payload["message"]["content"][0]["text"],
        )

    def test_manus_rejects_invalid_modes_before_uploading_files(self) -> None:
        def responder(_method, _path, _payload):
            return 500, {"error": "no provider request expected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.txt"
            source.write_text("safe source", encoding="utf-8")
            with CaptureServer(responder) as server:
                result = run_script(
                    "run_manus.sh",
                    "--file",
                    str(source),
                    "--manifest",
                    str(Path(tmpdir) / "manifest.json"),
                    "ordinary topic",
                    env={
                        "MANUS_API_KEY": "key",
                        "MANUS_API_BASE": server.base_url,
                    },
                )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("require --wide or --fanout", result.stderr)
        self.assertEqual(server.requests, [])

    def test_manus_refuses_non_runtime_or_existing_manifest_targets(self) -> None:
        def responder(_method, _path, _payload):
            return 500, {"error": "no provider request expected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items = root / "items.json"
            items.write_text('["ref-a"]', encoding="utf-8")
            victim = root / "README.md"
            victim.write_text("must survive\n", encoding="utf-8")
            source = root / "private-source.pdf"
            source.write_bytes(b"must not be uploaded")
            runtime_manifest = (
                root / ".elves" / "runtime" / "manus" / "existing.json"
            )
            runtime_manifest.parent.mkdir(parents=True)
            runtime_manifest.write_text("existing runtime data\n", encoding="utf-8")
            with CaptureServer(responder) as server:
                env = {"MANUS_API_KEY": "key", "MANUS_API_BASE": server.base_url}
                outside = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--items-file",
                    str(items),
                    "--manifest",
                    str(victim),
                    "--file",
                    str(source),
                    "research",
                    env=env,
                    cwd=root,
                )
                existing = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--items-file",
                    str(items),
                    "--manifest",
                    str(runtime_manifest),
                    "--file",
                    str(source),
                    "research",
                    env=env,
                    cwd=root,
                )
            victim_text = victim.read_text(encoding="utf-8")
            runtime_text = runtime_manifest.read_text(encoding="utf-8")

        self.assertEqual(outside.returncode, 2, outside.stderr)
        self.assertIn("must live under", outside.stderr)
        self.assertEqual(existing.returncode, 2, existing.stderr)
        self.assertIn("Refusing to overwrite", existing.stderr)
        self.assertEqual(victim_text, "must survive\n")
        self.assertEqual(runtime_text, "existing runtime data\n")
        self.assertEqual(server.requests, [])

    def test_manus_refuses_symlinked_runtime_root_before_upload(self) -> None:
        def responder(_method, _path, _payload):
            return 500, {"error": "no provider request expected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items = root / "items.json"
            items.write_text('["ref-a"]', encoding="utf-8")
            source = root / "private-source.pdf"
            source.write_bytes(b"must not be uploaded through symlinked runtime")
            redirected = root / "redirected-manus"
            redirected.mkdir()
            runtime_parent = root / ".elves" / "runtime"
            runtime_parent.mkdir(parents=True)
            (runtime_parent / "manus").symlink_to(redirected, target_is_directory=True)
            manifest = runtime_parent / "manus" / "manifest.json"
            with CaptureServer(responder) as server:
                result = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--items-file",
                    str(items),
                    "--manifest",
                    str(manifest),
                    "--file",
                    str(source),
                    "research",
                    env={"MANUS_API_KEY": "key", "MANUS_API_BASE": server.base_url},
                    cwd=root,
                )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(server.requests, [])
        self.assertFalse((redirected / "manifest.json").exists())

    def test_manus_does_not_retry_ambiguous_paid_task_creation(self) -> None:
        def responder(_method, _path, _payload):
            return 500, {"error": "ambiguous create failure"}

        with CaptureServer(responder) as server:
            result = run_script(
                "run_manus.sh",
                "ordinary topic",
                env={
                    "MANUS_API_KEY": "key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_API_RETRIES": "3",
                    "MANUS_MAX_WAIT_SECONDS": "5",
                },
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(len(server.requests), 1)
        self.assertEqual(server.requests[0][0:2], ("POST", "/task.create"))

    def test_manus_retries_idempotent_gets_without_recreating_task(self) -> None:
        state = {"create_count": 0, "detail_count": 0}

        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                state["create_count"] += 1
                return 200, {"data": {"task_id": "retry-get"}}
            if path.startswith("/task.detail?"):
                state["detail_count"] += 1
                if state["detail_count"] == 1:
                    return 503, {"error": "transient"}, {"Retry-After": "0"}
                return 200, {"task": {"status": "stopped"}}
            if path.startswith("/task.listMessages?"):
                return 200, {"messages": [{"assistant_message": {"content": "done"}}]}
            return 404, {"error": "unexpected"}

        with CaptureServer(responder) as server:
            result = run_script(
                "run_manus.sh",
                "retry idempotent read",
                env={
                    "MANUS_API_KEY": "key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_API_RETRIES": "1",
                    "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_MAX_WAIT_SECONDS": "5",
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "done")
        self.assertEqual(state, {"create_count": 1, "detail_count": 2})

    def test_manus_refuses_credential_paths_and_symlinks_before_upload(self) -> None:
        def responder(_method, _path, _payload):
            return 500, {"error": "no provider request expected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidates = [
                root / ".env.local",
                root / ".pgpass",
                root / "private.pem",
                root / "service.key",
                root / "kubeconfig",
                root / ".docker" / "config.json",
                root / ".kube" / "config",
            ]
            for candidate in candidates:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("credential material", encoding="utf-8")
            safe_source = root / "source.txt"
            safe_source.write_text("safe source", encoding="utf-8")
            symlink = root / "source-link.txt"
            symlink.symlink_to(safe_source)
            candidates.append(symlink)

            with CaptureServer(responder) as server:
                for candidate in candidates:
                    with self.subTest(candidate=candidate):
                        result = run_script(
                            "run_manus.sh",
                            "--file",
                            str(candidate),
                            "research topic",
                            env={
                                "MANUS_API_KEY": "key",
                                "MANUS_API_BASE": server.base_url,
                                "MANUS_MAX_WAIT_SECONDS": "0",
                            },
                        )
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertIn("Refusing to upload", result.stderr)

        self.assertEqual(server.requests, [])

    def test_manus_wide_repairs_only_missing_or_duplicate_items_then_synthesizes(self) -> None:
        items = ["paper-a", "paper-b", "paper-c"]
        state = {"create_count": 0}
        task_items: dict[str, str] = {}
        server: CaptureServer

        def responder(method, path, payload):
            if method == "POST" and path == "/task.create":
                state["create_count"] += 1
                if state["create_count"] == 1:
                    task_id = "wide-main"
                elif state["create_count"] <= 3:
                    task_id = f"repair-{state['create_count']}"
                    task_items[task_id] = payload["title"].split(": ", 1)[1]
                else:
                    task_id = "synthesis-main"
                return 200, {"data": {"task_id": task_id}}
            if method == "POST" and path == "/file.upload":
                return 200, {
                    "file": {"id": "synthesis-file"},
                    "upload_url": server.base_url + "/upload/synthesis-file",
                }
            if method == "PUT" and path == "/upload/synthesis-file":
                return 200, {}
            if path.startswith("/file.detail?"):
                return 200, {"file": {"status": "uploaded"}}
            if path.startswith("/task.detail?"):
                return 200, {"task": {"status": "stopped"}}
            if path.startswith("/task.listMessages?"):
                task_id = path.split("task_id=", 1)[1].split("&", 1)[0]
                if task_id == "wide-main":
                    value = {
                        "items": [
                            {"id": "paper-a", "status": "complete", "report": "A first"},
                            {"id": "paper-a", "status": "complete", "report": "A duplicate"},
                            {"id": "paper-c", "status": "complete", "report": "C evidence"},
                        ],
                        "summary": "incomplete native run",
                    }
                elif task_id == "synthesis-main":
                    value = {
                        "items": [
                            {"id": item, "status": "complete", "report": f"{item} final"}
                            for item in items
                        ],
                        "summary": "repaired synthesis",
                    }
                else:
                    item = task_items[task_id]
                    value = {"id": item, "status": "complete", "report": f"{item} repair"}
                return 200, {
                    "messages": [
                        {"structured_output_result": {"success": True, "value": value}}
                    ]
                }
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text(json.dumps(items), encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            server = CaptureServer(responder)
            with server:
                result = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "review",
                    "every reference",
                    env={
                        "MANUS_API_KEY": "wide-key",
                        "MANUS_API_BASE": server.base_url,
                        "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                        "MANUS_FILE_POLL_INTERVAL_SECONDS": "0.1",
                        "MANUS_CREATE_INTERVAL_SECONDS": "0.1",
                        "MANUS_MAX_WAIT_SECONDS": "5",
                    },
                    cwd=root,
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["summary"], "repaired synthesis")
        self.assertTrue(manifest["fallback_used"])
        self.assertEqual(manifest["coverage"]["missing"], [])
        self.assertEqual(set(manifest["fanout_tasks"]), {"paper-a", "paper-b"})
        self.assertEqual(state["create_count"], 4)
        self.assertEqual(
            len([request for request in server.requests if request[1] == "/task.sendMessage"]),
            0,
        )

    def test_manus_wide_manifest_resumes_without_duplicate_task_creation(self) -> None:
        state = {"create_count": 0}

        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                state["create_count"] += 1
                return 200, {"data": {"task_id": "wide-resume"}}
            if path.startswith("/task.detail?"):
                return 200, {"task": {"status": "stopped"}}
            if path.startswith("/task.listMessages?"):
                return 200, {
                    "messages": [
                        {
                            "structured_output_result": {
                                "success": True,
                                "value": {
                                    "items": [
                                        {"id": "paper-a", "status": "complete", "report": "done"}
                                    ],
                                    "summary": "resumed",
                                },
                            }
                        }
                    ]
                }
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text('["paper-a"]', encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            with CaptureServer(responder) as server:
                base_env = {
                    "MANUS_API_KEY": "wide-key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_CREATE_INTERVAL_SECONDS": "0.1",
                }
                created = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "resume test",
                    env={**base_env, "MANUS_MAX_WAIT_SECONDS": "0"},
                    cwd=root,
                )
                resumed = run_script(
                    "run_manus.sh",
                    "--resume",
                    str(manifest_path),
                    env={**base_env, "MANUS_MAX_WAIT_SECONDS": "5"},
                    cwd=root,
                )

        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(json.loads(created.stdout)["state"], "running")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["summary"], "resumed")
        self.assertEqual(state["create_count"], 1)

    def test_manus_resume_recreates_only_a_failed_coverage_repair(self) -> None:
        items = ["ref-a", "ref-b"]
        state = {"create_count": 0}
        task_roles: dict[str, str] = {}
        server: CaptureServer

        def responder(method, path, payload):
            if method == "POST" and path == "/task.create":
                state["create_count"] += 1
                task_id = {
                    1: "wide-main",
                    2: "repair-failed",
                    3: "repair-retry",
                    4: "synthesis-ok",
                }[state["create_count"]]
                task_roles[task_id] = str(payload.get("title") or "")
                return 200, {"data": {"task_id": task_id}}
            if method == "POST" and path == "/file.upload":
                return 200, {
                    "file": {"id": "repair-results"},
                    "upload_url": server.base_url + "/upload/repair-results",
                }
            if method == "PUT" and path == "/upload/repair-results":
                return 200, {}
            if path.startswith("/file.detail?"):
                return 200, {"file": {"status": "uploaded"}}
            if path.startswith("/task.detail?"):
                task_id = path.split("task_id=", 1)[1].split("&", 1)[0]
                status = "error" if task_id == "repair-failed" else "stopped"
                return 200, {"task": {"status": status}}
            if path.startswith("/task.listMessages?"):
                task_id = path.split("task_id=", 1)[1].split("&", 1)[0]
                if task_id == "wide-main":
                    value = {
                        "items": [
                            {"id": "ref-a", "status": "complete", "report": "A evidence"}
                        ],
                        "summary": "native partial",
                    }
                elif task_id == "repair-retry":
                    value = {"id": "ref-b", "status": "complete", "report": "B evidence"}
                elif task_id == "synthesis-ok":
                    value = {
                        "items": [
                            {"id": item, "status": "complete", "report": f"{item} final"}
                            for item in items
                        ],
                        "summary": "repair recovered",
                    }
                else:
                    return 200, {"messages": []}
                return 200, {
                    "messages": [
                        {"structured_output_result": {"success": True, "value": value}}
                    ]
                }
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text(json.dumps(items), encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            server = CaptureServer(responder)
            with server:
                env = {
                    "MANUS_API_KEY": "key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_FILE_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_CREATE_INTERVAL_SECONDS": "0.1",
                    "MANUS_MAX_WAIT_SECONDS": "5",
                }
                failed = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "recover repair",
                    env=env,
                    cwd=root,
                )
                resumed = run_script(
                    "run_manus.sh", "--resume", str(manifest_path), env=env, cwd=root
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(failed.returncode, 4, failed.stderr)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["summary"], "repair recovered")
        self.assertEqual(state["create_count"], 4)
        self.assertEqual(
            [failure["id"] for failure in manifest["failed_task_attempts"]],
            ["repair-failed"],
        )
        self.assertEqual(manifest["fanout_tasks"]["ref-b"]["id"], "repair-retry")
        self.assertEqual(
            sum(role == "Manus Wide Research" for role in task_roles.values()),
            1,
        )

    def test_manus_resume_recreates_an_unusable_no_fallback_main_task(self) -> None:
        state = {"create_count": 0}

        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                state["create_count"] += 1
                task_id = "main-empty" if state["create_count"] == 1 else "main-retry"
                return 200, {"data": {"task_id": task_id}}
            if path.startswith("/task.detail?"):
                return 200, {"task": {"status": "stopped"}}
            if path.startswith("/task.listMessages?"):
                task_id = path.split("task_id=", 1)[1].split("&", 1)[0]
                if task_id == "main-empty":
                    return 200, {"messages": []}
                return 200, {
                    "messages": [
                        {
                            "structured_output_result": {
                                "success": True,
                                "value": {
                                    "items": [
                                        {
                                            "id": "ref-a",
                                            "status": "complete",
                                            "report": "A evidence",
                                        }
                                    ],
                                    "summary": "main recovered",
                                },
                            }
                        }
                    ]
                }
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text('["ref-a"]', encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            with CaptureServer(responder) as server:
                env = {
                    "MANUS_API_KEY": "key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_CREATE_INTERVAL_SECONDS": "0.1",
                    "MANUS_MAX_WAIT_SECONDS": "5",
                }
                empty = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--no-fallback",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "recover main",
                    env=env,
                    cwd=root,
                )
                resumed = run_script(
                    "run_manus.sh", "--resume", str(manifest_path), env=env, cwd=root
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(empty.returncode, 4, empty.stderr)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["summary"], "main recovered")
        self.assertEqual(state["create_count"], 2)
        self.assertEqual(manifest["failed_task_attempts"][0]["id"], "main-empty")

    def test_manus_resume_recreates_failed_synthesis_and_emits_validated_rows(self) -> None:
        state = {"create_count": 0, "upload_count": 0}
        server: CaptureServer

        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                state["create_count"] += 1
                task_id = {1: "item-ok", 2: "synthesis-failed", 3: "synthesis-retry"}[
                    state["create_count"]
                ]
                return 200, {"data": {"task_id": task_id}}
            if method == "POST" and path == "/file.upload":
                state["upload_count"] += 1
                file_id = f"synthesis-results-{state['upload_count']}"
                return 200, {
                    "file": {"id": file_id},
                    "upload_url": server.base_url + "/upload/" + file_id,
                }
            if method == "PUT" and path.startswith("/upload/synthesis-results-"):
                return 200, {}
            if path.startswith("/file.detail?"):
                return 200, {"file": {"status": "uploaded"}}
            if path.startswith("/task.detail?"):
                task_id = path.split("task_id=", 1)[1].split("&", 1)[0]
                status = "error" if task_id == "synthesis-failed" else "stopped"
                return 200, {"task": {"status": status}}
            if path.startswith("/task.listMessages?"):
                task_id = path.split("task_id=", 1)[1].split("&", 1)[0]
                if task_id == "item-ok":
                    value = {"id": "ref-a", "status": "complete", "report": "A evidence"}
                elif task_id == "synthesis-retry":
                    value = {
                        "items": [
                            {"id": "ref-a", "status": "complete", "report": "A final"}
                        ],
                        "summary": "synthesis recovered",
                    }
                else:
                    return 200, {"messages": []}
                return 200, {
                    "messages": [
                        {"structured_output_result": {"success": True, "value": value}}
                    ]
                }
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text('["ref-a"]', encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            server = CaptureServer(responder)
            with server:
                env = {
                    "MANUS_API_KEY": "key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_FILE_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_CREATE_INTERVAL_SECONDS": "0.1",
                    "MANUS_MAX_WAIT_SECONDS": "5",
                }
                failed = run_script(
                    "run_manus.sh",
                    "--fanout",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "recover synthesis",
                    env=env,
                    cwd=root,
                )
                resumed = run_script(
                    "run_manus.sh", "--resume", str(manifest_path), env=env, cwd=root
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertEqual(json.loads(failed.stdout)["items"][0]["id"], "ref-a")
        self.assertIn("Validated per-item results were emitted", failed.stderr)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["summary"], "synthesis recovered")
        self.assertEqual(state["create_count"], 3)
        self.assertEqual(manifest["failed_task_attempts"][0]["id"], "synthesis-failed")

    def test_manus_fanout_creates_one_task_per_item_then_one_synthesis(self) -> None:
        items = ["ref-a", "ref-b"]
        task_items: dict[str, str] = {}
        state = {"create_count": 0}
        server: CaptureServer

        def responder(method, path, payload):
            if method == "POST" and path == "/task.create":
                state["create_count"] += 1
                task_id = f"task-{state['create_count']}"
                if state["create_count"] <= len(items):
                    task_items[task_id] = payload["title"].split(": ", 1)[1]
                return 200, {"data": {"task_id": task_id}}
            if method == "POST" and path == "/file.upload":
                return 200, {
                    "file": {"id": "fanout-results"},
                    "upload_url": server.base_url + "/upload/fanout-results",
                }
            if method == "PUT" and path == "/upload/fanout-results":
                return 200, {}
            if path.startswith("/file.detail?"):
                return 200, {"file": {"status": "uploaded"}}
            if path.startswith("/task.detail?"):
                return 200, {"task": {"status": "stopped"}}
            if path.startswith("/task.listMessages?"):
                task_id = path.split("task_id=", 1)[1].split("&", 1)[0]
                if task_id in task_items:
                    item = task_items[task_id]
                    value = {"id": item, "status": "complete", "report": f"{item} evidence"}
                else:
                    value = {
                        "items": [
                            {"id": item, "status": "complete", "report": f"{item} final"}
                            for item in items
                        ],
                        "summary": "fanout synthesis",
                    }
                return 200, {
                    "messages": [
                        {"structured_output_result": {"success": True, "value": value}}
                    ]
                }
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text(json.dumps(items), encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            server = CaptureServer(responder)
            with server:
                result = run_script(
                    "run_manus.sh",
                    "--fanout",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "audit references",
                    env={
                        "MANUS_API_KEY": "fanout-key",
                        "MANUS_API_BASE": server.base_url,
                        "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                        "MANUS_FILE_POLL_INTERVAL_SECONDS": "0.1",
                        "MANUS_CREATE_INTERVAL_SECONDS": "0.1",
                        "MANUS_MAX_WAIT_SECONDS": "5",
                    },
                    cwd=root,
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["summary"], "fanout synthesis")
        self.assertEqual(state["create_count"], 3)
        self.assertEqual(set(manifest["fanout_tasks"]), set(items))
        self.assertEqual(manifest["synthesis_task"]["id"], "task-3")

    def test_manus_fanout_waiting_returns_waiting_and_resumes_without_recreating_item(self) -> None:
        state = {"create_count": 0, "item_status": "waiting"}
        server: CaptureServer

        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                state["create_count"] += 1
                task_id = "item-waiting" if state["create_count"] == 1 else "synthesis-ok"
                return 200, {"data": {"task_id": task_id}}
            if method == "POST" and path == "/file.upload":
                return 200, {
                    "file": {"id": "waiting-results"},
                    "upload_url": server.base_url + "/upload/waiting-results",
                }
            if method == "PUT" and path == "/upload/waiting-results":
                return 200, {}
            if path.startswith("/file.detail?"):
                return 200, {"file": {"status": "uploaded"}}
            if path.startswith("/task.detail?"):
                task_id = path.split("task_id=", 1)[1].split("&", 1)[0]
                status = state["item_status"] if task_id == "item-waiting" else "stopped"
                return 200, {"task": {"status": status}}
            if path.startswith("/task.listMessages?"):
                task_id = path.split("task_id=", 1)[1].split("&", 1)[0]
                if task_id == "item-waiting" and state["item_status"] == "waiting":
                    return 200, {"messages": []}
                if task_id == "item-waiting":
                    value = {"id": "ref-a", "status": "complete", "report": "A evidence"}
                else:
                    value = {
                        "items": [
                            {"id": "ref-a", "status": "complete", "report": "A final"}
                        ],
                        "summary": "continued after answer",
                    }
                return 200, {
                    "messages": [
                        {"structured_output_result": {"success": True, "value": value}}
                    ]
                }
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text('["ref-a"]', encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            server = CaptureServer(responder)
            with server:
                env = {
                    "MANUS_API_KEY": "key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_FILE_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_CREATE_INTERVAL_SECONDS": "0.1",
                    "MANUS_MAX_WAIT_SECONDS": "5",
                }
                waiting = run_script(
                    "run_manus.sh",
                    "--fanout",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "waiting fanout",
                    env=env,
                    cwd=root,
                )
                state["item_status"] = "stopped"
                resumed = run_script(
                    "run_manus.sh", "--resume", str(manifest_path), env=env, cwd=root
                )

        self.assertEqual(waiting.returncode, 3, waiting.stderr)
        self.assertEqual(json.loads(waiting.stdout)["waiting"], ["ref-a"])
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["summary"], "continued after answer")
        self.assertEqual(state["create_count"], 2)

    def test_manus_waiting_native_task_does_not_start_paid_fallback(self) -> None:
        state = {"create_count": 0, "remote_status": "waiting"}

        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                state["create_count"] += 1
                return 200, {"data": {"task_id": "wide-waiting"}}
            if path.startswith("/task.detail?"):
                return 200, {"task": {"status": state["remote_status"]}}
            if path.startswith("/task.listMessages?"):
                messages = []
                if state["remote_status"] == "stopped":
                    messages = [
                        {
                            "structured_output_result": {
                                "success": True,
                                "value": {
                                    "items": [
                                        {"id": "ref-a", "status": "complete", "report": "A"},
                                        {"id": "ref-b", "status": "complete", "report": "B"},
                                    ],
                                    "summary": "continued after answer",
                                },
                            }
                        }
                    ]
                return 200, {"messages": messages}
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text('["ref-a", "ref-b"]', encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            with CaptureServer(responder) as server:
                env = {
                    "MANUS_API_KEY": "wide-key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_CREATE_INTERVAL_SECONDS": "0.1",
                    "MANUS_MAX_WAIT_SECONDS": "5",
                }
                result = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "waiting test",
                    env=env,
                    cwd=root,
                )
                state["remote_status"] = "stopped"
                resumed = run_script(
                    "run_manus.sh",
                    "--resume",
                    str(manifest_path),
                    env=env,
                    cwd=root,
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["summary"], "continued after answer")
        self.assertEqual(state["create_count"], 1)
        self.assertEqual(manifest["state"], "complete")
        self.assertEqual(manifest["fanout_tasks"], {})

    def test_manus_wide_timeout_is_hard_bounded_and_resumable(self) -> None:
        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                return 200, {"data": {"task_id": "wide-running"}}
            if path.startswith("/task.detail?"):
                return 200, {"task": {"status": "running"}}
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text('["ref-a"]', encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            with CaptureServer(responder) as server:
                started = time.monotonic()
                result = run_script(
                    "run_manus.sh",
                    "--wide",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "timeout test",
                    env={
                        "MANUS_API_KEY": "wide-key",
                        "MANUS_API_BASE": server.base_url,
                        "MANUS_POLL_INTERVAL_SECONDS": "5",
                        "MANUS_MAX_WAIT_SECONDS": "0.05",
                    },
                    cwd=root,
                )
                elapsed = time.monotonic() - started
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertLess(elapsed, 2)
        self.assertIn("Resume with: run_manus.sh --resume", result.stderr)
        self.assertEqual(manifest["state"], "timed_out")
        self.assertEqual(manifest["main_task"]["id"], "wide-running")

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
                        "DEVIN_POLL_INTERVAL_SECONDS": "0.1",
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
        self.assertEqual(create[3]["secret_ids"], [])
        self.assertEqual(create[3]["knowledge_ids"], [])

    def test_devin_poll_request_cannot_outlive_remaining_wait_budget(self) -> None:
        def responder(method, path, _payload):
            if method == "POST" and path == "/sessions":
                return 200, {"session_id": "slow-session", "url": "https://devin/slow"}
            if method == "GET" and path == "/sessions/slow-session":
                time.sleep(3)
                return 200, {"status_enum": "running"}
            return 404, {"error": "unexpected"}

        with CaptureServer(responder) as server:
            started = time.monotonic()
            result = run_script(
                "run_devin.sh",
                "bounded poll",
                env={
                    "DEVIN_API_KEY": "key",
                    "DEVIN_API_BASE": server.base_url,
                    "DEVIN_POLL_INTERVAL_SECONDS": "0.1",
                    "DEVIN_MAX_WAIT_SECONDS": "1",
                },
            )
            elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertLess(elapsed, 2)
        self.assertIn("still running after 1s", result.stderr)

    def test_devin_create_request_cannot_outlive_wait_budget(self) -> None:
        def responder(method, path, _payload):
            if method == "POST" and path == "/sessions":
                time.sleep(3)
                return 200, {"session_id": "too-late"}
            return 404, {"error": "unexpected"}

        with CaptureServer(responder) as server:
            started = time.monotonic()
            result = run_script(
                "run_devin.sh",
                "bounded creation",
                env={
                    "DEVIN_API_KEY": "key",
                    "DEVIN_API_BASE": server.base_url,
                    "DEVIN_POLL_INTERVAL_SECONDS": "0.1",
                    "DEVIN_MAX_WAIT_SECONDS": "1",
                },
            )
            elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertLess(elapsed, 2)
        self.assertIn("session creation timed out after 1s", result.stderr.lower())

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

    def test_remote_runners_reject_zero_poll_intervals(self) -> None:
        manus = run_script(
            "run_manus.sh",
            "topic",
            env={
                "MANUS_API_KEY": "key",
                "MANUS_POLL_INTERVAL_SECONDS": "0",
                "MANUS_MAX_WAIT_SECONDS": "0",
            },
        )
        devin = run_script(
            "run_devin.sh",
            "task",
            env={
                "DEVIN_API_KEY": "key",
                "DEVIN_POLL_INTERVAL_SECONDS": "0",
                "DEVIN_MAX_WAIT_SECONDS": "0",
            },
        )

        self.assertEqual(manus.returncode, 2, manus.stderr)
        self.assertIn("at least 0.1", manus.stderr)
        self.assertNotEqual(devin.returncode, 0, devin.stderr)
        self.assertIn("at least 0.1 seconds", devin.stderr)


if __name__ == "__main__":
    unittest.main()
