import asyncio
import json
import subprocess
from typing import Dict, Optional, Tuple

from . import mikrotik, monitor, secret
from .config import settings
from .db import audit, get_setting, set_setting

ALERTS_ENABLED = "alerts_enabled"
ALERTS_INTERVAL = "alerts_interval"
ALERTS_AUTO_RESTART = "alerts_auto_restart"
ALERTS_TG_TOKEN = "alerts_tg_token"
ALERTS_TG_CHAT = "alerts_tg_chat"
ALERTS_DISK_THRESHOLD = "alerts_disk_threshold"
ALERTS_ROUTER_CPU = "alerts_router_cpu_threshold"
ALERTS_SOURCE_IP = "alerts_source_ip"
ALERTS_LAST = "alerts_last_state"

def source_ips():
    try:
        result = subprocess.run(['ip', '-j', '-4', 'address', 'show'], capture_output=True, text=True, timeout=5, check=True)
        return sorted({a['local'] for row in json.loads(result.stdout) for a in row.get('addr_info', []) if a.get('scope') == 'global'})
    except (OSError, ValueError, subprocess.SubprocessError):
        return []

DEFAULTS = {
    ALERTS_ENABLED: "0",
    ALERTS_INTERVAL: "60",
    ALERTS_AUTO_RESTART: "1",
    ALERTS_TG_TOKEN: "",
    ALERTS_TG_CHAT: "",
    ALERTS_DISK_THRESHOLD: "90",
    ALERTS_ROUTER_CPU: "90",
    ALERTS_SOURCE_IP: "",
}

# При сохранении значение с «…» (маской из GET) означает «не менять»:
# не перезаписываем секрет маской из формы.


def mask_token(token: str) -> str:
    if not token:
        return ""
    return token[:4] + "…" if len(token) > 6 else "…"


def mask_chat(chat: str) -> str:
    if not chat:
        return ""
    if len(chat) > 8:
        return chat[:4] + "…" + chat[-2:]
    if len(chat) > 2:
        return chat[:2] + "…"
    return "…"


def get_alerts_config() -> dict:
    return {
        "enabled": (get_setting(ALERTS_ENABLED, DEFAULTS[ALERTS_ENABLED]) or "0") == "1",
        "interval": int(get_setting(ALERTS_INTERVAL, DEFAULTS[ALERTS_INTERVAL]) or DEFAULTS[ALERTS_INTERVAL]),
        "auto_restart": (get_setting(ALERTS_AUTO_RESTART, DEFAULTS[ALERTS_AUTO_RESTART]) or "0") == "1",
        "tg_token": secret.decrypt(get_setting(ALERTS_TG_TOKEN, "") or "") or "",
        "tg_chat": secret.decrypt(get_setting(ALERTS_TG_CHAT, "") or "") or "",
        "disk_threshold": int(
            get_setting(ALERTS_DISK_THRESHOLD, DEFAULTS[ALERTS_DISK_THRESHOLD])
            or DEFAULTS[ALERTS_DISK_THRESHOLD]
        ),
        "router_cpu_threshold": int(
            get_setting(ALERTS_ROUTER_CPU, DEFAULTS[ALERTS_ROUTER_CPU])
            or DEFAULTS[ALERTS_ROUTER_CPU]
        ),
        "source_ip": get_setting(ALERTS_SOURCE_IP, DEFAULTS[ALERTS_SOURCE_IP])
        or DEFAULTS[ALERTS_SOURCE_IP],
    }


def set_alerts_config(data: dict) -> Tuple[bool, str]:
    interval = int(data.get("interval") or DEFAULTS[ALERTS_INTERVAL])
    interval = max(10, min(interval, 3600))
    threshold = int(data.get("disk_threshold") or DEFAULTS[ALERTS_DISK_THRESHOLD])
    threshold = max(1, min(threshold, 100))
    router_cpu = int(data.get("router_cpu_threshold") or DEFAULTS[ALERTS_ROUTER_CPU])
    router_cpu = max(1, min(router_cpu, 100))
    source_ip = (data.get("source_ip") or DEFAULTS[ALERTS_SOURCE_IP]).strip()
    if source_ip and source_ip not in source_ips():
        return False, "выбранный IP не назначен интерфейсу этой ВМ"
    set_setting(ALERTS_ENABLED, "1" if data.get("enabled") else "0")
    set_setting(ALERTS_INTERVAL, str(interval))
    set_setting(ALERTS_AUTO_RESTART, "1" if data.get("auto_restart") else "0")

    cur = get_alerts_config()
    token = (data.get("tg_token") or "").strip()
    if "…" in token:
        token = cur["tg_token"]
    chat = (data.get("tg_chat") or "").strip()
    if "…" in chat:
        chat = cur["tg_chat"]

    set_setting(ALERTS_TG_TOKEN, secret.encrypt(token))
    set_setting(ALERTS_TG_CHAT, secret.encrypt(chat))
    set_setting(ALERTS_DISK_THRESHOLD, str(threshold))
    set_setting(ALERTS_ROUTER_CPU, str(router_cpu))
    set_setting(ALERTS_SOURCE_IP, source_ip)
    audit(
        "alerts_config",
        f"enabled={data.get('enabled')} interval={interval}s "
        f"auto_restart={data.get('auto_restart')} source_ip={source_ip}",
    )
    return True, "saved"


def _tg_send(token: str, chat_id: str, text: str, source_ip: str = "") -> Tuple[bool, str]:
    if not token or not chat_id:
        return False, "telegram not configured"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    ).encode("utf-8")
    try:
        cmd = [
            "curl", "-4", "-sS", "--max-time", "12",
            "-H", "Content-Type: application/json", "--data-binary", "@-",
        ]
        if source_ip:
            cmd.extend(["--interface", source_ip])
        cmd.append(url)
        result = subprocess.run(cmd, input=payload, capture_output=True, timeout=15)
        if result.returncode != 0:
            return False, result.stderr.decode("utf-8", "replace").strip() or "curl error"
        body = json.loads(result.stdout.decode("utf-8"))
        if body.get("ok"):
            return True, "sent"
        return False, body.get("description", "telegram error")
    except Exception as e:  # noqa: BLE001
        return False, str(e)


async def send_telegram(text: str) -> Tuple[bool, str]:
    cfg = get_alerts_config()
    return await asyncio.to_thread(
        _tg_send, cfg["tg_token"], cfg["tg_chat"], text, cfg["source_ip"]
    )


def _tg_get(token: str, path: str, timeout: float = 12.0) -> Tuple[bool, object, str]:
    if not token:
        return False, {}, "telegram not configured"
    url = f"https://api.telegram.org/bot{token}/{path}"
    try:
        source_ip = get_alerts_config()["source_ip"]
        cmd = ["curl", "-4", "-sS", "--max-time", str(int(timeout))]
        if source_ip:
            cmd.extend(["--interface", source_ip])
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 3)
        if result.returncode != 0:
            return False, {}, result.stderr.decode("utf-8", "replace").strip() or "curl error"
        body = json.loads(result.stdout.decode("utf-8"))
        if body.get("ok"):
            return True, body.get("result") or {}, ""
        return False, {}, body.get("description", "telegram error")
    except Exception as e:  # noqa: BLE001
        return False, {}, str(e)


def tg_get_me(token: str) -> Tuple[bool, str]:
    """Проверка токена бота через getMe."""
    ok, res, err = _tg_get(token, "getMe")
    if not ok:
        return False, err or "telegram error"
    username = res.get("username", "") if isinstance(res, dict) else ""
    return True, f"@{username}" if username else "ok"


def tg_get_updates(token: str) -> Tuple[bool, list]:
    """Последние чаты, писавшие боту (для подбора chat_id получателя)."""
    ok, res, err = _tg_get(token, "getUpdates?timeout=0")
    if not ok:
        return False, err or "telegram error"
    chats: Dict[int, dict] = {}
    for u in res if isinstance(res, list) else []:
        msg = (u.get("message") or u.get("edited_message") or {}) if isinstance(u, dict) else {}
        c = msg.get("chat") or {}
        cid = c.get("id")
        if cid is None:
            continue
        name = c.get("title") or c.get("username") or c.get("first_name") or ""
        chats[cid] = {"chat_id": cid, "type": c.get("type", ""), "name": name}
    return True, list(chats.values())


def _get_state() -> dict:
    raw = get_setting(ALERTS_LAST) or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _set_state(state: dict) -> None:
    set_setting(ALERTS_LAST, json.dumps(state))


async def _notify(title: str, body: str) -> None:
    text = f"{title}\n{body}"
    ok, err = await send_telegram(text)
    audit("alert", f"{title}: {body}" if ok else f"{title}: tg send failed ({err})")


async def _run_checks() -> list:
    problems = []

    tunnel = await asyncio.to_thread(monitor.check_tunnel)
    if not tunnel["ok"]:
        detail = tunnel.get("error") or "tunnel check failed"
        problems.append(f"TUNNEL: {detail}")
    else:
        problems.append(f"TUNNEL_OK ip={tunnel.get('ip')} latency={tunnel.get('latency_ms')}ms")

    services = await asyncio.to_thread(monitor.read_services)
    if services.get("xl2tpd") != "active" and get_alerts_config()["auto_restart"]:
        await asyncio.to_thread(monitor.restart_tunnel)
        services = await asyncio.to_thread(monitor.read_services)
    for unit, state in services.items():
        if state != "active":
            problems.append(f"SERVICE: {unit} = {state}")
    problems.append("SERVICES_OK")

    sysinfo = await asyncio.to_thread(monitor.read_system)
    disk = sysinfo["disk"]
    threshold = get_alerts_config()["disk_threshold"]
    if disk["total"]:
        pct = round(disk["used"] / disk["total"] * 100, 1)
        if pct >= threshold:
            problems.append(f"DISK: {pct}% used (threshold {threshold}%)")
        else:
            problems.append(f"DISK_OK {pct}%")

    if mikrotik.get_mt_config()["host"]:
        router_cpu = get_alerts_config()["router_cpu_threshold"]
        code, res, err = await asyncio.to_thread(
            mikrotik.rest, "/system/resource", "GET", None, 6
        )
        if code != 0:
            problems.append(f"ROUTER: {err or 'недоступен'}")
        else:
            cpu = res.get("cpu-load") if isinstance(res, dict) else None
            if cpu is not None and int(cpu) >= router_cpu:
                problems.append(f"ROUTER_CPU: {cpu}% (threshold {router_cpu}%)")
            else:
                problems.append(f"ROUTER_OK cpu={cpu}%")
    else:
        problems.append("ROUTER_SKIP (не настроен)")
    return problems


async def watchdog_tick() -> list:
    cfg = get_alerts_config()
    if not cfg["enabled"]:
        return []
    if not cfg["tg_token"] or not cfg["tg_chat"]:
        audit("alert", "watchdog: enabled but telegram not configured")
        return []

    checks = await _run_checks()
    failing = [c for c in checks if not c.split(" ", 1)[0].endswith(("_OK", "_SKIP"))]
    previous = _get_state()
    now = "OK" if not failing else "FAIL"

    changed = previous.get("state") != now
    previous["state"] = now
    previous["ts"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    _set_state(previous)

    if changed:
        if failing:
            await _notify("VPN gateway: problem", "\n".join(failing))
        else:
            await _notify("VPN gateway: recovered", "all checks OK")
    return checks


async def watchdog_loop() -> None:
    while True:
        try:
            await watchdog_tick()
        except Exception as e:  # noqa: BLE001
            audit("alert", f"watchdog error: {e}")
        cfg = get_alerts_config()
        await asyncio.sleep(cfg["interval"] if cfg["enabled"] else 30)
