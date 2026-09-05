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
from cobbler_runtime.teams import contributor, reviewer_check, readiness_check, brainstorm, resolved_team_lanes, helper_packet
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

    def test_public_route_detects_team_without_explicit_session(self):
        cli = Path(__file__).resolve().parents[1] / 'scripts/cobbler_agents.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'.elves-session.json').write_text(json.dumps(session()))
            command = [sys.executable,str(cli),'review-route','--repo-root',str(root),'--host','codex','--json']
            missing = subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(missing.returncode,0)
            self.assertIn('team_reviewer_identity_missing',missing.stdout)
            candidate=root/'candidate.json'; candidate.write_text(json.dumps(DRIVER))
            excluded=subprocess.run(command+['--reviewer-identity',str(candidate)],capture_output=True,text=True)
            self.assertIn('team_reviewer_contributor',excluded.stdout)
            candidate.write_text(json.dumps(REVIEWER))
            accepted=subprocess.run(command+['--reviewer-identity',str(candidate)],capture_output=True,text=True)
            self.assertEqual(accepted.returncode,0,accepted.stdout+accepted.stderr)
            candidate.write_text(json.dumps(HELPER))
            mismatch=subprocess.run(command+['--reviewer-identity',str(candidate)],capture_output=True,text=True)
            self.assertIn('team_reviewer_route_mismatch',mismatch.stdout)

    def test_helper_packet_uses_own_credential_and_bound_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            state=session(); state['run_id']='run'; state['worktree_path']=str(root)
            driver_cred=root/'driver-credential.json'; helper_cred=root/'helper-credential.json'
            driver_actor={**DRIVER,'actor_id':'driver','role':'driver','run_id':'run','task_ids':['task'],'peers':['helper']}
            helper_actor={**HELPER,'actor_id':'helper','role':'helper','run_id':'run','task_ids':['task'],'peers':['driver']}
            driver_cred.write_text(json.dumps({'protocol':1,'actor':driver_actor,'token':'private-driver-token'}))
            helper_cred.write_text(json.dumps({'protocol':1,'actor':helper_actor,'token':'private-helper-token'}))
            state['team_callback']={'protocol':1,'executable':str(root/'mailbox.py'),'state_dir':str(root),'actor_credential':str(driver_cred)}
            state['team']['helpers']['task']={'task':'Read database code','role':'investigator','identity':HELPER,'intent':'Find cause','build_on':['src'],'owned_surfaces':['analysis'],'forbidden_surfaces':['product writes'],'acceptance':['Cite query evidence'],'callback':{**state['team_callback'],'actor_credential':str(helper_cred)}}
            packet=helper_packet(state,'task',root)
            self.assertIn('team-report',packet)
            self.assertIn('Before exit, publish completion',packet)
            self.assertNotIn('private-driver-token',packet)
            self.assertNotIn('private-helper-token',packet)
            self.assertNotIn(str(driver_cred),packet)
            state['team']['helpers']['task']['callback']['actor_credential']=str(driver_cred)
            with self.assertRaises(ValidationIssue): helper_packet(state,'task',root)
            state['team']['helpers']['task']['callback']['actor_credential']=str(helper_cred)
            helper_actor['session_id']='changed'
            helper_cred.write_text(json.dumps({'protocol':1,'actor':helper_actor,'token':'private-helper-token'}))
            with self.assertRaises(ValidationIssue): helper_packet(state,'task',root)


class CallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = {'protocol':1, 'executable':str(self.root/'fake.py'), 'state_dir':str(self.root/'mailbox'), 'actor_credential':str(self.root/'actor.json'), 'timeout_seconds':0.01}
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


class CallbackConcurrencyTests(unittest.TestCase):
    def test_100_reports_persist_without_loss(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {'protocol':1,'executable':str(root/'fake'),'state_dir':str(root/'state'),'actor_credential':str(root/'cred')}
            adapter = CallbackAdapter(config, root/'runtime')
            def call(*args):
                if args[0] == 'capabilities': return {'protocol':1,'delivery':'checkpoint','automatic_wake':False}
                message = json.loads(Path(args[-1]).read_text())
                return {'message_id':message['message_id'],'status':'queued'}
            with patch.object(adapter,'call',side_effect=call):
                def post(index):
                    return adapter.post({'message_id':str(index),'run_id':'r','task_id':'t','recipient':'driver','kind':'progress','body':{'index':index}})
                with ThreadPoolExecutor(max_workers=8) as pool:
                    self.assertEqual(len(list(pool.map(post, range(100)))),100)
            self.assertEqual(len(adapter.status()['outbox']),100)
            self.assertTrue(all(row['status']=='stored' for row in adapter.status()['outbox']))

    def test_message_limit_precedes_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {'protocol':1,'executable':str(root/'fake'),'state_dir':str(root/'state'),'actor_credential':str(root/'cred')}
            adapter = CallbackAdapter(config,root/'runtime')
            with patch.object(adapter,'call') as call:
                with self.assertRaises(ValidationIssue): adapter.post({'message_id':'too-large','body':{'text':'x'*65536}})
                call.assert_not_called()


@unittest.skipUnless(os.environ.get('ELVES_TEST_LANTERN_MAILBOX'), 'Set ELVES_TEST_LANTERN_MAILBOX for cross-repository protocol qualification')
class LiveLanternProtocolTests(unittest.TestCase):
    def test_near_limit_batch_remains_consumable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); state=root/'mailbox'; state.mkdir()
            exe=Path(os.environ['ELVES_TEST_LANTERN_MAILBOX']).resolve()
            for actor, peer in [('driver','helper'),('helper','driver')]:
                definition={'actor_id':actor,'run_id':'r','role':actor,'server_id':'server','pane_id':actor,'session_id':actor+'-session','kind':'codex','model':'gpt-6-astra','generation':'g','task_ids':['t'],'peers':[peer]}
                source=root/(actor+'.json'); source.write_text(json.dumps(definition))
                command=[sys.executable,str(exe),'--state-dir',str(state),'register','--input',str(source),'--output',str(state/(actor+'-credential.json'))]
                subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
            def make(actor):
                return CallbackAdapter({'protocol':1,'executable':str(exe),'state_dir':str(state),'actor_credential':str(state/(actor+'-credential.json'))},root/(actor+'-runtime'))
            helper=make('helper'); driver=make('driver')
            for index in range(20):
                helper.post({'message_id':str(index),'run_id':'r','task_id':'t','recipient':'driver','kind':'progress','body':{'text':'x'*58000}})
            seen=[]
            for _ in range(20):
                messages=driver.checkpoint('before-review')['messages']
                if not messages: break
                for message in messages:
                    seen.append(message['message_id'])
                    driver.consume(message['message_id'], {'recorded':True})
            self.assertEqual(len(seen),20)
            self.assertEqual(len(set(seen)),20)
            self.assertEqual(helper.retry('0')['status'],'consumed')


if __name__ == '__main__': unittest.main()
