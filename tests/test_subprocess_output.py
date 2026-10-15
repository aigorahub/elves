"""Live subprocess regressions for capture-time limits (issue #281)."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cobbler_runtime import subprocess_output as output
from cobbler_runtime import native_worker, team_callbacks
from cobbler_runtime.schema import ValidationIssue
from cobbler_runtime.full_run_monitor import _capture_omp_session_id
import resume_watchdog
import verify_repo


class CaptureTests(unittest.TestCase):
    def test_exact_limit_is_complete_and_next_byte_fails(self):
        capture = output.ByteCapture(10)
        capture.feed(b"0123456789")
        self.assertFalse(capture.exceeded)
        self.assertEqual(capture.value(), b"0123456789")
        capture.feed(b"x")
        self.assertTrue(capture.exceeded)
        self.assertEqual(capture.value(), b"123456789x")

    def test_overflow_retains_only_bounded_tail_even_during_cleanup(self):
        capture = output.ByteCapture(100_000)
        capture.feed(b"a" * 100_000)
        for _ in range(30):
            capture.feed(b"z" * 65_536)
            self.assertLessEqual(len(capture.value()), output.DIAGNOSTIC_TAIL_BYTES)
        self.assertTrue(capture.exceeded)
        self.assertEqual(capture.value(), b"z" * output.DIAGNOSTIC_TAIL_BYTES)

    def test_limits_reject_bool_zero_and_negative(self):
        for limit in (True, 0, -1, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                output.ByteCapture(limit)


@unittest.skipUnless(os.name == "posix", "Elves runtime requires POSIX or WSL2")
class SyncCaptureTests(unittest.TestCase):
    def run_code(self, code, **kwargs):
        return output.run_bounded([sys.executable, "-c", code], timeout=3, **kwargs)

    def test_small_output_stdin_eof_and_nonzero_status_preserved(self):
        result = self.run_code("import sys; assert not sys.stdin.read(); print('out'); print('err',file=sys.stderr); sys.exit(7)", text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (7, "out\n", "err\n"))

    def test_stdout_and_stderr_limits_are_independent(self):
        for fd in (1, 2):
            with self.subTest(fd=fd), self.assertRaises(output.OutputLimitExceeded) as error:
                self.run_code(f"import os,time; os.write({fd},b'x'*8192); time.sleep(30)", max_stdout=4096, max_stderr=4096)
            self.assertEqual(error.exception.stream, "stdout" if fd == 1 else "stderr")
            self.assertLessEqual(len(error.exception.stdout), 4096)
            self.assertLessEqual(len(error.exception.stderr), 4096)

    def test_both_streams_are_drained_without_deadlock(self):
        result = self.run_code("import os;\nfor _ in range(20):\n os.write(1,b'a'*8192); os.write(2,b'b'*8192)")
        self.assertEqual(result.stdout, b"a" * (20 * 8192))
        self.assertEqual(result.stderr, b"b" * (20 * 8192))

    def test_fast_exit_zero_does_not_hide_overflow(self):
        with self.assertRaises(output.OutputLimitExceeded):
            self.run_code("import os; os.write(1,b'x'*4097)", max_stdout=4096)

    def test_timeout_preserves_partial_output_and_reaps_child(self):
        with self.assertRaises(subprocess.TimeoutExpired) as error:
            output.run_bounded([sys.executable, "-c", "import os,time; print(os.getpid(),flush=True); time.sleep(30)"], timeout=.3)
        pid = int(error.exception.output.strip())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_overflow_reaps_producer(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "pid"
            code = f"import os,time; open({str(pid_file)!r},'w').write(str(os.getpid())); os.write(2,b'x'*10000); time.sleep(30)"
            with self.assertRaises(output.OutputLimitExceeded):
                self.run_code(code, max_stderr=4096)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)

    def test_inherited_pipes_cannot_defeat_deadline(self):
        started = time.monotonic()
        code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print('parent',flush=True)"
        with self.assertRaises(subprocess.TimeoutExpired):
            output.run_bounded([sys.executable,"-c",code], timeout=.3)
        self.assertLess(time.monotonic() - started, 3)


class AsyncCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_output_and_stdin_are_preserved(self):
        proc = await asyncio.create_subprocess_exec(sys.executable,"-c", "import sys; print(sys.stdin.read()); print('err',file=sys.stderr)", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        capture = output.AsyncCapture(4096,4096)
        communication = asyncio.create_task(capture.communicate(proc,input=b"hello"))
        await asyncio.wait_for(capture.wait_for_exit(proc.wait()),3)
        out,err = await communication
        self.assertEqual((out,err),(b"hello\n",b"err\n"))
        self.assertIsNone(capture.error())

    async def test_overflow_wakes_owner_before_producer_exits(self):
        for fd in (1,2):
            with self.subTest(fd=fd):
                proc = await asyncio.create_subprocess_exec(sys.executable,"-c",f"import os,time; os.write({fd},b'x'*8192); time.sleep(30)", stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                capture = output.AsyncCapture(4096,4096)
                communication = asyncio.create_task(capture.communicate(proc))
                try:
                    with self.assertRaises(output.OutputLimitExceeded):
                        await asyncio.wait_for(capture.wait_for_exit(proc.wait()),3)
                    self.assertIsNone(proc.returncode)
                finally:
                    if proc.returncode is None:
                        proc.kill()
                    await asyncio.wait_for(communication,3)
                self.assertIsNotNone(capture.error())
                self.assertLessEqual(len(capture.stdout.value()),4096)
                self.assertLessEqual(len(capture.stderr.value()),4096)

    async def test_cancelled_capture_leaves_no_internal_tasks(self):
        proc = await asyncio.create_subprocess_exec(sys.executable,"-c","import time; time.sleep(30)",stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        capture = output.AsyncCapture(4096,4096)
        communication = asyncio.create_task(capture.communicate(proc))
        await asyncio.sleep(.03)
        communication.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await communication
        proc.kill()
        await proc.wait()
        pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
        self.assertEqual(pending,[])


class ExternalLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def launch(self, code, *, cleanup_ok=True):
        from cobbler_runtime import dispatch_external as external
        plan = external.ExternalLaunchPlan(
            argv=[sys.executable, "-c", code], cwd=str(Path.cwd()),
            env=dict(os.environ), isolated=None, isolation_meta={},
            fallback_host_native=False, invocation=None, stdin_bytes=None,
        )
        async def contain(proc, **kwargs):
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            return {"reaped": True, "group_absent": cleanup_ok,
                    "error": None if cleanup_ok else "fixture cleanup unproved"}
        # Only the containment boundary is a fixture; both output pipes and
        # the capture-time overflow come from a real subprocess.
        with mock.patch.object(external, "_require_qualified_process_boundary", return_value="pid-namespace"), \
             mock.patch.object(external, "terminate_process_group", side_effect=contain) as cleanup, \
             mock.patch.object(external, "EXTERNAL_STDOUT_MAX_BYTES", 4096), \
             mock.patch.object(external, "EXTERNAL_STDERR_MAX_BYTES", 4096):
            result = await asyncio.wait_for(external.run_external_subprocess(plan=plan, timeout_seconds=3), 6)
        return result, cleanup

    async def test_overflow_uses_existing_cleanup_and_never_success(self):
        for fd in (1, 2):
            with self.subTest(fd=fd):
                result, cleanup = await self.launch(f"import os,time; os.write({fd},b'x'*8192); time.sleep(30)")
                self.assertFalse(result["ok"])
                self.assertEqual(result["failure_class"], "output_limit")
                self.assertTrue(result["cleanup"]["isolation_cleaned"])
                cleanup.assert_awaited()
                self.assertLessEqual(len(result["stdout_raw"]), 4096)
                self.assertLessEqual(len(result["stderr_raw"]), 4096)

    async def test_fast_exit_overflow_is_not_a_clean_result(self):
        result, _ = await self.launch("import os; os.write(1,b'x'*8192)")
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_class"], "output_limit")

    async def test_containment_failure_takes_precedence_over_limit(self):
        result, _ = await self.launch("import os,time; os.write(1,b'x'*8192); time.sleep(30)", cleanup_ok=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_class"], "isolation_failure")


@unittest.skipUnless(os.name == "posix", "Elves runtime requires POSIX or WSL2")
class IntegrationTests(unittest.TestCase):
    def phase(self, root, code):
        state_path,log_path = native_worker.native_worker_paths(root,"output-test")
        state={"run_id":"output-test","worktree":str(root),"status":"launching","session_id":None,"provider_event_count":0}
        native_worker._write_private_json(state_path,state)
        result=native_worker._run_worker_phase(state_path=state_path,log_path=log_path,state=state,phase="execution",argv=(sys.executable,"-c",code),input_text="",child_env=dict(os.environ),expected_session_id=None)
        return state,result,log_path

    def test_native_unterminated_line_fails_and_reaps_child(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(native_worker,"NATIVE_OUTPUT_LINE_MAX_BYTES",1024):
            root=Path(tmp)
            code=f"import os,time; open({str(root/'pid')!r},'w').write(str(os.getpid())); os.write(1,b'x'*2048); time.sleep(30)"
            with self.assertRaises(ValidationIssue) as error:
                self.phase(root,code)
            self.assertEqual(error.exception.code,"native_worker_output_limit")
            with self.assertRaises(ProcessLookupError):
                os.kill(int((root/'pid').read_text()),0)

    def test_native_many_small_lines_hit_log_budget_before_write(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(native_worker,"NATIVE_OUTPUT_LOG_MAX_BYTES",1000):
            root=Path(tmp)
            with self.assertRaises(ValidationIssue) as error:
                self.phase(root,"for _ in range(100): print('hello')")
            self.assertEqual(error.exception.code,"native_worker_output_limit")
            _,log=native_worker.native_worker_paths(root,"output-test")
            self.assertLessEqual(log.stat().st_size,1000)

    def test_native_stream_budget_counts_small_lines(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(native_worker,"NATIVE_OUTPUT_STREAM_MAX_BYTES",1024):
            with self.assertRaises(ValidationIssue):
                self.phase(Path(tmp),"for _ in range(1000): print('abc')")

    def test_native_split_utf8_and_identity_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            code="import os,json,time; os.write(1,b'caf\\xc3'); time.sleep(.03); os.write(1,b'\\xa9\\n'); print(json.dumps({'type':'thread.started','thread_id':'exact-thread'}),flush=True)"
            state,result,log=self.phase(Path(tmp),code)
            self.assertEqual(state['session_id'],'exact-thread')
            self.assertEqual(result.exit_code,0)
            rows=[json.loads(line) for line in log.read_text().splitlines()]
            self.assertIn('caf\u00e9',[row['line'] for row in rows])

    def test_callback_rejects_oversized_stderr_with_valid_stdout(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(team_callbacks,"MAX_BYTES",1024):
            root=Path(tmp); script=root/'callback.py'
            script.write_text("import os; print('{}',flush=True); os.write(2,b'x'*2048)")
            adapter=team_callbacks.CallbackAdapter({'protocol':1,'executable':str(script),'state_dir':str(root/'state'),'actor_credential':str(root/'credential')},root/'runtime')
            with self.assertRaises(ValidationIssue) as error:
                adapter.call('capabilities')
            self.assertEqual(error.exception.code,'team_callback_output')

    def test_verify_overflow_is_failed_gate_not_success(self):
        real=output.run_bounded
        def small(*args,**kwargs):
            return real(*args,**kwargs,max_stdout=1024,max_stderr=1024)
        with mock.patch.object(verify_repo,'run_bounded',side_effect=small):
            result=verify_repo._run([sys.executable,'-c',"print('x'*2048)"],cwd=Path.cwd())
        self.assertEqual(result.returncode,125)
        self.assertIn('subprocess_output_limit',result.stderr)

    def test_watchdog_does_not_classify_partial_success(self):
        error=output.OutputLimitExceeded('stdout',1024,stdout=b'full_run_resume_prepare_live')
        with mock.patch.object(resume_watchdog,'run_bounded',side_effect=error):
            result=resume_watchdog._run_hub({'repo_root':str(Path.cwd())},['full-run-prepare'])
        self.assertEqual(result.returncode,125)
        self.assertEqual(resume_watchdog._classify(result)[0],'refused_other')

    def test_omp_oversized_file_never_binds_truncated_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); sid='11111111-2222-3333-4444-555555555555'
            with (root/'omp.ndjson').open('wb') as handle:
                handle.write(json.dumps({'type':'session','id':sid}).encode()+b'\n')
                handle.truncate(16*1024*1024+1)
            (root/'provider.stdout').write_text(json.dumps({'type':'session','id':sid}))
            self.assertIsNone(_capture_omp_session_id({},root,root))

    def test_omp_normal_identity_and_conflicts_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'omp.ndjson'; sid='11111111-2222-3333-4444-555555555555'
            path.write_text(json.dumps({'type':'session','id':sid})+'\n')
            self.assertEqual(_capture_omp_session_id({},root,root),sid)
            with path.open('a') as handle:
                handle.write(json.dumps({'type':'session','id':'22222222-2222-3333-4444-555555555555'})+'\n')
            self.assertIsNone(_capture_omp_session_id({},root,root))


if __name__ == '__main__':
    unittest.main()
