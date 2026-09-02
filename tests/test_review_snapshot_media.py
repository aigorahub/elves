"""Read-only review snapshots omit oversized media; every other path fails closed.

Course repositories carry large MP4, WAV, FLAC, and PPTX files. Before this policy
one oversized tracked file failed the whole shared isolation snapshot, so Fugu and
Grok review never started. The snapshot now omits oversized binary media in
read-only lanes, records each omission in the context manifest, and keeps
fail-closed behavior for source, prose instructions, executable agent
configuration, and explicit ``--include`` paths.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.isolation import (  # noqa: E402
    IsolationSpec,
    OmittedContextFile,
    classify_oversized_media,
    context_bundle_report,
    create_tracked_snapshot,
    oversized_media_remediation,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402


LIMIT = 1024


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)


def _commit_all(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "-m", "fixture"],
        check=True,
    )


def _write_big(path: Path, size: int = LIMIT * 4) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return size


def _manifest(lane) -> dict:
    return json.loads(
        (lane.snapshot / "_elves_context" / "manifest.json").read_text(encoding="utf-8")
    )


class OversizedMediaClassificationTests(unittest.TestCase):
    def test_media_categories_cover_video_audio_presentation_archive(self) -> None:
        self.assertEqual(classify_oversized_media("assets/lesson.mp4"), "video")
        self.assertEqual(classify_oversized_media("assets/lesson.MOV"), "video")
        self.assertEqual(classify_oversized_media("audio/take.wav"), "audio")
        self.assertEqual(classify_oversized_media("audio/take.flac"), "audio")
        self.assertEqual(classify_oversized_media("decks/day1.pptx"), "presentation")
        self.assertEqual(classify_oversized_media("bundle.zip"), "archive")
        self.assertEqual(classify_oversized_media("shot.png"), "image")

    def test_source_and_prose_are_never_media(self) -> None:
        for rel in (
            "scripts/run.py",
            "README.md",
            "AGENTS.md",
            "diagram.svg",
            "Makefile",
            "notes.mp4.md",
            "data.json",
        ):
            self.assertIsNone(classify_oversized_media(rel), rel)

    def test_remediation_names_a_derived_artifact_and_keeps_the_limit(self) -> None:
        text = oversized_media_remediation("a/lesson.mp4", 20_000_000, 16 * 1024 * 1024)
        self.assertIn("transcript", text)
        self.assertIn("20000000 bytes", text)
        self.assertIn("not raised", text)


class ReadOnlySnapshotOmissionTests(unittest.TestCase):
    def _lane(self, repo: Path, **kwargs):
        return create_tracked_snapshot(
            IsolationSpec(
                repo_root=repo,
                lane_id="review-media",
                max_context_file_bytes=LIMIT,
                **kwargs,
            )
        )

    def test_oversized_video_is_omitted_and_review_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            size = _write_big(repo / "assets" / "lesson.mp4")
            (repo / "app.py").write_text("print(1)\n", encoding="utf-8")
            _commit_all(repo)

            lane = self._lane(repo)
            try:
                self.assertFalse((lane.snapshot / "assets" / "lesson.mp4").exists())
                self.assertTrue((lane.snapshot / "app.py").is_file())
                self.assertEqual(len(lane.omitted_context_files), 1)
                record = lane.omitted_context_files[0]
                self.assertEqual(record["path"], "assets/lesson.mp4")
                self.assertEqual(record["bytes"], size)
                self.assertEqual(record["category"], "video")
                self.assertEqual(record["reason"], "oversized_binary_media")
                self.assertEqual(record["limit_bytes"], LIMIT)
                self.assertIn("transcript", record["remediation"])
            finally:
                lane.cleanup()

    def test_audio_presentation_and_archive_categories_are_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            _write_big(repo / "audio" / "take.wav")
            _write_big(repo / "audio" / "master.flac")
            _write_big(repo / "decks" / "day1.pptx")
            _write_big(repo / "dist" / "bundle.zip")
            (repo / "app.py").write_text("print(1)\n", encoding="utf-8")
            _commit_all(repo)

            lane = self._lane(repo)
            try:
                categories = {
                    item["path"]: item["category"] for item in lane.omitted_context_files
                }
                self.assertEqual(
                    categories,
                    {
                        "audio/take.wav": "audio",
                        "audio/master.flac": "audio",
                        "decks/day1.pptx": "presentation",
                        "dist/bundle.zip": "archive",
                    },
                )
                self.assertEqual(lane.tracked_file_count, 1)
            finally:
                lane.cleanup()

    def test_oversized_source_still_fails_closed_with_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            _write_big(repo / "generated.py")
            _commit_all(repo)

            with self.assertRaises(ValidationIssue) as ctx:
                self._lane(repo)
            self.assertEqual(ctx.exception.code, "isolation_context_file_too_large")
            self.assertIn("derived text", ctx.exception.hint or "")

    def test_oversized_prose_instruction_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            _write_big(repo / "AGENTS.md")
            _commit_all(repo)

            with self.assertRaises(ValidationIssue) as ctx:
                self._lane(repo, include_instructions_as_data=True)
            self.assertEqual(ctx.exception.code, "isolation_context_file_too_large")

    def test_executable_agent_config_is_excluded_not_omitted_as_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            _write_big(repo / ".mcp.json")
            (repo / "app.py").write_text("print(1)\n", encoding="utf-8")
            _commit_all(repo)

            lane = self._lane(repo)
            try:
                self.assertFalse((lane.snapshot / ".mcp.json").exists())
                self.assertEqual(lane.omitted_context_files, [])
                reasons = {
                    item["path"]: item["reason"] for item in lane.context_diagnostics
                }
                self.assertEqual(reasons[".mcp.json"], "executable_agent_config")
            finally:
                lane.cleanup()

    def test_explicit_include_of_oversized_media_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            _write_big(repo / "assets" / "lesson.mp4")
            _commit_all(repo)

            with self.assertRaises(ValidationIssue) as ctx:
                self._lane(repo, include_paths=("assets/lesson.mp4",))
            self.assertEqual(ctx.exception.code, "isolation_context_file_too_large")
            self.assertIn("transcript", ctx.exception.hint or "")

    def test_writable_lane_keeps_fail_closed_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            _write_big(repo / "assets" / "lesson.mp4")
            _commit_all(repo)

            with self.assertRaises(ValidationIssue) as ctx:
                self._lane(repo, snapshot_writable=True)
            self.assertEqual(ctx.exception.code, "isolation_context_file_too_large")

    def test_policy_can_be_switched_off_per_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            _write_big(repo / "assets" / "lesson.mp4")
            _commit_all(repo)

            with self.assertRaises(ValidationIssue) as ctx:
                self._lane(repo, omit_oversized_media=False)
            self.assertEqual(ctx.exception.code, "isolation_context_file_too_large")

    def test_general_limit_is_unchanged(self) -> None:
        from cobbler_runtime.isolation import DEFAULT_CONTEXT_MAX_FILE_BYTES

        self.assertEqual(DEFAULT_CONTEXT_MAX_FILE_BYTES, 16 * 1024 * 1024)

    def test_media_under_the_limit_is_copied_normally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            small = repo / "assets" / "thumb.png"
            small.parent.mkdir(parents=True)
            small.write_bytes(b"\x00" * 32)
            _commit_all(repo)

            lane = self._lane(repo)
            try:
                self.assertTrue((lane.snapshot / "assets" / "thumb.png").is_file())
                self.assertEqual(lane.omitted_context_files, [])
            finally:
                lane.cleanup()


class ContextManifestReportingTests(unittest.TestCase):
    def test_manifest_records_path_bytes_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            size = _write_big(repo / "assets" / "lesson.mp4")
            _write_big(repo / "audio" / "take.wav")
            (repo / "app.py").write_text("print(1)\n", encoding="utf-8")
            _commit_all(repo)

            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="manifest-media",
                    max_context_file_bytes=LIMIT,
                )
            )
            try:
                manifest = _manifest(lane)
                self.assertTrue(manifest["omit_oversized_media"])
                self.assertEqual(manifest["max_context_file_bytes"], LIMIT)
                self.assertEqual(manifest["omitted_file_count"], 2)
                self.assertEqual(manifest["omitted_bytes"], size * 2)
                by_path = {item["path"]: item for item in manifest["omitted_files"]}
                self.assertEqual(
                    sorted(by_path), ["assets/lesson.mp4", "audio/take.wav"]
                )
                self.assertEqual(by_path["assets/lesson.mp4"]["bytes"], size)
                self.assertEqual(
                    by_path["assets/lesson.mp4"]["reason"], "oversized_binary_media"
                )
                self.assertIn(
                    "transcript", by_path["assets/lesson.mp4"]["remediation"]
                )
                omitted_diagnostics = [
                    item
                    for item in manifest["diagnostics"]
                    if item["status"] == "omitted"
                ]
                self.assertEqual(len(omitted_diagnostics), 2)
                self.assertEqual(
                    omitted_diagnostics[0]["reason"], "oversized_binary_media:video"
                )
            finally:
                lane.cleanup()

    def test_manifest_stays_private_and_inside_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            _write_big(repo / "assets" / "lesson.mp4")
            _commit_all(repo)

            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="manifest-mode",
                    max_context_file_bytes=LIMIT,
                )
            )
            try:
                manifest_path = lane.snapshot / "_elves_context" / "manifest.json"
                self.assertEqual(
                    lane.context_manifest_path, "_elves_context/manifest.json"
                )
                self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o600)
            finally:
                lane.cleanup()


class CrossHarnessParityTests(unittest.TestCase):
    """One snapshot policy and one preamble for every supported harness."""

    HOST_LABELS = ("Fugu", "Grok", "omp", "Claude Code")

    def test_every_harness_reports_the_same_omission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            size = _write_big(repo / "assets" / "lesson.mp4")
            (repo / "app.py").write_text("print(1)\n", encoding="utf-8")
            _commit_all(repo)

            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="parity",
                    max_context_file_bytes=LIMIT,
                )
            )
            try:
                for label in self.HOST_LABELS:
                    lines = context_bundle_report(lane, label=label)
                    body = "\n".join(lines)
                    self.assertIn(f"{label} context bundle:", body)
                    self.assertIn("assets/lesson.mp4", body)
                    self.assertIn(str(size), body)
                    self.assertIn("the review continues without them", body)
                    self.assertIn("transcript", body)
            finally:
                lane.cleanup()

    def test_every_harness_shares_one_default_spec(self) -> None:
        spec = IsolationSpec(repo_root=Path("."), lane_id="defaults")
        self.assertTrue(spec.omit_oversized_media)
        self.assertFalse(spec.snapshot_writable)

    def test_runner_sources_use_the_shared_report(self) -> None:
        root = SCRIPTS.parent
        for rel, label in (
            ("scripts/run_grok.sh", "Grok"),
            ("scripts/run_omp.sh", "omp"),
        ):
            body = (root / rel).read_text(encoding="utf-8")
            self.assertIn("context_bundle_report", body, rel)
            self.assertIn(f'label="{label}"', body, rel)

        fugu = (root / "scripts" / "cobbler_runtime" / "fugu.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("context_bundle_report", fugu)

        dispatch = (
            root / "scripts" / "cobbler_runtime" / "dispatch_external.py"
        ).read_text(encoding="utf-8")
        self.assertIn("omitted_context_files", dispatch)


class OmittedContextFileRecordTests(unittest.TestCase):
    def test_record_serializes_with_remediation(self) -> None:
        record = OmittedContextFile(
            path="a/b.wav",
            bytes=99,
            category="audio",
            reason="oversized_binary_media",
            limit_bytes=10,
        )
        payload = record.to_dict()
        self.assertEqual(payload["path"], "a/b.wav")
        self.assertEqual(payload["bytes"], 99)
        self.assertEqual(payload["category"], "audio")
        self.assertEqual(payload["limit_bytes"], 10)
        self.assertIn("derived text", payload["remediation"])
        # JSON-serializable for the context manifest.
        json.dumps(payload)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
