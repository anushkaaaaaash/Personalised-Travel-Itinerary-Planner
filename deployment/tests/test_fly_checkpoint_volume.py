import copy
import contextlib
import importlib.util
import http.server
import io
import textwrap
import pathlib
import threading
import unittest
from unittest.mock import patch

path = pathlib.Path(__file__).resolve().parents[1] / 'fly_checkpoint_volume.py'
spec = importlib.util.spec_from_file_location('volume', path)
volume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(volume)

MACHINE = {'id': '48edd43eb29178', 'region': 'sin', 'state': 'started', 'config': {'guest': {'cpu_kind': 'shared', 'cpus': 1, 'memory_mb': 512}}}
VOLUME = {'id': 'vol_123abc', 'name': 'planner_checkpoints', 'region': 'sin', 'size_gb': 1, 'encrypted': True, 'auto_backup_enabled': False, 'state': 'created', 'attached_machine_id': None}


class VolumeTests(unittest.TestCase):
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

    def test_machine_guards(self):
        volume.validate_machine_list([MACHINE])
        for val in ([], [MACHINE, MACHINE], [None], [{'region': 'iad'}], [{'region':'sin','state':'started','config':{'guest':None}}]):
            with self.subTest(val=val), self.assertRaises(volume.Stop): volume.validate_machine_list(val)
        for key, value in [('memory_mb', 1024), ('cpu_kind', 'performance'), ('cpus', 2)]:
            m = copy.deepcopy(MACHINE); m['config']['guest'][key] = value
            with self.assertRaises(volume.Stop): volume.validate_machine_list([m])
        for env in (None, {'ADAPTIVE_PLANNING_ENABLED': 'true'}, {'PLANNING_JOBS_ENABLED': 'true'}):
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

if __name__ == '__main__': unittest.main()
