"""Optional Lantern protocol v1 adapter. Delivery is pull-only at checkpoints."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import sys
import uuid
from typing import Any

from .schema import ValidationIssue

CHECKPOINTS = ('after-staging', 'batch-boundary', 'packet-boundary', 'before-review', 'before-readiness', 'before-landing')
MAX_BYTES = 1024 * 1024


def fail(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, message)


def validate_callback(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict) or config.get('protocol') != 1:
        raise fail('team_callback_protocol', 'Callback protocol must be 1')
    for key in ('executable', 'state_dir', 'actor_credential'):
        value = config.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise fail('team_callback_path', f'Callback {key} must be an absolute path')
    timeout = config.get('timeout_seconds', 10)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise fail('team_callback_timeout', 'Callback timeout must be greater than zero and at most 60 seconds')
    return config


class CallbackAdapter:
    def __init__(self, config: dict[str, Any], runtime: Path):
        self.config = validate_callback(config)
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = runtime / 'callbacks.sqlite3'
        if self.path.is_symlink():
            raise fail('team_callback_state', 'Callback state must not be a symbolic link')
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            encoded_config = json.dumps(self.config, sort_keys=True)
            prior = db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
            if prior and prior[0] != encoded_config:
                raise fail('team_callback_identity_drift', 'Callback storage belongs to a different endpoint identity')
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('config',?)", (encoded_config,))
            db.execute('CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, message TEXT NOT NULL, status TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS inbox (id TEXT PRIMARY KEY, message TEXT NOT NULL, status TEXT NOT NULL, result TEXT)')
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def call(self, *args: str) -> dict[str, Any]:
        command = [self.config['executable'], '--state-dir', self.config['state_dir'], *args]
        if Path(command[0]).suffix.lower() == '.py':
            command.insert(0, sys.executable)
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                        timeout=self.config.get('timeout_seconds', 10), check=False)
            except subprocess.TimeoutExpired as exc:
                raise fail('team_callback_ambiguous', 'Callback timed out; retain its message ID and reconcile') from exc
            except OSError as exc:
                raise fail('team_callback_unavailable', 'Callback executable could not start') from exc
            out.seek(0)
            raw = out.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise fail('team_callback_output', 'Callback output exceeded the size limit')
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise fail('team_callback_output', 'Callback returned invalid JSON; reconcile before retry') from exc
        if not isinstance(data, dict):
            raise fail('team_callback_output', 'Callback result must be an object')
        if result.returncode:
            raise fail('team_callback_failed', str(data.get('error', 'Callback returned failure'))[:200])
        return data

    def probe(self):
        data = self.call('capabilities')
        if data.get('protocol') != 1 or data.get('delivery') != 'checkpoint' or data.get('automatic_wake') is not False:
            raise fail('team_callback_incompatible', 'Lantern callback requires protocol 1 checkpoint delivery without automatic wake')
        return data

    def post(self, message: dict[str, Any]) -> dict[str, Any]:
        message = dict(message)
        message.setdefault('message_id', str(uuid.uuid4()))
        message.setdefault('schema_version', 1)
        for field in ('message_id', 'run_id', 'task_id', 'recipient'):
            if not isinstance(message.get(field), str) or not message[field].strip():
                raise fail('team_callback_message_invalid', f'Message requires nonempty {field}')
        if message['schema_version'] != 1 or not isinstance(message.get('body'), dict):
            raise fail('team_callback_message_invalid', 'Message requires schema 1 and an object body')
        if message.get('kind') not in ('assignment','progress','question','answer','decision','pr_opened','review_requested','review_result','blocked','completion','cancellation'):
            raise fail('team_callback_message_invalid', 'Message kind is unsupported')
        ttl = message.get('ttl_seconds', 86400)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 0 < ttl <= 604800:
            raise fail('team_callback_message_invalid', 'Message TTL must be 1 to 604800 seconds')
        encoded = json.dumps(message, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise fail('team_callback_message_size', 'Message exceeds the size limit')
        mid = message['message_id']
        if not isinstance(mid, str) or not mid:
            raise fail('team_callback_message_id', 'Message ID must be a nonempty string')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT message,status FROM outbox WHERE id=?', (mid,)).fetchone()
            if prior and prior[0] != encoded:
                raise fail('team_callback_duplicate', 'Message ID already has different content')
            if prior and prior[1] == 'stored':
                return {'message_id': mid, 'status': 'stored', 'duplicate': True}
            db.execute('INSERT OR IGNORE INTO outbox VALUES (?,?,?)', (mid, encoded, 'pending'))
        return self.retry(mid)

    def retry(self, mid: str) -> dict[str, Any]:
        with self.db() as db:
            row = db.execute('SELECT message FROM outbox WHERE id=?', (mid,)).fetchone()
        if not row:
            raise fail('team_callback_message_missing', 'No persisted message has this ID')
        self.probe()
        fd, filename = tempfile.mkstemp(prefix='elves-message-', suffix='.json')
        try:
            with os.fdopen(fd, 'w') as handle:
                handle.write(row[0])
            result = self.call('post', '--actor', self.config['actor_credential'], '--input', filename)
            if result.get('message_id') != mid or result.get('status') not in ('stored', 'queued', 'claimed', 'consumed', 'expired', 'unresolved', 'retired'):
                raise fail('team_callback_receipt', 'Callback did not return a storage receipt for the expected message')
            with self.db() as db:
                db.execute('UPDATE outbox SET status=? WHERE id=?', ('stored', mid))
            return result
        finally:
            Path(filename).unlink(missing_ok=True)

    def checkpoint(self, name: str, *, parked: bool = False) -> dict[str, Any]:
        if name not in CHECKPOINTS or parked:
            raise fail('team_callback_unsafe_checkpoint', 'Consume at a named driver checkpoint after the worker has returned')
        self.probe()
        payload = self.call('receive', '--actor', self.config['actor_credential'], '--limit', '20')
        messages = payload.get('messages')
        if not isinstance(messages, list):
            raise fail('team_callback_output', 'Receive must return messages')
        acknowledgements = []
        with self.db() as db:
            for message in messages:
                if not isinstance(message, dict) or not isinstance(message.get('message_id'), str) or not message.get('receipt'):
                    raise fail('team_callback_output', 'Received message lacks identity or receipt')
                mid = message['message_id']
                prior = db.execute('SELECT status,message FROM inbox WHERE id=?', (mid,)).fetchone()
                encoded = json.dumps(message)
                if prior:
                    original = json.loads(prior[1])
                    stable = lambda item: {key:value for key,value in item.items() if key not in ('receipt','status')}
                    if stable(original) != stable(message):
                        raise fail('team_callback_duplicate', 'Received message ID has different content')
                    db.execute('UPDATE inbox SET message=? WHERE id=?', (encoded,mid))
                    if prior[0] == 'consumed':
                        acknowledgements.append((mid,message['receipt']))
                else:
                    db.execute('INSERT INTO inbox VALUES (?,?,?,NULL)', (mid,encoded,'received'))
            unresolved = set(payload.get('unresolved', []))
            ready = [json.loads(row[0]) for row in db.execute("SELECT message FROM inbox WHERE status='received' ORDER BY rowid LIMIT 20") if json.loads(row[0])['message_id'] not in unresolved]
        for mid, receipt in acknowledgements:
            self.call('ack', '--actor', self.config['actor_credential'], '--message-id', mid, '--receipt', receipt)
        return {'checkpoint': name, 'messages': ready, 'unresolved': payload.get('unresolved', []), 'automatic_actions': False}

    def consume(self, mid: str, result: dict[str, Any]) -> dict[str, Any]:
        with self.db() as db:
            row = db.execute('SELECT message,status,result FROM inbox WHERE id=?', (mid,)).fetchone()
            if not row:
                raise fail('team_callback_message_missing', 'Message was not received at a checkpoint')
            encoded = json.dumps(result, sort_keys=True, allow_nan=False)
            if row[1] == 'consumed' and row[2] != encoded:
                raise fail('team_callback_duplicate', 'Consumed result cannot change')
            db.execute('UPDATE inbox SET status=?,result=? WHERE id=?', ('consumed', encoded, mid))
        message = json.loads(row[0])
        # The host result is durable before the remote receipt. On an expired claim,
        # reconciliation is explicit and does not repeat the host action.
        return self.call('ack', '--actor', self.config['actor_credential'], '--message-id', mid, '--receipt', message['receipt'])

    def status(self):
        with self.db() as db:
            return {'outbox': [{'message_id': r[0], 'status': r[1]} for r in db.execute('SELECT id,status FROM outbox')],
                    'inbox': [{'message_id': r[0], 'status': r[1]} for r in db.execute('SELECT id,status FROM inbox')]}


def report_command(args):
    """Scoped helper transport. Does not load or mutate the driver session."""
    try:
        from .teams import read_json
        adapter = CallbackAdapter(read_json(args.config), Path(args.runtime))
        action = args.report_action
        if action == 'post':
            payload = adapter.post(read_json(args.input))
        elif action == 'retry':
            payload = adapter.retry(args.message_id)
        elif action == 'checkpoint':
            payload = adapter.checkpoint(args.checkpoint)
        elif action == 'consume':
            payload = adapter.consume(args.message_id, read_json(args.input))
        elif action == 'status':
            payload = adapter.status()
        elif action == 'inspect':
            payload = adapter.call('inspect','--actor',adapter.config['actor_credential'],'--message-id',args.message_id)
        elif action == 'reconcile':
            payload = adapter.call('reconcile','--actor',adapter.config['actor_credential'],'--message-id',args.message_id,'--outcome',args.outcome)
        else:
            payload = adapter.probe()
        print(json.dumps({'ok':True,'result':payload},sort_keys=True))
        return 0
    except (ValidationIssue,OSError,ValueError,TypeError) as exc:
        print(json.dumps({'ok':False,'error':getattr(exc,'code','team_callback_failed'),'message':str(exc)}))
        return 1


def add_report_parser(sub):
    parser = sub.add_parser('team-report',help='Helper scoped reports without driver session access')
    actions = parser.add_subparsers(dest='report_action',required=True)
    for action in ('probe','post','retry','checkpoint','consume','status','inspect','reconcile'):
        command=actions.add_parser(action)
        command.add_argument('--config',required=True,type=Path)
        command.add_argument('--runtime',required=True,type=Path)
        command.add_argument('--json',action='store_true')
        if action in ('post','consume'): command.add_argument('--input',required=True,type=Path)
        if action in ('retry','consume','inspect','reconcile'): command.add_argument('--message-id',required=True)
        if action == 'checkpoint': command.add_argument('--checkpoint',required=True,choices=CHECKPOINTS)
        if action == 'reconcile': command.add_argument('--outcome',required=True,choices=('consumed','retry'))
        command.set_defaults(func=report_command)
