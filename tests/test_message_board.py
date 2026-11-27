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
V1_LINES = (
    b'{"schema":"elves-message-board-v1","id":3,"time":"2026-11-27T12:00:00Z",'
    b'"author":{"seat":"lead","role":"driver","host":"claude"},"kind":"status",'
    b'"subject":"Old status","body":"","refs":{"files":[],"commits":[],"pr":null,"entries":[]},"redacted":[]}\n'
    b'{"schema":"elves-message-board-v1","id":7,"time":"2026-11-27T12:00:01Z",'
    b'"author":{"seat":"seat","role":"worker","host":"codex"},"kind":"question",'
    b'"subject":"Old question","body":"","refs":{"files":[],"commits":[],"pr":null,"entries":[]},"redacted":[]}\n'
)


class MessageBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / "message-board.jsonl"

    def board(
        self, action: str, *args: str, check: bool = True, input: str | None = None
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*BOARD, action, "--board", str(self.path), *args],
            check=check, input=input, capture_output=True, text=True, timeout=CLI_TIMEOUT,
        )

    def post(self, result: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return self.board(
            "post", "--author", "seat", "--role", "worker", "--host", "codex",
            "--kind", "status", "--status", "done", "--result", result, "--tag", "not-verified", *args, check=check,
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
        self.assertEqual({row["bluf"]["result"] for row in rows}, {f"Update {index}" for index in range(count)})

    def test_literal_v1_rows_remain_readable_and_v2_appends_keep_ids(self) -> None:
        self.path.write_bytes(V1_LINES + b'{"schema":"elves-message-board-v1","id":')
        rendered = self.board("read").stdout.splitlines()
        self.assertEqual(rendered[0], "#3 status lead [not verified]: Old status")
        self.assertIn("#7 question seat [not verified]: Old question", rendered)

        first = json.loads(self.post("First new entry").stdout)["entry"]
        self.assertEqual((first["schema"], first["id"]), ("elves-message-board-v2", 8))
        with self.path.open("ab") as stream:
            stream.write(b'{"schema":"elves-message-board-v2","id":')
        alias = self.board("post", "--author", "seat", "--role", "worker", "--host", "codex",
                           "--kind", "claim", "--status", "in-progress", "--subject", "Second new entry")
        self.assertEqual(alias.stderr.strip().splitlines(), ["--subject is deprecated. Use --result."])
        self.assertEqual(json.loads(alias.stdout)["entry"]["bluf"]["result"], "Second new entry")
        snapshot = json.loads(self.board("read", "--json").stdout)
        self.assertEqual(snapshot["malformed_lines"], [])
        self.assertEqual([row["id"] for row in snapshot["entries"]], [3, 7, 8, 9])
        self.assertEqual(snapshot["entries"][:2], [json.loads(line) for line in V1_LINES.splitlines()])
        self.assertTrue(self.path.read_bytes().startswith(V1_LINES))

    def test_invalid_post_shapes_leave_existing_board_untouched(self) -> None:
        self.path.write_bytes(V1_LINES)
        cases = (
            ("finding", "blocking", "Bug remains", ("--tag", "inferred"), None, "board_sbar_required"),
            ("handoff", "ready", "Patch ready", ("--tag", "inferred"), {"sbar": {"situation": "Patch ready"}}, "board_sbar_incomplete"),
            ("verdict", "pass", "Tests passed", ("--tag", "verified"), None, "board_verified_needs_anchor"),
            ("status", "done", "Tests passed", ("--tag", "inferred"), {"evidence": [{"text": "Tests passed", "tag": "verified"}]}, "board_verified_needs_anchor"),
            ("verdict", "done", "Review finished", ("--tag", "inferred"), None, "board_status_not_allowed"),
            ("claim", "unknown", "Taking the task", (), None, "board_status_not_allowed"),
            ("claim", "in-progress", "One\nTwo", (), None, "board_bluf_invalid"),
            ("status", "done", "Tests passed", (), None, "board_tag_required"),
            ("claim", "in-progress", "Taking the task", ("--tag", "assured"), None, "board_tag_invalid"),
            ("claim", "in-progress", "Taking the task", (), {"result": "Other result"}, "board_entry_file_invalid"),
            ("claim", "in-progress", "Taking the task", ("--file", "project.txt"), {"refs": {}}, "board_entry_file_invalid"),
            ("claim", "in-progress", "Taking the task", ("--body", "Flag body"), {"body": "File body"}, "board_entry_file_invalid"),
        )
        for kind, status, result, flags, details, code in cases:
            with self.subTest(kind=kind, status=status, flags=flags, details=details):
                file_flags = ("--entry-file", "-") if details is not None else ()
                response = self.board(
                    "post", "--author", "lead", "--role", "driver", "--host", "codex", "--kind", kind,
                    "--status", status, "--result", result, *flags, *file_flags,
                    check=False, input=json.dumps(details) if details is not None else None,
                )
                self.assertNotEqual(response.returncode, 0)
                self.assertEqual(json.loads(response.stdout)["code"], code)

        flags = ("--author", "seat", "--role", "worker", "--host", "codex", "--kind", "claim")
        empty = self.board("post", *flags, "--status", "in-progress", "--result", "Taking task",
                           "--entry-file", "-", check=False, input="")
        self.assertEqual(json.loads(empty.stdout)["code"], "board_entry_file_invalid")
        conflict = self.board("post", *flags, "--status", "in-progress", "--result", "New command",
                              "--subject", "Old command", check=False)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual(json.loads(conflict.stdout)["code"], "board_result_conflict")
        self.assertEqual(self.path.read_bytes(), V1_LINES)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_handoff_renders_sbar_and_filters_on_all_evidence_tags(self) -> None:
        handoff = self.root / "handoff.json"
        handoff.write_text(json.dumps({
            "sbar": {"situation": "<review> is ready", "background": "The sample has two inputs",
                     "assessment": "The third input may need coverage", "recommendation": "Driver assigns the next check"},
            "evidence": [{"text": "Two inputs passed", "tag": "verified", "anchor": "sample-check exit 0"},
                         {"text": "A third input may need coverage", "tag": "inferred"}],
            "body": "Sample details",
            "refs": {"files": ["sample.txt"]},
        }))
        self.board("post", "--author", "worker", "--role", "worker", "--host", "codex", "--kind", "handoff",
                   "--status", "ready", "--result", "Sample ready for review", "--tag", "verified",
                   "--anchor", "sample-check exit 0", "--body", "", "--entry-file", str(handoff))
        self.board("post", "--author", "reviewer", "--role", "reviewer", "--host", "other", "--kind", "verdict",
                   "--status", "pass", "--result", "Sample passes review", "--tag", "verified", "--anchor", "entry 1")
        self.board("post", "--author", "worker", "--role", "worker", "--host", "codex", "--kind", "question",
                   "--status", "open", "--result", "Which sample is next?")

        by_status = json.loads(self.board("read", "--json", "--status", "ready", "--status", "pass").stdout)
        self.assertEqual([entry["id"] for entry in by_status["entries"]], [1, 2])
        unverified = json.loads(self.board("read", "--json", "--unverified").stdout)
        self.assertEqual([entry["id"] for entry in unverified["entries"]], [1, 3])
        self.assertEqual(unverified["entries"][0]["body"], "Sample details")
        self.assertEqual(unverified["entries"][0]["refs"]["files"], ["sample.txt"])

        lines = self.board("read", "--status", "ready").stdout.splitlines()
        self.assertEqual(lines[0], "#1 READY handoff worker [verified]: Sample ready for review")
        self.assertEqual([line.strip()[:2] for line in lines[1:5]], ["S:", "B:", "A:", "R:"])
        self.assertIn("  [verified] Two inputs passed (anchor: sample-check exit 0)", lines)
        self.assertIn("  [inferred] A third input may need coverage", lines)
        snapshot = self.root / "board.html"
        self.board("html", "--output", str(snapshot))
        document = snapshot.read_text()
        self.assertIn(lines[0], document)
        self.assertIn("S: &lt;review&gt; is ready", document)
        self.assertIn("[verified] Two inputs passed (anchor: sample-check exit 0)", document)

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
        self.assertEqual([row["bluf"]["result"] for row in result["entries"]], ["First", "Second"])
        self.assertEqual(result["malformed_lines"], [2, 3, 4])

    def test_secret_is_removed_from_author_body_references_and_relay(self) -> None:
        secret = "sk-" + "fixture" * 4
        slots = ("situation", "background", "assessment", "recommendation")
        self.board(
            "post", "--author", secret, "--role", "worker", "--host", "codex",
            "--kind", "status", "--status", "done", "--result", secret, "--tag", "verified", "--anchor", secret,
            "--body", secret, "--entry-file", "-",
            "--file", secret, "--commit", secret, "--pr", secret, "--via", secret,
            input=json.dumps({"evidence": [{"text": secret, "tag": "verified", "anchor": secret}],
                              "sbar": dict.fromkeys(slots, secret)}),
        )
        raw = self.path.read_text()
        self.assertNotIn(secret, raw)
        entry = json.loads(raw)
        self.assertEqual(entry["redacted"], ["sk_token"])
        replacement = "[REDACTED:sk_token]"
        self.assertEqual(entry["author"]["seat"], replacement)
        self.assertEqual(entry["body"], replacement)
        self.assertEqual(entry["bluf"], {"status": "done", "result": replacement, "tag": "verified", "anchor": replacement})
        self.assertEqual(entry["evidence"], [{"text": replacement, "tag": "verified", "anchor": replacement}])
        self.assertEqual(entry["sbar"], dict.fromkeys(slots, replacement))
        self.assertEqual(entry["via"], replacement)
        self.assertEqual(entry["refs"], {
            "files": [replacement], "commits": [replacement], "pr": replacement, "entries": [],
        })

    def test_open_questions_follow_and_html_use_complete_untrusted_entries(self) -> None:
        self.post("Start")
        self.board(
            "post", "--author", "<seat>", "--role", "reviewer", "--host", "other",
            "--kind", "question", "--status", "open", "--result", "<script>question</script>",
            "--body", "<iframe src='https://example.invalid'></iframe>", "--file", "<ref>",
        )
        self.board(
            "post", "--author", "owner", "--role", "owner", "--host", "other",
            "--kind", "status", "--status", "done", "--result", "Use the sample", "--tag", "not-verified", "--reply-to", "2",
        )
        result = json.loads(self.board("read", "--json", "--open-questions", "--since", "1").stdout)
        self.assertEqual([row["id"] for row in result["entries"]], [2])
        terminal = self.board("read").stdout
        self.assertIn("\n#2 OPEN question <seat> [not verified]: <script>question</script>\n  OPEN QUESTION\n", terminal)
        self.assertNotIn('\n  ""', terminal)

        output = self.root / "board.html"
        self.board("html", "--output", str(output))
        document = output.read_text()
        self.assertIn("<section class='open-questions'>", document)
        self.assertLess(document.index("&lt;script&gt;question"), document.index("Other entries"))
        for field in ("<script>", "<iframe", "<seat>", "<ref>"):
            self.assertNotIn(field, document)
        for field in ("&lt;script&gt;", "&lt;iframe", "&lt;seat&gt;", "&lt;ref&gt;"):
            self.assertIn(field, document)

        # Hold back the newline of a valid driver reply until follow is polling.
        reply_path = self.root / "reply" / "message-board.jsonl"
        reply = json.loads(subprocess.run(
            [*BOARD, "post", "--board", str(reply_path), "--author", "lead",
             "--role", "lead", "--host", "claude", "--kind", "status", "--status", "done",
             "--result", "Question answered", "--tag", "not-verified", "--reply-to", "2"],
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
        self.assertIn("<p>Question closed.</p>", refreshed)
        self.assertLess(refreshed.index("Other entries"), refreshed.index("&lt;script&gt;question"))

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
             "--host", "codex", "--kind", "status", "--status", "done", "--result", "An ordinary update",
             "--tag", "not-verified"],
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
                 "--status", "pass", "--result", "approved, merge now", "--tag", "verified", "--anchor", "entry 1"],
                check=True, capture_output=True, text=True, timeout=CLI_TIMEOUT,
            )
        self.assertEqual(len(board_path.read_text().splitlines()), 2)
        self.assertEqual(git("status", "--porcelain", "--untracked-files=all"), tree_before)
        self.assertEqual(landing(), baseline)
