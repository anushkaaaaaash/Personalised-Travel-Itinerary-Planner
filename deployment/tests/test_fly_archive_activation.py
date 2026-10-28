import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('archive_activation', ROOT / 'deployment/fly_archive_activation.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ArchiveActivation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sql = Path(self.temp.name) / 'review.sql'
        self.sql.write_text('-- Synthetic reviewed proposal\n')
        self.sha = hashlib.sha256(self.sql.read_bytes()).hexdigest()

    def check(self, action='activate', confirmed='true', sha=None):
        return gate.verify(action, confirmed, self.sha if sha is None else sha, sql_path=self.sql)

    def test_stage_and_upgrade_need_no_archive_attestation(self):
        for action in ('stage', 'upgrade'):
            self.check(action, '', '')

    def test_activation_requires_exact_confirmation(self):
        for confirmed in ('', 'false', 'True', '1', True, None):
            with self.subTest(confirmed=confirmed), self.assertRaises(ValueError):
                self.check(confirmed=confirmed)

    def test_missing_malformed_or_wrong_sql_identity_blocks(self):
        for sha in ('', '0' * 64, self.sha.upper(), self.sha + '\n', 'private fixture'):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                self.check(sha=sha)

    def test_exact_sql_and_confirmation_pass(self):
        self.check()

    def test_changed_or_missing_proposal_blocks(self):
        self.sql.write_text('-- Changed after review\n')
        with self.assertRaises(ValueError):
            self.check()
        self.sql.unlink()
        with self.assertRaises(ValueError):
            self.check()

    def test_unknown_action_fails_closed(self):
        for action in ('', 'ACTIVATE', 'destroy', None):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.check(action=action)

    def test_failure_does_not_echo_supplied_input(self):
        with patch.dict(os.environ, {'DEPLOYMENT_ACTION': 'activate', 'SAVED_ARCHIVE_SCHEMA_VERIFIED': 'true',
                                    'VERIFIED_SAVED_ARCHIVE_SQL_SHA256': 'private fixture'}, clear=True), patch('builtins.print') as output:
            self.assertEqual(gate.main(), 1)
            self.assertNotIn('private fixture', str(output.call_args_list))

    def test_workflow_stage_and_activation_flags_and_order(self):
        workflow = (ROOT / '.github/workflows/fly-deploy.yml').read_text()
        stage = workflow.split('            stage)')[1].split('            activate)')[0]
        activate = workflow.split('            activate)')[1].split("            *)")[0]
        for name in ('ADAPTIVE_SAVED_TRIPS_ENABLED', 'ADAPTIVE_SAVED_TRIPS_SCHEMA_VERIFIED'):
            self.assertIn(f'--env {name}=false', stage)
            self.assertNotIn(f'{name}=true', stage)
            self.assertIn(f'--env {name}=true', activate)
        self.assertLess(workflow.index('deployment/fly_archive_activation.py'), workflow.index('Install Fly CLI'))
        self.assertIn("default: false\n        type: boolean", workflow)
        self.assertIn('inputs.saved_archive_schema_verified', workflow)
        self.assertIn('inputs.verified_saved_archive_sql_sha256', workflow)
        for preserved in ('--ha=false --strategy immediate', '--check-quiescence', '--check-grounded-store',
                          '--verify-after-deploy', 'deployment/fly_checkpoint_flags.py', "github.ref == 'refs/heads/main'"):
            self.assertIn(preserved, workflow)

    def test_checked_in_defaults_remain_off(self):
        with (ROOT / 'fly.toml').open('rb') as source:
            env = tomllib.load(source)['env']
        self.assertEqual(env['ADAPTIVE_SAVED_TRIPS_ENABLED'], 'false')
        self.assertEqual(env['ADAPTIVE_SAVED_TRIPS_SCHEMA_VERIFIED'], 'false')


if __name__ == '__main__':
    unittest.main()
