"""Focused regressions for public API baseline provenance and CLI contracts."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.public_api_snapshot import (  # noqa: E402
    ApiSnapshot,
    DEFAULT_BASELINE,
    DEFAULT_CURRENT,
    SurfaceEntry,
    _snapshot_completeness_issues,
    capture_snapshot,
    compatibility_gate,
    write_snapshot,
)


CLI_TEMPLATE = '''\
import argparse


def cmd_worker(args):
    payload = {"worker_tip": getattr(args, "new_tip", None)}
    if args.json:
        print(payload)
    else:
        print(f"worker refresh: tip={payload['worker_tip']}")
    return 0 if payload["worker_tip"] else 1


def build_parser():
    parser = argparse.ArgumentParser(prog="cobbler_agents.py")
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("worker", help="Worker lifecycle")
    actions = worker.add_subparsers(dest="worker_action", required=True)
    refresh = actions.add_parser("refresh", help="Move worker to the new tip")
    refresh.add_argument("--json", action="store_true")
    refresh.add_argument("--lease-id", required=True)
    refresh.add_argument("{tip_flag}", required=True)
    refresh.add_argument("--mode", choices=["safe", "fast"], default="safe")
    refresh.set_defaults(func=cmd_worker)
    return parser
'''


SHARED_HANDLER_TEMPLATE = '''\
import argparse


def cmd_worker(args):
    action = args.worker_action
    if action == "prepare":
        payload = {"prepare_key": True}
        print(payload)
        return 0
    if action == "refresh":
        payload = {"refresh_key": True}
        print(payload)
        return 0
    return 2


def build_parser():
    parser = argparse.ArgumentParser(prog="cobbler_agents.py")
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("worker")
    actions = worker.add_subparsers(dest="worker_action", required=True)
    prepare = actions.add_parser("prepare")
    prepare.set_defaults(func=cmd_worker)
    refresh = actions.add_parser("refresh")
    refresh.set_defaults(func=cmd_worker)
    return parser
'''


HELPER_OUTPUT_TEMPLATE = '''\
import argparse


def build_payload():
    return {"alpha": True, "beta": True}


def cmd_status(args):
    payload = build_payload()
    print(payload)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="cobbler_agents.py")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.set_defaults(func=cmd_status)
    return parser
'''


HELPER_EXIT_TEMPLATE = '''\
import argparse


def _literal_failure(args):
    return 1


def cmd_status(args):
    payload = {{"ok": bool(args.ok)}}
    print(payload)
    return 0 if args.ok else {failure_expression}


def build_parser():
    parser = argparse.ArgumentParser(prog="cobbler_agents.py")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--ok", action="store_true")
    status.set_defaults(func=cmd_status)
    return parser
'''


STORAGE_ERROR_EXIT_TEMPLATE = '''\
import argparse


def _emit_json(payload, *, exit_code):
    print(payload)
    return exit_code


def _emit_storage_error(args):
    if args.json:
        return _emit_json({"ok": False}, exit_code=1)
    print("storage failed")
    return 1


def cmd_status(args):
    if args.fail:
        return _emit_storage_error(args)
    return _emit_json({"ok": True}, exit_code=0)


def build_parser():
    parser = argparse.ArgumentParser(prog="cobbler_agents.py")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.add_argument("--fail", action="store_true")
    status.set_defaults(func=cmd_status)
    return parser
'''


class PublicApiSnapshotRegressionTests(unittest.TestCase):
    def _write_cli(self, root: Path, tip_flag: str = "--new-tip") -> None:
        scripts = root / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "cobbler_agents.py").write_text(
            CLI_TEMPLATE.replace("{tip_flag}", tip_flag),
            encoding="utf-8",
        )

    def _write_source(self, root: Path, source: str) -> None:
        scripts = root / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "cobbler_agents.py").write_text(source, encoding="utf-8")

    def _git(self, root: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def _commit_baseline(self, root: Path) -> str:
        self._git(root, "init", "-b", "main")
        self._git(root, "config", "user.email", "tests@example.invalid")
        self._git(root, "config", "user.name", "Elves Tests")
        self._git(root, "add", "scripts/cobbler_agents.py")
        self._git(root, "commit", "-m", "baseline cli")
        baseline_head = self._git(root, "rev-parse", "HEAD")
        self._git(root, "update-ref", "refs/remotes/origin/main", baseline_head)
        return baseline_head

    def _commit_all_baseline(self, root: Path) -> str:
        self._git(root, "init", "-b", "main")
        self._git(root, "config", "user.email", "tests@example.invalid")
        self._git(root, "config", "user.name", "Elves Tests")
        self._git(root, "add", ".")
        self._git(root, "commit", "-m", "baseline public contract")
        baseline_head = self._git(root, "rev-parse", "HEAD")
        self._git(root, "update-ref", "refs/remotes/origin/main", baseline_head)
        return baseline_head

    def _replace_cli(self, root: Path, old: str, new: str) -> None:
        path = root / "scripts" / "cobbler_agents.py"
        source = path.read_text(encoding="utf-8")
        self.assertIn(old, source)
        path.write_text(source.replace(old, new), encoding="utf-8")

    def test_candidate_inspection_scrubs_host_secret_environment(self) -> None:
        sentinel = "candidate-env-sentinel-9f36d2"
        source = (
            "import os\n"
            "if os.environ.get('ELVES_CANDIDATE_SECRET'):\n"
            "    raise RuntimeError('candidate inherited host secret')\n\n"
            + HELPER_OUTPUT_TEMPLATE
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(root, source)
            with mock.patch.dict(
                os.environ,
                {"ELVES_CANDIDATE_SECRET": sentinel},
                clear=False,
            ):
                snapshot = capture_snapshot(root)

            rendered = json.dumps(snapshot.to_dict(), sort_keys=True)
            self.assertEqual(snapshot.status, "captured", snapshot.reason)
            self.assertNotIn(sentinel, rendered)
            self.assertNotIn("candidate inherited host secret", rendered)

    def test_candidate_failure_output_uses_exact_and_shared_redaction(self) -> None:
        sentinel = "arbitrary-candidate-sentinel-6ca84f"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            package = root / "scripts" / "cobbler_runtime"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(
                "import os\n"
                f"os.write(2, b'{sentinel} Bearer abcdefghijklmnop\\n')\n"
                "os._exit(17)\n"
                "__all__ = []\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {"ELVES_CANDIDATE_SECRET": sentinel},
                clear=False,
            ):
                snapshot = capture_snapshot(root)

            rendered = json.dumps(snapshot.to_dict(), sort_keys=True)
            self.assertEqual(snapshot.status, "degraded")
            self.assertNotIn(sentinel, rendered)
            self.assertNotIn("Bearer abcdefghijklmnop", rendered)
            self.assertIn("[REDACTED:exact_grant]", rendered)
            self.assertIn("[REDACTED:bearer_token]", rendered)

    def test_secret_shaped_openapi_route_name_is_redacted_before_persistence(self) -> None:
        secret = "xai-" + ("A" * 20)
        contract = {
            "openapi": "3.1.0",
            "info": {"title": "Fixture", "version": "1"},
            "paths": {
                f"/runs/{secret}": {
                    "get": {"responses": {"200": {"description": "ok"}}}
                }
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "openapi.json").write_text(
                json.dumps(contract),
                encoding="utf-8",
            )

            snapshot = capture_snapshot(root)
            rendered = json.dumps(snapshot.to_dict(), sort_keys=True)
            current = write_snapshot(root / DEFAULT_CURRENT, snapshot)
            persisted = current.read_text(encoding="utf-8")

            self.assertEqual(snapshot.status, "captured", snapshot.reason)
            self.assertNotIn(secret, rendered)
            self.assertNotIn(secret, persisted)
            self.assertIn("[REDACTED:xai_token]", rendered)
            self.assertIn("[REDACTED:xai_token]", persisted)

    def test_redacted_entry_identity_collision_degrades_and_omits_colliders(self) -> None:
        first_secret = "xai-" + ("A" * 20)
        second_secret = "xai-" + ("B" * 20)
        paths = {
            f"/runs/{first_secret}": {
                "get": {"responses": {"200": {"description": "first"}}}
            },
            f"/runs/{second_secret}": {
                "get": {"responses": {"200": {"description": "second"}}}
            },
        }
        contract = {
            "openapi": "3.1.0",
            "info": {"title": "Fixture", "version": "1"},
            "paths": paths,
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "openapi.json"
            path.write_text(json.dumps(contract), encoding="utf-8")

            snapshot = capture_snapshot(root)
            rendered = json.dumps(snapshot.to_dict(), sort_keys=True)

            self.assertEqual(snapshot.status, "degraded")
            self.assertIn(
                "public surface identity collision after redaction",
                snapshot.reason or "",
            )
            self.assertEqual(snapshot.entries, [])
            self.assertNotIn(first_secret, rendered)
            self.assertNotIn(second_secret, rendered)
            self.assertIn("[REDACTED:xai_token]", rendered)

            contract["paths"] = dict(reversed(list(paths.items())))
            path.write_text(json.dumps(contract), encoding="utf-8")
            repeated = capture_snapshot(root)
            self.assertEqual(repeated.reason, snapshot.reason)
            self.assertEqual(
                [entry.to_dict() for entry in repeated.entries],
                [entry.to_dict() for entry in snapshot.entries],
            )

    def test_cli_snapshot_includes_hierarchy_options_defaults_output_and_exit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            snapshot = capture_snapshot(root)

            entry = next(
                item
                for item in snapshot.entries
                if item.name == "cobbler_agents worker refresh"
            )
            contract = json.loads(entry.signature)
            by_dest = {item["dest"]: item for item in contract["arguments"]}
            self.assertEqual(contract["path"], ["worker", "refresh"])
            self.assertEqual(by_dest["new_tip"]["flags"], ["--new-tip"])
            self.assertTrue(by_dest["new_tip"]["required"])
            self.assertEqual(by_dest["mode"]["default"], "safe")
            self.assertEqual(by_dest["mode"]["choices"], ["safe", "fast"])
            handler = contract["handler_contract"]
            self.assertIn("worker_tip", handler["output_keys"])
            self.assertTrue(handler["output_calls"])
            self.assertIn("0 if payload['worker_tip'] else 1", handler["exit_expressions"])

    def test_required_mode_does_not_seed_baseline_from_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)

            result = compatibility_gate(
                root,
                required=True,
                base_ref="origin/main",
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["action"], "required_baseline_missing")
            self.assertFalse((root / DEFAULT_BASELINE).exists())

    def test_required_mode_rejects_preexisting_candidate_local_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            seeded = compatibility_gate(root, required=False)
            self.assertTrue(seeded["ok"], seeded)
            self.assertTrue((root / DEFAULT_BASELINE).exists())

            result = compatibility_gate(root, required=True)

            self.assertFalse(result["ok"])
            self.assertEqual(result["action"], "required_baseline_missing")
            self.assertEqual(result["baseline_source"], "unresolved")

    def test_required_mode_captures_origin_main_and_detects_option_rename(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            self._commit_baseline(root)

            self._write_cli(root, tip_flag="--next-tip")
            result = compatibility_gate(
                root,
                required=True,
                base_ref="origin/main",
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["baseline_source"], "captured:origin/main")
            self.assertIn("cli:cobbler_agents worker refresh", result["breaking"])
            self.assertFalse((root / DEFAULT_BASELINE).exists())

    def test_advisory_mode_prefers_git_base_over_stale_local_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            self._commit_baseline(root)

            # Simulate an earlier candidate-side capture produced by a stale or
            # incompatible inspector.  The real current CLI still matches the
            # committed base and must not be compared with this runtime file.
            self._write_cli(root, tip_flag="--stale-tip")
            write_snapshot(root / DEFAULT_BASELINE, capture_snapshot(root))
            self._write_cli(root)

            result = compatibility_gate(root, required=False)

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["baseline_source"], "captured:origin/main")
            self.assertEqual(result["breaking"], [])

    def test_compatible_additions_and_help_changes_do_not_break_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            self._commit_baseline(root)
            self._replace_cli(
                root,
                'payload = {"worker_tip": getattr(args, "new_tip", None)}',
                'payload = {"worker_tip": getattr(args, "new_tip", None), "status": "ok"}',
            )
            self._replace_cli(
                root,
                'choices=["safe", "fast"]',
                'choices=["safe", "fast", "careful"]',
            )
            self._replace_cli(
                root,
                'refresh.add_argument("--mode",',
                'refresh.add_argument("--label")\n    refresh.add_argument("--mode",',
            )
            self._replace_cli(root, 'help="Move worker to the new tip"', 'help="Refresh worker"')

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertTrue(result["ok"], result)
            self.assertIn(
                "cli:cobbler_agents worker refresh",
                result["diff"]["compatible_changes"],
            )
            self.assertEqual(result["breaking"], [])

    def test_changed_default_is_breaking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            self._commit_baseline(root)
            self._replace_cli(root, 'default="safe"', 'default="fast"')

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"])
            reasons = result["diff"]["change_reasons"][
                "cli:cobbler_agents worker refresh"
            ]
            self.assertTrue(any("changed default" in reason for reason in reasons), reasons)

    def test_explicit_break_approval_does_not_change_default_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            self._commit_baseline(root)
            self._replace_cli(root, 'default="safe"', 'default="fast"')
            surface = "cli:cobbler_agents worker refresh"

            blocked = compatibility_gate(root, required=True, base_ref="origin/main")
            approved = compatibility_gate(
                root,
                required=True,
                approved_breaks=[surface],
                base_ref="origin/main",
            )

            self.assertFalse(blocked["ok"], blocked)
            self.assertEqual(blocked["breaking"], [surface])
            self.assertTrue(approved["ok"], approved)
            self.assertEqual(approved["breaking"], [])
            self.assertEqual(approved["diff"]["breaking"], [surface])

    def test_narrowed_choices_and_new_required_inputs_are_breaking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            self._commit_baseline(root)
            self._replace_cli(
                root,
                'choices=["safe", "fast"]',
                'choices=["safe"]',
            )
            self._replace_cli(
                root,
                'refresh.add_argument("--mode",',
                'refresh.add_argument("--token", required=True)\n    refresh.add_argument("--mode",',
            )

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"])
            reasons = result["diff"]["change_reasons"][
                "cli:cobbler_agents worker refresh"
            ]
            self.assertTrue(any("removed accepted choice" in reason for reason in reasons))
            self.assertTrue(any("new required argument" in reason for reason in reasons))

    def test_changed_store_const_and_new_mutual_exclusion_are_breaking(self) -> None:
        const_source = HELPER_OUTPUT_TEMPLATE.replace(
            'status.set_defaults(func=cmd_status)',
            'status.add_argument("--json", action="store_const", const="json", '
            'default="text")\n    status.set_defaults(func=cmd_status)',
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(root, const_source)
            self._commit_baseline(root)
            self._replace_cli(root, 'const="json"', 'const="yaml"')

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            reasons = result["diff"]["change_reasons"]["cli:cobbler_agents status"]
            self.assertTrue(any("changed const" in reason for reason in reasons), reasons)

        independent = HELPER_OUTPUT_TEMPLATE.replace(
            'status.set_defaults(func=cmd_status)',
            'status.add_argument("--left", action="store_const", const="left", dest="mode")\n'
            '    status.add_argument("--right", action="store_const", const="right", dest="mode")\n'
            '    status.set_defaults(func=cmd_status)',
        )
        exclusive = HELPER_OUTPUT_TEMPLATE.replace(
            'status.set_defaults(func=cmd_status)',
            'choice = status.add_mutually_exclusive_group(required=True)\n'
            '    choice.add_argument("--left", action="store_const", const="left", dest="mode")\n'
            '    choice.add_argument("--right", action="store_const", const="right", dest="mode")\n'
            '    status.set_defaults(func=cmd_status)',
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(root, independent)
            self._commit_baseline(root)
            self._write_source(root, exclusive)

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            reasons = result["diff"]["change_reasons"]["cli:cobbler_agents status"]
            self.assertTrue(any("became mutually exclusive" in reason for reason in reasons), reasons)
            self.assertTrue(any("group became required" in reason for reason in reasons), reasons)

    def test_global_cli_arguments_are_part_of_the_root_contract(self) -> None:
        source = HELPER_OUTPUT_TEMPLATE.replace(
            'commands = parser.add_subparsers(dest="command", required=True)',
            'parser.add_argument("--profile", required=True)\n'
            '    commands = parser.add_subparsers(dest="command", required=True)',
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(root, source)
            self._commit_baseline(root)
            self._replace_cli(root, '    parser.add_argument("--profile", required=True)\n', "")

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            self.assertIn("cli:cobbler_agents", result["breaking"])

    def test_per_emission_json_output_shapes_cannot_lose_a_shared_key(self) -> None:
        source = '''\
import argparse


def cmd_status(args):
    if args.fail:
        print({"ok": False, "common": True, "issues": []})
        return 1
    print({"ok": True, "common": True, "data": {}})
    return 0


def build_parser():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--fail", action="store_true")
    status.set_defaults(func=cmd_status)
    return parser
'''
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(root, source)
            self._commit_baseline(root)
            self._replace_cli(
                root,
                '{"ok": True, "common": True, "data": {}}',
                '{"ok": True, "data": {}}',
            )

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            reasons = result["diff"]["change_reasons"]["cli:cobbler_agents status"]
            self.assertIn("JSON output variant lost keys or emission", reasons)

    def test_removed_output_key_and_changed_exit_contract_are_breaking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            self._commit_baseline(root)
            self._replace_cli(
                root,
                'payload = {"worker_tip": getattr(args, "new_tip", None)}',
                "payload = {}",
            )
            self._replace_cli(
                root,
                'return 0 if payload["worker_tip"] else 1',
                "return 0",
            )

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"])
            reasons = result["diff"]["change_reasons"][
                "cli:cobbler_agents worker refresh"
            ]
            self.assertTrue(any("JSON output keys removed" in reason for reason in reasons))
            self.assertTrue(any("process exit contract changed" in reason for reason in reasons))

    def test_shared_handler_outputs_are_compared_per_subcommand_branch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(root, SHARED_HANDLER_TEMPLATE)
            self._commit_baseline(root)
            self._replace_cli(root, 'payload = {"prepare_key": True}', 'payload = {"ok": True}')

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"])
            self.assertIn("cli:cobbler_agents worker prepare", result["breaking"])
            self.assertNotIn("cli:cobbler_agents worker refresh", result["breaking"])
            self.assertIn(
                "JSON output keys removed: prepare_key",
                result["diff"]["change_reasons"]["cli:cobbler_agents worker prepare"],
            )

    def test_dynamic_exit_expression_changes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            self._replace_cli(
                root,
                'return 0 if payload["worker_tip"] else 1',
                'return int(bool(payload["worker_tip"]))',
            )
            self._commit_baseline(root)
            self._replace_cli(
                root,
                'return int(bool(payload["worker_tip"]))',
                'return 1 - int(bool(payload["worker_tip"]))',
            )

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"])
            reasons = result["diff"]["change_reasons"][
                "cli:cobbler_agents worker refresh"
            ]
            self.assertIn("process exit contract changed", reasons)

    def test_direct_local_helper_literal_exit_is_normalized_and_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(
                root,
                HELPER_EXIT_TEMPLATE.format(failure_expression="1"),
            )
            self._commit_baseline(root)
            self._write_source(
                root,
                HELPER_EXIT_TEMPLATE.format(
                    failure_expression="_literal_failure(args)"
                ),
            )

            snapshot = capture_snapshot(root)
            entry = next(
                item
                for item in snapshot.entries
                if item.name == "cobbler_agents status"
            )
            handler = json.loads(entry.signature)["handler_contract"]
            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertEqual(handler["exit_codes"], [0, 1])
            self.assertFalse(handler["dynamic_exit"], handler)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["breaking"], [])

    def test_nested_storage_error_emitter_resolves_literal_exit_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(root, STORAGE_ERROR_EXIT_TEMPLATE)

            snapshot = capture_snapshot(root)
            entry = next(
                item
                for item in snapshot.entries
                if item.name == "cobbler_agents status"
            )
            handler = json.loads(entry.signature)["handler_contract"]

            self.assertEqual(snapshot.status, "captured", snapshot.reason)
            self.assertEqual(handler["exit_codes"], [0, 1])
            self.assertFalse(handler["dynamic_exit"], handler)

    def test_direct_local_helper_system_exit_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(
                root,
                HELPER_EXIT_TEMPLATE.format(
                    failure_expression="_literal_failure(args)"
                ),
            )
            self._commit_baseline(root)
            self._write_source(
                root,
                HELPER_EXIT_TEMPLATE.replace(
                    "    return 1\n",
                    "    raise SystemExit(1)\n",
                ).format(failure_expression="_literal_failure(args)"),
            )

            snapshot = capture_snapshot(root)
            entry = next(
                item
                for item in snapshot.entries
                if item.name == "cobbler_agents status"
            )
            handler = json.loads(entry.signature)["handler_contract"]
            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertEqual(handler["exit_codes"], [0, 1])
            self.assertFalse(handler["dynamic_exit"], handler)
            self.assertTrue(result["ok"], result)

    def test_unknown_dynamic_and_cyclic_exit_helpers_fail_closed(self) -> None:
        current_sources = {
            "unknown": HELPER_EXIT_TEMPLATE.format(
                failure_expression="_unknown_failure(args)"
            ),
            "dynamic": HELPER_EXIT_TEMPLATE.replace(
                "    return 1\n",
                '    return int(getattr(args, "code", 1))\n',
            ).format(failure_expression="_literal_failure(args)"),
            "cyclic": HELPER_EXIT_TEMPLATE.replace(
                "def _literal_failure(args):\n    return 1\n",
                "def _literal_failure(args):\n    return _other_failure(args)\n\n\n"
                "def _other_failure(args):\n    return _literal_failure(args)\n",
            ).format(failure_expression="_literal_failure(args)"),
            "mixed_raise": HELPER_EXIT_TEMPLATE.replace(
                "    return 1\n",
                "    if args.ok:\n        return 1\n"
                '    raise RuntimeError("unknown exit path")\n',
            ).format(failure_expression="_literal_failure(args)"),
        }
        for label, current_source in current_sources.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                baseline_source = HELPER_EXIT_TEMPLATE.format(
                    failure_expression="_literal_failure(args)"
                )
                self._write_source(root, baseline_source)
                self._commit_baseline(root)
                self._write_source(root, current_source)

                snapshot = capture_snapshot(root)
                entry = next(
                    item
                    for item in snapshot.entries
                    if item.name == "cobbler_agents status"
                )
                handler = json.loads(entry.signature)["handler_contract"]
                result = compatibility_gate(
                    root,
                    required=True,
                    base_ref="origin/main",
                )

                self.assertTrue(handler["dynamic_exit"], handler)
                self.assertFalse(result["ok"], result)
                reasons = result["diff"]["change_reasons"][
                    "cli:cobbler_agents status"
                ]
                self.assertIn("process exit contract changed", reasons)

    def test_required_mode_fails_closed_when_argparse_inspection_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(
                root,
                "import argparse\n\n"
                "def build_parser():\n"
                "    parser = argparse.ArgumentParser()\n"
                "    parser.add_subparsers().add_parser('status')\n"
                "    raise RuntimeError('inspection unavailable')\n",
            )
            self._commit_baseline(root)

            snapshot = capture_snapshot(root)
            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertEqual(snapshot.status, "degraded")
            self.assertIn("fell back", snapshot.reason or "")
            self.assertFalse(result["ok"])
            self.assertEqual(result["action"], "current_inspection_incomplete")

    def test_advisory_git_repo_without_base_does_not_self_seed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_cli(root)
            self._git(root, "init", "-b", "feature-only")
            self._git(root, "config", "user.email", "tests@example.invalid")
            self._git(root, "config", "user.name", "Elves Tests")
            self._git(root, "add", "scripts/cobbler_agents.py")
            self._git(root, "commit", "-m", "candidate")

            result = compatibility_gate(root, required=False)

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["action"], "advisory_baseline_unresolved")
            self.assertFalse((root / DEFAULT_BASELINE).exists())

    def test_indirect_helper_json_key_removal_is_breaking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(root, HELPER_OUTPUT_TEMPLATE)
            self._commit_baseline(root)
            self._replace_cli(root, ', "beta": True', "")

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            reasons = result["diff"]["change_reasons"]["cli:cobbler_agents status"]
            self.assertIn("JSON output keys removed: beta", reasons)

    def test_direct_helper_output_is_tracked_and_dynamic_unpack_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            direct = HELPER_OUTPUT_TEMPLATE.replace(
                "    payload = build_payload()\n    print(payload)\n",
                "    print(build_payload())\n",
            )
            self._write_source(root, direct)
            self._commit_baseline(root)
            self._replace_cli(root, ', "beta": True', "")
            result = compatibility_gate(root, required=True, base_ref="origin/main")
            self.assertFalse(result["ok"], result)
            self.assertIn(
                "JSON output keys removed: beta",
                result["diff"]["change_reasons"]["cli:cobbler_agents status"],
            )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            dynamic = HELPER_OUTPUT_TEMPLATE.replace(
                '    return {"alpha": True, "beta": True}',
                '    return {"alpha": True, **unknown_payload}',
            )
            self._write_source(root, dynamic)
            snapshot = capture_snapshot(root)
            self.assertEqual(snapshot.status, "degraded")
            self.assertIn("unknown mapping", snapshot.reason or "")

    def test_local_imported_handler_is_inspected_but_external_source_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "handlers.py").write_text(
                "def cmd_status(args):\n"
                "    payload = {'status': 'ok'}\n"
                "    print(payload)\n"
                "    return 0\n",
                encoding="utf-8",
            )
            self._write_source(
                root,
                "import argparse\nfrom handlers import cmd_status\n\n"
                "def build_parser():\n"
                "    parser = argparse.ArgumentParser()\n"
                "    sub = parser.add_subparsers(dest='command', required=True)\n"
                "    status = sub.add_parser('status')\n"
                "    status.set_defaults(func=cmd_status)\n"
                "    return parser\n",
            )
            snapshot = capture_snapshot(root)
            self.assertEqual(snapshot.status, "captured", snapshot.reason)
            external = root / "external_handlers.py"
            external.write_text((scripts / "handlers.py").read_text(), encoding="utf-8")
            cli = scripts / "cobbler_agents.py"
            cli.write_text(cli.read_text().replace(
                "from handlers import cmd_status",
                "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parent.parent))\nfrom external_handlers import cmd_status",
            ), encoding="utf-8")
            snapshot = capture_snapshot(root)
            self.assertEqual(snapshot.status, "degraded")
            self.assertIn("outside inspected CLI module", snapshot.reason or "")

    def test_json_emitters_fail_closed_on_computed_or_unresolved_output_shapes(self) -> None:
        template = '''\
import argparse


def _emit_json(payload, **kwargs):
    print(payload)
    return 0


def cmd_status(args):
    payload = {payload}
    return _emit_json({emitted})


def build_parser():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.set_defaults(func=cmd_status)
    return parser
'''
        cases = {
            "computed key": ("{args.command: True}", "payload"),
            "unresolved subscript": ('{"data": {"ok": True}}', 'payload["data"]'),
            "unresolved union": ('{"known": True}', "payload | unknown_payload"),
        }
        for label, (payload, emitted) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                self._write_source(
                    root,
                    template.format(payload=payload, emitted=emitted),
                )
                snapshot = capture_snapshot(root)
                self.assertEqual(snapshot.status, "degraded", snapshot.reason)
                self.assertIn("output inspection incomplete", snapshot.reason or "")

    def test_leaf_command_without_handler_is_incomplete_but_parent_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(
                root,
                "import argparse\n\n"
                "def build_parser():\n"
                "    parser = argparse.ArgumentParser()\n"
                "    commands = parser.add_subparsers(dest='command', required=True)\n"
                "    parent = commands.add_parser('parent')\n"
                "    parent.add_subparsers(dest='action', required=True).add_parser('leaf')\n"
                "    return parser\n",
            )

            snapshot = capture_snapshot(root)

            self.assertEqual(snapshot.status, "degraded")
            self.assertIn("leaf command has no inspectable handler", snapshot.reason or "")

    def test_snapshot_completeness_rejects_empty_malformed_and_duplicate_entries(self) -> None:
        empty = ApiSnapshot(status="captured", captured_at="now", source="fixture")
        malformed = ApiSnapshot(
            status="captured",
            captured_at="now",
            source="fixture",
            entries=[SurfaceEntry(kind="mystery", name="", signature="")],
        )
        duplicate = SurfaceEntry(kind="export", name="api", signature="api")
        duplicated = ApiSnapshot(
            status="captured",
            captured_at="now",
            source="fixture",
            entries=[duplicate, duplicate],
        )

        self.assertIn("no public surface entries", " ".join(_snapshot_completeness_issues(empty)))
        self.assertIn("unknown public surface kind", " ".join(_snapshot_completeness_issues(malformed)))
        self.assertIn("duplicate public surface entry", " ".join(_snapshot_completeness_issues(duplicated)))

    def test_advisory_does_not_fall_back_to_candidate_when_ref_capture_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_source(
                root,
                "import argparse\n\n"
                "def build_parser():\n"
                "    argparse.ArgumentParser().add_subparsers().add_parser('status')\n"
                "    raise RuntimeError('base cannot be inspected')\n",
            )
            self._commit_baseline(root)
            self._write_source(root, HELPER_OUTPUT_TEMPLATE)
            write_snapshot(root / DEFAULT_BASELINE, capture_snapshot(root))

            result = compatibility_gate(root, required=False, base_ref="origin/main")

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["action"], "advisory_baseline_incomplete")
            self.assertNotIn("diff", result)

    def test_json_schema_structural_change_breaks_but_prose_change_does_not(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Report",
            "description": "baseline prose",
            "type": "object",
            "required": ["status"],
            "properties": {
                "status": {"type": "string", "description": "status prose"}
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "references" / "implement-done-report.schema.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(schema), encoding="utf-8")
            self._commit_all_baseline(root)

            prose = json.loads(path.read_text(encoding="utf-8"))
            prose["description"] = "new prose only"
            prose["properties"]["status"]["description"] = "new field prose"
            path.write_text(json.dumps(prose), encoding="utf-8")
            result = compatibility_gate(root, required=True, base_ref="origin/main")
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["diff"]["identical"])

            prose["properties"]["status"]["type"] = "integer"
            path.write_text(json.dumps(prose), encoding="utf-8")
            result = compatibility_gate(root, required=True, base_ref="origin/main")
            self.assertFalse(result["ok"], result)
            self.assertIn(
                "schema:references/implement-done-report.schema.json",
                result["breaking"],
            )

    def test_json_schema_optional_property_addition_is_compatible(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "references" / "implement-done-report.schema.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(schema), encoding="utf-8")
            self._commit_all_baseline(root)

            schema["properties"]["confidence"] = {
                "type": "string",
                "enum": ["high", "medium", "low"],
            }
            path.write_text(json.dumps(schema), encoding="utf-8")
            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertTrue(result["ok"], result)
            self.assertIn(
                "schema:references/implement-done-report.schema.json",
                result["diff"]["compatible_changes"],
            )

    def test_json_schema_new_required_property_remains_breaking(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "references" / "implement-done-report.schema.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(schema), encoding="utf-8")
            self._commit_all_baseline(root)

            schema["properties"]["confidence"] = {"type": "string"}
            schema["required"].append("confidence")
            path.write_text(json.dumps(schema), encoding="utf-8")
            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            self.assertIn(
                "schema:references/implement-done-report.schema.json",
                result["breaking"],
            )

    def test_schema_property_named_description_is_structural_and_required_order_is_not(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["description", "id"],
            "properties": {
                "description": {"type": "string"},
                "id": {"type": "string"},
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "references" / "implement-done-report.schema.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(schema), encoding="utf-8")
            self._commit_all_baseline(root)

            schema["required"] = ["id", "description"]
            path.write_text(json.dumps(schema), encoding="utf-8")
            self.assertTrue(
                compatibility_gate(root, required=True, base_ref="origin/main")["ok"]
            )

            schema["properties"]["description"]["type"] = "integer"
            path.write_text(json.dumps(schema), encoding="utf-8")
            result = compatibility_gate(root, required=True, base_ref="origin/main")
            self.assertFalse(result["ok"], result)

    def test_swagger_definitions_are_part_of_the_contract(self) -> None:
        swagger = {
            "swagger": "2.0",
            "info": {"title": "Fixture", "version": "1"},
            "paths": {
                "/items": {
                    "get": {
                        "responses": {
                            "200": {"schema": {"$ref": "#/definitions/Item"}}
                        }
                    }
                }
            },
            "definitions": {
                "Item": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                }
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "swagger.json"
            path.write_text(json.dumps(swagger), encoding="utf-8")
            self._commit_all_baseline(root)
            swagger["definitions"]["Item"]["properties"]["id"]["type"] = "integer"
            path.write_text(json.dumps(swagger), encoding="utf-8")

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            self.assertIn("schema:swagger.json#/definitions/Item", result["breaking"])

    def test_openapi_request_response_and_component_contracts_are_structural(self) -> None:
        contract = {
            "openapi": "3.1.0",
            "info": {"title": "Fixture", "version": "1"},
            "paths": {
                "/runs": {
                    "post": {
                        "summary": "create prose",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RunInput"}
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "ok prose",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Run"}
                                    }
                                },
                            }
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "RunInput": {
                        "type": "object",
                        "required": ["task"],
                        "properties": {"task": {"type": "string"}},
                    },
                    "Run": {
                        "type": "object",
                        "required": ["id"],
                        "properties": {"id": {"type": "string"}},
                    },
                }
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "openapi.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            self._commit_all_baseline(root)

            contract["paths"]["/runs"]["post"]["responses"]["200"]["description"] = "changed prose"
            path.write_text(json.dumps(contract), encoding="utf-8")
            self.assertTrue(
                compatibility_gate(root, required=True, base_ref="origin/main")["ok"]
            )

            contract["components"]["schemas"]["RunInput"]["properties"]["task"]["type"] = "integer"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = compatibility_gate(root, required=True, base_ref="origin/main")
            self.assertFalse(result["ok"], result)
            self.assertIn(
                "schema:openapi.json#/components/schemas/RunInput",
                result["breaking"],
            )

    def test_same_operation_in_two_openapi_documents_keeps_source_identity(self) -> None:
        baseline = {
            "openapi": "3.1.0",
            "info": {"title": "Fixture", "version": "1"},
            "paths": {
                "/items": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"type": "string"}}
                                }
                            }
                        }
                    }
                }
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            docs = root / "docs"
            docs.mkdir()
            root_contract = root / "openapi.json"
            docs_contract = docs / "openapi.json"
            root_contract.write_text(json.dumps(baseline), encoding="utf-8")
            docs_contract.write_text(json.dumps(baseline), encoding="utf-8")
            self._commit_all_baseline(root)

            changed = json.loads(root_contract.read_text(encoding="utf-8"))
            changed["paths"]["/items"]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]["type"] = "integer"
            root_contract.write_text(json.dumps(changed), encoding="utf-8")

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            self.assertIn("rest:openapi.json#GET /items", result["breaking"])

    def test_openapi_header_named_description_remains_structural(self) -> None:
        contract = {
            "openapi": "3.1.0",
            "info": {"title": "Fixture", "version": "1"},
            "paths": {
                "/items": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "headers": {
                                    "description": {"schema": {"type": "string"}}
                                },
                            }
                        }
                    }
                }
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "openapi.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            self._commit_all_baseline(root)
            contract["paths"]["/items"]["get"]["responses"]["200"]["headers"][
                "description"
            ]["schema"]["type"] = "integer"
            path.write_text(json.dumps(contract), encoding="utf-8")

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            self.assertIn("rest:openapi.json#GET /items", result["breaking"])

    def test_openapi_path_level_servers_are_structural(self) -> None:
        contract = {
            "openapi": "3.1.0",
            "info": {"title": "Fixture", "version": "1"},
            "paths": {
                "/items": {
                    "servers": [{"url": "/v1"}],
                    "get": {"responses": {"200": {"description": "ok"}}},
                }
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "openapi.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            self._commit_all_baseline(root)
            contract["paths"]["/items"]["servers"][0]["url"] = "/v2"
            path.write_text(json.dumps(contract), encoding="utf-8")

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            self.assertIn("rest:openapi.json#PATH /items", result["breaking"])

    def test_exported_function_signature_changes_are_breaking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            package = root / "scripts" / "cobbler_runtime"
            package.mkdir(parents=True)
            init = package / "__init__.py"
            init.write_text(
                "def public_fn(value=None):\n    return value\n\n"
                '__all__ = ["public_fn"]\n',
                encoding="utf-8",
            )
            self._commit_all_baseline(root)
            init.write_text(
                "def public_fn(value, required):\n    return value\n\n"
                '__all__ = ["public_fn"]\n',
                encoding="utf-8",
            )

            result = compatibility_gate(root, required=True, base_ref="origin/main")

            self.assertFalse(result["ok"], result)
            self.assertIn("export:cobbler_runtime.public_fn", result["breaking"])


class _NoFilterTar(tarfile.TarFile):
    """Simulates interpreters predating extractall(filter=) (< 3.10.12 / 3.11.4)."""

    def extractall(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if "filter" in kwargs:
            raise TypeError("filter unsupported (simulated old interpreter)")
        return super().extractall(*args, **kwargs)


class ArchiveExtractionFailClosedTests(unittest.TestCase):
    def _tar_bytes(self, entries) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            for name, kind in entries:
                info = tarfile.TarInfo(name)
                info.mode = 0o755 if kind == "dir" else 0o644
                if kind == "dir":
                    info.type = tarfile.DIRTYPE
                    tar.addfile(info)
                elif kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "/tmp/target"
                    tar.addfile(info)
                else:
                    payload = b"content\n"
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
        return buffer.getvalue()

    def test_filter_unavailable_rejects_unsafe_members(self) -> None:
        from cobbler_runtime.public_api_snapshot import _extract_archive_members

        for entries, label in (
            ([("ok.txt", "file"), ("evil", "symlink")], "symlink member"),
            ([("../escape.txt", "file")], "dotdot member"),
            ([("/abs.txt", "file")], "absolute member"),
        ):
            with self.subTest(label=label):
                data = self._tar_bytes(entries)
                with tempfile.TemporaryDirectory() as raw:
                    temp_root = Path(raw)
                    with _NoFilterTar.open(
                        fileobj=io.BytesIO(data), mode="r:"
                    ) as tar:
                        reason = _extract_archive_members(tar, temp_root)
                    self.assertIsNotNone(reason)
                    self.assertIn("api_snapshot_tar_member_unsafe", reason)
                    self.assertEqual(
                        [p for p in temp_root.rglob("*")],
                        [],
                        "nothing may be extracted when validation fails",
                    )
                self.assertFalse((Path(raw).parent / "escape.txt").exists())

    def test_filter_unavailable_extracts_clean_archives(self) -> None:
        from cobbler_runtime.public_api_snapshot import _extract_archive_members

        data = self._tar_bytes([("pkg", "dir"), ("pkg/mod.py", "file")])
        with tempfile.TemporaryDirectory() as raw:
            temp_root = Path(raw)
            with _NoFilterTar.open(fileobj=io.BytesIO(data), mode="r:") as tar:
                reason = _extract_archive_members(tar, temp_root)
            self.assertIsNone(reason)
            self.assertTrue((temp_root / "pkg" / "mod.py").is_file())

    def test_modern_filter_path_extracts_clean_archives(self) -> None:
        from cobbler_runtime.public_api_snapshot import _extract_archive_members

        data = self._tar_bytes([("pkg", "dir"), ("pkg/mod.py", "file")])
        with tempfile.TemporaryDirectory() as raw:
            temp_root = Path(raw)
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
                reason = _extract_archive_members(tar, temp_root)
            self.assertIsNone(reason)
            self.assertTrue((temp_root / "pkg" / "mod.py").is_file())


if __name__ == "__main__":
    unittest.main()
