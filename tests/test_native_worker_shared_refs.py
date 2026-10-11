"""Native-worker shared-ref launch and authority diagnostics regressions (#284)."""
from __future__ import annotations

import contextlib
import concurrent.futures
import threading
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

    def record(self, repo, run_id, status, branch='feature/a', **extra):
        path, _ = worker.native_worker_paths(repo, run_id)
        worker._write_private_json(path, {'run_id': run_id, 'status': status,
            'assigned_branch': branch, 'worktree': str(repo), **extra})
        return path

    def launch(self, repo, run_id, repo_root=None):
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
            return worker.launch_native_worker(repo_root=repo_root or repo, run_id=run_id, spec=spec,
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

    def test_same_run_id_from_linked_worktree_is_refused(self):
        linked = self.root / 'linked'
        self.git(self.repo, 'worktree', 'add', '-b', 'feature/b', str(linked))
        # Record the active run directly; a mocked fixture launch's status is host-timing dependent.
        self.record(self.repo, 'same', 'executing')
        with self.assertRaises(ValidationIssue) as caught:
            self.launch(linked, 'same')
        self.assertEqual(caught.exception.code, 'native_worker_shared_refs_active_run')
        with self.assertRaises(ValidationIssue) as caught:
            self.launch(self.repo, 'same')
        self.assertEqual(caught.exception.code, 'native_worker_run_exists')

    def test_state_root_must_be_registered_in_same_repository(self):
        unrelated = self.root / 'unrelated'
        self.git(self.root, 'init', str(unrelated))
        for state_root in (unrelated, self.root, self.repo / '.elves'):
            state_root.mkdir(exist_ok=True)
            with self.subTest(state_root=state_root):
                with self.assertRaises(ValidationIssue) as caught:
                    self.launch(self.repo, 'outside', repo_root=state_root)
                self.assertEqual(caught.exception.code, 'native_worker_state_repository_mismatch')
                self.assertFalse(worker.native_worker_paths(state_root, 'outside')[0].exists())

    def test_launch_holds_common_lock_through_first_state_write(self):
        write = worker._write_private_json
        checked = []
        def check_first_write(path, state):
            if not checked:
                with (worker._git_common_dir(self.repo) / 'elves-native-worker-launch.lock').open('a') as lock:
                    with self.assertRaises(BlockingIOError):
                        worker.fcntl.flock(lock.fileno(), worker.fcntl.LOCK_EX | worker.fcntl.LOCK_NB)
                checked.append(True)
            return write(path, state)
        with mock.patch.object(worker, '_write_private_json', side_effect=check_first_write):
            self.launch(self.repo, 'locked')
        self.assertEqual(checked, [True])

    def test_concurrent_launch_scan_waits_for_initial_registration(self):
        linked = self.root / 'linked'
        self.git(self.repo, 'worktree', 'add', '-b', 'feature/b', str(linked))
        attempting = threading.Event()
        scanned = threading.Event()
        def second_registration():
            attempting.set()
            with worker._native_worker_launch_lock(linked, linked):
                scanned.set()
                worker._check_shared_refs_active_run(linked, 'second')
                self.record(linked, 'second', 'launching')
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with worker._native_worker_launch_lock(self.repo, self.repo):
                worker._check_shared_refs_active_run(self.repo, 'first')
                pending = pool.submit(second_registration)
                self.assertTrue(attempting.wait(5))
                self.assertFalse(scanned.wait(0.1))
                self.record(self.repo, 'first', 'launching')
            with self.assertRaises(ValidationIssue) as caught:
                pending.result(timeout=5)
            self.assertEqual(caught.exception.code, 'native_worker_shared_refs_active_run')
        self.assertFalse(worker.native_worker_paths(linked, 'second')[0].exists())

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

    def test_terminal_runs_do_not_block(self):
        for status in ('complete', 'failed'):
            with self.subTest(status=status):
                self.record(self.repo, 'run-a', status)
                self.assertEqual(self.launch(self.repo, f'after-{status}')['status'], 'running')
                self.record(self.repo, f'after-{status}', 'complete')

    def assert_unreadable_state_blocks(self, repo, path, run_id='new'):
        with self.assertRaises(ValidationIssue) as caught:
            self.launch(repo, run_id)
        self.assertEqual(caught.exception.code, 'native_worker_shared_refs_unreadable_state')
        message = str(caught.exception)
        self.assertIn(str(path), message)
        self.assertIn(run_id, message)
        self.assertIn('Inspect and repair that state file, or remove it only if no worker is running.', message)
        self.assertEqual(caught.exception.path, str(path))
        self.assertFalse(worker.native_worker_paths(repo, run_id)[0].exists())
        return message

    def test_unreadable_or_malformed_state_blocks_launch(self):
        cases = (
            ('malformed json', '{broken', False),
            ('non-object', '[]', False),
            ('null', 'null', False),
            ('directory', None, True),
        )
        for name, text, as_directory in cases:
            with self.subTest(name=name):
                path = self.record(self.repo, f'broken-{name}', 'executing')
                if as_directory:
                    path.unlink()
                    path.mkdir()
                else:
                    path.write_text(text)
                try:
                    self.assert_unreadable_state_blocks(self.repo, path, f'new-{name}')
                finally:
                    if as_directory and path.is_dir():
                        path.rmdir()
                    elif path.exists():
                        path.unlink()

    def test_unreadable_state_in_linked_worktree_blocks(self):
        linked = self.root / 'linked'
        self.git(self.repo, 'worktree', 'add', '-b', 'feature/b', str(linked))
        path = self.record(linked, 'broken', 'executing')
        path.write_text('{broken')
        self.assert_unreadable_state_blocks(self.repo, path)

    def test_non_git_checkout_skips_unreadable_state(self):
        scratch = self.root / 'scratch'
        scratch.mkdir()
        planted = scratch / '.elves' / 'runtime' / 'native-worker' / 'not-a-run' / 'state.json'
        planted.parent.mkdir(parents=True)
        planted.write_text('{broken')
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            worker._check_shared_refs_active_run(scratch, 'fixture-run')
            self.assertEqual(self.launch(scratch, 'fixture-run')['status'], 'running')
        self.assertNotIn('native_worker_shared_refs_unreadable_state', output.getvalue())
        self.assertNotIn(str(planted), output.getvalue())

    def record_dead_pair(self, repo, run_id, status='executing'):
        return self.record(
            repo, run_id, status, pid=4242, pid_start='worker-start',
            supervisor_pid=4343, supervisor_pid_start='supervisor-start',
        )

    def test_stale_active_run_does_not_block(self):
        linked = self.root / 'linked'
        self.git(self.repo, 'worktree', 'add', '-b', 'feature/b', str(linked))
        cases = (
            ('same checkout', self.repo, 'crashed-same', 'new-same'),
            ('linked worktree', linked, 'crashed-linked', 'new-linked'),
        )
        for name, home, stale_id, new_id in cases:
            with self.subTest(name=name):
                path = self.record_dead_pair(home, stale_id)
                output = io.StringIO()
                with mock.patch.object(worker, '_process_identity_matches', return_value=False), \
                     contextlib.redirect_stderr(output):
                    self.assertEqual(self.launch(self.repo, new_id)['status'], 'running')
                warning = output.getvalue()
                self.assertIn('Warning:', warning)
                self.assertIn(stale_id, warning)
                self.assertIn('supervisor and worker processes are gone', warning)
                self.assertEqual(json.loads(path.read_text())['status'], 'executing')
                self.record(self.repo, new_id, 'complete')

    def test_stale_decision_uses_process_identity_helper(self):
        path = self.record_dead_pair(self.repo, 'crashed')
        seen = []

        def match(pid, start):
            seen.append((pid, start))
            return False

        output = io.StringIO()
        with mock.patch.object(worker, '_process_identity_matches', side_effect=match), \
             contextlib.redirect_stderr(output):
            worker._check_shared_refs_active_run(self.repo, 'new')
        self.assertEqual(seen, [(4343, 'supervisor-start'), (4242, 'worker-start')])
        self.assertIn('crashed', output.getvalue())

        seen.clear()
        with mock.patch.object(worker, '_process_start', return_value=None), \
             mock.patch.object(worker.os, 'kill', side_effect=ProcessLookupError), \
             contextlib.redirect_stderr(output):
            worker._check_shared_refs_active_run(self.repo, 'new')
        self.assertEqual(json.loads(path.read_text())['status'], 'executing')

    def test_partial_or_live_identity_still_blocks(self):
        def identities(mapping):
            def match(pid, start):
                return mapping.get((pid, start))
            return mock.patch.object(worker, '_process_identity_matches', side_effect=match)

        both = ((4343, 'supervisor-start'), (4242, 'worker-start'))
        cases = (
            ('supervisor dead, worker alive', {'status': 'executing', 'pid': 4242, 'pid_start': 'worker-start',
                'supervisor_pid': 4343, 'supervisor_pid_start': 'supervisor-start'},
                {both[0]: False, both[1]: True}),
            ('supervisor alive, worker dead', {'status': 'running', 'pid': 4242, 'pid_start': 'worker-start',
                'supervisor_pid': 4343, 'supervisor_pid_start': 'supervisor-start'},
                {both[0]: True, both[1]: False}),
            ('identity unavailable', {'status': 'executing', 'pid': 4242, 'pid_start': 'worker-start',
                'supervisor_pid': 4343, 'supervisor_pid_start': 'supervisor-start'},
                {both[0]: None, both[1]: False}),
            ('worker pid not recorded', {'status': 'running', 'supervisor_pid': 4343,
                'supervisor_pid_start': 'supervisor-start'},
                {both[0]: False, (None, None): None}),
            ('no pid info', {'status': 'launching'}, {}),
            ('staged without pids', {'status': 'staged'}, {}),
        )
        for name, fields, mapping in cases:
            with self.subTest(name=name):
                self.record(self.repo, 'run-a', fields.pop('status'), **fields)
                with identities(mapping):
                    with self.assertRaises(ValidationIssue) as caught:
                        self.launch(self.repo, 'run-b')
                self.assertEqual(caught.exception.code, 'native_worker_shared_refs_active_run')
                self.assertFalse(worker.native_worker_paths(self.repo, 'run-b')[0].exists())
                worker.native_worker_paths(self.repo, 'run-a')[0].unlink()

    def test_unreadable_state_does_not_hide_authority_detail(self):
        broken = self.record(self.repo, 'broken', 'executing')
        broken.write_text('{broken')
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            detail = self.terminalize_moved_branch('feature/b', sibling=True)
        self.assertEqual(detail, 'The branch of another native worker run (other-run) moved in this repository. '
            'Two native workers cannot share one repository.')
        warning = output.getvalue()
        self.assertIn('Warning: cannot read native worker state', warning)
        self.assertIn(str(broken), warning)

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
            'The branch of another native worker run (other-run) moved in this repository. '
            'Two native workers cannot share one repository.')

    def test_unrelated_ref_failure_detail(self):
        self.assertEqual(self.terminalize_moved_branch('driver'),
            'refs/heads/driver moved outside this worker\'s assigned branch. '
            'A running worker treats every other ref in the repository as protected. '
            'Do not commit, branch, fetch, or push in this repository while it runs.')
