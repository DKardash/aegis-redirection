"""LAN-адреса ВМ с независимыми L2TP и Xray-выходами.

Основной адрес использует штатный xl2tpd. Для каждого дополнительного адреса
запускается отдельный экземпляр xl2tpd, который передаёт pppd уникальный
``ipparam``. PPP hook выбирает по нему отдельный TPROXY inbound/outbound.
"""

import ipaddress
import json
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Optional, Tuple

from . import crud, healthcheck, l2tp, xray
from .db import audit, get_setting, set_setting

PROFILES_KEY = "egress_profiles"
RUNTIME_KEY = "egress_runtime"
_LOCK = threading.RLock()
_TICK_LOCK = threading.Lock()


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return wrapped


def runtime_state() -> dict:
    try:
        return json.loads(get_setting(RUNTIME_KEY, "{}") or "{}")
    except (ValueError, TypeError):
        return {}


def active_id(profile: dict, state: dict) -> int:
    value = state.get(str(profile["id"]), {}).get("active_server_id", profile["server_id"])
    return int(value or 0) if value in (0, profile["server_id"], profile.get("backup_server_id")) else int(profile["server_id"])


def choose_route(profile: dict, previous: dict, checks: dict) -> dict:
    """Two failed rounds to switch; two successful rounds to return; unknown is neutral."""
    primary = int(profile["server_id"])
    backup = int(profile.get("backup_server_id") or 0)
    active = int(previous.get("active_server_id", primary) or 0)
    if active not in (0, primary, backup):
        active = primary
    failures, successes = {}, {}
    for server_id in filter(None, (primary, backup)):
        key = str(server_id)
        ok = checks.get(server_id, (False, None, "сервер недоступен"))[0]
        if ok is None:
            failures[key] = previous.get("failures", {}).get(key, 0)
            successes[key] = previous.get("successes", {}).get(key, 0)
        else:
            failures[key] = 0 if ok else min(2, previous.get("failures", {}).get(key, 0) + 1)
            successes[key] = min(2, previous.get("successes", {}).get(key, 0) + 1) if ok else 0
    main_ok = bool(successes.get(str(primary)))
    backup_ok = bool(backup and successes.get(str(backup)))
    if active == 0:
        active = primary if main_ok or checks.get(primary, (False,))[0] is None else backup if backup_ok or (backup and checks.get(backup, (False,))[0] is None) else 0
    elif active == backup and checks.get(primary, (False,))[0] is True and successes.get(str(primary), 0) >= 2:
        active = primary
    elif checks.get(active, (False,))[0] is None:
        pass
    elif failures.get(str(active), 0) >= 2:
        active = (backup if backup_ok else 0) if active == primary else (primary if main_ok else 0)
    active_result = checks.get(active, (False, None, "Нет подтверждённого рабочего выхода")) if active else (False, None, "Нет подтверждённого рабочего выхода")
    health = "degraded" if active and active_result[0] is None else "ok" if active and active_result[0] else "fail"
    return {
        "active_server_id": active,
        "failures": failures, "successes": successes,
        "health": health,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "error": "" if health == "ok" else active_result[2] or "Нет подтверждённого рабочего выхода",
    }


def failover_tick() -> str:
    if not _TICK_LOCK.acquire(blocking=False):
        return "проверка интерфейсов уже выполняется"
    try:
        return _failover_tick()
    finally:
        _TICK_LOCK.release()


def _failover_tick() -> str:
    snapshot = _stored_profiles()
    enabled = [p for p in snapshot if p.get("enabled")]
    ids = {int(sid) for p in enabled for sid in (p["server_id"], p.get("backup_server_id")) if sid}
    servers = {sid: crud.get_server(sid) for sid in ids}
    def probe(sid):
        server = servers[sid]
        return healthcheck.route_check(server) if server and server.get("enabled") else (False, None, "сервер отключён")
    with ThreadPoolExecutor(max_workers=3) as pool:
        checks = dict(zip(sorted(ids), pool.map(probe, sorted(ids))))
    with _LOCK:
        if _stored_profiles() != snapshot:
            return "интерфейсы изменились во время проверки; результат пропущен"
        old = runtime_state()
        new = {str(p["id"]): choose_route(p, old.get(str(p["id"]), {}), checks) for p in enabled}
        changed = [p for p in enabled if active_id(p, old) != active_id(p, new)]
        if changed:
            ok, error = xray.apply_config(build_full_config(state=new))
            if not ok:
                audit("profile_failover_error", error)
                return "не удалось применить маршруты: " + error
            for p in changed:
                audit("profile_failover", f"ip={p['local_ip']} from={active_id(p, old)} to={active_id(p, new)}")
        set_setting(RUNTIME_KEY, json.dumps(new))
    return f"проверено интерфейсов: {len(enabled)}, переключено: {len(changed)}"
DEFAULT_PREFIX = 24
FIRST_PORT = 12346
PROFILE_ROOT = Path("/etc/xray/l2tp/profiles")
MAP_PATH = Path("/etc/xray/ppp-profiles.conf")
HOOK_UP = Path("/etc/ppp/ip-up.d/99-xray-profile")
HOOK_DOWN = Path("/etc/ppp/ip-down.d/99-xray-profile")
APPLY_SCRIPT = Path("/usr/local/bin/xray-profile-apply.sh")
UNIT_PATH = Path("/etc/systemd/system/xray-l2tp-profile@.service")
BASE_PPP_OPTIONS = Path("/etc/ppp/options.xl2tpd")
BASE_XL2TP_CONF = Path("/etc/xl2tpd/xl2tpd.conf")
IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
IPPARAM_PREFIX = "xray-profile-"

_UNIT = """[Unit]
Description=Xray L2TP profile %i
After=network-online.target strongswan-starter.service
Wants=network-online.target strongswan-starter.service

[Service]
Type=simple
EnvironmentFile=/etc/xray/l2tp/profiles/%i/env
ExecStartPre=/usr/sbin/ip address replace ${LOCAL_CIDR} dev ${INTERFACE}
ExecStart=/usr/sbin/xl2tpd -D -c /etc/xray/l2tp/profiles/%i/xl2tpd.conf -p /run/xray-xl2tpd-%i.pid -C /run/xray-xl2tpd-%i.control
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

_APPLY_SCRIPT = r'''#!/usr/bin/env bash
set -u
MAP=/etc/xray/ppp-profiles.conf
RESERVED="0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4"

remove_iface() {
  local iface="$1" chain="XP_${1//[^A-Za-z0-9_]/_}"
  iptables -t mangle -D PREROUTING -i "$iface" -p tcp -j "$chain" 2>/dev/null || true
  iptables -t mangle -D PREROUTING -i "$iface" -p udp -j "$chain" 2>/dev/null || true
  iptables -t mangle -F "$chain" 2>/dev/null || true
  iptables -t mangle -X "$chain" 2>/dev/null || true
}

apply_iface() {
  local iface="$1" key="${2:-}" local_ip="${3:-}" port="" chain="XP_${1//[^A-Za-z0-9_]/_}"
  [ -r "$MAP" ] && port="$(awk -v key="$key" '$1 == key {print $2; exit}' "$MAP")"
  # The negotiated local PPP address is an independent fallback.  Unlike
  # ipparam it survives daemon restarts and can be read back from the live
  # interface, so apply-all can rebuild routing without reconnecting clients.
  if [ -z "$port" ] && [ -n "$local_ip" ] && [ -r "$MAP" ]; then
    port="$(awk -v local_ip="$local_ip" '$3 == local_ip {print $2; exit}' "$MAP")"
  fi
  remove_iface "$iface"
  [ -n "$port" ] || return 0
  iptables -t mangle -N "$chain"
  for net in $RESERVED; do iptables -t mangle -A "$chain" -d "$net" -j RETURN; done
  iptables -t mangle -A "$chain" -p tcp -j TPROXY --on-port "$port" --tproxy-mark 0x1/0x1
  iptables -t mangle -A "$chain" -p udp -j TPROXY --on-port "$port" --tproxy-mark 0x1/0x1
  iptables -t mangle -I PREROUTING 1 -i "$iface" -p udp -j "$chain"
  iptables -t mangle -I PREROUTING 1 -i "$iface" -p tcp -j "$chain"
}

profile_from_pid() {
  local pid="$1" prev="" arg
  while IFS= read -r -d '' arg; do
    if [ "$prev" = "ipparam" ]; then printf '%s' "$arg"; return; fi
    prev="$arg"
  done < "/proc/$pid/cmdline"
}

case "${1:-apply-all}" in
  up) apply_iface "$2" "${3:-}" "${4:-}" ;;
  down) remove_iface "$2" ;;
  apply-all)
    while read -r iface local_ip; do
      [ -n "$iface" ] || continue
      apply_iface "$iface" "" "$local_ip"
    done < <(ip -o -4 address show | awk '$2 ~ /^ppp/ {split($4, a, "/"); print $2, a[1]}')
    ;;
esac
'''

_HOOK_UP = '''#!/usr/bin/env bash
/usr/local/bin/xray-profile-apply.sh up "$1" "$6" "$4"
'''

_HOOK_DOWN = '''#!/usr/bin/env bash
/usr/local/bin/xray-profile-apply.sh down "$1"
'''


def _run(cmd: list[str], timeout: int = 45) -> Tuple[int, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, (res.stderr or res.stdout).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _stored_profiles() -> list[dict]:
    raw = get_setting(PROFILES_KEY, "[]") or "[]"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [dict(x) for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def list_profiles() -> list[dict]:
    out = []
    state = runtime_state()
    for item in _stored_profiles():
        row = dict(item)
        server = crud.get_server(int(row.get("server_id") or 0))
        row["server_name"] = server.get("name", "") if server else ""
        row["server_exists"] = server is not None
        backup = crud.get_server(int(row.get("backup_server_id") or 0))
        row["backup_server_name"] = backup.get("name", "") if backup else ""
        current = crud.get_server(active_id(row, state)) if row.get("enabled") else None
        row["active_server_id"] = current["id"] if current else None
        row["active_server_name"] = current.get("name", "") if current else ""
        row["on_backup"] = bool(current and current["id"] == row.get("backup_server_id"))
        row["health"] = state.get(str(row["id"]), {}).get("health", "unknown")
        row["health_error"] = state.get(str(row["id"]), {}).get("error", "")
        row["checked_at"] = state.get(str(row["id"]), {}).get("checked_at")
        unit = "xl2tpd" if row.get("primary") else f"xray-l2tp-profile@{row.get('id')}"
        code, status = _run(["systemctl", "is-active", unit], timeout=8)
        row["service"] = "active" if code == 0 and status == "active" else "inactive"
        out.append(row)
    return out


def _save(items: list[dict]) -> None:
    set_setting(PROFILES_KEY, json.dumps(items, ensure_ascii=False))


def _next_id(items: list[dict]) -> int:
    return max((int(x.get("id") or 0) for x in items), default=0) + 1


def _next_port(items: list[dict]) -> int:
    used = {int(x.get("tproxy_port") or 0) for x in items}
    port = FIRST_PORT
    while port in used:
        port += 1
    return port


def _primary_ip(interface: str) -> str:
    code, raw = _run(["ip", "-j", "route", "get", "1.1.1.1"], timeout=8)
    if code == 0:
        try:
            rows = json.loads(raw)
            if rows and rows[0].get("dev") == interface:
                return rows[0].get("prefsrc") or rows[0].get("src") or ""
        except (json.JSONDecodeError, IndexError):
            pass
    return ""


def _auto_ppp_network(profile_id: int) -> tuple[str, str, str]:
    third = 2 + profile_id
    if third > 254:
        raise ValueError("слишком много интерфейсов")
    return f"10.200.{third}.1", f"10.200.{third}.100", f"10.200.{third}.200"


def _validate(data: dict, existing_id: Optional[int] = None) -> Tuple[bool, str, dict]:
    items = _stored_profiles()
    name = (data.get("name") or "").strip()
    username = (data.get("username") or "").strip()
    local_ip = (data.get("local_ip") or "").strip()
    interface = (data.get("interface") or "eth0").strip()
    try:
        server_id = int(data.get("server_id") or 0)
        backup_server_id = int(data.get("backup_server_id") or 0) or None
        prefix = int(data.get("prefix") or DEFAULT_PREFIX)
    except (TypeError, ValueError):
        return False, "неверный server_id или prefix", {}
    if not name:
        return False, "укажите название интерфейса", {}
    if not IFACE_RE.match(interface):
        return False, "некорректное имя физического интерфейса", {}
    try:
        ipaddress.IPv4Address(local_ip)
    except ValueError:
        return False, "укажите корректный локальный IPv4", {}
    if not 1 <= prefix <= 32:
        return False, "prefix должен быть от 1 до 32", {}
    users = {u["username"] for u in l2tp.list_users()}
    if username not in users:
        return False, f"L2TP-пользователь не найден: {username}", {}
    server = crud.get_server(server_id)
    if not server or not server.get("enabled"):
        return False, "выбранный сервер не найден или отключён", {}
    if backup_server_id:
        backup = crud.get_server(backup_server_id)
        if backup_server_id == server_id:
            return False, "основной и резервный сервер должны отличаться", {}
        if not backup or not backup.get("enabled"):
            return False, "резервный сервер не найден или отключён", {}
    for p in items:
        if int(p.get("id") or 0) != int(existing_id or 0) and p.get("local_ip") == local_ip:
            return False, f"адрес уже используется интерфейсом {p.get('name')}", {}
    primary_ip = _primary_ip(interface)
    is_primary = local_ip == primary_ip
    if any(p.get("primary") and int(p.get("id") or 0) != int(existing_id or 0) for p in items) and is_primary:
        return False, "основной интерфейс уже добавлен", {}
    return True, "", {
        "name": name,
        "username": username,
        "local_ip": local_ip,
        "prefix": prefix,
        "interface": interface,
        "server_id": server_id,
        "backup_server_id": backup_server_id,
        "enabled": bool(data.get("enabled", True)),
        "primary": is_primary,
    }


def _write(path: Path, content: str, mode: Optional[int] = None) -> bool:
    old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
    if old == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    return True


def _base_options(ipparam: Optional[str]) -> str:
    text = BASE_PPP_OPTIONS.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?m)^\s*ipparam\s+\S+\s*\n?", "", text).rstrip() + "\n"
    if ipparam:
        text += f"ipparam {ipparam}\n"
    return text


def _write_hooks(items: list[dict]) -> None:
    enabled = [p for p in items if p.get("enabled")]
    _write(MAP_PATH, "".join(
        f"{IPPARAM_PREFIX}{p['id']} {p['tproxy_port']} {p['ppp_local_ip']}\n"
        for p in enabled
    ))
    _write(APPLY_SCRIPT, _APPLY_SCRIPT, 0o755)
    _write(HOOK_UP, _HOOK_UP, 0o755)
    _write(HOOK_DOWN, _HOOK_DOWN, 0o755)
    _write(UNIT_PATH, _UNIT, 0o644)


def _ensure_ipsec_any() -> Tuple[bool, str]:
    path = Path("/etc/ipsec.conf")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, str(exc)
    new = re.sub(r"(?m)^(\s*left=)\S+", r"\1%any", text)
    if new == text:
        return True, ""
    l2tp._backup(path)
    path.write_text(new, encoding="utf-8")
    code, err = _run(["systemctl", "restart", "strongswan-starter"])
    return (code == 0, err if code else "")


def _configure_primary(profile: dict) -> Tuple[bool, str]:
    changed = _write(BASE_PPP_OPTIONS, _base_options(IPPARAM_PREFIX + str(profile["id"])))
    try:
        text = BASE_XL2TP_CONF.read_text(encoding="utf-8")
    except OSError as exc:
        return False, str(exc)
    if re.search(r"(?m)^\s*listen-addr\s*=", text):
        new = re.sub(r"(?m)^(\s*listen-addr\s*=\s*)\S+", rf"\g<1>{profile['local_ip']}", text)
    else:
        new = re.sub(r"(?m)^\[global\]\s*$", f"[global]\nlisten-addr = {profile['local_ip']}", text, count=1)
    if new != text:
        l2tp._backup(BASE_XL2TP_CONF)
        BASE_XL2TP_CONF.write_text(new, encoding="utf-8")
        changed = True
    if changed or _run(["systemctl", "is-active", "xl2tpd"], 8)[0] != 0:
        code, err = _run(["systemctl", "restart", "xl2tpd"])
        if code != 0:
            return False, err
    return True, ""


def _profile_conf(profile: dict) -> tuple[str, str, str]:
    conf = f"""[global]
listen-addr = {profile['local_ip']}
port = 1701
ipsec saref = yes

[lns default]
ip range = {profile['pool_start']}-{profile['pool_end']}
local ip = {profile['ppp_local_ip']}
require chap = yes
refuse pap = yes
require authentication = yes
name = XrayGateway-{profile['id']}
ppp debug = no
pppoptfile = {PROFILE_ROOT}/{profile['id']}/ppp-options
length bit = yes
"""
    options = _base_options(IPPARAM_PREFIX + str(profile["id"]))
    env = f"LOCAL_CIDR={profile['local_ip']}/{profile['prefix']}\nINTERFACE={profile['interface']}\n"
    return conf, options, env


def _configure_secondary(profile: dict) -> Tuple[bool, str]:
    root = PROFILE_ROOT / str(profile["id"])
    conf, options, env = _profile_conf(profile)
    changed = _write(root / "xl2tpd.conf", conf)
    changed = _write(root / "ppp-options", options) or changed
    changed = _write(root / "env", env) or changed
    code, err = _run(["ip", "address", "replace", f"{profile['local_ip']}/{profile['prefix']}", "dev", profile["interface"]])
    if code != 0:
        return False, err
    unit = f"xray-l2tp-profile@{profile['id']}.service"
    _run(["systemctl", "enable", unit])
    code, err = _run(["systemctl", "restart" if changed else "start", unit])
    return (code == 0, err if code else "")


def _disable_profile(profile: dict, remove_ip: bool = True) -> None:
    if profile.get("primary"):
        try:
            _write(BASE_PPP_OPTIONS, _base_options(None))
            _run(["systemctl", "restart", "xl2tpd"])
        except OSError:
            pass
        return
    unit = f"xray-l2tp-profile@{profile['id']}.service"
    _run(["systemctl", "disable", "--now", unit])
    if remove_ip:
        _run(["ip", "address", "del", f"{profile['local_ip']}/{profile['prefix']}", "dev", profile["interface"]])


def _reconcile_secondary_units(items: list[dict]) -> None:
    """Stop instance services which no longer represent a secondary profile.

    A profile can become the primary one after its address changes.  Its old
    enabled instance would otherwise keep listening on the same UDP socket as
    the real secondary daemon and randomly accept connections for the wrong
    Xray route.
    """
    wanted = {
        int(p["id"])
        for p in items
        if p.get("enabled") and not p.get("primary")
    }
    if not PROFILE_ROOT.exists():
        return
    for root in PROFILE_ROOT.iterdir():
        if not root.is_dir() or not root.name.isdigit():
            continue
        profile_id = int(root.name)
        if profile_id not in wanted:
            unit = f"xray-l2tp-profile@{profile_id}.service"
            _run([
                "systemctl", "disable", "--now",
                unit,
            ])
            _run(["systemctl", "reset-failed", unit])


def build_full_config(default_server: Optional[dict] = None, state: Optional[dict] = None) -> dict:
    state = runtime_state() if state is None else state
    resolved = []
    for p in _stored_profiles():
        if not p.get("enabled"):
            continue
        server = crud.get_server(active_id(p, state))
        resolved.append({**p, "server": server if server and server.get("enabled") else None})
    return xray.build_multi_config(None, resolved)


@serialized
def apply_runtime(default_server: Optional[dict] = None, previous: Optional[list[dict]] = None) -> Tuple[bool, str]:
    items = _stored_profiles()
    try:
        cfg = build_full_config(default_server)
    except ValueError as exc:
        return False, str(exc)
    ok, err = xray.apply_config(cfg)
    if not ok:
        return False, err
    _write_hooks(items)
    _run(["systemctl", "daemon-reload"])
    _reconcile_secondary_units(items)
    ok, err = _ensure_ipsec_any()
    if not ok:
        return False, f"IPsec: {err}"
    current_ids = {int(p["id"]) for p in items if p.get("enabled")}
    for old in previous or []:
        if int(old.get("id") or 0) not in current_ids:
            _disable_profile(old)
        elif next((p for p in items if p.get("id") == old.get("id") and p.get("local_ip") != old.get("local_ip")), None):
            _run(["ip", "address", "del", f"{old['local_ip']}/{old['prefix']}", "dev", old["interface"]])
    for p in items:
        if not p.get("enabled"):
            continue
        ok, err = _configure_primary(p) if p.get("primary") else _configure_secondary(p)
        if not ok:
            return False, f"{p['name']}: {err}"
    code, hook_err = _run([str(APPLY_SCRIPT), "apply-all"])
    if code != 0:
        return False, f"PPP hook: {hook_err}"
    return True, "интерфейсы применены"


@serialized
def create_profile(data: dict) -> Tuple[bool, str, Optional[dict]]:
    items = _stored_profiles()
    ok, err, clean = _validate(data)
    if not ok:
        return False, err, None
    clean["id"] = _next_id(items)
    clean["tproxy_port"] = _next_port(items)
    if clean["primary"]:
        clean["ppp_local_ip"], clean["pool_start"], clean["pool_end"] = "10.200.2.1", "10.200.2.100", "10.200.2.200"
    else:
        clean["ppp_local_ip"], clean["pool_start"], clean["pool_end"] = _auto_ppp_network(clean["id"])
    items.append(clean)
    _save(items)
    ok, err = apply_runtime(previous=[])
    if not ok:
        _save(items[:-1])
        apply_runtime(previous=[clean])
        return False, err, None
    audit("interface_profile_add", f"ip={clean['local_ip']} server={clean['server_id']}")
    return True, "интерфейс добавлен", next((p for p in list_profiles() if p["id"] == clean["id"]), clean)


@serialized
def update_profile(profile_id: int, data: dict) -> Tuple[bool, str, Optional[dict]]:
    items = _stored_profiles()
    idx = next((i for i, p in enumerate(items) if int(p.get("id") or 0) == profile_id), None)
    if idx is None:
        return False, "интерфейс не найден", None
    ok, err, clean = _validate(data, profile_id)
    if not ok:
        return False, err, None
    old = dict(items[idx])
    if bool(old.get("primary")) != bool(clean.get("primary")):
        return False, "основной адрес нельзя превратить в дополнительный — удалите запись и создайте новую", None
    clean.update({k: old[k] for k in ("id", "tproxy_port", "ppp_local_ip", "pool_start", "pool_end")})
    items[idx] = clean
    prior_state = runtime_state()
    fresh_state = dict(prior_state)
    fresh_state.pop(str(profile_id), None)
    set_setting(RUNTIME_KEY, json.dumps(fresh_state))
    _save(items)
    ok, err = apply_runtime(previous=[old])
    if not ok:
        items[idx] = old
        _save(items)
        set_setting(RUNTIME_KEY, json.dumps(prior_state))
        apply_runtime(previous=[clean])
        return False, err, None
    audit("interface_profile_update", f"ip={clean['local_ip']} server={clean['server_id']}")
    return True, "интерфейс обновлён", next((p for p in list_profiles() if p["id"] == profile_id), clean)


@serialized
def delete_profile(profile_id: int) -> Tuple[bool, str]:
    items = _stored_profiles()
    old = next((p for p in items if int(p.get("id") or 0) == profile_id), None)
    if not old:
        return False, "интерфейс не найден"
    _save([p for p in items if int(p.get("id") or 0) != profile_id])
    ok, err = apply_runtime(previous=[old])
    if not ok:
        _save(items)
        apply_runtime()
        return False, err
    audit("interface_profile_delete", f"ip={old['local_ip']}")
    return True, "интерфейс удалён"


def restore_runtime() -> None:
    ok, error = apply_runtime()
    if not ok:
        raise RuntimeError(error)
    set_setting(crud.ACTIVE_KEY, "")
