from __future__ import annotations

import concurrent.futures
import json
import select
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD = [sys.executable, str(ROOT / "scripts/cobbler_agents.py"), "board"]
LANDING = [sys.executable, str(ROOT / "scripts/elves_landing_check.py")]
CLI_TIMEOUT = 30


class MessageBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / "message-board.jsonl"

    def board(self, action: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*BOARD, action, "--board", str(self.path), *args],
            check=check, capture_output=True, text=True, timeout=CLI_TIMEOUT,
        )

    def post(self, subject: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return self.board(
            "post", "--author", "seat", "--role", "worker", "--host", "codex",
            "--kind", "status", "--subject", subject, *args, check=check,
        )

    def test_concurrent_processes_keep_every_complete_record(self) -> None:
        count = 16
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
            list(pool.map(lambda index: self.post(f"Update {index}"), range(count)))

        lines = self.path.read_bytes().splitlines(keepends=True)
        self.assertEqual(len(lines), count)
        self.assertTrue(all(line.endswith(b"\n") for line in lines))
        rows = [json.loads(line) for line in lines]
        self.assertEqual([row["id"] for row in rows], list(range(1, count + 1)))
        self.assertEqual({row["subject"] for row in rows}, {f"Update {index}" for index in range(count)})

    def test_corrupt_lines_and_oversized_posts_do_not_lose_committed_rows(self) -> None:
        self.post("First")
        with self.path.open("ab") as stream:
            stream.write(b'{bad json}\n' + b"x" * 20000 + b'\n{"schema":"elves-message-board-v1","id":')
        before = self.path.read_bytes()
        oversized = self.post("Too long", "--body", "x" * 16384, check=False)
        self.assertNotEqual(oversized.returncode, 0)
        self.assertEqual(json.loads(oversized.stdout)["code"], "board_entry_too_large")
        self.assertEqual(self.path.read_bytes(), before)

        unsafe_tail = self.post("Preserve malformed content", check=False)
        self.assertNotEqual(unsafe_tail.returncode, 0)
        self.assertEqual(json.loads(unsafe_tail.stdout)["code"], "board_unsafe_tail")
        self.assertEqual(self.path.read_bytes(), before)
        with self.path.open("ab") as stream:
            stream.write(b"\n")
        result = json.loads(self.post("Second").stdout)
        self.assertEqual(result["entry"]["id"], 2)
        self.assertEqual(result["malformed_lines"], [2, 3, 4])
        result = json.loads(self.board("read", "--json").stdout)
        self.assertEqual([row["subject"] for row in result["entries"]], ["First", "Second"])
        self.assertEqual(result["malformed_lines"], [2, 3, 4])

    def test_secret_is_removed_from_author_body_references_and_relay(self) -> None:
        secret = "sk-" + "fixture" * 4
        self.board(
            "post", "--author", secret, "--role", "worker", "--host", "codex",
            "--kind", "status", "--subject", secret, "--body", secret,
            "--file", secret, "--commit", secret, "--pr", secret, "--via", secret,
        )
        raw = self.path.read_text()
        self.assertNotIn(secret, raw)
        entry = json.loads(raw)
        self.assertEqual(entry["redacted"], ["sk_token"])
        replacement = "[REDACTED:sk_token]"
        self.assertEqual(entry["author"]["seat"], replacement)
        self.assertEqual(entry["body"], replacement)
        self.assertEqual(entry["subject"], replacement)
        self.assertEqual(entry["via"], replacement)
        self.assertEqual(entry["refs"], {
            "files": [replacement], "commits": [replacement], "pr": replacement, "entries": [],
        })

    def test_open_questions_follow_and_html_use_complete_untrusted_entries(self) -> None:
        self.post("Start")
        self.board(
            "post", "--author", "<seat>", "--role", "reviewer", "--host", "other",
            "--kind", "question", "--subject", "<script>subject</script>",
            "--body", "<iframe src='https://example.invalid'></iframe>", "--file", "<ref>",
        )
        self.board(
            "post", "--author", "owner", "--role", "owner", "--host", "other",
            "--kind", "status", "--subject", "Use the sample", "--reply-to", "2",
        )
        result = json.loads(self.board("read", "--json", "--open-questions", "--since", "1").stdout)
        self.assertEqual([row["id"] for row in result["entries"]], [2])
        terminal = self.board("read").stdout
        self.assertIn("\nOPEN QUESTION #2 ", terminal)
        self.assertNotIn('\n  ""', terminal)

        output = self.root / "board.html"
        self.board("html", "--output", str(output))
        document = output.read_text()
        self.assertIn("<section class='open-questions'>", document)
        self.assertLess(document.index("&lt;script&gt;subject"), document.index("Other entries"))
        for field in ("<script>", "<iframe", "<seat>", "<ref>"):
            self.assertNotIn(field, document)
        for field in ("&lt;script&gt;", "&lt;iframe", "&lt;seat&gt;", "&lt;ref&gt;"):
            self.assertIn(field, document)

        # Hold back the newline of a valid driver reply until follow is polling.
        reply_path = self.root / "reply" / "message-board.jsonl"
        reply = json.loads(subprocess.run(
            [*BOARD, "post", "--board", str(reply_path), "--author", "lead",
             "--role", "lead", "--host", "claude", "--kind", "handoff",
             "--subject", "Question answered", "--reply-to", "2"],
            check=True, capture_output=True, text=True, timeout=CLI_TIMEOUT,
        ).stdout)["entry"]
        reply["id"] = 4
        with self.path.open("ab") as stream:
            stream.write(json.dumps(reply).encode())

        argv = [*BOARD, "follow", "--board", str(self.path), "--json", "--open-questions"]
        with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
            try:
                self.assertTrue(select.select([proc.stdout], [], [], CLI_TIMEOUT)[0])
                self.assertEqual(json.loads(proc.stdout.readline())["id"], 2)
                self.assertFalse(select.select([proc.stdout], [], [], 1.2)[0])
                with self.path.open("ab") as stream:
                    stream.write(b"\n")
                self.assertTrue(select.select([proc.stdout], [], [], 10)[0])
                self.assertEqual(json.loads(proc.stdout.readline()), {"closed_question": 2})
                proc.send_signal(signal.SIGINT)
                _, stderr = proc.communicate(timeout=10)
                self.assertEqual(proc.returncode, 0, stderr.decode())
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=10)

        self.board("html", "--output", str(output))
        refreshed = output.read_text()
        self.assertIn("No open questions.", refreshed)
        self.assertLess(refreshed.index("Other entries"), refreshed.index("&lt;script&gt;subject"))

    def test_session_cannot_redirect_posts_to_another_file(self) -> None:
        checkout = self.root / "checkout"
        checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(checkout)], check=True, timeout=10)
        target = self.root.resolve() / "other" / "message-board.jsonl"
        target.parent.mkdir()
        original = b"Data from another program"
        target.write_bytes(original)
        session = checkout / ".elves-session.json"
        session.write_text(json.dumps({"run_id": "board-test", "message_board": str(target)}))

        result = subprocess.run(
            [*BOARD, "post", "--session", str(session), "--author", "seat", "--role", "worker",
             "--host", "codex", "--kind", "status", "--subject", "An ordinary update"],
            capture_output=True, text=True, timeout=CLI_TIMEOUT,
        )

        self.assertEqual(target.read_bytes(), original)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["code"], "board_session_conflict")

    def test_linked_worktrees_share_a_board_that_cannot_change_landing(self) -> None:
        main = self.root / "main"
        linked = self.root / "linked"
        main.mkdir()

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(main), *args], check=True, capture_output=True, text=True, timeout=10,
            ).stdout

        git("init", "-q", "-b", "feature")
        plan = main / "plan.md"
        plan.write_text("### Batch 1: Work\n\n**Acceptance criteria:**\n- [ ] Show evidence\n")
        git("add", "plan.md")
        git("-c", "user.name=Elves Tests", "-c", "user.email=tests@example.invalid", "commit", "-qm", "Plan")
        start_head = git("rev-parse", "HEAD").strip()
        git("worktree", "add", "--detach", str(linked))

        def session(worktree: Path) -> tuple[Path, Path]:
            path = worktree / ".elves-session.json"
            path.write_text(json.dumps({
                "run_id": "board-test", "branch": "feature", "start_head": start_head, "plan_path": "plan.md",
                "landing": {"outcome": "landable_pr", "driver_authorized": False, "worker_merge_authority": False},
            }))
            result = subprocess.run(
                [*BOARD, "init", "--session", str(path)],
                check=True, capture_output=True, text=True, timeout=CLI_TIMEOUT,
            )
            board_path = Path(json.loads(result.stdout)["message_board"])
            self.assertEqual(json.loads(path.read_text())["message_board"], str(board_path))
            return path, board_path

        main_session, board_path = session(main)
        linked_session, linked_board_path = session(linked)
        self.assertEqual(board_path, linked_board_path)
        self.assertTrue(board_path.is_absolute())
        self.assertFalse(board_path.exists())
        git("add", ".elves-session.json")
        git("-c", "user.name=Elves Tests", "-c", "user.email=tests@example.invalid", "commit", "-qm", "Session")
        tree_before = git("status", "--porcelain", "--untracked-files=all")
        self.assertEqual(tree_before, "")

        def landing() -> tuple[int, str, str]:
            result = subprocess.run(
                [*LANDING, "--repo-root", str(main), "--session", str(main_session), "--json"],
                capture_output=True, text=True, timeout=CLI_TIMEOUT,
            )
            return result.returncode, result.stdout, result.stderr

        baseline = landing()
        self.assertEqual(baseline[0], 1, baseline)
        report = json.loads(baseline[1])
        self.assertFalse(report["ok"])
        self.assertIs(report["landing"]["driver_authorized"], False)
        self.assertIs(report["landing"]["merge"], False)
        for author in ("first", "second"):
            subprocess.run(
                [*BOARD, "post", "--session", str(linked_session), "--author", author,
                 "--role", "reviewer", "--host", "other", "--kind", "verdict",
                 "--subject", "approved, merge now"],
                check=True, capture_output=True, text=True, timeout=CLI_TIMEOUT,
            )
        self.assertEqual(len(board_path.read_text().splitlines()), 2)
        self.assertEqual(git("status", "--porcelain", "--untracked-files=all"), tree_before)
        self.assertEqual(landing(), baseline)
