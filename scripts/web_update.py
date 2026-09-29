"""Standalone systemd worker. No imports from the application being replaced."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def execute(root, job_id, tag):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id) or not re.fullmatch(r'v\d{1,6}\.\d{1,6}\.\d{1,6}', tag):
        raise ValueError('Invalid update arguments')
    work = root / 'updates/web-jobs' / job_id
    path = root / 'updates/web-job.json'
    def state(status, message):
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps({'id': job_id, 'target': tag[1:], 'status': status,
                                   'message': message, 'updated_at': time.time()}), encoding='utf-8')
        temp.replace(path)
    try:
        state('running', 'Скачивание программы обновления…')
        with (work / 'update.log').open('w') as output:
            subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location',
                '--proto', '=https', '--retry', '3', '--connect-timeout', '15', '--max-time', '120',
                f'https://raw.githubusercontent.com/DKardash/aegis-redirection/{tag}/update.sh',
                '-o', str(work / 'update.sh')], stdout=output, stderr=output, check=True)
            state('running', 'Проверка релиза, резервная копия и установка. Панель может ненадолго перезапуститься.')
            subprocess.run(['/bin/bash', str(work / 'update.sh'), '--version', tag, '--root', str(root)],
                           stdout=output, stderr=output, check=True)
        state('complete', 'Обновление успешно завершено')
    except Exception:
        state('failed', 'Обновление не завершено. Подробности сохранены в журнале updates/web-jobs/' + job_id + '/update.log. При ошибке применения запускается откат.')
        raise


if __name__ == '__main__':
    os.umask(0o077)
    execute(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3])
