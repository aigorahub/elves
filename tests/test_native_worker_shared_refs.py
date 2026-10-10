"""Native-worker shared-ref launch and authority diagnostics regressions (#284)."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
from cobbler_runtime import native_worker as worker
from cobbler_runtime.schema import ValidationIssue


class SharedRefsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.git(self.root, 'init', str(self.repo))
        self.git(self.repo, 'config', 'user.email', 'test@example.com')
        self.git(self.repo, 'config', 'user.name', 'Test')
        (self.repo / '.gitignore').write_text('.elves/\n')
        self.git(self.repo, 'add', '.')
        self.git(self.repo, 'commit', '-m', 'initial')
        self.git(self.repo, 'switch', '-c', 'feature/a')

    def git(self, cwd, *args):
        return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    def record(self, repo, run_id, status, branch='feature/a'):
        path, _ = worker.native_worker_paths(repo, run_id)
        worker._write_private_json(path, {'run_id': run_id, 'status': status,
            'assigned_branch': branch, 'worktree': str(repo)})
        return path

    def launch(self, repo, run_id):
        packet = self.root / 'packet.md'
        packet.write_text('fixture packet')
        spec = worker.NativeWorkerSpec(host='fixture', profile='fixture', effort='low',
            model_policy='exact', requested_model='fixture', separate_session=True,
            cwd=str(repo), argv=(sys.executable,), stdin_packet=True, session_id_source='stream')
        def publish_identity(_):
            path, _ = worker.native_worker_paths(repo, run_id)
            state = json.loads(path.read_text())
            state['pid'] = 123
            worker._write_private_json(path, state)
        real_popen = subprocess.Popen
        def start(argv, **kwargs):
            if argv[0] == 'git':
                return real_popen(argv, **kwargs)
            return mock.Mock(pid=123)
        with mock.patch.object(worker.subprocess, 'Popen', side_effect=start), \
             mock.patch.object(worker, '_process_start', return_value='fixture-start'), \
             mock.patch.object(worker.time, 'sleep', side_effect=publish_identity):
            return worker.launch_native_worker(repo_root=repo, run_id=run_id, spec=spec,
                packet=packet, cli_path=REPO_ROOT / 'scripts/cobbler_agents.py')

    def test_second_launch_from_linked_worktree_is_refused(self):
        linked = self.root / 'linked'
        self.git(self.repo, 'worktree', 'add', '-b', 'feature/b', str(linked))
        self.launch(self.repo, 'run-a')
        with self.assertRaises(ValidationIssue) as caught:
            self.launch(linked, 'run-b')
        self.assertEqual(caught.exception.code, 'native_worker_shared_refs_active_run')
        for text in ('run-a', 'run-b', str(self.repo), 'clone --bare'):
            self.assertIn(text, str(caught.exception))
        self.assertFalse(worker.native_worker_paths(linked, 'run-b')[0].exists())

    def test_all_active_phases_block(self):
        for status in ('staged', 'launching', 'running', 'launching_prewalk', 'prewalking',
                       'transition_ready', 'launching_execution', 'executing', 'execution_backoff'):
            with self.subTest(status=status):
                self.record(self.repo, 'run-a', status)
                with self.assertRaises(ValidationIssue):
                    self.launch(self.repo, 'run-b')

    def test_separate_clones_both_launch(self):
        clones = []
        for lane in ('a', 'b'):
            mirror = self.root / f'{lane}.git'
            clone = self.root / lane
            self.git(self.root, 'clone', '--bare', str(self.repo), str(mirror))
            self.git(self.root, 'clone', str(mirror), str(clone))
            clones.append(clone)
        for lane, clone in zip(('a', 'b'), clones):
            self.assertEqual(self.launch(clone, f'run-{lane}')['status'], 'running')

    def test_terminal_runs_and_same_run_do_not_block(self):
        for status in ('complete', 'failed'):
            with self.subTest(status=status):
                self.record(self.repo, 'run-a', status)
                self.assertEqual(self.launch(self.repo, f'after-{status}')['status'], 'running')
                self.record(self.repo, f'after-{status}', 'complete')
        self.record(self.repo, 'same', 'executing')
        worker._check_shared_refs_active_run(self.repo, 'same')

    def test_unreadable_state_warns_without_blocking(self):
        path = self.record(self.repo, 'broken', 'executing')
        path.write_text('{broken')
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(self.launch(self.repo, 'new')['status'], 'running')
        self.assertIn('Warning:', output.getvalue())
        self.assertIn(str(path), output.getvalue())

    def terminalize_moved_branch(self, branch, sibling=False):
        self.git(self.repo, 'branch', branch)
        if sibling:
            linked = self.root / 'linked'
            self.git(self.repo, 'worktree', 'add', str(linked), branch)
            self.record(linked, 'other-run', 'complete', branch)
        state = {'run_id': 'current', 'status': 'executing', 'git_authority_mode': 'feature_only',
                 **worker._native_git_contract(self.repo)}
        new_tip = self.git(self.repo, 'commit-tree', 'HEAD^{tree}', '-p', 'HEAD', '-m', 'other commit')
        self.git(self.repo, 'update-ref', f'refs/heads/{branch}', new_tip)
        path, _ = worker.native_worker_paths(self.repo, 'current')
        result = worker._terminalize_native_worker(state_path=path, state=state,
            worktree=self.repo, exit_code=0)
        self.assertEqual(result, 1)
        final = worker.native_worker_status(self.repo, 'current')
        self.assertEqual(final['status'], 'failed')
        self.assertEqual(final['failure_reason'], 'native_worker_git_authority_violation')
        self.assertTrue(any('protected ref moved' in error for error in final['authority_errors']))
        return final['failure_detail']

    def test_moved_sibling_branch_still_fails_with_detail(self):
        self.assertEqual(self.terminalize_moved_branch('feature/b', sibling=True),
            'Another native worker run (other-run) moved its own branch in this repository. '
            'Two native workers cannot share one repository.')

    def test_unrelated_ref_failure_detail(self):
        self.assertEqual(self.terminalize_moved_branch('driver'),
            'A process other than this worker moved refs/heads/driver. '
            'A running worker treats every other ref in the repository as protected. '
            'Do not commit, branch, fetch, or push in this repository while it runs.')
