#!/usr/bin/env python3
"""Hermetic transport tests for the optional provider convenience runners."""

from __future__ import annotations

import json
import os
import signal
import shutil
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


class SlowBody:
    def __init__(self, payload: object, interval: float = 0.1):
        self.encoded = json.dumps(payload).encode("utf-8")
        self.interval = interval


def run_script(
    name: str,
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path = REPO_ROOT,
    timeout: float = 15,
):
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
        timeout=timeout,
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
                slow_body = response if isinstance(response, SlowBody) else None
                if slow_body is not None:
                    encoded = slow_body.encoded
                    content_type = "application/json"
                elif isinstance(response, str):
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
                    if slow_body is None:
                        self.wfile.write(encoded)
                    else:
                        for byte in encoded:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(slow_body.interval)
                except (BrokenPipeError, ConnectionResetError):
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
            "printf '<%s>\\n' \"$@\"\n"
            "if [ \"$(basename \"$0\")\" = grok ]; then\n"
            "  if [ -n \"${XAI_API_KEY:-}\" ]; then printf 'provider-auth=<current>\\n'; fi\n"
            "  if [ -n \"${GROK_CODE_XAI_API_KEY:-}\" ]; then printf 'provider-auth=<legacy>\\n'; fi\n"
            "  case \"$(basename \"$GROK_SHELL\")\" in bash|zsh) TOOL_SHELL=$GROK_SHELL ;; *) TOOL_SHELL=/bin/bash ;; esac\n"
            "  printf 'tool-shell=<%s>\\n' \"$(basename \"$TOOL_SHELL\")\"\n"
            "  \"$TOOL_SHELL\" -lc 'printf '\"'\"'tool-current=<%s> tool-legacy=<%s>\\n'\"'\"' \"${XAI_API_KEY:-}\" \"${GROK_CODE_XAI_API_KEY:-}\"'\n"
            "  \"$TOOL_SHELL\" -lc 'if [ -r \"/proc/$PPID/environ\" ] && tr \"\\000\" \"\\n\" < \"/proc/$PPID/environ\" | grep -aEq \"^(XAI_API_KEY|GROK_CODE_XAI_API_KEY)=\"; then printf \"proc-parent-key=<visible>\\n\"; else printf \"proc-parent-key=<hidden>\\n\"; fi'\n"
            "  if printf 'forbidden\\n' > \"$PWD/grok-write-attempt\" 2>/dev/null; then\n"
            "    printf 'snapshot-write=<allowed>\\n'\n"
            "  else\n"
            "    printf 'snapshot-write=<blocked>\\n'\n"
            "  fi\n"
            "fi\n"
            "for file in \"${HOME:-}/.claude/settings.json\" \"${GROK_HOME:-}/requirements.toml\" \"${GROK_HOME:-}/sandbox.toml\"; do\n"
            "  if [ -f \"$file\" ]; then\n"
            "    while IFS= read -r line || [ -n \"$line\" ]; do printf 'config=<%s>\\n' \"$line\"; done < \"$file\"\n"
            "  fi\n"
            "done\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_killpg_hook(
        self,
        root: Path,
        *,
        forced_signal: signal.Signals,
    ) -> tuple[Path, Path, Path]:
        hook_dir = root / "python-hook"
        hook_dir.mkdir()
        signal_log = root / "killpg-signals.log"
        leader_kill_log = root / "leader-kill.log"
        (hook_dir / "sitecustomize.py").write_text(
            "import errno\n"
            "import os\n"
            "import signal\n"
            "import subprocess\n"
            f"_signal_log = {str(signal_log)!r}\n"
            f"_leader_kill_log = {str(leader_kill_log)!r}\n"
            f"_forced_signal = {int(forced_signal)}\n"
            "_real_killpg = os.killpg\n"
            "_real_popen_kill = subprocess.Popen.kill\n"
            "_forced = False\n"
            "def _killpg(pgid, signum):\n"
            "    global _forced\n"
            "    with open(_signal_log, 'a', encoding='utf-8') as handle:\n"
            "        handle.write(f'{signum}\\n')\n"
            "    if not _forced and signum == _forced_signal:\n"
            "        _forced = True\n"
            "        raise PermissionError(errno.EPERM, 'forced Darwin reap race')\n"
            "    return _real_killpg(pgid, signum)\n"
            "def _popen_kill(process):\n"
            "    with open(_leader_kill_log, 'a', encoding='utf-8') as handle:\n"
            "        handle.write(f'{process.pid}\\n')\n"
            "    return _real_popen_kill(process)\n"
            "os.killpg = _killpg\n"
            "subprocess.Popen.kill = _popen_kill\n",
            encoding="utf-8",
        )
        return hook_dir, signal_log, leader_kill_log

    def make_fugu_capture_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "OUTPUT_FILE=\n"
            "JSON_MODE=0\n"
            "PREVIOUS=\n"
            "for ARG in \"$@\"; do\n"
            "  if [ \"$PREVIOUS\" = \"--output-last-message\" ] || [ \"$PREVIOUS\" = \"-o\" ]; then OUTPUT_FILE=$ARG; fi\n"
            "  if [ \"$ARG\" = \"--json\" ]; then JSON_MODE=1; fi\n"
            "  PREVIOUS=$ARG\n"
            "done\n"
            "if [ \"$JSON_MODE\" = 1 ]; then\n"
            "  printf '{\"type\":\"thread.started\",\"thread_id\":\"019f0000-0000-7000-8000-000000000001\"}\\n'\n"
            "  {\n"
            "    printf 'No actionable findings\\n'\n"
            "    printf 'arg=<%s>\\n' \"$@\"\n"
            "  } > \"$OUTPUT_FILE\"\n"
            "  exit 0\n"
            "fi\n"
            "printf 'cwd=<%s>\\n' \"$PWD\"\n"
            "printf 'notice=<%s> update=<%s>\\n' \"$CODEX_FUGU_NO_NOTICE\" \"$CODEX_FUGU_NO_UPDATE\"\n"
            "printf 'unrelated-secret=<%s>\\n' \"${AWS_SECRET_ACCESS_KEY:-}\"\n"
            "printf 'arg=<%s>\\n' \"$@\"\n"
            "if [ -f _elves_review/change-context.txt ]; then\n"
            "  while IFS= read -r line || [ -n \"$line\" ]; do\n"
            "    printf 'evidence=<%s>\\n' \"$line\"\n"
            "  done < _elves_review/change-context.txt\n"
            "fi\n"
            "if [ -f untracked-context.txt ]; then\n"
            "  while IFS= read -r line || [ -n \"$line\" ]; do\n"
            "    printf 'context-file=<%s>\\n' \"$line\"\n"
            "  done < untracked-context.txt\n"
            "fi\n"
            "if printf 'forbidden\\n' > \"$PWD/fugu-write-attempt\" 2>/dev/null; then\n"
            "  printf 'snapshot-write=<allowed>\\n'\n"
            "else\n"
            "  printf 'snapshot-write=<blocked>\\n'\n"
            "fi\n"
            "/usr/bin/env -u SAKANA_API_KEY /bin/sh -c 'if [ -r \"/proc/$PPID/environ\" ] && tr \"\\000\" \"\\n\" < \"/proc/$PPID/environ\" | grep -aEq \"^SAKANA_API_KEY=\"; then printf \"proc-parent-key=<visible>\\n\"; else printf \"proc-parent-key=<hidden>\\n\"; fi'\n"
            "while IFS= read -r line || [ -n \"$line\" ]; do \n"
            "  printf 'prompt=<%s>\\n' \"$line\"\n"
            "done\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_staged_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "OUTPUT_FILE=\n"
            "IS_RESUME=0\n"
            "PREVIOUS=\n"
            "for ARG in \"$@\"; do\n"
            "  if [ \"$PREVIOUS\" = \"--output-last-message\" ] || [ \"$PREVIOUS\" = \"-o\" ]; then OUTPUT_FILE=$ARG; fi\n"
            "  if [ \"$ARG\" = \"resume\" ]; then IS_RESUME=1; fi\n"
            "  PREVIOUS=$ARG\n"
            "done\n"
            "if [ \"$IS_RESUME\" = 1 ]; then\n"
            "  {\n"
            "    printf 'No actionable findings\\n'\n"
            "    printf 'resume-arg=<%s>\\n' \"$@\"\n"
            "    while IFS= read -r LINE || [ -n \"$LINE\" ]; do printf 'synthesis=<%s>\\n' \"$LINE\"; done\n"
            "  } > \"$OUTPUT_FILE\"\n"
            "  exit 0\n"
            "fi\n"
            "while IFS= read -r LINE || [ -n \"$LINE\" ]; do :; done\n"
            "printf '{\"type\":\"thread.started\",\"thread_id\":\"019f0000-0000-7000-8000-000000000002\"}\\n'\n"
            "# External sandbox wrappers may normalize our intentional cutoff to status 1.\n"
            "trap 'exit 1' INT TERM\n"
            "while :; do sleep 1; done\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_stale_resume_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "OUTPUT_FILE=\n"
            "IS_RESUME=0\n"
            "PREVIOUS=\n"
            "for ARG in \"$@\"; do\n"
            "  if [ \"$PREVIOUS\" = \"--output-last-message\" ]; then OUTPUT_FILE=$ARG; fi\n"
            "  if [ \"$ARG\" = \"resume\" ]; then IS_RESUME=1; fi\n"
            "  PREVIOUS=$ARG\n"
            "done\n"
            "while IFS= read -r LINE || [ -n \"$LINE\" ]; do :; done\n"
            "if [ \"$IS_RESUME\" = 1 ]; then\n"
            "  printf '{\"type\":\"turn.completed\"}\\n'\n"
            "  exit 0\n"
            "fi\n"
            "printf 'STALE_EXPLORATION_MESSAGE\\n' > \"$OUTPUT_FILE\"\n"
            "printf '{\"type\":\"thread.started\",\"thread_id\":\"019f0000-0000-7000-8000-000000000003\"}\\n'\n"
            "printf '{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"STALE_EVENT_MESSAGE\"}}\\n'\n"
            "trap 'exit 1' INT TERM\n"
            "while :; do sleep 1; done\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_resume_timeout_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "IS_RESUME=0\n"
            "for ARG in \"$@\"; do [ \"$ARG\" = \"resume\" ] && IS_RESUME=1; done\n"
            "while IFS= read -r LINE || [ -n \"$LINE\" ]; do :; done\n"
            "if [ \"$IS_RESUME\" = 1 ]; then\n"
            "  trap '' INT TERM\n"
            "  sleep 10\n"
            "  exit 0\n"
            "fi\n"
            "printf '{\"type\":\"thread.started\",\"thread_id\":\"019f0000-0000-7000-8000-000000000004\"}\\n'\n"
            "trap 'exit 1' INT TERM\n"
            "while :; do sleep 1; done\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_descendant_fake(
        self,
        root: Path,
        *,
        delayed_write: bool = False,
        setsid: bool = False,
    ) -> Path:
        binary = root / "codex-fugu"
        if delayed_write:
            action = (
                "( /bin/sleep 2; printf 'late\\n' > \"$PWD/late-output.txt\" ) &"
            )
        elif setsid:
            action = (
                "/usr/bin/perl -MPOSIX -e "
                "'POSIX::setsid(); sleep 30' &"
            )
        else:
            action = "/bin/sleep 30 &"
        binary.write_text(
            "#!/bin/sh\n"
            "while IFS= read -r _LINE || [ -n \"$_LINE\" ]; do :; done\n"
            f"{action}\n"
            "CHILD=$!\n"
            "printf 'descendant-pid=<%s>\\n' \"$CHILD\"\n"
            + ("/bin/sleep 0.5\n" if setsid else "/bin/sleep 0.2\n")
            +
            "exit 0\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_runtime_growth_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "while IFS= read -r _LINE || [ -n \"$_LINE\" ]; do :; done\n"
            "/bin/dd if=/dev/zero of=\"$HOME/provider-growth.bin\" "
            "bs=4096 count=16 2>/dev/null\n"
            "/bin/sleep 5\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_final_runtime_growth_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "while IFS= read -r _LINE || [ -n \"$_LINE\" ]; do :; done\n"
            "COUNT=0\n"
            "while [ ! -e \"$HOME/.final-audit-ready\" ] && [ \"$COUNT\" -lt 300 ]; do\n"
            "  /bin/sleep 0.01\n"
            "  COUNT=$((COUNT + 1))\n"
            "done\n"
            "/bin/dd if=/dev/zero of=\"$HOME/provider-final-growth.bin\" "
            "bs=4096 count=1 2>/dev/null\n"
            "exit 0\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_runtime_special_file_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "while IFS= read -r _LINE || [ -n \"$_LINE\" ]; do :; done\n"
            "/usr/bin/mkfifo \"$HOME/provider-runtime.pipe\"\n"
            "/bin/sleep 5\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_adversarial_escape_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "printf 'provider-launched\\n'\n"
            "(/usr/bin/env -i /usr/bin/perl -MPOSIX -e "
            "'exit if fork(); POSIX::setsid(); exit if fork(); sleep 2') &\n"
            "exit 0\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_runtime_disappearance_hook(self, root: Path) -> Path:
        hook_dir = root / "runtime-race-hook"
        hook_dir.mkdir()
        (hook_dir / "sitecustomize.py").write_text(
            "import os\n"
            "import shutil\n"
            "import threading\n"
            "from pathlib import Path\n"
            "_real_open = os.open\n"
            "_race_identity = None\n"
            "_victim = None\n"
            "_removed = False\n"
            "def _open(path, flags, mode=0o777, *, dir_fd=None):\n"
            "    global _race_identity, _victim, _removed\n"
            "    candidate = Path(path) if dir_fd is None else None\n"
            "    if _race_identity is None and candidate is not None and candidate.name == 'home':\n"
            "        _victim = candidate / '.codex' / '.tmp' / 'plugins-clone-race' / 'agents'\n"
            "        _victim.mkdir(parents=True, exist_ok=True)\n"
            "        parent_info = _victim.parent.stat()\n"
            "        _race_identity = (parent_info.st_dev, parent_info.st_ino)\n"
            "    if path == 'agents' and dir_fd is not None and not _removed:\n"
            "        parent_info = os.fstat(dir_fd)\n"
            "        if (parent_info.st_dev, parent_info.st_ino) == _race_identity:\n"
            "            remover = threading.Thread(target=shutil.rmtree, args=(_victim,))\n"
            "            remover.start()\n"
            "            remover.join()\n"
            "            _removed = True\n"
            "    return _real_open(path, flags, mode, dir_fd=dir_fd)\n"
            "os.open = _open\n",
            encoding="utf-8",
        )
        return hook_dir

    def make_final_runtime_audit_hook(self, root: Path) -> Path:
        hook_dir = root / "final-runtime-audit-hook"
        hook_dir.mkdir()
        (hook_dir / "sitecustomize.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            "import cobbler_runtime.isolation as isolation\n"
            "_real_usage = isolation.provider_writable_tree_usage\n"
            "_calls = 0\n"
            "def _usage(roots):\n"
            "    global _calls\n"
            "    result = _real_usage(roots)\n"
            "    _calls += 1\n"
            "    if _calls == 2:\n"
            "        home = next(Path(root) for root in roots if Path(root).name == 'home')\n"
            "        (home / '.final-audit-ready').touch()\n"
            "    return result\n"
            "isolation.provider_writable_tree_usage = _usage\n",
            encoding="utf-8",
        )
        return hook_dir

    def make_missing_waitid_hook(self, root: Path) -> Path:
        hook_dir = root / "missing-waitid-hook"
        hook_dir.mkdir()
        (hook_dir / "sitecustomize.py").write_text(
            "import os\n"
            "if hasattr(os, 'waitid'):\n"
            "    del os.waitid\n",
            encoding="utf-8",
        )
        return hook_dir

    def make_fugu_oversized_event_line_fake(self, root: Path) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "while IFS= read -r _LINE || [ -n \"$_LINE\" ]; do :; done\n"
            "/bin/dd if=/dev/zero bs=1048577 count=1 2>/dev/null "
            "| /usr/bin/tr '\\000' x\n"
            "printf '\\n'\n"
            "printf '{\"type\":\"thread.started\","
            "\"thread_id\":\"019f0000-0000-7000-8000-000000000005\"}\\n'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_fugu_ultra_symlink_transport_fake(
        self,
        root: Path,
        outside: Path,
    ) -> Path:
        binary = root / "codex-fugu"
        binary.write_text(
            "#!/bin/sh\n"
            "IS_RESUME=0\n"
            "for ARG in \"$@\"; do [ \"$ARG\" = \"resume\" ] && IS_RESUME=1; done\n"
            "while IFS= read -r _LINE || [ -n \"$_LINE\" ]; do :; done\n"
            f"OUTSIDE={str(outside)!r}\n"
            "rm -f \"$TMPDIR/fugu-ultra-events.jsonl\" \"$TMPDIR/fugu-ultra-final.txt\"\n"
            "ln -s \"$OUTSIDE\" \"$TMPDIR/fugu-ultra-events.jsonl\"\n"
            "ln -s \"$OUTSIDE\" \"$TMPDIR/fugu-ultra-final.txt\"\n"
            "if [ \"$IS_RESUME\" = 1 ]; then\n"
            "  printf '%s\\n' '{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"SAFE_FINAL\"}}'\n"
            "  exit 0\n"
            "fi\n"
            "printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"019f0000-0000-7000-8000-000000000006\"}'\n"
            "trap 'exit 1' INT TERM\n"
            "while :; do sleep 1; done\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        return binary

    def make_supervision_failure_hook(self, root: Path) -> Path:
        hook_dir = root / "python-hook"
        hook_dir.mkdir()
        (hook_dir / "sitecustomize.py").write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            "import cobbler_runtime.dispatch_external as external\n"
            "async def _fail_supervision(_supervisor):\n"
            "    return {\n"
            "        'descendants_absent': False,\n"
            "        'descendants_found': [],\n"
            "        'supervision_error': 'forced-test-failure',\n"
            "    }\n"
            "external._terminate_supervised_descendants = _fail_supervision\n",
            encoding="utf-8",
        )
        return hook_dir

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
        self.assertIn("arg=<--dangerously-bypass-approvals-and-sandbox>", result.stdout)
        self.assertNotIn("arg=<--sandbox>", result.stdout)
        self.assertNotIn("arg=<--ask-for-approval>", result.stdout)
        self.assertRegex(result.stdout, r"arg=<--cd>\narg=<.*elves-iso-[^>]+/snapshot>")
        self.assertIn("arg=<exec>", result.stdout)
        self.assertIn("arg=<--skip-git-repo-check>", result.stdout)
        self.assertIn("arg=<--ephemeral>", result.stdout)
        self.assertIn("arg=<->", result.stdout)
        self.assertIn("prompt=<Review task: the auth flow>", result.stdout)
        self.assertIn("do not ask the caller to paste files", result.stdout)
        self.assertIn("proc-parent-key=<hidden>", result.stdout)
        self.assertIn("snapshot-write=<blocked>", result.stdout)
        self.assertNotIn("arg=<fugu-ultra", result.stdout)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_general_task_uses_task_appropriate_read_only_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "design a safer parser migration",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "prompt=<You are Sakana Fugu performing a bounded repository task.",
            result.stdout,
        )
        self.assertIn("prompt=<Task: design a safer parser migration>", result.stdout)
        self.assertIn("snapshot-write=<blocked>", result.stdout)
        self.assertNotIn("Return actionable findings first", result.stdout)
        self.assertNotIn('say exactly "No actionable findings"', result.stdout)

    @unittest.skipUnless(
        sys.platform == "darwin" and HAS_FS_SANDBOX,
        "Darwin filesystem sandbox unavailable",
    )
    def test_fugu_read_only_success_is_portable_without_os_waitid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            hook_dir = self.make_missing_waitid_hook(root)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "inspect portable read-only settlement",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "PYTHONPATH": str(hook_dir),
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("AttributeError", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    @unittest.skipUnless(
        HAS_FS_SANDBOX and sys.platform.startswith("linux"),
        "qualified writable Linux bwrap sandbox unavailable",
    )
    def test_fugu_authorized_write_exports_audited_handoff_without_host_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            temp_root = root / "tmp"
            temp_root.mkdir()
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "source.txt").write_text("host source\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "source.txt"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-q",
                    "-m",
                    "source",
                ],
                check=True,
            )
            result = run_script(
                "run_fugu.sh",
                "--write",
                "implement the requested change",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                    "TMPDIR": str(temp_root),
                },
                cwd=repo,
            )
            handoff_line = next(
                line
                for line in result.stderr.splitlines()
                if line.startswith("Fugu isolated-write handoff: ")
            )
            handoff = Path(
                handoff_line.removeprefix("Fugu isolated-write handoff: ").split(
                    " (", 1
                )[0]
            )
            manifest = json.loads(
                (handoff / "manifest.json").read_text(encoding="utf-8")
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("snapshot-write=<allowed>", result.stdout)
            self.assertIn("not automatically applied", handoff_line)
            self.assertEqual(manifest["kind"], "elves-fugu-isolated-write-handoff")
            self.assertFalse(manifest["automatically_applied"])
            self.assertEqual(manifest["metadata"]["mode"], "task")
            self.assertEqual(
                [(item["path"], item["status"]) for item in manifest["changes"]],
                [("fugu-write-attempt", "added")],
            )
            self.assertEqual(
                (handoff / "files" / "fugu-write-attempt").read_text(
                    encoding="utf-8"
                ),
                "forbidden\n",
            )
            self.assertFalse((repo / "fugu-write-attempt").exists())
            self.assertEqual(
                (repo / "source.txt").read_text(encoding="utf-8"), "host source\n"
            )
            shutil.rmtree(handoff)

    @unittest.skipUnless(
        sys.platform == "darwin" and HAS_FS_SANDBOX,
        "Darwin filesystem sandbox unavailable",
    )
    def test_fugu_success_descendant_is_reaped_and_result_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_descendant_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "inspect descendants",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
                # CI host load can stretch sandbox setup + generation-safe
                # settlement past the default 15s hermetic budget.
                timeout=45,
            )
            match = next(
                line for line in result.stdout.splitlines()
                if line.startswith("descendant-pid=<")
            )
            descendant_pid = int(match.removeprefix("descendant-pid=<").removesuffix(">"))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("live descendants", result.stderr)
        with self.assertRaises(ProcessLookupError):
            os.kill(descendant_pid, 0)

    @unittest.skipUnless(
        sys.platform == "darwin" and HAS_FS_SANDBOX,
        "Darwin filesystem sandbox unavailable",
    )
    def test_fugu_setsid_descendant_is_observed_and_reaped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_descendant_fake(bin_dir, setsid=True)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "inspect setsid descendants",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
                timeout=45,
            )
            match = next(
                line for line in result.stdout.splitlines()
                if line.startswith("descendant-pid=<")
            )
            descendant_pid = int(match.removeprefix("descendant-pid=<").removesuffix(">"))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("live descendants", result.stderr)
        with self.assertRaises(ProcessLookupError):
            os.kill(descendant_pid, 0)

    @unittest.skipUnless(sys.platform == "darwin", "Darwin-only containment policy")
    def test_fugu_write_refuses_fast_scrubbed_double_fork_before_provider_launch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_adversarial_escape_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "--write",
                "attempt delayed write",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("qualified recursive process containment", result.stderr)
        self.assertNotIn("provider-launched", result.stdout)
        self.assertNotIn("Fugu isolated-write handoff:", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_live_runtime_growth_limit_terminates_read_only_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_runtime_growth_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "grow runtime state",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_RUNTIME_MAX_GROWTH_BYTES": "1024",
                    "SAKANA_FUGU_RUNTIME_MAX_FILE_BYTES": "2048",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("live resource budget", result.stderr)
        self.assertNotIn("Fugu isolated-write handoff:", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_final_runtime_audit_catches_growth_after_last_poll(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_final_runtime_growth_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            hook_dir = self.make_final_runtime_audit_hook(root)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "write immediately before exit",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "PYTHONPATH": str(hook_dir),
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_RUNTIME_MAX_GROWTH_BYTES": "1",
                    "SAKANA_FUGU_RUNTIME_MAX_FILE_BYTES": "8192",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("live resource budget", result.stderr)
        self.assertIn("grew by", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_live_runtime_scan_tolerates_concurrent_subtree_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            hook_dir = self.make_runtime_disappearance_hook(root)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "inspect runtime race handling",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "PYTHONPATH": str(hook_dir),
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("runtime audit failed closed", result.stderr)
        self.assertNotIn("live resource budget", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_live_runtime_type_failure_is_not_mislabeled_as_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_runtime_special_file_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "create unsupported runtime type",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("runtime audit failed closed", result.stderr)
        self.assertIn("unsupported file type", result.stderr)
        self.assertNotIn("exceeded its live resource budget", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_ultra_event_parser_rejects_oversized_line_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_oversized_event_line_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "--ultra",
                "inspect bounded events",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_MAX_WAIT_SECONDS": "6",
                    "SAKANA_FUGU_ULTRA_EXPLORE_SECONDS": "1",
                    "SAKANA_FUGU_RUNTIME_MAX_FILE_BYTES": str(2 * 1024 * 1024),
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("fugu_ultra_event_line_limit", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_ultra_symlink_transport_cannot_read_or_mutate_outside_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            outside = root / "outside-sentinel.txt"
            outside.write_text("OUTSIDE_SECRET_SENTINEL\n", encoding="utf-8")
            self.make_fugu_ultra_symlink_transport_fake(bin_dir, outside)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "--ultra",
                "inspect adversarial output transport",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_MAX_WAIT_SECONDS": "3",
                    "SAKANA_FUGU_ULTRA_EXPLORE_SECONDS": "0.8",
                },
                cwd=repo,
            )
            outside_after = outside.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("fugu_ultra_output_file_invalid", result.stderr)
        self.assertNotIn("OUTSIDE_SECRET_SENTINEL", result.stdout + result.stderr)
        self.assertEqual(outside_after, "OUTSIDE_SECRET_SENTINEL\n")

    def test_fugu_mode_and_context_errors_fail_before_provider_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
            env = {
                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                "SAKANA_API_KEY": "test-sakana-key",
            }

            missing_task = run_script("run_fugu.sh", env=env, cwd=repo)
            review_write = run_script(
                "run_fugu.sh", "--write", "review", env=env, cwd=repo
            )
            forbidden_context = run_script(
                "run_fugu.sh",
                "--include",
                ".env.local",
                "inspect context",
                env=env,
                cwd=repo,
            )

        self.assertEqual(missing_task.returncode, 2)
        self.assertIn("a general Fugu task is required", missing_task.stderr)
        self.assertEqual(review_write.returncode, 2)
        self.assertIn("review mode is always read-only", review_write.stderr)
        self.assertEqual(forbidden_context.returncode, 2)
        self.assertIn("isolation_requested_path_forbidden", forbidden_context.stderr)

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
        self.assertIn("arg=<--model>\narg=<fugu-ultra-v1.1>", ultra.stdout)
        self.assertIn('arg=<model_reasoning_effort="high">', ultra.stdout)
        self.assertIn("arg=<--json>", ultra.stdout)
        self.assertIn("arg=<--output-last-message>", ultra.stdout)
        self.assertNotIn("arg=<--ephemeral>", ultra.stdout)
        self.assertIn("Fugu Ultra exploration phase", ultra.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_ultra_resumes_exact_session_for_bounded_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_staged_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "--ultra",
                "review",
                "exact resume",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_MAX_WAIT_SECONDS": "3",
                    "SAKANA_FUGU_ULTRA_EXPLORE_SECONDS": "0.8",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No actionable findings", result.stdout)
        self.assertIn("resume-arg=<resume>", result.stdout)
        self.assertIn(
            "resume-arg=<019f0000-0000-7000-8000-000000000002>",
            result.stdout,
        )
        self.assertIn("synthesis=<The bounded exploration phase is over", result.stdout)
        self.assertIn(
            "synthesis=<browse, run commands, or inspect more files", result.stdout
        )
        self.assertIn("Fugu Ultra exploration phase: up to 0.8s", result.stderr)
        self.assertIn("Fugu Ultra exact-session synthesis phase", result.stderr)
        self.assertNotIn("--last", result.stdout + result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_ultra_rejects_exploration_without_synthesis_reserve(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "--ultra",
                "review invalid budget",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_MAX_WAIT_SECONDS": "1",
                    "SAKANA_FUGU_ULTRA_EXPLORE_SECONDS": "1",
                },
                cwd=repo,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be finite, positive, and at most", result.stderr)
        self.assertIn("cleanup and synthesis retain reserved wall time", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_ultra_never_emits_stale_exploration_message_after_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_stale_resume_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "--ultra",
                "review stale output",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_MAX_WAIT_SECONDS": "3",
                    "SAKANA_FUGU_ULTRA_EXPLORE_SECONDS": "0.8",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("STALE_EXPLORATION_MESSAGE", result.stdout)
        self.assertNotIn("STALE_EVENT_MESSAGE", result.stdout)
        self.assertIn("completed without a final message", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_ultra_resume_timeout_includes_bounded_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_resume_timeout_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            started = time.monotonic()
            result = run_script(
                "run_fugu.sh",
                "--ultra",
                "review bounded timeout",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_MAX_WAIT_SECONDS": "4",
                    "SAKANA_FUGU_ULTRA_EXPLORE_SECONDS": "0.8",
                },
                cwd=repo,
            )
            elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 124, result.stderr)
        # Elapsed includes tracked-snapshot and sandbox bootstrap outside the
        # provider process-group deadline; allow loaded macOS runner overhead
        # while staying below the fake resume process's ten-second sleep.
        self.assertLess(
            elapsed,
            8.0,
            f"bounded Ultra shutdown took {elapsed:.3f}s",
        )
        self.assertIn("staged wall budget", result.stderr)

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
            deleted_safe = repo / "deleted.txt"
            deleted_excluded = repo / ".netrc"
            safe.write_text("safe baseline\n", encoding="utf-8")
            excluded.write_text("SECRET_BASELINE_MUST_NOT_CROSS\n", encoding="utf-8")
            deleted_safe.write_text("SAFE_DELETION_MARKER\n", encoding="utf-8")
            deleted_excluded.write_text(
                "SECRET_DELETION_MARKER_MUST_NOT_CROSS\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "-C", str(repo), "add", "safe.txt", ".env", "deleted.txt", ".netrc"],
                check=True,
            )
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "baseline"], check=True)
            safe.write_text("SAFE_DIFF_MARKER\n", encoding="utf-8")
            excluded.write_text("SECRET_DIFF_MARKER_MUST_NOT_CROSS\n", encoding="utf-8")
            deleted_safe.unlink()
            deleted_excluded.unlink()
            result = run_script(
                "run_fugu.sh",
                "review",
                "filtered changes",
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
        self.assertIn("SAFE_DELETION_MARKER", result.stdout)
        self.assertIn("diff --git a/deleted.txt b/deleted.txt", result.stdout)
        self.assertNotIn("SECRET_DELETION_MARKER_MUST_NOT_CROSS", result.stdout)
        self.assertNotIn("diff --git a/.netrc", result.stdout)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_selected_untracked_context_is_available_without_prompt_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fugu_capture_fake(bin_dir)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            target = repo / "untracked-context.txt"
            target.write_text("SELECTED_UNTRACKED_CONTEXT\n", encoding="utf-8")
            result = run_script(
                "run_fugu.sh",
                "--include",
                str(target),
                "analyze the selected context",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "SAKANA_API_KEY": "test-sakana-key",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("context-file=<SELECTED_UNTRACKED_CONTEXT>", result.stdout)
        self.assertIn("prompt=<Task: analyze the selected context>", result.stdout)
        self.assertNotIn("prompt=<SELECTED_UNTRACKED_CONTEXT>", result.stdout)
        self.assertIn("1 non-ignored untracked", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_fugu_enforces_finite_hard_wall_clock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            sleeper = bin_dir / "codex-fugu"
            sleeper.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
            sleeper.chmod(0o755)
            self.make_fake(bin_dir, "codex")
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            env = {
                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                "SAKANA_API_KEY": "test-sakana-key",
                "SAKANA_FUGU_MAX_WAIT_SECONDS": "2",
            }
            started = time.monotonic()
            timed_out = run_script("run_fugu.sh", "review", env=env, cwd=repo)
            elapsed = time.monotonic() - started
            env["SAKANA_FUGU_MAX_WAIT_SECONDS"] = "nan"
            non_finite = run_script("run_fugu.sh", "review", env=env, cwd=repo)

        self.assertEqual(timed_out.returncode, 124, timed_out.stderr)
        # The wrapper includes tracked-snapshot and sandbox bootstrap time,
        # but must still finish well before the fake's ten-second sleep.
        self.assertLess(elapsed, 8.0)
        self.assertIn("terminating it", timed_out.stderr)
        self.assertNotEqual(non_finite.returncode, 0)
        self.assertIn("must be finite and positive", non_finite.stderr)

    @unittest.skipUnless(
        sys.platform == "darwin" and HAS_FS_SANDBOX,
        "Darwin filesystem sandbox unavailable",
    )
    def test_fugu_timeout_uses_native_cleanup_without_numeric_group_signal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            sleeper = bin_dir / "codex-fugu"
            sleeper.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
            sleeper.chmod(0o755)
            self.make_fake(bin_dir, "codex")
            hook_dir, signal_log, leader_kill_log = self.make_killpg_hook(
                root,
                forced_signal=signal.SIGTERM,
            )
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "review",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "PYTHONPATH": str(hook_dir),
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_MAX_WAIT_SECONDS": "2",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("terminating it", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(signal_log.exists())
        self.assertFalse(leader_kill_log.exists())

    @unittest.skipUnless(
        sys.platform == "darwin" and HAS_FS_SANDBOX,
        "Darwin filesystem sandbox unavailable",
    )
    def test_fugu_read_only_timeout_does_not_claim_recursive_containment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            sleeper = bin_dir / "codex-fugu"
            sleeper.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
            sleeper.chmod(0o755)
            self.make_fake(bin_dir, "codex")
            hook_dir = self.make_supervision_failure_hook(root)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = run_script(
                "run_fugu.sh",
                "review",
                env={
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "PYTHONPATH": str(hook_dir),
                    "SAKANA_API_KEY": "test-sakana-key",
                    "SAKANA_FUGU_MAX_WAIT_SECONDS": "0.2",
                },
                cwd=repo,
            )

        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertNotIn("descendant absence", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    @unittest.skipUnless(HAS_FS_SANDBOX, "qualified filesystem sandbox unavailable")
    def test_grok_uses_read_only_checked_key_scrubbed_non_bypass_mode(self) -> None:
        for env_name, expected_auth in (
            ("XAI_API_KEY", "current"),
            ("GROK_CODE_XAI_API_KEY", "legacy"),
        ):
            with self.subTest(env_name=env_name), tempfile.TemporaryDirectory() as tmpdir:
                bin_dir = Path(tmpdir)
                self.make_fake(bin_dir, "grok")
                result = run_script(
                    "run_grok.sh",
                    "inspect",
                    "this",
                    env={
                        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                        "XAI_API_KEY": "",
                        "GROK_CODE_XAI_API_KEY": "",
                        env_name: "test-xai-key",
                        "AWS_SECRET_ACCESS_KEY": "must-not-cross",
                    },
                )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("unrelated-secret=<>", result.stdout)
            self.assertIn(f"provider-auth=<{expected_auth}>", result.stdout)
            self.assertIn("tool-shell=<bash>", result.stdout)
            self.assertIn("tool-current=<> tool-legacy=<>", result.stdout)
            self.assertIn("proc-parent-key=<hidden>", result.stdout)
            self.assertIn("snapshot-write=<blocked>", result.stdout)
            self.assertIn("<--single=inspect this>", result.stdout)
            self.assertIn('config=<    "defaultMode": "dontAsk">', result.stdout)
            self.assertIn("config=<disable_bypass_permissions_mode = true>", result.stdout)
            self.assertNotIn("config=<read_only = [", result.stdout)
            self.assertNotIn("<--permission-mode>", result.stdout)
            self.assertIn("<--effort>", result.stdout)
            self.assertIn("<high>", result.stdout)
            self.assertIn("<--check>", result.stdout)
            self.assertIn("<--sandbox>", result.stdout)
            self.assertIn("<strict>", result.stdout)
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
        self.assertEqual(create[3]["message"]["connectors"], [])
        self.assertEqual(create[3]["message"]["enable_skills"], [])
        self.assertEqual(create[3]["message"]["force_skills"], [])
        self.assertNotIn("connectors", create[3])
        self.assertNotIn("enable_skills", create[3])
        self.assertNotIn("force_skills", create[3])

    def test_manus_create_slow_drip_cannot_outlive_wait_budget(self) -> None:
        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                return 200, SlowBody(
                    {"ok": True, "data": {"task_id": "too-late", "task_url": "https://manus/late"}}
                )
            return 404, {"error": "unexpected"}

        with CaptureServer(responder) as server:
            started = time.monotonic()
            result = run_script(
                "run_manus.sh",
                "bounded slow response",
                env={
                    "MANUS_API_KEY": "key",
                    "MANUS_API_BASE": server.base_url,
                    "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                    "MANUS_MAX_WAIT_SECONDS": "1",
                },
            )
            elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertLess(elapsed, 2)
        self.assertIn("hard wall-clock timeout", result.stderr)

    def test_manus_upload_slow_drip_cannot_outlive_wait_budget(self) -> None:
        server: CaptureServer

        def responder(method, path, _payload):
            if method == "POST" and path == "/file.upload":
                return 200, {
                    "ok": True,
                    "data": {
                        "file": {"id": "slow-file"},
                        "upload_url": server.base_url + "/upload/slow-file",
                    },
                }
            if method == "PUT" and path == "/upload/slow-file":
                return 200, SlowBody({"ok": True, "padding": "slow-response"})
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.pdf"
            source.write_bytes(b"source bytes")
            server = CaptureServer(responder)
            with server:
                started = time.monotonic()
                result = run_script(
                    "run_manus.sh",
                    "--file",
                    str(source),
                    "bounded upload",
                    env={
                        "MANUS_API_KEY": "key",
                        "MANUS_API_BASE": server.base_url,
                        "MANUS_FILE_POLL_INTERVAL_SECONDS": "0.1",
                        "MANUS_MAX_WAIT_SECONDS": "1",
                    },
                )
                elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertLess(elapsed, 2)
        self.assertNotIn("/task.create", [request[1] for request in server.requests])

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
        self.assertEqual(payload["message"]["connectors"], [])
        self.assertEqual(payload["message"]["enable_skills"], [])
        self.assertEqual(payload["message"]["force_skills"], [])
        self.assertNotIn("connectors", payload)
        self.assertNotIn("enable_skills", payload)
        self.assertNotIn("force_skills", payload)
        self.assertIn("structured_output_schema", payload)
        self.assertEqual(
            payload["message"]["content"][1],
            {"type": "file", "file_id": "source-file"},
        )
        self.assertIn(
            "exactly one independent research subagent",
            payload["message"]["content"][0]["text"],
        )

    def test_manus_create_intent_prevents_ambiguous_resume_duplication(self) -> None:
        observed_pending: list[object] = []
        manifest_path: Path

        def responder(method, path, _payload):
            if method == "POST" and path == "/task.create":
                current = json.loads(manifest_path.read_text(encoding="utf-8"))
                observed_pending.append(current.get("pending_create"))
                return 200, {"data": {"task_id": "fanout-created"}}
            return 404, {"error": "unexpected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items_path = root / "items.json"
            items_path.write_text('["ref-a"]', encoding="utf-8")
            manifest_path = root / ".elves" / "runtime" / "manus" / "manifest.json"
            server = CaptureServer(responder)
            env = {
                "MANUS_API_KEY": "intent-key",
                "MANUS_API_BASE": server.base_url,
                "MANUS_CREATE_INTERVAL_SECONDS": "0.1",
                "MANUS_POLL_INTERVAL_SECONDS": "0.1",
                "MANUS_MAX_WAIT_SECONDS": "0",
            }
            with server:
                created = run_script(
                    "run_manus.sh",
                    "--fanout",
                    "--items-file",
                    str(items_path),
                    "--manifest",
                    str(manifest_path),
                    "audit ref-a",
                    env=env,
                    cwd=root,
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertIsNone(manifest["pending_create"])
                manifest["fanout_tasks"] = {}
                manifest["pending_create"] = {
                    "role": "fanout",
                    "item_id": "ref-a",
                    "started_at": int(time.time()),
                }
                manifest["state"] = "creating"
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                request_count = len(server.requests)
                resumed = run_script(
                    "run_manus.sh",
                    "--resume",
                    str(manifest_path),
                    env=env,
                    cwd=root,
                )

        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(len(observed_pending), 1)
        self.assertIsInstance(observed_pending[0], dict)
        self.assertEqual(observed_pending[0]["role"], "fanout")
        self.assertEqual(observed_pending[0]["item_id"], "ref-a")
        self.assertIsInstance(observed_pending[0]["started_at"], int)
        self.assertEqual(resumed.returncode, 2, resumed.stderr)
        self.assertIn("ambiguous in-flight Manus task creation", resumed.stderr)
        self.assertIn("refuses to create a duplicate", resumed.stderr)
        self.assertEqual(len(server.requests), request_count)

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

    def test_manus_refuses_in_repo_alias_to_repo_before_upload(self) -> None:
        def responder(_method, _path, _payload):
            return 500, {"error": "no provider request expected"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items = root / "items.json"
            items.write_text('["ref-a"]', encoding="utf-8")
            source = root / "private-source.pdf"
            source.write_bytes(b"must not be uploaded through a repo alias")
            alias = root / "alias"
            alias.symlink_to(root, target_is_directory=True)
            manifest = alias / ".elves" / "runtime" / "manus" / "alias.json"
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
        self.assertFalse((root / ".elves" / "runtime" / "manus" / "alias.json").exists())

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

    def test_devin_create_slow_drip_cannot_outlive_wait_budget(self) -> None:
        def responder(method, path, _payload):
            if method == "POST" and path == "/sessions":
                return 200, SlowBody({"session_id": "too-late", "url": "https://devin/late"})
            return 404, {"error": "unexpected"}

        with CaptureServer(responder) as server:
            started = time.monotonic()
            result = run_script(
                "run_devin.sh",
                "bounded slow creation",
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
