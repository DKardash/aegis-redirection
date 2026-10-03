"""ZeroTier node controls for the local management network."""
import ipaddress
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .db import get_setting, set_setting

NETWORK_KEY = 'zerotier_network_id'
CIDR_KEY = 'zerotier_cidr'
APP = Path(__file__).resolve().parent.parent
ROOT = APP.parent
UNIT = 'aegis-zerotier-setup'
_LOCK = threading.RLock()


def config():
    return {'network_id': get_setting(NETWORK_KEY, '') or '',
            'cidr': get_setting(CIDR_KEY, '10.241.0.0/16') or '10.241.0.0/16'}


def save_config(network_id, cidr):
    network_id = network_id.strip().lower()
    if not re.fullmatch(r'[0-9a-f]{16}', network_id):
        raise ValueError('Network ID должен содержать 16 шестнадцатеричных символов')
    network = ipaddress.ip_network(cidr.strip(), strict=True)
    if network.version != 4 or network.prefixlen > 30:
        raise ValueError('Укажите IPv4-подсеть, например 10.241.0.0/16')
    set_setting(NETWORK_KEY, network_id)
    set_setting(CIDR_KEY, str(network))
    return config()


def _run(*args, timeout=5):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def unit_active():
    try:
        result = _run('systemctl', 'show', UNIT, '-p', 'ActiveState', '--value')
        return result.stdout.strip() in ('active', 'activating', 'deactivating')
    except (OSError, subprocess.SubprocessError):
        return False


def _job():
    try:
        value = json.loads((ROOT / 'updates/zerotier-setup.json').read_text())
    except (OSError, ValueError):
        return None
    if value.get('status') == 'running' and time.time() - value.get('updated_at', 0) > 30 and not unit_active():
        value.update(status='failed', message='Подключение прервано. Повторите попытку.')
    return value


def _network_data(network_id):
    if not network_id or not shutil.which('zerotier-cli'):
        return {}
    try:
        info = json.loads(_run('zerotier-cli', '-j', 'info').stdout)
        networks = json.loads(_run('zerotier-cli', '-j', 'listnetworks').stdout)
        return {'node_id': info.get('address', ''), 'node_status': info.get('online', False),
                'network': next((n for n in networks if n.get('nwid') == network_id), {})}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def status():
    cfg = config()
    service = 'inactive'
    if shutil.which('zerotier-cli'):
        try:
            service = _run('systemctl', 'is-active', 'zerotier-one').stdout.strip() or 'inactive'
        except (OSError, subprocess.SubprocessError):
            service = 'unknown'
    data = _network_data(cfg['network_id'])
    network = data.get('network') or {}
    state = network.get('status', 'NOT_JOINED' if not network else 'UNKNOWN')
    return {**cfg, 'installed': bool(shutil.which('zerotier-cli')), 'service': service,
            'node_id': data.get('node_id', ''), 'network_status': state,
            'device': network.get('portDeviceName', ''),
            'assigned_ips': network.get('assignedAddresses', []), 'job': _job()}


def start_connect():
    with _LOCK:
        cfg = config()
        if not cfg['network_id']:
            raise ValueError('Сначала сохраните Network ID')
        current = status()
        if current['network_status'] == 'OK':
            raise ValueError('Эта ВМ уже подключена к сети')
        job = current.get('job')
        if unit_active() or (job and job.get('status') == 'running'):
            raise ValueError('Подключение уже выполняется')
        folder = ROOT / 'updates'
        job_id = uuid.uuid4().hex
        work = folder / 'zerotier-jobs' / job_id
        work.mkdir(mode=0o700, parents=True)
        shutil.copy2(APP / 'scripts/zerotier_worker.py', work / 'worker.py')
        state = {'id': job_id, 'status': 'running', 'message': 'Подключаем ZeroTier…', 'updated_at': time.time()}
        path = folder / 'zerotier-setup.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(state), encoding='utf-8')
        temp.replace(path)
        try:
            subprocess.run(['systemd-run', '--quiet', '--collect', '--unit=' + UNIT,
                '--property=Type=exec', '--property=UMask=0077', '--property=RuntimeMaxSec=900',
                '/usr/bin/python3', str(work / 'worker.py'), str(ROOT), job_id, cfg['network_id']],
                capture_output=True, text=True, check=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            state.update(status='failed', message='Не удалось запустить подключение', updated_at=time.time())
            temp.write_text(json.dumps(state), encoding='utf-8')
            temp.replace(path)
            raise ValueError(state['message']) from exc
        return state
