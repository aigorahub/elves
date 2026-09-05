import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cobbler_runtime.team_callbacks import CallbackAdapter
from cobbler_runtime.teams import contributor, reviewer_check, readiness_check, brainstorm, resolved_team_lanes
from cobbler_runtime.schema import ValidationIssue, ResolvedConfig
from cobbler_runtime.dispatch_models import LaneSpec, CouncilResult
from cobbler_runtime.delegated_git import reconcile_worker_report
from cobbler_runtime.preferences import set_preference, load_preferences

DRIVER = {'kind': 'codex', 'model': 'gpt-6-astra', 'session_id': 'driver-exact'}
HELPER = {'kind': 'claude-code', 'model': 'claude-fable-5-1', 'session_id': 'helper-exact'}
REVIEWER = {**DRIVER, 'session_id': 'reviewer-fresh'}


def session():
    return {'team': {'version': 1, 'driver': DRIVER, 'contributors': [{**DRIVER, 'role':'lead'}], 'helpers': {}}}


class TeamTests(unittest.TestCase):
    def test_contributors_cannot_review_same_family_fresh_can(self):
        state = session()
        contributor(state, HELPER, 'investigator')
        for candidate in (DRIVER, HELPER):
            with self.assertRaises(ValidationIssue) as cm:
                reviewer_check(state, candidate)
            self.assertEqual(cm.exception.code, 'team_reviewer_contributor')
        result = reviewer_check(state, REVIEWER)
        self.assertTrue(result['independent'])
        self.assertFalse(result['different_family'])

    def test_worker_report_cannot_remove_ledger_or_callback(self):
        state = {**session(), 'team_callback': {'protocol':1}}
        report = {'session_id':'worker', 'branch':'feat/a', 'team':{}, 'team_callback':{'executable':'evil'}}
        merged = reconcile_worker_report(state, report, expected_session_id='worker', expected_branch='feat/a')
        self.assertEqual(merged['team'], state['team'])
        self.assertEqual(merged['team_callback'], state['team_callback'])

    def test_readiness_requires_report_exact_head_and_artifact(self):
        state = session()
        with self.assertRaises(ValidationIssue):
            readiness_check(state, 'a'*40)
        with tempfile.TemporaryDirectory() as tmp:
            import hashlib
            artifact = Path(tmp) / 'review.md'
            artifact.write_text('Inspected code, tests, and docs. No findings.')
            state['team']['review'] = {'identity': REVIEWER, 'head':'a'*40, 'clean':True, 'artifact':str(artifact), 'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}
            readiness_check(state, 'a'*40)
            with self.assertRaises(ValidationIssue): readiness_check(state, 'b'*40)
            artifact.write_text('changed')
            with self.assertRaises(ValidationIssue): readiness_check(state, 'a'*40)
        readiness_check({}, 'a'*40)

    def test_independent_proposals_precede_critique(self):
        calls = []
        def dispatch(lanes, **kwargs):
            calls.append(kwargs)
            return CouncilResult(run_id='r', ok=True, council_verified=True, blocked=False, confidence='high', successful_reports=[{'proposal':'one'},{'proposal':'two'}])
        lanes = [LaneSpec('one','architect','host-native','host-native'), LaneSpec('two','critic','host-native','host-native')]
        result = brainstorm(lanes, repo_root=Path('.'), task='Improve checkout', dispatch=dispatch)
        self.assertTrue(result['ok'])
        self.assertNotIn('"proposal": "one"', calls[0]['task'])
        self.assertIn('"proposal": "one"', calls[1]['task'])
        self.assertEqual([x['phase'] for x in calls], ['planning','review'])

    def test_no_critique_after_incomplete_proposal(self):
        calls = []
        def dispatch(*args, **kwargs):
            calls.append(kwargs)
            return CouncilResult(run_id='r', ok=False, council_verified=False, blocked=True, confidence='blocked')
        lanes = [LaneSpec(str(i),'architect','host-native','host-native') for i in range(2)]
        result = brainstorm(lanes, repo_root=Path('.'), task='task', dispatch=dispatch)
        self.assertFalse(result['ok'])
        self.assertEqual(len(calls), 1)

    def test_missing_named_profile_fails_without_substitution(self):
        with self.assertRaises(ValidationIssue): resolved_team_lanes(ResolvedConfig(), ['not-installed','planning'], 10)

    def test_preferences_save_roles_without_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'config.json'
            set_preference('team.proposer','claude-code-planning',path=path)
            self.assertEqual(load_preferences(path)['team']['proposer'], 'claude-code-planning')
            with self.assertRaises(ValidationIssue): set_preference('team.merge','yes',path=path)


class CallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = {'protocol':1, 'executable':str(self.root/'fake'), 'state_dir':str(self.root/'mailbox'), 'actor_credential':str(self.root/'actor.json'), 'timeout_seconds':0.01}
        self.adapter = CallbackAdapter(self.config, self.root/'runtime')
        self.msg = {'message_id':'m1', 'run_id':'r1', 'task_id':'t1', 'recipient':'driver', 'kind':'progress', 'body':{'text':'ready'}}

    def tearDown(self): self.tmp.cleanup()

    def test_ambiguous_send_persists_id_and_retry_uses_same_content(self):
        sent = []
        def call(*args):
            if args[0] == 'capabilities': return {'protocol':1,'delivery':'checkpoint','automatic_wake':False}
            sent.append(json.loads(Path(args[-1]).read_text()))
            if len(sent) == 1: raise ValidationIssue('team_callback_ambiguous','timeout')
            return {'message_id':'m1','status':'queued'}
        with patch.object(self.adapter, 'call', side_effect=call):
            with self.assertRaises(ValidationIssue): self.adapter.post(self.msg)
            recovered = CallbackAdapter(self.config, self.root/'runtime')
            with patch.object(recovered,'call',side_effect=call): recovered.retry('m1')
        self.assertEqual(sent[0],sent[1])
        self.assertEqual(recovered.status()['outbox'][0]['status'],'stored')

    def test_duplicate_id_mismatch_rejected_before_call(self):
        with patch.object(self.adapter,'retry',return_value={}): self.adapter.post(self.msg)
        with self.assertRaises(ValidationIssue): self.adapter.post({**self.msg,'body':{'text':'changed'}})

    def test_busy_checkpoint_never_calls_transport(self):
        with patch.object(self.adapter,'call') as call:
            with self.assertRaises(ValidationIssue): self.adapter.checkpoint('batch-boundary',parked=True)
            call.assert_not_called()

    def test_receive_is_persistent_until_host_consumes(self):
        incoming = {**self.msg, 'receipt':'receipt', 'sender':HELPER, 'status':'claimed'}
        def call(*args):
            if args[0] == 'capabilities': return {'protocol':1,'delivery':'checkpoint','automatic_wake':False}
            if args[0] == 'receive': return {'messages':[incoming],'unresolved':[]}
            return {'status':'consumed'}
        with patch.object(self.adapter,'call',side_effect=call):
            self.assertEqual(len(self.adapter.checkpoint('before-review')['messages']),1)
            self.adapter.consume('m1', {'decision':'recorded'})
            self.assertEqual(self.adapter.checkpoint('before-review')['messages'],[])
            with self.assertRaises(ValidationIssue): self.adapter.consume('m1', {'decision':'different'})

    def test_real_subprocess_timeout_and_closed_stdin(self):
        script = Path(self.config['executable'])
        script.write_text('#!'+sys.executable+'\nimport sys,time\nassert sys.stdin.read()==""\ntime.sleep(0.1)\n')
        script.chmod(0o700)
        with self.assertRaises(ValidationIssue) as cm: self.adapter.probe()
        self.assertEqual(cm.exception.code,'team_callback_ambiguous')

    def test_protocol_mismatch(self):
        with patch.object(self.adapter,'call',return_value={'protocol':2,'delivery':'checkpoint','automatic_wake':False}):
            with self.assertRaises(ValidationIssue): self.adapter.probe()


if __name__ == '__main__': unittest.main()
