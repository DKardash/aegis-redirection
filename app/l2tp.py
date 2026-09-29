import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .db import audit

XL2TPD_CONF = Path("/etc/xl2tpd/xl2tpd.conf")
IPSEC_SECRETS = Path("/etc/ipsec.secrets")
IPSEC_CONF = Path("/etc/ipsec.conf")
CHAP_SECRETS = Path("/etc/ppp/chap-secrets")
PPP_OPTIONS = Path("/etc/ppp/options.xl2tpd")
BACKUP_SUFFIX = ".bak"


def _run(cmd: List[str], timeout: int = 15) -> Tuple[int, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, (res.stdout or res.stderr).strip()
    except FileNotFoundError:
        return 1, "binary not found"
    except subprocess.TimeoutExpired:
        return 1, "timeout"


def _is_active(unit: str) -> bool:
    code, out = _run(["systemctl", "is-active", unit])
    return code == 0 and out == "active"


def _find_in(path: Path, pattern: str) -> str:
    if not path.exists():
        return ""
    m = re.search(pattern, path.read_text(encoding="utf-8", errors="replace"))
    return m.group(1).strip() if m else ""


def read_status() -> dict:
    ppp_ifaces = _ppp_interfaces()
    return {
        "services": {
            "strongswan": "active" if _is_active("strongswan-starter") else "inactive",
            "xl2tpd": "active" if _is_active("xl2tpd") else "inactive",
        },
        "config_exists": XL2TPD_CONF.exists() and CHAP_SECRETS.exists(),
        "interface": {
            "local_ip": _find_in(XL2TPD_CONF, r"local ip\s*=\s*(\S+)"),
            "listen_addr": _find_in(XL2TPD_CONF, r"listen-addr\s*=\s*(\S+)"),
        },
        "pool": {
            "start": _find_in(XL2TPD_CONF, r"ip range\s*=\s*([^-]+)-"),
            "end": _find_in(XL2TPD_CONF, r"ip range\s*=\s*[^-]+-(\S+)"),
        },
        "auth": {
            "username": _find_in(CHAP_SECRETS, r"^(\S+)\s+\*\s+\S+",),
            "password_present": bool(_find_in(CHAP_SECRETS, r"^\S+\s+\*\s+(\S+)")),
            "psk_present": bool(_find_in(IPSEC_SECRETS, r":\s*PSK\s+[\"']?(\S+)")),
        },
        "users": list_users(),
        "sessions": ppp_ifaces,
    }


def _ppp_interfaces() -> List[dict]:
    code, out = _run(["ip", "-br", "addr", "show", "type", "ppp"])
    if code != 0:
        return []
    sessions = []
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        iface = parts[0]
        if iface == "ppp+":
            continue
        state = "connecting"
        local_addr = parts[2].split("/")[0] if len(parts) > 2 else ""
        addr = local_addr
        if "peer" in parts:
            addr = parts[parts.index("peer") + 1]
            state = "connected"
        rx, tx = _iface_traffic(iface)
        sessions.append(
            {
                "interface": iface,
                "state": state,
                "address": addr,
                "local_address": local_addr,
                "rx_bytes": rx,
                "tx_bytes": tx,
            }
        )
    return sessions


def _iface_traffic(iface: str) -> Tuple[int, int]:
    code, out = _run(["ip", "-s", "link", "show", iface])
    if code != 0:
        return 0, 0
    rx = tx = 0
    for line in out.splitlines():
        m = re.match(r"\s+(\d+)\s+(\d+)", line)
        if m:
            if rx == 0:
                rx = int(m.group(2))
            else:
                tx = int(m.group(2))
    return rx, tx


def _backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + BACKUP_SUFFIX))


def _apply_ipsec_conf(listen_addr: str) -> None:
    if not IPSEC_CONF.exists():
        return
    _backup(IPSEC_CONF)
    text = IPSEC_CONF.read_text(encoding="utf-8")
    text = re.sub(r"left=\S+", f"left={listen_addr}", text)
    IPSEC_CONF.write_text(text, encoding="utf-8")


def _apply_secrets(psk: str, username: str, password: str) -> None:
    _backup(IPSEC_SECRETS)
    IPSEC_SECRETS.write_text(f': PSK "{psk}"\n', encoding="utf-8")
    _backup(CHAP_SECRETS)
    CHAP_SECRETS.write_text(f"{username} * {password} *\n", encoding="utf-8")


def _apply_xl2tpd(local_ip: str, pool_start: str, pool_end: str, listen_addr: str) -> None:
    if not XL2TPD_CONF.exists():
        return
    _backup(XL2TPD_CONF)
    text = XL2TPD_CONF.read_text(encoding="utf-8")
    text = re.sub(r"local ip\s*=\s*\S+", f"local ip = {local_ip}", text)
    text = re.sub(r"ip range\s*=\s*[^-]+-\S+", f"ip range = {pool_start}-{pool_end}", text)
    text = re.sub(r"listen-addr\s*=\s*\S+", f"listen-addr = {listen_addr}", text)
    XL2TPD_CONF.write_text(text, encoding="utf-8")


def _validate_ip(raw: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(raw)
        return True
    except ValueError:
        return False


def apply_config(data: dict) -> Tuple[bool, str]:
    local_ip = (data.get("local_ip") or "10.100.77.195").strip()
    listen_addr = (data.get("listen_addr") or local_ip).strip()
    pool_start = (data.get("pool_start") or "").strip()
    pool_end = (data.get("pool_end") or "").strip()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    psk = (data.get("psk") or "").strip()

    if not _validate_ip(local_ip):
        return False, "invalid local_ip"
    if not _validate_ip(listen_addr):
        return False, "invalid listen_addr"
    if not _validate_ip(pool_start) or not _validate_ip(pool_end):
        return False, "invalid pool range"
    if len(username) < 1:
        return False, "username required"
    if len(password) < 8:
        return False, "password must be >= 8 chars"
    if len(psk) < 8:
        return False, "PSK must be >= 8 chars"

    _apply_secrets(psk, username, password)
    _apply_xl2tpd(local_ip, pool_start, pool_end, listen_addr)
    _apply_ipsec_conf(listen_addr)

    ok, err = restart()
    if not ok:
        return False, err
    audit("l2tp_config", f"user={username} local={local_ip} pool={pool_start}-{pool_end}")
    return True, "config applied"


def restart() -> Tuple[bool, str]:
    failed = []
    for unit in ("strongswan-starter", "xl2tpd"):
        code, out = _run(["systemctl", "restart", unit])
        if code != 0 or not _is_active(unit):
            failed.append(f"{unit}: {out}")
    if failed:
        return False, "; ".join(failed)
    audit("l2tp_restart", "strongswan xl2tpd")
    return True, "restarted"


def list_users() -> List[dict]:
    if not CHAP_SECRETS.exists():
        return []
    users = []
    for line in CHAP_SECRETS.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^(\S+)\s+\*\s+(\S+)\s+(\S+)", line.strip())
        if m:
            allowed = m.group(3)
            users.append({
                "username": m.group(1),
                "password": m.group(2),
                "peer_ip": "" if allowed == "*" else allowed,
            })
    return users


def set_user_peer_ip(username: str, peer_ip: str) -> Tuple[bool, str]:
    """Set a fixed client address, or clear it so each L2TP pool assigns one."""
    import ipaddress

    allowed = peer_ip.strip() or "*"
    if allowed != "*":
        try:
            ipaddress.IPv4Address(allowed)
        except ValueError:
            return False, "invalid PPP peer IP"
    lines = CHAP_SECRETS.read_text(encoding="utf-8", errors="replace").splitlines()
    found = False
    result = []
    for line in lines:
        m = re.match(rf"^({re.escape(username)}\s+\*\s+\S+\s+)\S+(.*)$", line.strip())
        if m:
            result.append(f"{m.group(1)}{allowed}{m.group(2)}")
            found = True
        else:
            result.append(line)
    if not found:
        return False, f"L2TP user not found: {username}"
    _backup(CHAP_SECRETS)
    CHAP_SECRETS.write_text("\n".join(result) + "\n", encoding="utf-8")
    return True, "peer IP assigned" if allowed != "*" else "peer IP is assigned by profile pool"


def enable_multi_address_listener() -> Tuple[bool, str]:
    """Разрешить L2TP/IPsec принимать соединения на всех локальных IP ВМ."""
    try:
        xl2tp_text = XL2TPD_CONF.read_text(encoding="utf-8")
        ipsec_text = IPSEC_CONF.read_text(encoding="utf-8")
    except OSError as exc:
        return False, str(exc)
    new_xl2tp = re.sub(r"(?m)^\s*listen-addr\s*=.*\n?", "", xl2tp_text)
    new_ipsec = re.sub(r"(?m)^(\s*left=)\S+", r"\1%any", ipsec_text)
    if new_xl2tp == xl2tp_text and new_ipsec == ipsec_text:
        return True, "already enabled"
    _backup(XL2TPD_CONF)
    _backup(IPSEC_CONF)
    XL2TPD_CONF.write_text(new_xl2tp, encoding="utf-8")
    IPSEC_CONF.write_text(new_ipsec, encoding="utf-8")
    ok, err = restart()
    if not ok:
        return False, err
    audit("l2tp_multi_address", "listen on all local VM addresses")
    return True, "L2TP listens on all local addresses"


def add_user(username: str, password: str) -> Tuple[bool, str]:
    username = username.strip()
    password = password.strip()
    if not re.match(r"^[A-Za-z0-9_.-]{1,32}$", username):
        return False, "invalid username (letters/digits/_-. , max 32)"
    if len(password) < 8:
        return False, "password must be >= 8 chars"
    for u in list_users():
        if u["username"] == username:
            return False, f"user already exists: {username}"
    _backup(CHAP_SECRETS)
    with CHAP_SECRETS.open("a", encoding="utf-8") as f:
        f.write(f"{username} * {password} *\n")
    audit("l2tp_user_add", username)
    return True, "user added"


def delete_user(username: str) -> Tuple[bool, str]:
    users = list_users()
    if not any(u["username"] == username for u in users):
        return False, "user not found"
    _backup(CHAP_SECRETS)
    lines = [
        line for line in CHAP_SECRETS.read_text(encoding="utf-8", errors="replace").splitlines()
        if not re.match(rf"^{re.escape(username)}\s+\*\s+\S+\s+\*", line.strip())
    ]
    CHAP_SECRETS.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    audit("l2tp_user_del", username)
    return True, "user deleted"
