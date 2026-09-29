import base64
import json
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from . import secret
from .config import settings
from .db import audit, get_setting, set_setting

MT_HOST = "mikrotik_host"
MT_PORT = "mikrotik_port"
MT_USER = "mikrotik_user"
MT_PASS = "mikrotik_pass"
MT_USE_SSL = "mikrotik_use_ssl"
MT_AUTO_FAILOVER = "mikrotik_auto_failover"
MT_FAILOVER_INTERVAL = "mikrotik_failover_interval"
MT_FAILOVER_STREAK = "mikrotik_failover_streak"


def get_mt_config() -> dict:
    return {
        "host": get_setting(MT_HOST, "") or "",
        "port": int(get_setting(MT_PORT, "8728") or "8728"),
        "username": get_setting(MT_USER, "") or "",
        "password": secret.decrypt(get_setting(MT_PASS, "") or ""),
        "use_ssl": (get_setting(MT_USE_SSL, "0") or "0") == "1",
        "auto_failover": (get_setting(MT_AUTO_FAILOVER, "0") or "0") == "1",
        "failover_interval": int(get_setting(MT_FAILOVER_INTERVAL, "30") or "30"),
    }


def set_mt_config(data: dict) -> Tuple[bool, str]:
    host = (data.get("host") or "").strip()
    user = (data.get("username") or "").strip()
    if not host:
        set_setting(MT_HOST, "")
        set_setting(MT_PORT, str(data.get("port") or 8728))
        set_setting(MT_USER, "")
        set_setting(MT_PASS, "")
        set_setting(MT_USE_SSL, "1" if data.get("use_ssl") else "0")
        audit("mikrotik_config", "cleared")
        return True, "cleared"
    if not user:
        return False, "username required"
    port = int(data.get("port") or (443 if data.get("use_ssl") else 8728))
    port = min(max(port, 1), 65535)
    set_setting(MT_HOST, host)
    set_setting(MT_PORT, str(port))
    set_setting(MT_USER, user)
    password = (data.get("password") or "").strip()
    set_setting(MT_PASS, secret.encrypt(password) if password else "")
    set_setting(MT_USE_SSL, "1" if data.get("use_ssl") else "0")
    set_setting(MT_AUTO_FAILOVER, "1" if data.get("auto_failover") else "0")
    interval = int(data.get("failover_interval") or 30)
    set_setting(MT_FAILOVER_INTERVAL, str(min(max(interval, 15), 600)))
    audit("mikrotik_config", f"host={host}:{port} ssl={bool(data.get('use_ssl'))} failover={bool(data.get('auto_failover'))}")
    return True, "saved"


def _is_true(val) -> bool:
    """RouterOS возвращает булевы поля строками 'true'/'false'."""
    return str(val).lower() == "true"


def _friendly(err: str) -> str:
    if not err:
        return err
    for frag, msg in (
        ("401", "неверный логин/пароль MikroTik"),
        ("403", "недостаточно прав на MikroTik"),
        ("404", "REST-команда не найдена (проверьте путь/версию RouterOS)"),
        ("405", "метод не поддерживается роутером"),
        ("400", "MikroTik отклонил запрос (проверьте параметры)"),
        ("timed out", "таймаут соединения с MikroTik"),
        ("Connection refused", "MikroTik недоступен (соединение отклонено)"),
        ("Connection reset", "MikroTik сбросил соединение"),
        ("Name or service not known", "не удаётся разрешить адрес MikroTik"),
    ):
        if frag in err:
            return msg
    return err


def _rest_request(path: str, method: str = "GET", data: object = None, timeout: float = 8.0) -> Tuple[int, object, str]:
    cfg = get_mt_config()
    if not cfg["host"]:
        return 1, None, "MikroTik не настроен"
    scheme = "https" if cfg["use_ssl"] else "http"
    url = f"{scheme}://{cfg['host']}:{cfg['port']}/rest{path}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{cfg['username']}:{cfg['password']}'.encode()).decode()}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, data=body, headers=headers)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
            return 0, (json.loads(raw) if raw.strip() else None), ""
    except urllib.error.HTTPError as e:
        return 1, None, _friendly(f"HTTP {e.code}")
    except urllib.error.URLError as e:
        return 1, None, _friendly(str(e.reason))
    except Exception as e:  # noqa: BLE001
        return 1, None, _friendly(str(e))


def rest(path: str, method: str = "GET", data: object = None, timeout: float = 8.0) -> Tuple[int, object, str]:
    """Публичный helper для REST-запросов к MikroTik."""
    return _rest_request(path, method=method, data=data, timeout=timeout)


def test_connection() -> dict:
    code, data, err = _rest_request("/system/resource")
    if code != 0:
        return {"ok": False, "error": err, "details": None}
    return {"ok": True, "error": "", "details": data}


def _read_all(path: str) -> Tuple[int, list, str]:
    code, data, err = _rest_request(path)
    if code != 0:
        return code, [], err
    if isinstance(data, dict):
        data = [data]
    return 0, data, ""


_DUR_RE = re.compile(r"(\d+(?:\.\d+)?)([wdhms])", re.IGNORECASE)
_DUR_UNITS = {"w": 7 * 86400, "d": 86400, "h": 3600, "m": 60, "s": 1}


def _parse_duration_sec(raw) -> Optional[int]:
    """Парсит длительность в секунды: '9s', '1m37s', '3w4d18h45m21s' и вариант с пробелами."""
    if raw is None:
        return None
    m = _DUR_RE.findall(str(raw))
    if not m:
        return None
    return int(sum(float(v) * _DUR_UNITS[u.lower()] for v, u in m))


def tunnel_health() -> dict:
    """Живость и трафик туннелей wg0 / l2tp-gw."""
    out = {"wg": {"up": False}, "l2tp": {"up": False}}

    code, peers, _ = _read_all("/interface/wireguard/peers?interface=wg0")
    if code == 0 and peers:
        p = peers[0]
        out["wg"].update(
            {
                "up": p.get("disabled") != "true",
                "handshake_sec": _parse_duration_sec(p.get("last-handshake")),
                "endpoint": p.get("current-endpoint-address", ""),
                "rx": p.get("rx", 0),
                "tx": p.get("tx", 0),
            }
        )

    code, l2tps, _ = _read_all("/interface/l2tp-client")
    if code == 0:
        for c in l2tps if isinstance(l2tps, list) else []:
            if c.get("name") == "l2tp-gw":
                out["l2tp"].update(
                    {
                        "up": c.get("running") == "true" and c.get("disabled") != "true",
                        "connect_to": c.get("connect-to", ""),
                    }
                )
                break

    code, ifaces, _ = _read_all("/interface")
    if code == 0:
        for i in ifaces if isinstance(ifaces, list) else []:
            if i.get("name") not in ("wg0", "l2tp-gw"):
                continue
            key = "wg" if i.get("name") == "wg0" else "l2tp"
            out[key].update(
                {
                    "running": i.get("running") == "true",
                    "rx": i.get("rx-byte", 0),
                    "tx": i.get("tx-byte", 0),
                    "last_link_up": i.get("last-link-up-time", ""),
                }
            )
            out[key]["up"] = out[key].get("up") and i.get("running") == "true"
    return out


def read_status() -> dict:
    out = {"configured": bool(get_mt_config()["host"]), "ok": False, "error": ""}

    code, res, err = _rest_request("/system/resource")
    if code != 0:
        out["error"] = err
        return out
    out["ok"] = True
    out["uptime_sec"] = _parse_duration_sec(res.get("uptime", "")) or 0
    out["version"] = res.get("version", "")
    out["cpu_load"] = res.get("cpu-load", None)
    out["free_memory"] = res.get("free-memory", None)
    out["total_memory"] = res.get("total-memory", None)
    out["cpu_freq"] = res.get("cpu-frequency", None)
    out["board"] = res.get("board-name", "")
    out["uptime_raw"] = res.get("uptime", "")

    code, health, err = _read_all("/system/health")
    if code == 0 and health:
        vals = {h.get("name"): h.get("value") for h in health if h.get("value") is not None}
        out["temperature"] = vals.get("temperature")
        out["voltage"] = vals.get("voltage")

    code, mangle, err = _read_all("/ip/firewall/mangle")
    if code == 0:
        out["mangle"] = [
            {
                "chain": m.get("chain", ""),
                "action": m.get("action", ""),
                "comment": m.get("comment", ""),
                "bytes": m.get("bytes", 0),
                "packets": m.get("packets", 0),
                "disabled": _is_true(m.get("disabled")),
            }
            for m in mangle
        ]
    else:
        out["mangle"] = []

    code, addrlist, err = _read_all("/ip/firewall/address-list")
    if code == 0:
        out["address_lists"] = {
            "total": len(addrlist),
            "dynamic": sum(1 for a in addrlist if _is_true(a.get("dynamic"))),
        }
    else:
        out["address_lists"] = {"total": 0, "dynamic": 0}

    code, ifaces, err = _read_all("/interface")
    if code == 0:
        out["interfaces"] = [
            {
                "name": i.get("name", ""),
                "type": i.get("type", ""),
                "running": bool(i.get("running", False)),
                "rx": i.get("rx-byte", 0),
                "tx": i.get("tx-byte", 0),
            }
            for i in ifaces
            if i.get("name") in ("ether1", "ether2", "bridge", "wg0", "pppoe-out1") or i.get("type") == "ppp"
        ]
    else:
        out["interfaces"] = []

    return out


def _is_mode_rule(rule: dict, table: str) -> bool:
    """Режимное правило = mark-routing целевой таблицы с in-interface
    (исключение интерфейса, напр. !wg0 / !l2tp-gw) или chain=output.
    Обычные правила DNS-маршрутизации (DISCORD/YOUTUBE → mark_table_VPN)
    не считаются режимными."""
    if rule.get("action") != "mark-routing":
        return False
    if rule.get("new-routing-mark") != table:
        return False
    if rule.get("in-interface"):
        return True
    return rule.get("chain") == "output"


def _mode_rules() -> Tuple[dict, str]:
    """mark-routing правила режима туннеля."""
    code, rules, err = rest("/ip/firewall/mangle")
    if code != 0:
        return {}, err
    if not isinstance(rules, list):
        rules = [rules] if isinstance(rules, dict) else []

    wg = [r for r in rules if _is_mode_rule(r, "mark_table_VPN")]
    l2tp = [r for r in rules if _is_mode_rule(r, "mark_table_L2TP")]
    client_vpn = [
        r
        for r in rules
        if (r.get("comment") or "").startswith(CLIENT_RULE_PREFIX + " ")
        and not _is_true(r.get("disabled"))
    ]
    return {"wg": wg, "l2tp": l2tp, "client_vpn": client_vpn}, ""


def get_tunnel_mode() -> dict:
    sets, err = _mode_rules()
    if not sets:
        return {"ok": False, "error": err, "mode": ""}
    wg_enabled = any(r.get("disabled") != "true" for r in sets["wg"])
    l2tp_enabled = any(r.get("disabled") != "true" for r in sets["l2tp"])
    if l2tp_enabled:
        mode = "l2tp"
    elif wg_enabled:
        mode = "wg"
    else:
        mode = "none"
    client_tables = {r.get("new-routing-mark") for r in sets["client_vpn"] if r.get("new-routing-mark")}
    return {
        "ok": True,
        "mode": mode,
        "wg_enabled": wg_enabled,
        "l2tp_enabled": l2tp_enabled,
        "wg_rules": len(sets["wg"]),
        "l2tp_rules": len(sets["l2tp"]),
        "client_vpn_count": len(sets["client_vpn"]),
        "client_vpn_table": "|".join(sorted(client_tables)),
        "tunnels": tunnel_health(),
        "routes": get_routes(),
    }


def get_routes() -> list:
    """Активные маршруты для mark_table_VPN / mark_table_L2TP."""
    code, routes, _ = _read_all("/ip/route")
    if code != 0:
        return []
    out = []
    for r in routes if isinstance(routes, list) else []:
        if r.get("routing-table") not in ("mark_table_VPN", "mark_table_L2TP"):
            continue
        out.append(
            {
                "table": r.get("routing-table"),
                "gateway": r.get("gateway", ""),
                "distance": r.get("distance"),
                "active": r.get("active") == "true",
            }
        )
    return out


def _ensure_mode_route(mode: str) -> Tuple[bool, str]:
    """Гарантирует маршрут активной таблицы режима (создаёт, если отсутствует)."""
    table = "mark_table_L2TP" if mode == "l2tp" else "mark_table_VPN"
    iface = "l2tp-gw" if mode == "l2tp" else "wg0"
    code, routes, err = _read_all("/ip/route")
    if code != 0:
        return False, f"routes read: {err}"
    for r in routes if isinstance(routes, list) else []:
        if r.get("routing-table") == table and not _is_true(r.get("disabled")):
            return True, ""
    code, _, err = rest(
        "/ip/route",
        method="PUT",
        data={"dst-address": "0.0.0.0/0", "gateway": iface, "routing-table": table},
    )
    if code != 0:
        return False, f"route create {table}->{iface}: {err}"
    return True, f"создан маршрут {table}->{iface}"


def _retarget_client_vpn(new_table: str) -> Tuple[int, str]:
    """Переводит активные «клиенты через VPN» на таблицу активного режима."""
    code, rules, err = _read_all("/ip/firewall/mangle")
    if code != 0:
        return 0, err
    n = 0
    for r in rules if isinstance(rules, list) else []:
        if not (r.get("comment") or "").startswith(CLIENT_RULE_PREFIX + " "):
            continue
        if _is_true(r.get("disabled")):
            continue
        if r.get("new-routing-mark") == new_table:
            continue
        code2, _, e2 = rest(
            f"/ip/firewall/mangle/{r['.id']}",
            method="PATCH",
            data={"new-routing-mark": new_table},
        )
        if code2 == 0:
            n += 1
    return n, ""


def set_tunnel_mode(mode: str, force: bool = False) -> Tuple[bool, str]:
    if mode not in ("wg", "l2tp"):
        return False, "invalid mode"
    sets, err = _mode_rules()
    if not sets:
        return False, err
    if not sets["wg"] or not sets["l2tp"]:
        return False, "mangle rules not found (mark_table_VPN / mark_table_L2TP)"

    health = tunnel_health()
    target = health.get(mode, {})
    if not target.get("up") and not force:
        return False, (
            f"tunnel_down:{mode}: туннель {mode.upper()} не отвечает — "
            "переключение отключит маршрутизацию. Нажмите ещё раз для принудительного переключения."
        )

    enable_set = sets["l2tp"] if mode == "l2tp" else sets["wg"]
    disable_set = sets["wg"] if mode == "l2tp" else sets["l2tp"]
    orig = {r[".id"]: r.get("disabled", "false") for r in sets["wg"] + sets["l2tp"]}
    applied = []

    def revert() -> None:
        for rid in reversed(applied):
            try:
                rest(f"/ip/firewall/mangle/{rid}", method="PATCH", data={"disabled": orig.get(rid, "false")})
            except Exception:  # noqa: BLE001
                pass

    for r in disable_set:
        code, _, e = rest(f"/ip/firewall/mangle/{r['.id']}", method="PATCH", data={"disabled": "true"})
        if code != 0:
            revert()
            return False, f"disable {r['.id']}: {e} (изменения откачены)"
        applied.append(r[".id"])
    for r in enable_set:
        code, _, e = rest(f"/ip/firewall/mangle/{r['.id']}", method="PATCH", data={"disabled": "false"})
        if code != 0:
            revert()
            return False, f"enable {r['.id']}: {e} (изменения откачены)"
        applied.append(r[".id"])

    # После успешного переключения: маршрут активной таблицы + клиентские
    # правила следуют за активным туннелем (убирает путаницу WG↔L2TP).
    notes = []
    okr, msg = _ensure_mode_route(mode)
    if msg:
        notes.append(("ok" if okr else "warn") + ":" + msg)
    new_table = "mark_table_L2TP" if mode == "l2tp" else "mark_table_VPN"
    n, e = _retarget_client_vpn(new_table)
    if n:
        notes.append(f"клиенты через VPN → {new_table} ({n} правил)")
    elif e:
        notes.append(f"warn:client-vpn: {e}")

    audit("tunnel_mode", f"mode={mode}{' (force)' if force else ''}" + (f"; {'; '.join(notes)}" if notes else ""))
    msg = f"mode: {mode}"
    if notes:
        msg += " — " + "; ".join(notes)
    return True, msg


def get_address_list(list_name: Optional[str] = None) -> Tuple[bool, dict]:
    """Записи из /ip/firewall/address-list (с необязательным фильтром по листу)."""
    path = "/ip/firewall/address-list"
    if list_name:
        path += f"?list={list_name}"
    code, entries, err = rest(path)
    if code != 0:
        return False, {"error": err, "entries": [], "lists": []}
    if not isinstance(entries, list):
        entries = [entries] if isinstance(entries, dict) else []
    lists = sorted({e.get("list", "") for e in entries if e.get("list")})
    return True, {"entries": entries, "total": len(entries), "lists": lists}


def add_address_list(list_name: str, address: str, comment: str = "", check_duplicate: bool = True, disabled: bool = False) -> Tuple[bool, str]:
    if not list_name or not address:
        return False, "укажите лист и адрес"
    list_name = list_name.strip()
    address = address.strip()
    if check_duplicate:
        ok, data = get_address_list(list_name)
        if ok:
            low = address.lower()
            for e in data.get("entries", []):
                if (e.get("address") or "").lower() == low:
                    return False, f"запись {address} уже есть в листе {list_name}"
    data = {"list": list_name, "address": address, "disabled": "true" if disabled else "false"}
    if comment:
        data["comment"] = comment.strip()
    code, _, err = rest("/ip/firewall/address-list", method="PUT", data=data)
    if code != 0:
        return False, err
    audit("address_list_add", f"list={list_name} address={address}")
    return True, "запись добавлена"


def update_address_list(item_id: str, comment: Optional[str] = None, disabled: Optional[bool] = None) -> Tuple[bool, str]:
    if not item_id:
        return False, "не указан id записи"
    data = {}
    if comment is not None:
        data["comment"] = comment
    if disabled is not None:
        data["disabled"] = "true" if disabled else "false"
    if not data:
        return False, "нечего обновлять"
    code, _, err = rest(f"/ip/firewall/address-list/{item_id}", method="PATCH", data=data)
    if code != 0:
        return False, err
    audit("address_list_update", f"id={item_id}")
    return True, "запись обновлена"


def delete_address_list(item_id: str) -> Tuple[bool, str]:
    if not item_id:
        return False, "не указан id записи"
    code, _, err = rest(f"/ip/firewall/address-list/{item_id}", method="DELETE")
    if code != 0:
        return False, err
    audit("address_list_delete", f"id={item_id}")
    return True, "запись удалена"


_IMPORT_RE = re.compile(r'^add\s+list=(\S+)(?:\s+comment="([^"]*)")?\s+address=(\S+)')


def import_address_list(text: str) -> Tuple[bool, str]:
    """Import the three managed lists, preserving disabled entries."""
    from .addresslists import parse_rsc
    try:
        groups = parse_rsc(text)
    except ValueError as exc:
        return False, str(exc)
    added = 0
    failed = []
    for entry in (e for g in groups for e in g["entries"]):
        address = entry["address"]
        ok, err = add_address_list(entry["list"], address, entry["comment"], check_duplicate=True, disabled=entry["disabled"])
        if ok:
            added += 1
        else:
            failed.append(f"{address}: {err}")
    audit("address_list_import", f"added={added} failed={len(failed)}")
    if failed:
        return False, f"добавлено {added}; ошибки: {'; '.join(failed[:3])}"
    return True, f"импортировано записей: {added}"


def _tunnel_alive(mode: str, h: dict) -> bool:
    if not h.get("up"):
        return False
    if mode == "wg":
        hs = h.get("handshake_sec")
        return hs is not None and hs <= 300
    return True


def failover_tick() -> Tuple[bool, str]:
    """Авто-переключение: если включённый туннель мёртв (2 тика подряд),
    а другой жив — переключить режим."""
    if not get_mt_config()["host"]:
        return False, "mikrotik not configured"
    st = get_tunnel_mode()
    if not st.get("ok"):
        return False, st.get("error") or "mode unavailable"
    mode = st.get("mode")
    if mode not in ("wg", "l2tp"):
        return False, f"нет активного туннеля ({mode})"
    health = st.get("tunnels") or {}
    active = health.get(mode, {})
    if _tunnel_alive(mode, active):
        if get_setting(MT_FAILOVER_STREAK) != "0":
            set_setting(MT_FAILOVER_STREAK, "0")
        return False, f"{mode} alive"

    streak = int(get_setting(MT_FAILOVER_STREAK, "0") or "0") + 1
    set_setting(MT_FAILOVER_STREAK, str(streak))
    if streak < 2:
        return False, f"{mode} down ({streak}/2 тиков)"

    other = "l2tp" if mode == "wg" else "wg"
    if not health.get(other, {}).get("up"):
        set_setting(MT_FAILOVER_STREAK, "0")
        return False, f"{mode} down, {other} тоже down"

    ok, msg = set_tunnel_mode(other, force=True)
    set_setting(MT_FAILOVER_STREAK, "0")
    if ok:
        audit("tunnel_failover", f"{mode} -> {other}")
    return ok, f"{mode} down -> {other}: {msg}"


ROUTER_BACKUP_ENABLED = "router_backup_enabled"
ROUTER_BACKUP_TIME = "router_backup_time"
ROUTER_BACKUP_LAST = "router_backup_last_run"
CONFIG_BACKUP_KEEP = 20
CONFIG_BACKUP_RE = re.compile(r"^router-config-\d{14}\.(json|rsc)$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

_BACKUP_SECTIONS = [
    ("identity", "/system/identity"),
    ("resource", "/system/resource"),
    ("interface", "/interface"),
    ("wg", "/interface/wireguard"),
    ("wg_peers", "/interface/wireguard/peers"),
    ("l2tp_client", "/interface/l2tp-client"),
    ("address", "/ip/address"),
    ("route", "/ip/route"),
    ("dns", "/ip/dns"),
    ("service", "/ip/service"),
    ("firewall_filter", "/ip/firewall/filter"),
    ("firewall_mangle", "/ip/firewall/mangle"),
    ("firewall_nat", "/ip/firewall/nat"),
    ("address_list", "/ip/firewall/address-list"),
]


def _router_backup_dir() -> Path:
    p = settings.backups_dir / "router-configs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _prune_router_backups() -> None:
    for ext in (".json", ".rsc"):
        files = sorted(_router_backup_dir().glob(f"router-config-*{ext}"), reverse=True)
        for f in files[CONFIG_BACKUP_KEEP:]:
            try:
                f.unlink()
            except OSError:
                pass


def backup_router_config() -> Tuple[bool, str]:
    """Слепок основных секций конфига роутера в JSON (.json) + CLI-скрипт (.rsc)."""
    if not get_mt_config()["host"]:
        return False, "mikrotik not configured"
    data = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sections": {},
    }
    for key, path in _BACKUP_SECTIONS:
        code, res, err = _read_all(path)
        data["sections"][key] = res if code == 0 else {"error": err}
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    name_json = f"router-config-{stamp}.json"
    (_router_backup_dir() / name_json).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    name_rsc = f"router-config-{stamp}.rsc"
    (_router_backup_dir() / name_rsc).write_text(
        render_router_config_rsc(data["sections"]), encoding="utf-8"
    )
    _prune_router_backups()
    audit("router_config_backup", f"file={name_json},rsc={name_rsc}")
    return True, name_json


def list_router_backups() -> list:
    out = []
    for p in sorted(_router_backup_dir().glob("router-config-*.*"), reverse=True):
        if p.suffix not in (".json", ".rsc"):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        out.append(
            {
                "name": p.name,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return out


def get_router_backup(name: str) -> Tuple[bool, str]:
    name = Path(name).name
    if not CONFIG_BACKUP_RE.match(name):
        return False, "недопустимое имя бэкапа"
    p = _router_backup_dir() / name
    if not p.exists():
        return False, "бэкап не найден"
    return True, p.read_text(encoding="utf-8", errors="replace")


def get_router_backup_config() -> dict:
    return {
        "enabled": (get_setting(ROUTER_BACKUP_ENABLED, "0") or "0") == "1",
        "time": get_setting(ROUTER_BACKUP_TIME, "03:00") or "03:00",
        "last_run": get_setting(ROUTER_BACKUP_LAST, "") or "",
    }


def set_router_backup_config(data: dict) -> Tuple[bool, str]:
    time = (data.get("time") or "03:00").strip()
    if not _HHMM_RE.match(time):
        return False, "неверный формат времени (HH:MM)"
    set_setting(ROUTER_BACKUP_ENABLED, "1" if data.get("enabled") else "0")
    set_setting(ROUTER_BACKUP_TIME, time)
    audit("router_backup_cfg", f"enabled={bool(data.get('enabled'))} time={time}")
    return True, "saved"


# ===== Экспорт конфига роутера в формате RouterOS CLI (.rsc) =====

_RULE_FIELDS = (
    "action", "chain", "comment", "disabled",
    "connection-bytes", "connection-mark", "connection-nat-state", "connection-state",
    "content", "days", "dscp", "dst-address", "dst-address-list", "dst-address-type",
    "dst-port", "flow-account", "gateway", "hotspot", "icmp-options", "in-interface",
    "in-interface-list", "ipsec-interface", "ipsec-policy", "layer7-protocol", "limit",
    "log", "log-prefix", "new-connection-mark", "new-dscp", "new-packet-mark",
    "new-routing-mark", "out-interface", "out-interface-list", "packet-mark",
    "packet-size", "passthrough", "per-connection-classifier", "place-before",
    "priority", "protocol", "psd", "random", "src-address", "src-address-list",
    "src-address-type", "src-mac-address", "src-port", "tcp-flags", "tcp-mss", "time",
    "timeout", "to-addresses", "to-ports", "to-source-port", "target-scope",
)

_IFACE_PATHS = {
    "ether": "/interface ethernet",
    "bridge": "/interface bridge",
    "vlan": "/interface vlan",
    "pppoe-client": "/interface pppoe-client",
    "gre": "/interface gre",
    "vxlan": "/interface vxlan",
    "bonding": "/interface bonding",
    "veth": "/interface veth",
    "bridge-port": "/interface bridge port",
}

_WG_SAFE = ("name", "disabled", "comment", "mtu", "listen-port", "private-key")

_WG_PEER_SAFE = (
    "name", "interface", "disabled", "comment", "public-key", "preshared-key",
    "endpoint-address", "endpoint-port", "allowed-address", "client-address",
    "client-endpoint", "persistent-keepalive",
)

_L2TP_SAFE = (
    "name", "connect-to", "user", "password", "profile", "comment", "disabled",
    "max-mtu", "max-mru", "mrru", "keepalive-timeout", "allow", "ipsec-secret",
    "add-default-route", "dial-on-demand", "random-source-port",
)

_ROUTE_SAFE = (
    "dst-address", "gateway", "distance", "routing-table", "type", "scope",
    "target-scope", "comment", "disabled",
)

_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._/:@%+-]+$")


def _rsc_fmt(key: str, value) -> str:
    """Форматирует значение для RouterOS CLI: yes/no, числа и простые токены без кавычек."""
    s = str(value)
    if s in ("true", "false"):
        return "yes" if s == "true" else "no"
    if _NUM_RE.match(s) or _SAFE_TOKEN_RE.match(s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _rsc_rows(sections: dict, key: str) -> list:
    rows = sections.get(key) or []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _rsc_set_by_name(rows: list, fields) -> list:
    out = []
    for r in rows:
        parts = [f'name="{r.get("name", "")}"']
        for k in fields:
            if k == "name" or r.get(k) is None:
                continue
            parts.append(f"{k}={_rsc_fmt(k, r[k])}")
        if len(parts) > 1:
            out.append("set [ find where %s ] %s" % (parts[0], " ".join(parts[1:])))
    return out


def _rsc_adds(rows: list, fields) -> list:
    out = []
    for r in rows:
        parts = []
        for k in fields:
            if r.get(k) is None:
                continue
            parts.append(f"{k}={_rsc_fmt(k, r[k])}")
        if parts:
            out.append("add " + " ".join(parts))
    return out


def render_router_config_rsc(sections: dict) -> str:
    """Собирает .rsc из словаря секций (структура как в JSON-бэкапе)."""
    ap = []
    add = ap.append

    add("# ------------------------------------------------------------")
    add("# RouterOS config export")
    res = _rsc_rows(sections, "resource")
    if res:
        r = res[0]
        add(f"# Router: {r.get('board-name', '')} ({r.get('architecture-name', '')})")
        add(f"# RouterOS: {r.get('version', '')}")
    add(f"# Snapshot: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    add("# Generated by xray-gateway from REST snapshot (not a raw /export).")
    add("# Paste into a terminal to re-apply most settings; order follows router listing.")
    add("# ------------------------------------------------------------")
    add("")

    rows = _rsc_rows(sections, "identity")
    if rows and rows[0].get("name"):
        add("/system identity")
        add(f'set name="{rows[0]["name"]}"')
        add("")

    ifaces = [r for r in _rsc_rows(sections, "interface") if not _is_true(r.get("dynamic", "false"))]
    by_type = {}
    for r in ifaces:
        by_type.setdefault(r.get("type", ""), []).append(r)
    for itype, items in sorted(by_type.items()):
        if itype in ("wireguard", "wg", "l2tp-client", "l2tp-out"):
            continue
        add(_IFACE_PATHS.get(itype, f"/interface {itype}"))
        add("\n".join(_rsc_set_by_name(items, ("name", "disabled", "mtu", "comment"))))
        add("")

    rows = _rsc_rows(sections, "wg")
    if rows:
        add("/interface wireguard")
        add("\n".join(_rsc_set_by_name(rows, _WG_SAFE)))
        add("")

    rows = _rsc_rows(sections, "wg_peers")
    if rows:
        add("/interface wireguard peers")
        add("\n".join(_rsc_adds(rows, _WG_PEER_SAFE)))
        add("")

    rows = _rsc_rows(sections, "l2tp_client")
    if rows:
        add("/interface l2tp-client")
        add("\n".join(_rsc_adds(rows, _L2TP_SAFE)))
        add("")

    rows = [r for r in _rsc_rows(sections, "address") if not _is_true(r.get("dynamic", "false"))]
    if rows:
        add("/ip address")
        add("\n".join(_rsc_adds(rows, ("address", "interface", "comment", "disabled"))))
        add("")

    rows = [r for r in _rsc_rows(sections, "route") if _is_true(r.get("static", "false"))]
    if rows:
        add("/ip route")
        add("\n".join(_rsc_adds(rows, _ROUTE_SAFE)))
        add("")

    dns_rows = _rsc_rows(sections, "dns")
    if dns_rows:
        add("/ip dns")
        d = dns_rows[0]
        parts = []
        if d.get("servers"):
            parts.append(f'servers="{d["servers"]}"')
        if d.get("dynamic-servers"):
            parts.append(f'dynamic-servers="{d["dynamic-servers"]}"')
        if d.get("use-doh-server"):
            parts.append(f'use-doh-server="{d["use-doh-server"]}"')
        if d.get("verify-doh-certificate") is not None:
            parts.append(f"verify-doh-certificate={_rsc_fmt('verify-doh-certificate', d['verify-doh-certificate'])}")
        if d.get("allow-remote-requests") is not None:
            parts.append(f"allow-remote-requests={_rsc_fmt('allow-remote-requests', d['allow-remote-requests'])}")
        if parts:
            add("set " + " ".join(parts))
        add("")

    rows = _rsc_rows(sections, "service")
    if rows:
        add("/ip service")
        add("\n".join(_rsc_set_by_name(rows, ("name", "disabled", "port"))))
        add("")

    for key, menu in (
        ("firewall_filter", "/ip firewall filter"),
        ("firewall_mangle", "/ip firewall mangle"),
        ("firewall_nat", "/ip firewall nat"),
    ):
        rows = _rsc_rows(sections, key)
        if rows:
            add(menu)
            add("\n".join(_rsc_adds(rows, _RULE_FIELDS)))
            add("")

    rows = [r for r in _rsc_rows(sections, "address_list") if not _is_true(r.get("dynamic", "false"))]
    if rows:
        add("/ip firewall address-list")
        add("\n".join(_rsc_adds(rows, ("list", "address", "comment", "disabled", "timeout"))))
        add("")

    return "\n".join(ap)


def export_router_config() -> Tuple[bool, str]:
    """Собирает актуальный конфиг роутера в текст .rsc (без записи на диск)."""
    if not get_mt_config()["host"]:
        return False, "mikrotik not configured"
    sections = {}
    for key, path in _BACKUP_SECTIONS:
        code, res, err = _read_all(path)
        sections[key] = res if code == 0 else {"error": err}
    try:
        return True, render_router_config_rsc(sections)
    except Exception as e:  # noqa: BLE001
        return False, f"render failed: {e}"


CLIENT_VPN_KEY = "vpn_client_overrides"
CLIENT_RULE_PREFIX = "PC VIA VPN"


def _valid_ipv4(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return False
    return all(0 <= int(p) <= 255 for p in parts)


def _load_client_overrides() -> list:
    raw = get_setting(CLIENT_VPN_KEY, "[]") or "[]"
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save_client_overrides(items: list) -> None:
    set_setting(CLIENT_VPN_KEY, json.dumps(items))


def list_client_vpn() -> dict:
    """Список клиентских override-правил + фактическое состояние на роутере."""
    items = _load_client_overrides()
    code, rules, err = _read_all("/ip/firewall/mangle")
    status = {}
    if code == 0:
        for r in rules if isinstance(rules, list) else []:
            c = (r.get("comment") or "").strip()
            if c.startswith(CLIENT_RULE_PREFIX + " "):
                ip = c[len(CLIENT_RULE_PREFIX) + 1:].strip()
                status[ip] = {
                    "id": r.get(".id"),
                    "router_enabled": not _is_true(r.get("disabled")),
                }
    out = []
    for it in items:
        ip = it.get("ip", "")
        s = status.get(ip)
        out.append(
            {
                "ip": ip,
                "enabled": bool(it.get("enabled")),
                "on_router": s is not None,
                "router_enabled": s["router_enabled"] if s else None,
            }
        )
    return {"items": out, "error": "" if code == 0 else err, "ok": code == 0}


def _apply_client_vpn(ip: str, enabled: bool) -> Tuple[bool, str]:
    code, rules, err = _read_all("/ip/firewall/mangle")
    if code != 0:
        return False, err
    found = None
    for r in rules if isinstance(rules, list) else []:
        if ((r.get("comment") or "").strip()) == f"{CLIENT_RULE_PREFIX} {ip}":
            found = r
            break
    if found is None:
        if enabled:
            data = {
                "chain": "prerouting",
                "action": "mark-routing",
                "new-routing-mark": "mark_table_VPN",
                "src-address": ip,
                "dst-address-list": "!noVPN",
                "comment": f"{CLIENT_RULE_PREFIX} {ip}",
            }
            code, _, e = rest("/ip/firewall/mangle", method="PUT", data=data)
            if code != 0:
                return False, e
        return True, "noop"
    if enabled and _is_true(found.get("disabled")):
        code, _, e = rest(
            f"/ip/firewall/mangle/{found['.id']}", method="PATCH", data={"disabled": "false"}
        )
        if code != 0:
            return False, e
    elif not enabled and not _is_true(found.get("disabled")):
        code, _, e = rest(
            f"/ip/firewall/mangle/{found['.id']}", method="PATCH", data={"disabled": "true"}
        )
        if code != 0:
            return False, e
    return True, "ok"


def set_client_vpn(ip: str, enabled: bool) -> Tuple[bool, str]:
    ip = (ip or "").strip()
    if not _valid_ipv4(ip):
        return False, "укажите корректный IPv4-адрес клиента"
    items = _load_client_overrides()
    idx = next((i for i, x in enumerate(items) if x.get("ip") == ip), None)
    if idx is None:
        items.append({"ip": ip, "enabled": enabled})
    else:
        items[idx]["enabled"] = enabled
    _save_client_overrides(items)
    ok, msg = _apply_client_vpn(ip, enabled)
    if not ok:
        return False, msg
    audit("client_vpn", f"ip={ip} enabled={enabled}")
    return True, f"{ip}: {'в VPN' if enabled else 'вне VPN'}"


def delete_client_vpn(ip: str) -> Tuple[bool, str]:
    ip = (ip or "").strip()
    items = [x for x in _load_client_overrides() if x.get("ip") != ip]
    _save_client_overrides(items)
    code, rules, err = _read_all("/ip/firewall/mangle")
    if code == 0:
        for r in rules if isinstance(rules, list) else []:
            if ((r.get("comment") or "").strip()) == f"{CLIENT_RULE_PREFIX} {ip}":
                rest(f"/ip/firewall/mangle/{r['.id']}", method="DELETE")
    audit("client_vpn_del", f"ip={ip}")
    return True, "удалено"
