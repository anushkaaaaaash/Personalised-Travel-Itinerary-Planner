"""Source guards for the disposable native SQL runner; never launches Docker."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NativeSQLRunner(unittest.TestCase):
    def test_shell_syntax_and_loopback_isolation(self):
        path = ROOT / 'backend-python/tests/sql/run_native_ci.sh'
        subprocess.run(['bash', '-n', str(path)], check=True)
        script = path.read_text()
        for required in ('set -euo pipefail', 'unset PGSERVICE PGSERVICEFILE', 'trap cleanup EXIT', '--network host',
                         '--tmpfs /var/lib/postgresql/data:', 'listen_addresses=127.0.0.1',
                         'host(inet_server_addr())', "('planning_queue_test', '127.0.0.1')",
                         "hostaddr='127.0.0.1'", 'connect_timeout=5',
                         'docker rm --force --volumes', 'test_adaptive_archive_migration_postgres.py'):
            self.assertIn(required, script)
        for prohibited in ('--publish', '--privileged', '/var/run/docker.sock', 'SUPABASE_'):
            self.assertNotIn(prohibited, script)

    def test_workflow_does_not_use_bridge_service(self):
        workflow = (ROOT / '.github/workflows/planning-sql.yml').read_text()
        self.assertNotIn('services:', workflow)
        self.assertIn('bash backend-python/tests/sql/run_native_ci.sh', workflow)
        self.assertIn('contents: read', workflow)

    def test_standalone_harness_pins_address_before_ddl(self):
        source = (ROOT / 'backend-python/tests/sql/planning_jobs_postgres.py').read_text()
        self.assertIn("'PGHOSTADDR': '127.0.0.1'", source)
        self.assertIn("{'PGSERVICE', 'PGSERVICEFILE'}", source)
        self.assertLess(source.index('host(inet_server_addr())'), source.index("sql('create role anon"))

    def test_cleanup_runs_on_success_and_test_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docker = root / 'docker'
            docker.write_text('#!/bin/sh\nprintf "docker %s\\n" "$*" >> "$COMMAND_LOG"\nexit 0\n')
            python = root / 'python'
            python.write_text('#!/bin/sh\nprintf "python %s\\n" "$*" >> "$COMMAND_LOG"\nexit "$MOCK_PYTHON_STATUS"\n')
            docker.chmod(0o700)
            python.chmod(0o700)
            for status in (0, 7):
                log = root / f'commands-{status}'
                env = {**os.environ, 'PATH': directory + os.pathsep + os.environ['PATH'],
                       'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                       'COMMAND_LOG': str(log), 'MOCK_PYTHON_STATUS': str(status)}
                result = subprocess.run(['bash', str(ROOT / 'backend-python/tests/sql/run_native_ci.sh')],
                                        env=env, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, status, result.stderr)
                commands = log.read_text().splitlines()
                self.assertTrue(commands[-1].startswith('docker rm --force --volumes roamora-sql-123-1'))
                self.assertEqual(sum(line.startswith('docker run ') for line in commands), 1)
                if status:
                    self.assertFalse(any('planning_jobs_postgres.py' in line for line in commands))
                else:
                    self.assertTrue(any('test_adaptive_archive_migration_postgres.py' in line for line in commands))


if __name__ == '__main__':
    unittest.main()
