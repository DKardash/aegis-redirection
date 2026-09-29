import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple

from . import l2tp
from .config import settings
from .db import add_traffic_sample, get_setting, get_traffic_samples, purge_traffic_samples, set_setting

EXPECTED_IP_KEY = "expected_public_ip"


def _run(cmd, timeout=8):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, (res.stdout or res.stderr).strip()
    except FileNotFoundError:
        return 1, ""
    except subprocess.TimeoutExpired:
        return 1, ""


def _is_active(unit: str) -> bool:
    code, out = _run(["systemctl", "is-active", unit])
    return code == 0 and out == "active"


def _first(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return ""


def read_system() -> dict:
    cpu = _loadavg()
    mem = _meminfo()
    disk = _disk()
    return {
        "cpu": cpu,
        "memory": mem,
        "disk": disk,
        "uptime": _uptime(),
        "hostname": _first(Path("/proc/sys/kernel/hostname")) or "",
        "kernel": (_first(Path("/proc/version")) or "").split(" ", 3)[:3],
        "loadavg": _first(Path("/proc/loadavg")) or "",
    }


def _loadavg() -> float:
    code, out = _run(["sh", "-c", "nproc && grep -c ^processor /proc/cpuinfo"])
    cores = 0
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit() and int(line) > 0:
            cores = int(line)
            break
    load = _first(Path("/proc/loadavg")).split()
    if not load:
        return 0.0
    try:
        one = float(load[0])
    except ValueError:
        return 0.0
    return round(one / cores * 100, 1) if cores else 0.0


def _meminfo() -> dict:
    total = used = 0
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) * 1024
                used = total - avail
    except OSError:
        pass
    return {"total": total, "used": used}


def _disk() -> dict:
    code, out = _run(["df", "-k", "--output=size,used,avail", "/"])
    if code != 0:
        return {"total": 0, "used": 0, "free": 0}
    lines = out.splitlines()
    if len(lines) < 2:
        return {"total": 0, "used": 0, "free": 0}
    size, used, free = lines[1].split()
    return {
        "total": int(size) * 1024,
        "used": int(used) * 1024,
        "free": int(free) * 1024,
    }


def _uptime() -> float:
    try:
        return float(_first(Path("/proc/uptime")).split()[0])
    except (OSError, IndexError, ValueError):
        return 0.0


def read_services() -> dict:
    units = ("xray", "strongswan-starter", "xl2tpd", "manager")
    return {u: "active" if _is_active(u) else "inactive" for u in units}


def read_tunnel() -> dict:
    wg = _run(["ip", "-br", "link", "show", "wg0"])[1]
    ppp = _run(["ip", "-br", "link", "show", "type", "ppp"])[1]
    ppp_count = sum(
        1 for line in ppp.splitlines()
        if line.split() and line.split()[0] != "ppp+"
    )
    return {
        "wg0": bool(wg.strip()),
        "ppp_count": ppp_count,
    }


def read_traffic() -> dict:
    """Суммарные счётчики rx/tx (bytes) для wg0 и всех ppp-интерфейсов."""
    out = {}
    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"wg0": {"rx": 0, "tx": 0}, "ppp": {"rx": 0, "tx": 0}}
    ppp_rx = ppp_tx = 0
    wg_rx = wg_tx = 0
    for line in lines:
        if ":" not in line:
            continue
        iface, _, rest = line.partition(":")
        iface = iface.strip()
        fields = rest.split()
        if len(fields) < 10:
            continue
        try:
            rx, tx = int(fields[0]), int(fields[8])
        except ValueError:
            continue
        if iface == "wg0":
            wg_rx, wg_tx = rx, tx
        elif iface.startswith("ppp"):
            ppp_rx += rx
            ppp_tx += tx
    return {
        "wg0": {"rx": wg_rx, "tx": wg_tx},
        "ppp": {"rx": ppp_rx, "tx": ppp_tx},
    }


def read_public_ip() -> str:
    code, out = _run(
        ["curl", "-4", "-sS", "--max-time", "5", "--noproxy", "*", "https://api.ipify.org"]
    )
    if code != 0:
        return ""
    return out.strip()


def check_tunnel() -> dict:
    from . import profiles
    rows = [p for p in profiles.list_profiles() if p.get("enabled")]
    bad = [p for p in rows if p["health"] != "ok" or p["service"] != "active"]
    return {
        "ok": bool(rows) and not bad,
        "ip": "",
        "expected": "",
        "latency_ms": None,
        "error": "; ".join(f"{p['local_ip']}: {p['health']} / {p['service']}" for p in bad) if rows else "Нет настроенных интерфейсов",
        "profiles": rows,
    }


def _legacy_check_tunnel() -> dict:
    code, out = _run(
        ["curl", "-4", "-sS", "--max-time", "8", "-w", "|%{time_total}",
         "--socks5-hostname", "127.0.0.1:1080", "http://api.ipify.org"]
    )
    if code != 0:
        return {
            "ok": False,
            "ip": "",
            "expected": get_setting(EXPECTED_IP_KEY, ""),
            "latency_ms": None,
            "error": (out or "curl failed")[:300],
        }
    ip, _, t = out.rpartition("|")
    ip = ip.strip()
    try:
        latency_ms = round(float(t) * 1000, 1)
    except ValueError:
        latency_ms = None

    expected = get_setting(EXPECTED_IP_KEY, "") or settings.healthcheck_expected_ip
    if expected and ip != expected:
        return {
            "ok": False,
            "ip": ip,
            "expected": expected,
            "latency_ms": latency_ms,
            "error": f"public IP mismatch: got {ip}, expected {expected}",
        }
    if not expected and ip:
        set_setting(EXPECTED_IP_KEY, ip)
    return {
        "ok": bool(ip),
        "ip": ip,
        "expected": get_setting(EXPECTED_IP_KEY, ""),
        "latency_ms": latency_ms,
        "error": "" if ip else "no public IP",
    }


def restart_tunnel() -> Tuple[bool, str]:
    return l2tp.restart()


def sample_traffic() -> None:
    """Один сэмпл счётчиков wg0/ppp в БД. Вызывается по таймеру."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data = read_traffic()
    for iface in ("wg0", "ppp"):
        add_traffic_sample(now, iface, data[iface]["rx"], data[iface]["tx"])
    purge_traffic_samples(
        (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    )


def traffic_series(iface: str, minutes: int = 60) -> list:
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return [
        {"ts": r["ts"], "iface": r["iface"], "rx": r["rx"], "tx": r["tx"]}
        for r in get_traffic_samples(iface, since)
    ]
