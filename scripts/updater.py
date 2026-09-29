#!/usr/bin/env python3
"""Transactional updater for existing /opt/xray-gateway installations (Linux)."""
import argparse
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

RELEASE = Path(__file__).resolve().parent.parent
NETWORK_PATHS = ['/etc/ppp', '/etc/xl2tpd', '/etc/xray', '/etc/ipsec.conf',
                 '/usr/local/bin/xray-profile-apply.sh',
                 '/etc/systemd/system/xray-l2tp-profile@.service']


def run(*args, **kw):
    return subprocess.run([str(a) for a in args], check=True, text=True, **kw)


def capture(*args):
    return run(*args, stdout=subprocess.PIPE).stdout.strip()


def save_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(temp, path)


def sqlite_backup(source, target):
    with closing(sqlite3.connect(f'file:{source}?mode=ro', uri=True)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def copy_path(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target, follow_symlinks=False)


def installed_environment(root):
    cwd = capture('systemctl', 'show', 'manager', '-p', 'WorkingDirectory', '--value')
    command = capture('systemctl', 'show', 'manager', '-p', 'ExecStart', '--value')
    if Path(cwd).resolve() != root / 'manager' or str(root / 'venv/bin/uvicorn') not in command or 'app.main:app' not in command:
        raise RuntimeError('Unsupported manager.service layout; no services were changed')
    pid = int(capture('systemctl', 'show', 'manager', '-p', 'MainPID', '--value'))
    if pid <= 0:
        raise RuntimeError('manager.service must be running before update')
    env = dict(os.environ)
    for part in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):
        if b'=' in part:
            k, v = part.decode().split('=', 1)
            env[k] = v
    env['DATABASE_PATH'] = env.get('DATABASE_PATH', str(root / 'data/gateway.db'))
    env['XRAY_CONFIG_PATH'] = env.get('XRAY_CONFIG_PATH', '/etc/xray/config.json')
    for key in ('DATABASE_PATH', 'XRAY_CONFIG_PATH'):
        if not Path(env[key]).is_absolute() or not Path(env[key]).is_file():
            raise RuntimeError(f'{key} must refer to an existing absolute file')
    port = re.search(r'--port(?:=|\s+)(\d+)', command)
    return env, int(port.group(1)) if port else 8000


def wait_ready(port, version=None, timeout=45):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            path = '/api/healthz' if version else '/'
            with opener.open(f'http://127.0.0.1:{port}{path}', timeout=3) as response:
                if not version:
                    return
                data = json.load(response)
                if data.get('version') == version and data.get('ok') is True:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('Panel readiness check failed')


def stage(root, env):
    version = (RELEASE / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise RuntimeError('Invalid release version')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    transaction = Path(tempfile.mkdtemp(prefix=f'{stamp}-', dir=root / 'updates'))
    runtime = root / 'runtimes' / transaction.name
    runtime.parent.mkdir(exist_ok=True, mode=0o700)
    print(f'Preparing v{version}; transaction {transaction.name}', flush=True)
    run(sys.executable, '-m', 'venv', runtime)
    python = runtime / 'bin/python'
    run(python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', RELEASE / 'requirements.txt', timeout=600)
    candidate = transaction / 'candidate'
    candidate.mkdir(mode=0o755)
    for name in ('app', 'web', 'scripts', 'VERSION', 'requirements.txt', 'update.sh'):
        copy_path(RELEASE / name, candidate / name)
    # User-owned lists and their backups are data, not release assets.
    old_static = root / 'manager/web/static'
    for source in old_static.glob('mikrotik-vpn-lists.rsc*'):
        if source.is_file() and not source.is_symlink():
            shutil.copy2(source, candidate / 'web/static' / source.name)
    lists = candidate / 'web/static/mikrotik-vpn-lists.rsc'
    if not lists.exists():
        lists.write_text('# Address lists are configured on this VM.\n')
    if (root / 'manager/.env').is_file():
        shutil.copy2(root / 'manager/.env', candidate / '.env')
    # Explicit paths avoid BASE_DIR changes while checking a staged release.
    probe_env = {**env, 'DATABASE_PATH': str(transaction / 'probe.db'),
                 'BACKUPS_DIR': str(transaction / 'probe-backups'),
                 'GENERATED_DIR': str(transaction / 'probe-generated'),
                 'LOG_PATH': str(transaction / 'probe.log')}
    sqlite_backup(Path(env['DATABASE_PATH']), transaction / 'probe.db')
    run(python, '-m', 'app.upgrade', cwd=candidate, env=probe_env, timeout=120)
    run(python, '-c', 'from app.main import app; print("Application import OK")', cwd=candidate, env=probe_env, timeout=30)
    return transaction, runtime, version


def snapshot(transaction, root, env, port, version):
    backup = transaction / 'backup'
    backup.mkdir(mode=0o700)
    database = Path(env['DATABASE_PATH'])
    sqlite_backup(database, backup / 'gateway.db')
    paths = list(dict.fromkeys(NETWORK_PATHS + [env['XRAY_CONFIG_PATH']]))
    for index, name in enumerate(paths):
        source = Path(name)
        if source.exists() or source.is_symlink():
            copy_path(source, backup / 'network' / str(index))
    with (backup / 'mangle.rules').open('w') as output:
        run('iptables-save', '-t', 'mangle', stdout=output)
    previous = root / 'updates/last-successful'
    state = {'root': str(root), 'database': str(database), 'paths': paths,
             'previous_success': previous.read_text().strip() if previous.exists() else '',
             'port': port, 'version': version, 'phase': 'backed-up'}
    save_json(transaction / 'state.json', state)
    return state


def rollback(transaction):
    state = json.loads((transaction / 'state.json').read_text())
    root = Path(state['root'])
    if transaction.parent.resolve() != (root / 'updates').resolve():
        raise RuntimeError('Transaction is outside this installation')
    backup = transaction / 'backup'
    if state['phase'] == 'rolled-back':
        raise RuntimeError('This transaction has already been rolled back')
    marker = root / 'updates/last-successful'
    if state['phase'] == 'complete' and (not marker.exists() or marker.read_text().strip() != transaction.name):
        raise RuntimeError('Only the most recent successful update can be rolled back')
    run('systemctl', 'stop', 'manager')
    # Preserve the failed version too; recovery never recursively deletes it.
    for name in ('manager', 'venv'):
        saved = backup / name
        current = root / name
        if saved.exists() or saved.is_symlink():
            if current.exists() or current.is_symlink():
                current.rename(transaction / ('failed-' + name))
            saved.rename(current)
    database = Path(state['database'])
    for suffix in ('', '-wal', '-shm'):
        current = Path(str(database) + suffix)
        if current.exists():
            current.rename(transaction / ('failed-database' + suffix))
    shutil.copy2(backup / 'gateway.db', database)
    for index, name in enumerate(state['paths']):
        current, saved = Path(name), backup / 'network' / str(index)
        if current.exists() or current.is_symlink():
            dest = transaction / 'failed-network' / str(index)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(dest))
        if saved.exists() or saved.is_symlink():
            copy_path(saved, current)
    run('systemctl', 'daemon-reload')
    with (backup / 'mangle.rules').open() as rules:
        run('iptables-restore', stdin=rules)
    run('systemctl', 'restart', 'strongswan-starter', 'xray', 'xl2tpd', 'manager')
    wait_ready(state['port'])
    state['phase'] = 'rolled-back'
    save_json(transaction / 'state.json', state)
    marker.write_text(state.get('previous_success', '') + '\n')
    print('Rollback complete. Previous code, environment, database and routing restored.', flush=True)


def update(root, check_only=False):
    env, port = installed_environment(root)
    transaction, runtime, version = stage(root, env)
    if check_only:
        print(f'CHECK OK: v{version}; services untouched. Staging retained at {transaction}')
        return
    stopped = False
    try:
        run('systemctl', 'stop', 'manager')
        stopped = True
        state = snapshot(transaction, root, env, port, version)
        print(f'Backup ready: {transaction / "backup"}', flush=True)
        (root / 'manager').rename(transaction / 'backup/manager')
        (transaction / 'candidate').rename(root / 'manager')
        (root / 'venv').rename(transaction / 'backup/venv')
        (root / 'venv').symlink_to(runtime, target_is_directory=True)
        state['phase'] = 'activating'
        save_json(transaction / 'state.json', state)
        run(runtime / 'bin/python', '-m', 'app.upgrade', cwd=root / 'manager', env=env, timeout=120)
        run('systemctl', 'start', 'manager')
        wait_ready(port, version)
        run('systemctl', 'is-active', '--quiet', 'manager', 'xray', 'xl2tpd')
        state['phase'] = 'complete'
        save_json(transaction / 'state.json', state)
        (root / 'updates/last-successful').write_text(transaction.name + '\n')
        print(f'UPDATE OK: v{version}. Rollback: sudo python3 {root}/manager/scripts/updater.py --rollback {transaction.name}')
    except BaseException:
        if (transaction / 'state.json').exists():
            print('Update failed; restoring previous version.', flush=True)
            rollback(transaction)
        elif stopped:
            run('systemctl', 'start', 'manager')
        raise


def main():
    parser = argparse.ArgumentParser(description='Aegis Redirection updater; existing Ubuntu/systemd gateway only')
    parser.add_argument('--check', action='store_true', help='Stage and validate without stopping services')
    parser.add_argument('--root', default='/opt/xray-gateway')
    parser.add_argument('--rollback', metavar='TRANSACTION')
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() != 0:
        parser.error('Linux root privileges required')
    import fcntl
    root = Path(args.root).resolve()
    if root == Path('/') or not (root / 'manager/app').is_dir() or not (root / 'venv/bin/python').exists():
        parser.error('An existing gateway installation is required; nothing was changed')
    updates = root / 'updates'
    updates.mkdir(mode=0o700, exist_ok=True)
    with (updates / 'lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another update is already running')
        def interrupted(signum, frame):
            raise KeyboardInterrupt('Update interrupted')
        signal.signal(signal.SIGTERM, interrupted)
        if args.rollback:
            if not re.fullmatch(r'[A-Za-z0-9_-]+', args.rollback):
                parser.error('Invalid transaction name')
            rollback(updates / args.rollback)
        else:
            update(root, args.check)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
