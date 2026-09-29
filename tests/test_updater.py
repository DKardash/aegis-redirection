import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import upgrade
from scripts import updater


class UpgradeTests(unittest.TestCase):
    def test_existing_profiles_preserved(self):
        profile = dict(id=4, server_id=9, local_ip='10.20.30.40', interface='ens18',
                       prefix=24, tproxy_port=12349, ppp_local_ip='10.200.5.1',
                       pool_start='10.200.5.100', pool_end='10.200.5.200', primary=True, enabled=True)
        with patch.object(upgrade.db, 'init_db'), patch.object(upgrade.db, 'get_setting', return_value=json.dumps([profile])), \
             patch.object(upgrade.crud, 'get_server', return_value={'id': 9}), \
             patch.object(upgrade.profiles, '_save') as save, \
             patch.object(upgrade.profiles, 'build_full_config', return_value={}), \
             patch.object(upgrade.xray, 'test_config', return_value=(True, '')):
            upgrade.migrate()
            save.assert_not_called()

    def test_legacy_active_server_migration(self):
        with patch.object(upgrade.db, 'init_db'), \
             patch.object(upgrade.db, 'get_setting', side_effect=['[]', '9']), \
             patch.object(upgrade.crud, 'get_server', return_value={'id': 9}), \
             patch.object(upgrade, 'legacy_profile', return_value={'id': 1}) as convert, \
             patch.object(upgrade.profiles, '_save') as save:
            # Incomplete synthetic profile must fail validation, rather than activate.
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                upgrade.migrate()
            convert.assert_called_once_with(9)
            save.assert_called_once()

    def test_legacy_profile_uses_actual_vm_addresses(self):
        status = {'users': [{'username': 'local-user'}],
                  'interface': {'listen_addr': '10.20.30.40', 'local_ip': '10.88.0.1'},
                  'pool': {'start': '10.88.0.10', 'end': '10.88.0.30'}}
        addresses = [{'ifname': 'ens18', 'addr_info': [{'local': '10.20.30.40', 'prefixlen': 27}]}]
        with patch.object(upgrade.l2tp, 'read_status', return_value=status), \
             patch.object(upgrade.subprocess, 'check_output', return_value=json.dumps(addresses)):
            p = upgrade.legacy_profile(9)
        self.assertEqual((p['local_ip'], p['prefix'], p['interface']), ('10.20.30.40', 27, 'ens18'))
        self.assertEqual(p['pool_start'], '10.88.0.10')
        self.assertEqual(p['server_id'], 9)

    def test_unknown_layout_refused_before_stop(self):
        with patch.object(updater, 'capture', side_effect=['/wrong/path', 'uvicorn app.main:app']), \
             patch.object(updater, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
                updater.installed_environment(Path('/opt/xray-gateway'))
            run.assert_not_called()


class RollbackTests(unittest.TestCase):
    def test_rollback_restores_code_database_and_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            txn = root / 'updates/test-transaction'
            backup = txn / 'backup'
            backup.mkdir(parents=True)
            for location, content in [(root / 'manager', 'new'), (backup / 'manager', 'old'),
                                      (root / 'venv', 'new-env'), (backup / 'venv', 'old-env')]:
                location.mkdir()
                (location / 'marker').write_text(content)
            database = root / 'gateway.db'
            with sqlite3.connect(database) as conn:
                conn.execute('CREATE TABLE settings(value TEXT)')
                conn.execute("INSERT INTO settings VALUES ('old-settings')")
            conn.close()
            updater.sqlite_backup(database, backup / 'gateway.db')
            with sqlite3.connect(database) as conn:
                conn.execute("UPDATE settings SET value='new-settings'")
            conn.close()
            config = root / 'network.conf'
            config.write_text('old-network')
            updater.copy_path(config, backup / 'network/0')
            config.write_text('new-network')
            (backup / 'mangle.rules').write_text('*mangle\nCOMMIT\n')
            updater.save_json(txn / 'state.json', {'root': str(root), 'database': str(database),
                'paths': [str(config)], 'port': 8790, 'phase': 'activating'})
            with patch.object(updater, 'run'), patch.object(updater, 'wait_ready'):
                updater.rollback(txn)
            self.assertEqual((root / 'manager/marker').read_text(), 'old')
            self.assertEqual((root / 'venv/marker').read_text(), 'old-env')
            self.assertEqual(config.read_text(), 'old-network')
            with sqlite3.connect(database) as conn:
                self.assertEqual(conn.execute('SELECT value FROM settings').fetchone()[0], 'old-settings')
            conn.close()
            self.assertTrue((txn / 'failed-database').exists())
            with self.assertRaisesRegex(RuntimeError, 'already'):
                updater.rollback(txn)


if __name__ == '__main__':
    unittest.main()
