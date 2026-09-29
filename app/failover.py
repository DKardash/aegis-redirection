from typing import Dict, List, Optional, Tuple

from . import crud, healthcheck, xray
from .config import settings
from .db import audit, get_setting, set_setting

def get_active_server() -> Optional[dict]:
    active_id = get_setting(crud.ACTIVE_KEY)
    if not active_id:
        return None
    return crud.get_server(int(active_id))


def _enabled_servers() -> List[dict]:
    return [s for s in crud.list_servers() if s["enabled"]]


def _best_order(servers: List[dict]) -> List[dict]:
    def key(s):
        lat = s.get("best_latency_ms")
        return (0 if lat is not None else 1, lat if lat is not None else 0, s["priority"], s["id"])

    return sorted(servers, key=key)


def find_best(verbose: bool = False) -> Optional[dict]:
    """Лучший доступный сервер: enabled + TCP reachable, минимальная latency."""
    for s in _best_order(_enabled_servers()):
        ok, lat, err = healthcheck.tcp_check(s)
        if verbose:
            audit("best_probe", f"server={s['name']} tcp={ok} latency={lat}ms")
        if ok:
            return {**s, "probe_latency_ms": lat}
    return None


def activate_server(server_id: int) -> Tuple[bool, str]:
    server = crud.get_server(server_id)
    if not server:
        return False, "server not found"
    if not server["enabled"]:
        return False, "server disabled"

    try:
        # Переключение основного сервера не должно удалять отдельные PPP-профили.
        from . import profiles

        config = profiles.build_full_config(default_server=server)
    except ValueError as e:
        return False, str(e)

    ok, err = xray.apply_config(config)
    if not ok:
        audit("activate_failed", f"server={server['name']}: {err}")
        return False, err

    h_ok, latency, h_err = healthcheck.check_server(server)
    if not h_ok:
        prev = get_active_server()
        rollback_ok = True
        if prev and prev["id"] != server_id:
            rollback_ok, r_err = activate_server(prev["id"])
            audit(
                "rollback",
                f"from {server['name']} to {prev['name']}: {h_err or 'health failed'}",
            )
            return False, f"health failed ({h_err or 'no detail'}), rolled back"
        audit("activate_health_failed", f"server={server['name']}: {h_err or 'no detail'}")
        return False, f"health failed ({h_err or 'no detail'})"

    set_setting(crud.ACTIVE_KEY, str(server_id))
    audit("activate", f"server={server['name']} latency={latency}ms")
    try:
        from .monitor import EXPECTED_IP_KEY

        set_setting(EXPECTED_IP_KEY, "")
    except Exception:
        pass
    return True, f"active: {server['name']} ({latency}ms)"


def activate_best() -> Tuple[bool, str]:
    """Проверить всех, переключиться на лучшего (если текущий не лучший/упал)."""
    current = get_active_server()
    if current:
        ok, lat, err = healthcheck.check_server(current)
        if ok:
            best = find_best()
            if best and best["id"] == current["id"]:
                return True, f"active server OK and best: {current['name']} ({lat}ms)"
            if best and best.get("best_latency_ms") is not None:
                cur_lat = current.get("best_latency_ms")
                if cur_lat is not None and best["best_latency_ms"] >= cur_lat:
                    return True, f"active server OK (best is not better): {current['name']}"
            return True, f"active server OK: {current['name']} ({lat}ms)"

    best = find_best()
    if not best:
        ok, msg = activate_kill_switch()
        if ok:
            return True, msg
        return False, "failover: no reachable server, kill switch failed"

    ok, msg = activate_server(best["id"])
    if ok:
        return True, msg
    for s in _best_order([s for s in _enabled_servers() if s["id"] != best["id"]]):
        ok, msg = activate_server(s["id"])
        if ok:
            return True, msg
    ok, msg = activate_kill_switch()
    if ok:
        return True, msg
    return False, "failover: no healthy server, kill switch failed: " + msg


def activate_kill_switch() -> Tuple[bool, str]:
    cfg = xray.current_config() or {}
    if cfg:
        for rule in cfg.get("routing", {}).get("rules", []):
            # Kill switch относится к основному выходу. Профильные маршруты
            # продолжают работать через закреплённые за ними серверы.
            if not rule.get("inboundTag"):
                rule["outboundTag"] = "block"
        ok, err = xray.apply_config(cfg)
        if ok:
            set_setting(crud.ACTIVE_KEY, "")
            audit("kill_switch", "all servers down -> DROP")
            return True, "kill switch: selected traffic -> DROP"
        return False, err
    return False, "no current config"


def run_failover() -> str:
    ok, msg = activate_best()
    return msg
