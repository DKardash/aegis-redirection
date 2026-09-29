import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from fastapi import HTTPException
from app import updates
from app.routers import updates as routes
from scripts import web_update


class UpdateTests(unittest.TestCase):
    def tearDown(self):
        updates._CACHE.clear()

    def test_versions_compare_numerically(self):
        self.assertGreater(updates.version_tuple('v3.10.0'), updates.version_tuple('3.9.9'))
        for value in ('v3.0.0;id', '../main', 'v3.0.0-rc1', 'http://example.com'):
            with self.assertRaises(ValueError):
                updates.version_tuple(value)

    def test_release_requires_complete_assets(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        release = {'tag_name': 'v3.1.0', 'assets': [{'name': 'aegis-redirection.tar.gz'}, {'name': 'SHA256SUMS'}]}
        response.read.return_value = json.dumps(release).encode()
        with patch.object(updates.urllib.request, 'urlopen', return_value=response), patch.object(updates, 'current_version', return_value='3.0.0'):
            self.assertTrue(updates.check_release()['available'])
            updates._CACHE.clear()
            release['assets'] = []
            response.read.return_value = json.dumps(release).encode()
            with self.assertRaises(ValueError):
                updates.check_release()

    def test_same_version_never_starts_install(self):
        with patch.object(updates, 'check_release', return_value={'tag': 'v3.0.0', 'available': False}), patch.object(updates.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                updates.start_update('v3.0.0')
            run.assert_not_called()

    def test_duplicate_job_never_starts_install(self):
        with patch.object(updates, 'check_release', return_value={'tag': 'v3.1.0', 'available': True}), \
             patch.object(updates, 'read_job', return_value={'status': 'running'}), \
             patch.object(updates, 'unit_active', return_value=True), patch.object(updates.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                updates.start_update('v3.1.0')
            run.assert_not_called()

    def test_password_required_even_if_legacy_auth_disabled(self):
        with patch.object(routes.settings, 'admin_password', ''), patch.object(routes, 'get_setting', return_value=''):
            with self.assertRaises(HTTPException) as error:
                routes.authorized(Mock())
            self.assertEqual(error.exception.status_code, 403)

    def test_authenticated_routes_reject_missing_token(self):
        with patch.object(routes.settings, 'admin_password', 'test-only-password'):
            with self.assertRaises(HTTPException) as error:
                routes.authorized(Mock(headers={}))
            self.assertEqual(error.exception.status_code, 401)

    def test_worker_survives_independently_and_persists_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            job_id = 'a' * 32
            (root / 'updates/web-jobs' / job_id).mkdir(parents=True)
            with patch.object(web_update.subprocess, 'run') as run:
                web_update.execute(root, job_id, 'v3.1.0')
                self.assertIn('--version', run.call_args.args[0])
            job = json.loads((root / 'updates/web-job.json').read_text())
            self.assertEqual(job['status'], 'complete')
            with patch.object(web_update.subprocess, 'run', side_effect=OSError('offline')):
                with self.assertRaises(OSError):
                    web_update.execute(root, job_id, 'v3.1.0')
            self.assertEqual(json.loads((root / 'updates/web-job.json').read_text())['status'], 'failed')

    def test_systemd_worker_is_copied_outside_manager(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = root / 'manager'
            (app / 'scripts').mkdir(parents=True)
            (app / 'scripts/web_update.py').write_text('# worker')
            with patch.object(updates, 'ROOT', root), patch.object(updates, 'APP', app), \
                 patch.object(updates, 'check_release', return_value={'tag': 'v3.1.0', 'available': True}), \
                 patch.object(updates, 'unit_active', return_value=False), patch.object(updates.subprocess, 'run') as run:
                job = updates.start_update('v3.1.0')
                command = run.call_args.args[0]
                self.assertEqual(command[0], 'systemd-run')
                self.assertIn('/usr/bin/python3', command)
                self.assertTrue((root / 'updates/web-jobs' / job['id'] / 'worker.py').exists())


if __name__ == '__main__':
    unittest.main()
