"""Install ZeroTier and join the configured private network as a systemd job."""
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def execute(root, job_id, network_id, mode, requested_source):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id) or not re.fullmatch(r'[a-f0-9]{16}', network_id) or mode not in ('connect', 'retry'):
        raise ValueError('Invalid ZeroTier setup arguments')
    if requested_source != 'auto':
        try:
            requested_source = str(ipaddress.IPv4Address(requested_source))
        except ipaddress.AddressValueError as exc:
            raise ValueError('Invalid ZeroTier source IP') from exc
    work = root / 'updates/zerotier-jobs' / job_id
    path = root / 'updates/zerotier-setup.json'

    def state(status, message):
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps({'id': job_id, 'status': status, 'message': message,
                                   'updated_at': time.time()}), encoding='utf-8')
        temp.replace(path)

    def pin_original_ip():
        if requested_source == 'auto':
            routes = json.loads(subprocess.check_output(['ip', '-j', 'route', 'get', '1.1.1.1'], text=True, timeout=10))
            route = routes[0]
            source, interface = route.get('src', ''), route.get('dev', '')
        else:
            devices = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show'], text=True, timeout=10))
            match = next(((device.get('ifname', ''), address.get('local', ''))
                          for device in devices for address in device.get('addr_info', [])
                          if address.get('local') == requested_source), None)
            if not match:
                raise RuntimeError('Selected source IP is no longer assigned to this VM')
            interface, source = match
        try:
            source = str(ipaddress.IPv4Address(source))
        except ipaddress.AddressValueError as exc:
            raise RuntimeError('Original physical IPv4 uplink is unavailable') from exc
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', interface):
            raise RuntimeError('Original physical IPv4 uplink is unavailable')
        excluded = ('ppp', 'zt', 'wg', 'tun', 'tap', 'tailscale', 'docker', 'br-', 'virbr', 'veth', 'cni', 'flannel', 'podman')
        if interface == 'lo' or interface.startswith(excluded):
            raise RuntimeError('Selected interface is a tunnel or virtual interface, not an uplink')
        folder = Path('/var/lib/zerotier-one')
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        local_conf = folder / 'local.conf'
        backup = folder / 'local.conf.aegis-original-ip.bak'
        config = json.loads(local_conf.read_text()) if local_conf.exists() else {}
        if not isinstance(config, dict) or not isinstance(config.get('settings', {}), dict):
            raise RuntimeError('ZeroTier local.conf has an unsupported format')
        if local_conf.exists() and not backup.exists():
            backup.write_bytes(local_conf.read_bytes())
            backup.chmod(0o600)
        settings = config.setdefault('settings', {})
        changed = settings.get('bind') != [source]
        settings['bind'] = [source]
        if changed:
            temporary = local_conf.with_suffix('.tmp')
            temporary.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
            temporary.chmod(0o600)
            temporary.replace(local_conf)
        return source, changed

    try:
        cli_path = shutil.which('zerotier-cli')
        if not cli_path:
            cli_path = next((p for p in ('/usr/sbin/zerotier-cli', '/usr/bin/zerotier-cli') if Path(p).exists()), None)
        if mode == 'retry' and not cli_path:
            raise RuntimeError('ZeroTier is not installed')
        if mode == 'connect' and not cli_path:
            state('running', 'Устанавливаем ZeroTier…')
            installer = work / 'install-zerotier.sh'
            with (work / 'setup.log').open('w') as output:
                subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location',
                    '--proto', '=https', '--retry', '3', '--connect-timeout', '15', '--max-time', '120',
                    'https://install.zerotier.com', '-o', str(installer)], stdout=output, stderr=output, check=True)
                # Keep the system package keyring readable by apt's unprivileged _apt user.
                previous_umask = os.umask(0o022)
                try:
                    keyring = Path('/usr/share/keyrings/zerotier-debian-package-key.gpg')
                    if keyring.exists():
                        keyring.chmod(0o644)
                    subprocess.run(['/bin/bash', str(installer)], stdout=output, stderr=output, check=True, timeout=600)
                finally:
                    os.umask(previous_umask)
            cli_path = shutil.which('zerotier-cli') or next(
                (p for p in ('/usr/sbin/zerotier-cli', '/usr/bin/zerotier-cli') if Path(p).exists()), None)
            if not cli_path:
                raise RuntimeError('ZeroTier installation completed but zerotier-cli was not found')
        source_ip, changed = pin_original_ip()
        state('running', 'Настраиваем исходный IP ' + source_ip + '…')
        subprocess.run(['systemctl', 'enable', '--now', 'zerotier-one'], check=True, timeout=30)
        if changed:
            subprocess.run(['systemctl', 'restart', 'zerotier-one'], check=True, timeout=30)
        message = 'ZeroTier закреплён за исходным IP ' + source_ip + '.'
        if mode in ('connect', 'retry'):
            if mode == 'retry':
                state('running', 'Повторно отправляем запрос через ' + source_ip + '…')
                subprocess.run([cli_path, 'leave', network_id], capture_output=True, text=True, check=True, timeout=30)
                time.sleep(1)
            result = subprocess.run([cli_path, 'join', network_id], capture_output=True, text=True, check=True, timeout=30)
            info = json.loads(subprocess.check_output([cli_path, '-j', 'info'], text=True, timeout=15))
            message += ' Запрос отправлен' + (' повторно' if mode == 'retry' else '') + '. Node ID: ' + info.get('address', 'не определён') + '. Проверьте его в ZeroTier Central.'
            if 'join OK' not in result.stdout and 'already joined' not in result.stdout.lower():
                message += ' Ответ: ' + (result.stdout.strip() or result.stderr.strip())
        state('complete', message)
    except Exception as exc:
        log_path = work / 'setup.log'
        with log_path.open('a', encoding='utf-8') as output:
            output.write(type(exc).__name__ + ': ' + str(exc) + '\n')
            for name in ('stdout', 'stderr', 'output'):
                detail = getattr(exc, name, None)
                if detail:
                    if isinstance(detail, bytes):
                        detail = detail.decode('utf-8', errors='replace')
                    output.write(name + ': ' + str(detail).strip() + '\n')
        state('failed', 'Не удалось подключиться. Подробности сохранены в журнале updates/zerotier-jobs/' + job_id + '/setup.log.')
        raise


if __name__ == '__main__':
    os.umask(0o077)
    execute(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
