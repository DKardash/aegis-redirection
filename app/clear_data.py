import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from . import addresslists, db, l2tp, wireguard
from .config import settings
from .crud import ACTIVE_KEY

RETENTION_KEY = "backup_retention_days"
RETENTION_DEFAULT = 10

DEFAULT_LISTS_RSC = (
    "# =====================================================================\n"
    "#  MikroTik VPN address-lists (пресет очищен)\n"
    "# =====================================================================\n"
    "/ip firewall address-list\n\n"
)

SECTIONS: List[dict] = [
    {"name": "backups", "label": "Бэкапы", "danger": False,
     "desc": "Все бэкапы: адрес-листов, конфига роутера, конфигов Xray"},
    {"name": "servers", "label": "Серверы", "danger": True,
     "desc": "Список серверов + история проверок (активный сервер сбросится)"},
    {"name": "lists", "label": "Адрес-листы (пресет)", "danger": False,
     "desc": "Сбросить пресет .rsc в пустой шаблон"},
    {"name": "audit", "label": "Журнал действий", "danger": False,
     "desc": "Очистить журнал (audit_log)"},
    {"name": "traffic", "label": "История трафика", "danger": False,
     "desc": "Сэмплы трафика за всё время"},
    {"name": "wg_peers", "label": "Пиры WireGuard", "danger": True,
     "desc": "Удалить всех пиров из wg0.conf (с бэкапом и перезапуском сервиса)"},
    {"name": "l2tp_users", "label": "Пользователи L2TP", "danger": True,
     "desc": "Удалить всех пользователей L2TP (с бэкапом)"},
]


def _age_days(path: Path) -> float:
    return (datetime.now().timestamp() - path.stat().st_mtime) / 86400.0


def list_backup_files() -> List[Path]:
    """Все файлы бэкапов: адрес-листы, роутер, конфиги Xray."""
    files: List[Path] = []
    for p in addresslists.LISTS_FILE.parent.glob("mikrotik-vpn-lists.rsc.bak-*"):
        files.append(p)
    router_dir = settings.backups_dir / "router-configs"
    if router_dir.exists():
        for p in router_dir.glob("router-config-*"):
            files.append(p)
    for p in settings.backups_dir.glob("config.*.json"):
        files.append(p)
    return files


def _delete_older_than(path: Path, days: float) -> bool:
    try:
        if path.is_file() and _age_days(path) >= days:
            path.unlink()
            return True
    except OSError:
        pass
    return False


def cleanup_backups(days: int) -> Dict[str, int]:
    """Удаляет бэкапы старше N дней. Возвращает количество удалённых."""
    removed = 0
    for p in list_backup_files():
        if _delete_older_than(p, days):
            removed += 1
    return {"days": days, "removed": removed}


def get_retention_days() -> int:
    try:
        return int(db.get_setting(RETENTION_KEY, str(RETENTION_DEFAULT)) or RETENTION_DEFAULT)
    except ValueError:
        return RETENTION_DEFAULT


def set_retention_days(days: int) -> Tuple[bool, str]:
    if not (1 <= days <= 365):
        return False, "неверное значение (1..365 дней)"
    db.set_setting(RETENTION_KEY, str(days))
    db.audit("backup_retention", f"days={days}")
    return True, "saved"


def clear_section(name: str) -> dict:
    """Очистка одного раздела данных. Возвращает результат для отчёта."""
    if name == "backups":
        removed = 0
        for p in list_backup_files():
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        db.audit("clear_data_backups", f"removed={removed}")
        return {"ok": True, "removed": removed}

    if name == "servers":
        with db.db() as conn:
            servers = conn.execute("SELECT COUNT(*) AS c FROM servers").fetchone()["c"]
            conn.execute("DELETE FROM servers")
            conn.execute("DELETE FROM health_checks")
        db.set_setting(ACTIVE_KEY, "")
        db.audit("clear_data_servers", f"servers={servers}")
        return {"ok": True, "servers": servers}

    if name == "lists":
        addresslists.LISTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if addresslists.LISTS_FILE.exists():
            addresslists.make_backup()
        addresslists.LISTS_FILE.write_text(DEFAULT_LISTS_RSC, encoding="utf-8")
        db.audit("clear_data_lists", "preset reset")
        return {"ok": True}

    if name == "audit":
        with db.db() as conn:
            conn.execute("DELETE FROM audit_log")
        db.audit("clear_data_audit", "journal cleared")
        return {"ok": True}

    if name == "traffic":
        with db.db() as conn:
            conn.execute("DELETE FROM traffic_samples")
        db.audit("clear_data_traffic", "samples cleared")
        return {"ok": True}

    if name == "wg_peers":
        if not wireguard.WG_CONF.exists():
            return {"ok": False, "skipped": "wg0.conf не найден"}
        cfg = wireguard.parse_conf()
        count = len(cfg.get("peers", []))
        cfg["peers"] = []
        ok, err = wireguard.apply_config(cfg)
        db.audit("clear_data_wg_peers", f"peers={count} ok={ok}")
        return {"ok": ok, "peers": count, "error": "" if ok else err}

    if name == "l2tp_users":
        if not l2tp.CHAP_SECRETS.exists():
            return {"ok": False, "skipped": "chap-secrets не найден"}
        users = [u["username"] for u in l2tp.list_users()]
        for username in users:
            l2tp.delete_user(username)
        db.audit("clear_data_l2tp_users", f"users={len(users)}")
        return {"ok": True, "users": len(users)}

    return {"ok": False, "error": f"unknown section: {name}"}
