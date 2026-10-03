"""Install ZeroTier and join the configured private network as a systemd job."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def execute(root, job_id, network_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id) or not re.fullmatch(r'[a-f0-9]{16}', network_id):
        raise ValueError('Invalid ZeroTier setup arguments')
    work = root / 'updates/zerotier-jobs' / job_id
    path = root / 'updates/zerotier-setup.json'

    def state(status, message):
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps({'id': job_id, 'status': status, 'message': message,
                                   'updated_at': time.time()}), encoding='utf-8')
        temp.replace(path)

    try:
        if not Path('/usr/sbin/zerotier-cli').exists() and not Path('/usr/bin/zerotier-cli').exists():
            state('running', 'Устанавливаем ZeroTier…')
            installer = work / 'install-zerotier.sh'
            with (work / 'setup.log').open('w') as output:
                subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location',
                    '--proto', '=https', '--retry', '3', '--connect-timeout', '15', '--max-time', '120',
                    'https://install.zerotier.com', '-o', str(installer)], stdout=output, stderr=output, check=True)
                subprocess.run(['/bin/bash', str(installer)], stdout=output, stderr=output, check=True, timeout=600)
        state('running', 'Запускаем службу и подключаем сеть…')
        subprocess.run(['systemctl', 'enable', '--now', 'zerotier-one'], check=True, timeout=30)
        result = subprocess.run(['zerotier-cli', 'join', network_id], capture_output=True, text=True, check=True, timeout=30)
        message = 'Запрос отправлен. Подтвердите новое устройство в ZeroTier Central.'
        if 'join OK' not in result.stdout and 'already joined' not in result.stdout.lower():
            message = result.stdout.strip() or message
        state('complete', message)
    except Exception:
        state('failed', 'Не удалось подключиться. Подробности сохранены в журнале updates/zerotier-jobs/' + job_id + '/setup.log.')
        raise


if __name__ == '__main__':
    os.umask(0o077)
    execute(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3])
