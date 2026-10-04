"""Short-lived per-server probes; never use or restart the live gateway."""
import json
import shlex
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from .config import settings
from .crud import set_health
from . import xray

_SLOTS = threading.BoundedSemaphore(3)
_START_LOCK = threading.Lock()


def _http_probe_succeeded(returncode: int, status_code: str) -> bool:
    """A complete HTTP response proves proxy egress even if the target rejects us."""
    try:
        status = int(status_code)
    except (TypeError, ValueError):
        return False
    return returncode == 0 and 100 <= status <= 599


def tcp_check(server: Dict) -> Tuple[bool, Optional[float], str]:
    try:
        start = time.monotonic()
        with socket.create_connection((server["address"], int(server["port"])), timeout=settings.healthcheck_timeout):
            return True, round((time.monotonic() - start) * 1000, 1), ""
    except OSError as exc:
        return False, None, f"TCP: {exc}"


def _probe(server: Dict) -> Tuple[bool, Optional[float], str]:
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="xray-probe-") as folder:
            with _START_LOCK:
                with socket.socket() as reserved:
                    reserved.bind(("127.0.0.1", 0))
                    port = reserved.getsockname()[1]
                config = xray.build_config(server)
                config["log"] = {"loglevel": "none"}
                config["inbounds"] = [{
                    "tag": "probe", "listen": "127.0.0.1", "port": port,
                    "protocol": "socks", "settings": {"auth": "noauth", "udp": False},
                }]
                path = Path(folder) / "config.json"
                path.write_text(json.dumps(config), encoding="utf-8")
                binary = shlex.split(settings.xray_test_cmd or "xray")[0]
                process = subprocess.Popen(
                    [binary, "run", "-config", str(path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                deadline = time.monotonic() + 5
                while True:
                    if process.poll() is not None:
                        return False, None, "Тестовый Xray не запустился; проверьте конфигурацию"
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=.15):
                            break
                    except OSError:
                        if time.monotonic() >= deadline:
                            return False, None, "Тестовый прокси не открыл порт за 5 секунд"
                        time.sleep(.05)
            timeout = max(5, min(float(settings.healthcheck_timeout), 20))
            targets = ["https://www.gstatic.com/generate_204", "https://www.cloudflare.com/cdn-cgi/trace"]
            errors = []
            for attempt, target in enumerate(targets):
                result = subprocess.run([
                    "curl", "-4", "-sS", "--noproxy", "", "--proxy", f"socks5h://127.0.0.1:{port}",
                    "--connect-timeout", str(timeout), "--max-time", str(timeout),
                    "-o", "/dev/null", "-w", "%{http_code} %{time_total}", target,
                ], capture_output=True, text=True, timeout=timeout + 2)
                parts = result.stdout.strip().split()
                if len(parts) == 2 and _http_probe_succeeded(result.returncode, parts[0]):
                    return True, round(float(parts[1]) * 1000, 1), ""
                errors.append((result.stderr or f"HTTP {parts[0] if parts else '?'}").strip()[-180:])
                if attempt == 0:
                    time.sleep(.4)
            return False, None, "Не прошли 2 попытки через этот сервер: " + "; ".join(errors)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return False, None, str(exc)[:400]
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def check_server(server: Dict, persist: bool = True) -> Tuple[bool, Optional[float], str]:
    with _SLOTS:
        result = _probe(server)
    if persist:
        set_health(server["id"], *result)
    return result
