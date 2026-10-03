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


def original_uplink():
    try:
        routes = json.loads(_run('ip', '-j', 'route', 'get', '1.1.1.1').stdout)
        route = routes[0]
        address = ipaddress.ip_address(route.get('src', ''))
        interface = route.get('dev', '')
        if address.version != 4 or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', interface):
            raise ValueError('No original IPv4 uplink found')
        if interface == 'lo' or interface.startswith(('ppp', 'zt', 'wg', 'tun', 'tap')):
            raise ValueError('Default route does not use the original physical uplink')
        return {'uplink_ip': str(address), 'uplink_interface': interface}
    except (OSError, ValueError, IndexError, KeyError, subprocess.SubprocessError, json.JSONDecodeError):
        return {'uplink_ip': '', 'uplink_interface': ''}
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
    return {**cfg, **original_uplink(), 'installed': bool(shutil.which('zerotier-cli')), 'service': service,
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
            raise ValueError('Эта ВМ уже подключена к ZeroTier')
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
        mode = 'retry' if current['network_status'] in ('ACCESS_DENIED', 'REQUESTING_CONFIGURATION') else 'connect'
        if mode == 'retry':
            state['message'] = 'Повторно отправляем запрос в ZeroTier…'
        return _launch_worker(work, job_id, cfg['network_id'], mode, state, temp, path)


def start_apply_original_ip():
    with _LOCK:
        cfg = config()
        if not cfg['network_id']:
            raise ValueError('Сначала сохраните Network ID')
        if not shutil.which('zerotier-cli'):
            raise ValueError('Сначала установите ZeroTier и подключите сеть')
        uplink = original_uplink()
        if not uplink['uplink_ip']:
            raise ValueError('Не удалось определить исходный физический IP этой ВМ')
        current = status()
        if unit_active() or (current.get('job') and current['job'].get('status') == 'running'):
            raise ValueError('Настройка ZeroTier уже выполняется')
        folder = ROOT / 'updates'
        job_id = uuid.uuid4().hex
        work = folder / 'zerotier-jobs' / job_id
        work.mkdir(mode=0o700, parents=True)
        shutil.copy2(APP / 'scripts/zerotier_worker.py', work / 'worker.py')
        state = {'id': job_id, 'status': 'running', 'message': 'Закрепляем ZeroTier за исходным IP…', 'updated_at': time.time()}
        path = folder / 'zerotier-setup.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(state), encoding='utf-8')
        temp.replace(path)
        return _launch_worker(work, job_id, cfg['network_id'], 'bind', state, temp, path)


def _launch_worker(work, job_id, network_id, mode, state, temp, path):
    try:
        subprocess.run(['systemd-run', '--quiet', '--collect', '--unit=' + UNIT,
            '--property=Type=exec', '--property=UMask=0077', '--property=RuntimeMaxSec=900',
            '/usr/bin/python3', str(work / 'worker.py'), str(ROOT), job_id, network_id, mode],
            capture_output=True, text=True, check=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        state.update(status='failed', message='Не удалось запустить настройку ZeroTier', updated_at=time.time())
        temp.write_text(json.dumps(state), encoding='utf-8')
        temp.replace(path)
        raise ValueError(state['message']) from exc
    return state
