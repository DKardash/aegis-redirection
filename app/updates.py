"""Authenticated update control; installation lives outside manager.service."""
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
ROOT = APP.parent
REPO = 'DKardash/aegis-redirection'
UNIT = 'aegis-panel-update'
_LOCK = threading.RLock()
_CACHE = {}


def version_tuple(value):
    if not re.fullmatch(r'v?\d{1,6}\.\d{1,6}\.\d{1,6}', value):
        raise ValueError('Неверный формат версии')
    return tuple(map(int, value.lstrip('v').split('.')))


def current_version():
    path = APP / 'VERSION'
    return path.read_text().strip() if path.exists() else '0.0.0'


def check_release():
    with _LOCK:
        if _CACHE and time.time() - _CACHE['checked_at'] < 60:
            return dict(_CACHE)
        request = urllib.request.Request(f'https://api.github.com/repos/{REPO}/releases/latest',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Aegis-Redirection'})
        with urllib.request.urlopen(request, timeout=12) as response:
            release = json.loads(response.read(1024 * 1024))
        tag = release.get('tag_name', '')
        latest = version_tuple(tag)
        if release.get('draft') or release.get('prerelease'):
            raise ValueError('Стабильный релиз не найден')
        assets = {a.get('name') for a in release.get('assets', [])}
        if not {'aegis-redirection.tar.gz', 'SHA256SUMS'} <= assets:
            raise ValueError('Релиз ещё не готов к установке')
        _CACHE.clear()
        _CACHE.update({'latest_version': tag.lstrip('v'), 'tag': tag,
            'available': latest > version_tuple(current_version()),
            'release_url': f'https://github.com/{REPO}/releases/tag/{tag}',
            'notes': (release.get('body') or '')[:12000], 'checked_at': time.time()})
        return dict(_CACHE)


def unit_active():
    try:
        result = subprocess.run(['systemctl', 'show', UNIT, '-p', 'ActiveState', '--value'],
                                capture_output=True, text=True, timeout=5)
        return result.stdout.strip() in ('active', 'activating', 'deactivating')
    except (OSError, subprocess.SubprocessError):
        return False


def read_job():
    try:
        job = json.loads((ROOT / 'updates/web-job.json').read_text())
    except (OSError, ValueError):
        return None
    if job.get('status') in ('starting', 'running') and time.time() - job.get('updated_at', 0) > 20 and not unit_active():
        job = {**job, 'status': 'failed', 'message': 'Процесс обновления прерван. Проверьте журнал обновления на ВМ.'}
    return job


def status():
    return {'current_version': current_version(), 'release': dict(_CACHE) or None, 'job': read_job()}


def start_update(tag):
    with _LOCK:
        release = check_release()
        if tag != release['tag'] or not release['available']:
            raise ValueError('Доступная версия изменилась или уже установлена. Повторите проверку.')
        job = read_job()
        if unit_active() or (job and job.get('status') in ('starting', 'running')):
            raise ValueError('Обновление уже выполняется')
        folder = ROOT / 'updates'
        folder.mkdir(mode=0o700, exist_ok=True)
        job_id = uuid.uuid4().hex
        work = folder / 'web-jobs' / job_id
        work.mkdir(mode=0o700, parents=True)
        # The worker must survive replacement of /manager and its Python venv.
        shutil.copy2(APP / 'scripts/web_update.py', work / 'worker.py')
        job = {'id': job_id, 'target': tag.lstrip('v'), 'status': 'starting',
               'message': 'Запуск обновления…', 'updated_at': time.time()}
        path = folder / 'web-job.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(job), encoding='utf-8')
        temporary.replace(path)
        try:
            subprocess.run(['systemd-run', '--quiet', '--collect', '--unit=' + UNIT,
                '--property=Type=exec', '--property=UMask=0077', '--property=RuntimeMaxSec=1800',
                '/usr/bin/python3', str(work / 'worker.py'), str(ROOT), job_id, tag],
                capture_output=True, text=True, check=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            job.update(status='failed', message='Не удалось запустить службу обновления', updated_at=time.time())
            temporary.write_text(json.dumps(job), encoding='utf-8')
            temporary.replace(path)
            raise ValueError(job['message']) from exc
        return job
