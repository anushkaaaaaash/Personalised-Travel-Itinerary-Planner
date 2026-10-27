import copy
import contextlib
import importlib.util
import http.server
import io
import textwrap
import pathlib
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

path = pathlib.Path(__file__).resolve().parents[1] / 'fly_checkpoint_volume.py'
spec = importlib.util.spec_from_file_location('volume', path)
volume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(volume)

MACHINE = {'id': '48edd43eb29178', 'region': 'sin', 'state': 'started', 'config': {'guest': {'cpu_kind': 'shared', 'cpus': 1, 'memory_mb': 512}}}
VOLUME = {'id': 'vol_123abc', 'name': 'planner_checkpoints', 'region': 'sin', 'size_gb': 1, 'encrypted': True, 'auto_backup_enabled': False, 'state': 'created', 'attached_machine_id': None}


class VolumeTests(unittest.TestCase):
    def test_quiescence_probe_on_existing_image_schema(self):
        with tempfile.TemporaryDirectory() as d:
            db = pathlib.Path(d) / 'test.sqlite3'
            with sqlite3.connect(db) as c:
                c.execute('CREATE TABLE plans(data TEXT NOT NULL)')
                c.execute('CREATE TABLE sections(data TEXT NOT NULL)')
                c.execute('PRAGMA user_version=1')
            runtime = types.ModuleType('app.adaptive_sqlite_runtime')
            runtime.verify_volume = lambda: str(db)
            app = types.ModuleType('app'); app.__path__ = []
            def probe():
                out = io.StringIO()
                with patch.dict(sys.modules, {'app': app, 'app.adaptive_sqlite_runtime': runtime}), patch('os.geteuid',return_value=10001), patch('os.umask'), contextlib.redirect_stdout(out):
                    with self.assertRaises(SystemExit) as end: exec(volume.QUIESCENCE_PROBE, {})
                return end.exception.code, __import__('json').loads(out.getvalue())
            code, result = probe()
            self.assertEqual(code, 0)
            self.assertEqual(result, {'ready': True, 'code': 'READY', 'counts': {'active_plans': 0, 'queued': 0, 'submitting': 0, 'running': 0, 'submission_unknown':0, **{f'{prefix}_{status}':0 for prefix in ('research','revision') for status in ('queued','submitting','running','submission_unknown')}}})
            for table, status in [('plans','active'),('sections','queued'),('sections','submitting'),('sections','running')]:
                with sqlite3.connect(db) as c: c.execute(f'INSERT INTO {table}(data) VALUES (?)', ('{"status":"' + status + '","private":"not-output"}',))
                code, result = probe()
                self.assertEqual(code, 1); self.assertFalse(result['ready']); self.assertEqual(result['code'], 'PLANNING_IN_PROGRESS')
                self.assertNotIn('not-output', str(result))
                with sqlite3.connect(db) as c: c.execute(f'DELETE FROM {table}')
            with sqlite3.connect(db) as c: c.execute('INSERT INTO sections(data) VALUES (?)', ('{"status":"submission_unknown"}',))
            self.assertEqual(probe()[1]['code'],'PLANNING_UNCERTAIN')
            with sqlite3.connect(db) as c: c.execute('DELETE FROM sections')
            for table in ('plans', 'sections'):
                for raw in ('{}', '{"status":null}', '{"status":3}', '{"status":"future"}', '{"status":"expired"}', '[]', 'not-json'):
                    with self.subTest(table=table, raw=raw):
                        with sqlite3.connect(db) as c: c.execute(f'INSERT INTO {table}(data) VALUES (?)', (raw,))
                        code, result = probe()
                        self.assertEqual(code, 1)
                        self.assertEqual(result, {'ready':False, 'code':'PREFLIGHT_FAILED'})
                        with sqlite3.connect(db) as c: c.execute(f'DELETE FROM {table}')

            with sqlite3.connect(db) as c:
                c.execute('PRAGMA user_version=2')
            self.assertEqual(probe()[1], {'ready':False,'code':'PREFLIGHT_FAILED'})
            with sqlite3.connect(db) as c:
                c.execute('CREATE TABLE research_jobs(data TEXT NOT NULL)')
                c.execute('CREATE TABLE revision_jobs(data TEXT NOT NULL)')
                c.execute('CREATE TABLE revision_controls(id TEXT)')
            self.assertEqual(probe()[0],0)
            for table in ('research_jobs','revision_jobs'):
                for status in ('queued','submitting','running'):
                    with self.subTest(table=table,status=status):
                        with sqlite3.connect(db) as c: c.execute(f'INSERT INTO {table}(data) VALUES (?)', ('{"status":"'+status+'","private":"not-output"}',))
                        code,result=probe(); self.assertEqual(code,1); self.assertEqual(result['code'],'PLANNING_IN_PROGRESS'); self.assertNotIn('not-output',str(result))
                        with sqlite3.connect(db) as c: c.execute(f'DELETE FROM {table}')
                with sqlite3.connect(db) as c: c.execute(f'INSERT INTO {table}(data) VALUES (?)', ('{"status":"submission_unknown"}',))
                self.assertEqual(probe()[1]['code'],'PLANNING_UNCERTAIN')
                with sqlite3.connect(db) as c: c.execute(f'DELETE FROM {table}')
                for raw in ('{}','{"status":null}','{"status":"future"}','[]','not-json'):
                    with self.subTest(table=table,raw=raw):
                        with sqlite3.connect(db) as c: c.execute(f'INSERT INTO {table}(data) VALUES (?)',(raw,))
                        self.assertEqual(probe()[1],{'ready':False,'code':'PREFLIGHT_FAILED'})
                        with sqlite3.connect(db) as c: c.execute(f'DELETE FROM {table}')

    def test_quiescence_drops_root_before_open_and_fails_closed(self):
        runtime = types.ModuleType('app.adaptive_sqlite_runtime')
        runtime.verify_volume = lambda: '/private/test.sqlite3'
        app = types.ModuleType('app'); app.__path__ = []
        def run(uid_values, failure=None):
            out=io.StringIO()
            with patch.dict(sys.modules, {'app':app,'app.adaptive_sqlite_runtime':runtime}), patch('os.geteuid',side_effect=uid_values), patch('os.umask') as mask, patch('os.setgroups') as groups, patch('os.setgid') as gid, patch('os.setuid',side_effect=failure) as uid, patch('sqlite3.connect',side_effect=RuntimeError('private')) as connect, contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit):exec(volume.QUIESCENCE_PROBE,{})
            return __import__('json').loads(out.getvalue()),mask,groups,gid,uid,connect
        result,mask,groups,gid,uid,connect=run([0,0,10001])
        mask.assert_called_once_with(0o077); groups.assert_called_once_with([]); gid.assert_called_once_with(10001); uid.assert_called_once_with(10001); connect.assert_called_once()
        self.assertEqual(result,{'ready':False,'code':'PREFLIGHT_FAILED'})
        result,_,_,_,_,connect=run([0,0],PermissionError('private'))
        connect.assert_not_called(); self.assertEqual(result,{'ready':False,'code':'PREFLIGHT_FAILED'})
        result,_,_,_,_,connect=run([1234])
        connect.assert_not_called(); self.assertEqual(result,{'ready':False,'code':'PREFLIGHT_FAILED'})

    def test_quiescence_wrapper_refuses_unavailable_or_active(self):
        zero = {'active_plans': 0, 'queued': 0, 'submitting': 0, 'running': 0, 'submission_unknown':0, **{f'{prefix}_{status}':0 for prefix in ('research','revision') for status in ('queued','submitting','running','submission_unknown')}}
        ready = {'exit_code': 0, 'exit_signal': 0, 'stdout': __import__('json').dumps({'ready': True, 'code': 'READY', 'counts': zero})}
        active = dict(zero, active_plans=1)
        bad = [None, {'exit_code': 0, 'stdout': 'private'}, {'exit_code': 0, 'stdout': __import__('json').dumps({'ready': True, 'code': 'READY', 'counts': active})}, {'exit_code': 1, 'stdout': __import__('json').dumps({'ready': False, 'code': 'PLANNING_IN_PROGRESS', 'counts': active})}]
        for response in bad:
            with self.subTest(response=response), patch.object(volume, 'verify', return_value=MACHINE['id']), patch.object(volume, 'request', return_value=response) as req:
                with self.assertRaises(volume.Stop) as error: volume.check_quiescence()
                self.assertNotIn('private', str(error.exception)); self.assertEqual(req.call_count, 1)
        with patch.object(volume, 'verify', return_value=MACHINE['id']), patch.object(volume, 'request', return_value=ready) as req:
            volume.check_quiescence()
            self.assertEqual(req.call_args.args[2]['command'], ['env','PYTHONPATH=/app','python','-c',volume.QUIESCENCE_PROBE])
        unknown = dict(zero, revision_submission_unknown=1)
        result = {'exit_code':1,'stdout':__import__('json').dumps({'ready':False,'code':'PLANNING_UNCERTAIN','counts':unknown})}
        with patch.object(volume,'verify',return_value=MACHINE['id']),patch.object(volume,'request',return_value=result):
            with self.assertRaisesRegex(volume.Stop,'uncertain outcome'):volume.check_quiescence()

    def test_grounded_actions_are_fixed_off_and_fail_closed(self):
        ok = {'exit_code':0,'exit_signal':0,'stdout':'{"ready":true,"code":"READY"}'}
        for check in (False,True):
            with self.subTest(check=check),patch.object(volume,'verify',return_value=MACHINE['id']) as verify,patch.object(volume,'request',return_value=ok) as req:
                volume.grounded_store_action(check_only=check)
                verify.assert_called_once_with(require_attached=True,require_disabled=True)
                command=req.call_args.args[2]['command']
                self.assertEqual(command[-3:],['--path','/data/checkpoints/planning.sqlite3','--check' if check else '--approve'])
                self.assertIn('ADAPTIVE_PLANNING_ENABLED=false',command)
                self.assertIn('ADAPTIVE_RESEARCH_ENABLED=false',command)
                self.assertIn('ADAPTIVE_STREAMING_ENABLED=false',command)
                self.assertEqual(req.call_count,1)
        for result in (None,{'exit_code':0,'stdout':'private'}, {'exit_code':1,'stdout':'{"ready":false,"code":"private"}'}, {'exit_code':0,'stdout':'{"ready":1,"code":"READY"}'}):
            with self.subTest(result=result),patch.object(volume,'verify',return_value=MACHINE['id']),patch.object(volume,'request',return_value=result) as req:
                with self.assertRaises(volume.Stop) as error:volume.grounded_store_action()
                self.assertNotIn('private',str(error.exception));self.assertEqual(req.call_count,1)
        for check in (False, True):
            result = {'exit_code':1, 'stderr':'private', 'stdout':'{"ready":false,"code":"SQLITE_PRIVILEGE_DROP_FAILED"}'}
            with self.subTest(check=check),patch.object(volume,'verify',return_value=MACHINE['id']),patch.object(volume,'request',return_value=result) as req:
                with self.assertRaises(volume.Stop) as error:volume.grounded_store_action(check_only=check)
                self.assertIn('SQLITE_PRIVILEGE_DROP_FAILED',str(error.exception))
                self.assertNotIn('private',str(error.exception));self.assertEqual(req.call_count,1)

    def test_workflow_mount_config_guard(self):
        root = path.parents[1]
        workflow = (root / '.github/workflows/fly-checkpoint-volume.yml').read_text()
        body = workflow.split("python3 - <<'PYCODE'\n", 1)[1].split('          PYCODE', 1)[0]
        code = compile(textwrap.dedent(body), '<workflow-config-guard>', 'exec')
        config = (root / 'fly.toml').read_bytes()
        def check(source):
            with patch('builtins.open', return_value=io.BytesIO(source)):
                exec(code, {})
        check(config)
        for bad in (config.replace(b'primary_region = "sin"', b'primary_region = "iad"'),
                    config.replace(b'scheduled_snapshots = false', b'scheduled_snapshots = true'),
                    config.replace(b'scheduled_snapshots = false', b'scheduled_snapshots = false\n  extend_threshold_percent = 80'),
                    config + b'\n[[mounts]]\nsource = "extra"\ndestination = "/extra"\n'):
            with self.subTest(bad=bad[-150:]), self.assertRaises(AssertionError): check(bad)

    def test_grounded_workflow_sequence_and_budget(self):
        workflow = (path.parents[1] / '.github/workflows/fly-deploy.yml').read_text()
        self.assertIn('options: [stage, upgrade, activate]', workflow)
        self.assertNotIn('--initialize-store', workflow)
        gate = workflow.index('run: python3 deployment/fly_checkpoint_volume.py --check-quiescence')
        upgrade = workflow.index('run: python3 deployment/fly_checkpoint_volume.py --upgrade-grounded-store')
        check = workflow.index('run: python3 deployment/fly_checkpoint_volume.py --check-grounded-store')
        deploy = workflow.index('name: Deploy one Machine with explicit processing state')
        self.assertLess(gate, upgrade); self.assertLess(upgrade, check); self.assertLess(check, deploy)
        self.assertIn("if: inputs.deployment_action == 'stage' || inputs.deployment_action == 'activate'", workflow)
        stage = workflow.split('stage)',1)[1].split(';;',1)[0]
        for key in ('ADAPTIVE_PLANNING_ENABLED','PLANNING_JOBS_ENABLED','ADAPTIVE_RESEARCH_ENABLED','ADAPTIVE_STREAMING_ENABLED'):
            self.assertIn('--env '+key+'=false', stage)
        self.assertIn('--env ADAPTIVE_RESEARCH_MAX_TOOLS=6', workflow)
        self.assertIn('--env ADAPTIVE_RESEARCH_ENABLED=true', workflow)
        self.assertIn('--env ADAPTIVE_STREAMING_ENABLED=true', workflow)

    def test_machine_guards(self):
        volume.validate_machine_list([MACHINE])
        for val in ([], [MACHINE, MACHINE], [None], [{'region': 'iad'}], [{'region':'sin','state':'started','config':{'guest':None}}]):
            with self.subTest(val=val), self.assertRaises(volume.Stop): volume.validate_machine_list(val)
        for key, value in [('memory_mb', 1024), ('cpu_kind', 'performance'), ('cpus', 2)]:
            m = copy.deepcopy(MACHINE); m['config']['guest'][key] = value
            with self.assertRaises(volume.Stop): volume.validate_machine_list([m])
        for env in (None, {'ADAPTIVE_PLANNING_ENABLED': 'true'}, {'PLANNING_JOBS_ENABLED': 'true'}, {'ADAPTIVE_RESEARCH_ENABLED':'true'}, {'ADAPTIVE_STREAMING_ENABLED':'true'}):
            m = copy.deepcopy(MACHINE); m['config']['env'] = env
            with self.assertRaises(volume.Stop): volume.validate_machine_list([m])

    def test_volume_guards(self):
        self.assertEqual(volume.validate_volume([VOLUME]), 'vol_123abc')
        for val in ([], [VOLUME, VOLUME], [None], None):
            with self.subTest(val=val), self.assertRaises(volume.Stop): volume.validate_volume(val)
        for key, val in [('name','other'),('region','iad'),('size_gb',2),('size_gb',True),('encrypted',False),('auto_backup_enabled',True),('auto_backup_enabled',None),('state','destroyed'),('attached_machine_id','machine'),('id','../../x')]:
            v = dict(VOLUME, **{key:val})
            with self.subTest(key=key, val=val), self.assertRaises(volume.Stop): volume.validate_volume([v])

    def test_one_shot_and_exact_body(self):
        with patch.object(volume, 'request', side_effect=[[MACHINE], [], {}, [VOLUME], []]) as req:
            volume.provision()
        self.assertEqual([x.args[0] for x in req.call_args_list], ['GET', 'GET', 'POST', 'GET', 'GET'])
        body = req.call_args_list[2].args[2]
        self.assertEqual(body['auto_backup_enabled'], False)
        self.assertEqual(body['size_gb'], 1)
        self.assertEqual(body['compute']['memory_mb'], 512)

    def test_preexisting_refused_before_post(self):
        with patch.object(volume, 'request', side_effect=[[MACHINE], [VOLUME]]) as req:
            with self.assertRaises(volume.Stop): volume.provision()
        self.assertEqual(req.call_count, 2)

    def test_uncertain_post_not_retried(self):
        with patch.object(volume, 'request', side_effect=[[MACHINE], [], volume.Stop('uncertain')]) as req:
            with self.assertRaises(volume.Stop): volume.provision()
        self.assertEqual(req.call_count, 3)

    def test_read_only_verification_attachment(self):
        mid = MACHINE['id']
        for attached, required, allowed in [(None, False, True), (mid, False, True), (mid, True, True), (None, True, False), ('different', False, False)]:
            v = dict(VOLUME, attached_machine_id=attached)
            with self.subTest(attached=attached, required=required):
                with patch.object(volume, 'request', side_effect=[[MACHINE], [v], []]) as req:
                    if allowed:
                        volume.verify(require_attached=required)
                    else:
                        with self.assertRaises(volume.Stop): volume.verify(require_attached=required)
                    self.assertTrue(all(call.args[0] == 'GET' for call in req.call_args_list))

    def test_fixed_store_commands(self):
        for initialize in (True, False):
            ok = {'exit_code': 0, 'exit_signal': 0, 'stdout': '{"code":"READY","ready":true}', 'stderr': ''}
            with self.subTest(initialize=initialize), patch.object(volume, 'verify', return_value=MACHINE['id']) as check, patch.object(volume, 'request', return_value=ok) as req:
                volume.run_store_preflight(initialize)
            check.assert_called_once_with(require_attached=True, require_disabled=initialize)
            self.assertEqual(req.call_count, 1)
            self.assertEqual(req.call_args.args[0:2], ('POST', '/machines/48edd43eb29178/exec'))
            expected = ['env', 'PYTHONPATH=/app', 'ADAPTIVE_PREFLIGHT_APPROVED=true']
            if initialize: expected.append('ADAPTIVE_SQLITE_INITIALIZE_APPROVED=true')
            expected += ['python', '-m', 'app.adaptive_sqlite_preflight']
            if initialize: expected.append('--initialize')
            self.assertEqual(req.call_args.args[2], {'command': expected, 'timeout': 25})

    def test_store_failure_hides_output_and_never_retries(self):
        responses = [None, {'exit_code': 1, 'stderr':'private'}, {'exit_code': 0, 'stdout':'private'},
                     {'exit_code': 0, 'stdout':'{"ready":1,"code":"READY"}'},
                     {'exit_code': 0, 'exit_signal': 9, 'stdout':'{"ready":true,"code":"READY"}'}]
        for response in responses:
            with self.subTest(response=response), patch.object(volume, 'verify', return_value=MACHINE['id']), patch.object(volume, 'request', return_value=response) as req:
                out = io.StringIO()
                with contextlib.redirect_stdout(out), self.assertRaises(volume.Stop) as error:
                    volume.run_store_preflight(True)
                self.assertNotIn('private', str(error.exception) + out.getvalue())
                self.assertEqual(req.call_count, 1)

    def test_only_allowlisted_failure_codes_are_reported(self):
        for code, visible in [('SQLITE_DIRECTORY_CREATE_DENIED', True), ('PRIVATE_SECRET_VALUE', False)]:
            response = {'exit_code': 1, 'stderr': 'sensitive', 'stdout': '{"ready":false,"code":"' + code + '"}'}
            with self.subTest(code=code), patch.object(volume, 'verify', return_value=MACHINE['id']), patch.object(volume, 'request', return_value=response):
                with self.assertRaises(volume.Stop) as error:
                    volume.run_store_preflight(True)
                self.assertEqual(code in str(error.exception), visible)
                self.assertNotIn('sensitive', str(error.exception))

    def test_snapshot_and_malformed_read_refused(self):
        for snapshots in ([{'id':'snap_1'}], None, {}):
            with self.subTest(snapshots=snapshots), patch.object(volume, 'request', side_effect=[[MACHINE], [], {}, [VOLUME], snapshots]):
                with self.assertRaises(volume.Stop): volume.provision()

    def test_redirect_is_not_followed_with_bearer(self):
        requests = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/sink')
                self.end_headers()
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(volume, 'BASE', f'http://127.0.0.1:{server.server_port}'), patch.dict('os.environ', {'FLY_API_TOKEN': 'synthetic-test-token'}):
                with self.assertRaises(volume.Stop): volume.request('GET', '/start')
            self.assertEqual(requests, ['/start'])
        finally:
            server.shutdown(); server.server_close(); thread.join()

class StartupWaitTests(unittest.TestCase):
    def test_wait_is_get_only_and_does_not_redeploy(self):
        states=[[dict(MACHINE,state=s)] for s in ('starting','replacing','started')]
        with patch.object(volume,'request',side_effect=states) as request, patch.object(volume.time,'sleep') as sleep, patch.object(volume,'verify',return_value=MACHINE['id']) as verify:
            volume.verify_after_deploy()
            self.assertEqual(request.call_count,3);self.assertEqual(sleep.call_count,2)
            self.assertTrue(all(call.args==('GET','/machines') for call in request.call_args_list))
            verify.assert_called_once_with(require_attached=True)
    def test_transition_wait_is_bounded(self):
        with patch.object(volume,'request',return_value=[dict(MACHINE,state='starting')]) as request, patch.object(volume.time,'sleep') as sleep:
            with self.assertRaises(volume.Stop):volume.verify_after_deploy()
            self.assertEqual(request.call_count,12);self.assertEqual(sleep.call_count,11)
    def test_terminal_or_wrong_resources_stop_immediately(self):
        for machine in (dict(MACHINE,state='stopped'),dict(MACHINE,state='destroyed'),dict(MACHINE,state='starting',region='iad')):
            with patch.object(volume,'request',return_value=[machine]) as request,patch.object(volume.time,'sleep') as sleep:
                with self.assertRaises(volume.Stop):volume.verify_after_deploy()
                self.assertEqual(request.call_count,1);sleep.assert_not_called()

if __name__ == '__main__': unittest.main()
