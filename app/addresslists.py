import concurrent.futures
import hashlib
import json
import re
import shutil
import socket
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import mikrotik
from .db import audit, get_setting, set_setting

LISTS_FILE = Path(__file__).resolve().parent.parent / "web" / "static" / "mikrotik-vpn-lists.rsc"
ALLOWED_LISTS = ("TELEGRAM_DNS", "DISCORD_DNS", "PUBG_DNS")
BACKUP_KEEP = 20
_BACKUP_RE = re.compile(r"^mikrotik-vpn-lists\.rsc\.bak-\d{14}$")

AUTO_SYNC_ENABLED = "auto_sync_enabled"
AUTO_SYNC_TIME = "auto_sync_time"
AUTO_SYNC_LAST = "auto_sync_last_run"
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Пуш на слабый роутер (mipsbe, CPU 100%): батчи по 25 записей,
# 2 параллельных REST-запроса, до 5 попыток с растущей паузой.
# Параллелизм снижен с 4 до 2: на загруженном роутере больше одновременных
# запросов = больше таймаутов и ретраев (и деградация его DNS).
_PUSH_BATCH = 25
_PUSH_WORKERS = 2
_PUSH_RETRY = 5
_PUSH_PAUSE = 1.0

# Кэш DNS-резолва: желаемый набор IP должен быть стабильным между прогонами
# синка, иначе CDN-дрейф заставляет каждый прогон пересоздавать записи
# (удалить ~200 старых IP и добавить ~200 новых) и синк никогда не сходится.
# Снапшот пересоздаётся, если .rsc изменился или истёк TTL.
RESOLVE_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "resolve_cache.json"
RESOLVE_CACHE_TTL = 24 * 3600

# Максимум итераций verify-цикла: применить дифф, перечитать роутер с тем же
# снапшотом, добить остаток — пока diff не станет нулевым.
SYNC_MAX_ROUNDS = 3

# Порог «стабильного» снапшота: доля FQDN с положительным резолвом ИЛИ
# авторитетным отрицательным ответом (NXDOMAIN/NODATA) должна быть >= порога.
# NXDOMAIN/NODATA стабильны между прогонами — они не «портят» снапшот. Ниже
# порога свежий снапшот не сохраняется и синк откатывается к прошлому (стейл)
# снапшоту, чтобы транзиентный DNS-сбой не «удалял» записи живых доменов.
_RESOLVE_STABLE_MIN = 0.95

_CIDR_IP_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+(/\d+)?$")

_JOB_LOCK = threading.Lock()
_SYNC_JOB = {
    "running": False,
    "started": None,
    "finished": None,
    "ok": None,
    "message": "",
    "phase": "idle",
    "progress": 0.0,
    "removed": 0,
    "added": 0,
    "failed": 0,
    "total_remove": 0,
    "total_add": 0,
    "rounds": 0,
}


def _job_update(**kw) -> None:
    with _JOB_LOCK:
        _SYNC_JOB.update(kw)


def get_auto_sync_status() -> dict:
    with _JOB_LOCK:
        return dict(_SYNC_JOB)


def read_raw() -> str:
    if not LISTS_FILE.exists():
        return ""
    return LISTS_FILE.read_text(encoding="utf-8", errors="replace")


def _prune_backups() -> None:
    backups = sorted(LISTS_FILE.parent.glob("mikrotik-vpn-lists.rsc.bak-*"), reverse=True)
    for p in backups[BACKUP_KEEP:]:
        try:
            p.unlink()
        except OSError:
            pass


def make_backup() -> Optional[str]:
    """Создаёт именованный бэкап текущего .rsc (оставляет до BACKUP_KEEP штук)."""
    if not LISTS_FILE.exists():
        return None
    name = f"{LISTS_FILE.name}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        shutil.copy2(LISTS_FILE, LISTS_FILE.parent / name)
    except OSError:
        return None
    _prune_backups()
    return name


def list_backups() -> List[dict]:
    out = []
    for p in sorted(LISTS_FILE.parent.glob("mikrotik-vpn-lists.rsc.bak-*"), reverse=True):
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


def get_backup(name: str) -> Tuple[bool, str]:
    name = Path(name).name
    if not _BACKUP_RE.match(name):
        return False, "недопустимое имя бэкапа"
    p = LISTS_FILE.parent / name
    if not p.exists():
        return False, "бэкап не найден"
    return True, p.read_text(encoding="utf-8", errors="replace")


def restore_backup(name: str) -> Tuple[bool, str]:
    ok, text = get_backup(name)
    if not ok:
        return ok, text
    ok, error = save_raw(text)
    if not ok:
        return False, error
    audit("addresslists_restore", f"backup={name}")
    return True, "восстановлено из " + name


def save_raw(text: str) -> Tuple[bool, str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not text.strip():
        return False, "empty content"
    try:
        groups = parse_rsc(text)
    except ValueError as exc:
        return False, str(exc)
    if not groups:
        return False, "Нет записей адрес-листов"
    text = build_ip_rsc(groups)
    if LISTS_FILE.exists():
        make_backup()
    LISTS_FILE.write_text(text + "\n", encoding="utf-8")
    audit(
        "addresslists_save",
        f"lines={len(text.splitlines())} size={len(text)}",
    )
    return True, "saved"


def parse_rsc(text: str) -> List[dict]:
    """RouterOS export: any property order, wrapped lines, disabled flags."""
    import shlex
    groups = {}
    text = re.sub(r"\\\r?\n\s*", "", text)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line == "/ip firewall address-list":
            continue
        words = shlex.split(line)
        if not words or words[0] != "add":
            raise ValueError("Допустимы только записи add в /ip firewall address-list")
        entry = dict(word.split("=", 1) for word in words[1:] if "=" in word)
        name = entry.get("list")
        if not name or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name) or not entry.get("address"):
            raise ValueError("Укажите адрес и корректное имя списка (буквы, цифры, _, -, .)")
        group = groups.setdefault(name, {"title": name, "entries": [], "count": 0})
        group["entries"].append({"list": name, "address": entry["address"], "comment": entry.get("comment", ""), "disabled": entry.get("disabled", "no") in ("yes", "true")})
        group["count"] += 1
    return list(groups.values())


def parse_groups() -> List[dict]:
    if not LISTS_FILE.exists():
        return []
    return parse_rsc(LISTS_FILE.read_text(encoding="utf-8", errors="replace"))


def _resolve(host: str, timeout: float = 4.0):
    """Возвращает (ips, err). err=None при успехе; err='stable' для авторитетного
    отрицательного ответа (NXDOMAIN/NODATA — стабилен между прогонами);
    err='transient' для таймаутов/EAI_AGAIN/прочих сбоев (может меняться)."""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as e:
        if e.errno in (socket.EAI_NONAME, socket.EAI_NODATA, socket.EAI_ADDRFAMILY):
            return [], "stable"
        return [], "transient"
    except OSError:
        return [], "transient"
    ips = []
    seen = set()
    for info in infos:
        ip = info[4][0]
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)
        if len(ips) >= 8:
            break
    return ips, (None if ips else "transient")


def _rsc_hash() -> str:
    if not LISTS_FILE.exists():
        return ""
    return hashlib.sha256(LISTS_FILE.read_bytes()).hexdigest()


def _stable_ratio(groups: List[dict]) -> float:
    """Доля FQDN со стабильным ответом: есть ips ИЛИ авторитетный отрицательный
    (NXDOMAIN/NODATA). IP/CIDR-литералы не считаются нужными. Транзиентные сбои
    (таймаут, EAI_AGAIN) понижают ratio — снапшот с ними не закрепляется."""
    need = 0
    ok = 0
    for g in groups:
        for e in g["entries"]:
            if _CIDR_IP_RE.match(e.get("address", "")):
                continue
            need += 1
            if e.get("ips") or e.get("resolve_err") == "stable":
                ok += 1
    return (ok / need) if need else 1.0


def _annotate_resolved(groups: List[dict]) -> None:
    """Проставляет resolved/failed по ips (нужно и для свежего резолва, и для кэша).
    IP/CIDR-литералы считаются resolved — им резолв не нужен."""
    for g in groups:
        resolved = 0
        for e in g["entries"]:
            literal = bool(_CIDR_IP_RE.match(e.get("address", "")))
            ips = e.get("ips")
            if not isinstance(ips, list):
                ips = [] if literal else []
                e["ips"] = ips
            e["resolved"] = literal or bool(ips)
            resolved += 1 if e["resolved"] else 0
        g["resolved"] = resolved
        g["failed"] = g["count"] - resolved


def _load_resolve_cache(hashval: str, ignore_ttl: bool = False) -> Optional[List[dict]]:
    if not hashval:
        return None
    try:
        data = json.loads(RESOLVE_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("hash") != hashval:
        return None
    created = data.get("created") or ""
    age = RESOLVE_CACHE_TTL + 1
    if created:
        try:
            age = time.time() - datetime.fromisoformat(created).timestamp()
        except ValueError:
            age = RESOLVE_CACHE_TTL + 1
    if not ignore_ttl and age > RESOLVE_CACHE_TTL:
        return None
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        return None
    _annotate_resolved(groups)
    return groups


def _save_resolve_cache(hashval: str, groups: List[dict]) -> None:
    if not hashval or not groups:
        return
    if _stable_ratio(groups) < _RESOLVE_STABLE_MIN:
        # Много транзиентных сбоев — не фиксируем нестабильный снапшот, чтобы не
        # «удалить» на роутере записи временно нерезолвящихся доменов.
        return
    try:
        RESOLVE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "hash": hashval,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "groups": groups,
        }
        tmp = RESOLVE_CACHE_FILE.with_name(RESOLVE_CACHE_FILE.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(RESOLVE_CACHE_FILE)
    except OSError:
        pass


def resolve_groups(max_workers: int = 16, use_cache: bool = True) -> List[dict]:
    groups = parse_groups()
    if not groups:
        return []

    hashval = _rsc_hash()
    if use_cache:
        cached = _load_resolve_cache(hashval)
        if cached is not None:
            return cached

    tasks = {}
    futures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for gi, g in enumerate(groups):
            for ei, e in enumerate(g["entries"]):
                if not _CIDR_IP_RE.match(e["address"]):
                    f = ex.submit(_resolve, e["address"])
                    tasks[f] = (gi, ei)
                    futures.append(f)
        for f in concurrent.futures.as_completed(futures):
            gi, ei = tasks[f]
            ips, err = f.result()
            groups[gi]["entries"][ei]["ips"] = ips
            if err:
                groups[gi]["entries"][ei]["resolve_err"] = err

    for g in groups:
        for e in g["entries"]:
            if e.get("ips") is None:
                e["ips"] = [] if _CIDR_IP_RE.match(e["address"]) else []
    _annotate_resolved(groups)

    if _stable_ratio(groups) >= _RESOLVE_STABLE_MIN:
        _save_resolve_cache(hashval, groups)
        return groups
    if use_cache:
        # Много транзиентных сбоев: возвращаем прошлый снапшот, чтобы не менять
        # желаемый набор между прогонами (источник «бесконечного» синка).
        stale = _load_resolve_cache(hashval, ignore_ttl=True)
        if stale is not None:
            return stale
    return groups


def _entry_line(entry: dict, address: str) -> str:
    comment = entry.get("comment", "").replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return f'add list={entry["list"]} comment="{comment}" address={address} disabled={"yes" if entry.get("disabled") else "no"}'


def build_ip_rsc(groups: List[dict]) -> str:
    out = []
    for gi, g in enumerate(groups, start=1):
        out.append(f"# ==================== {gi}. {g['title']} ====================")
        out.append("/ip firewall address-list")
        for e in g["entries"]:
            ips = e.get("ips") or []
            comment = e.get("comment", "")
            if ips:
                for ip in ips:
                    out.append(
                        _entry_line(e, ip)
                    )
            else:
                out.append(
                    _entry_line(e, e["address"])
                )
        out.append("")
    return "\n".join(out)


def build_sync_script(groups: List[dict]) -> str:
    out = [
        "# ============================================================",
        "# MikroTik sync script (vpn-lists)",
        "# Обновляет TELEGRAM_DNS, DISCORD_DNS и PUBG_DNS",
        "# (домены, которые не резолвятся здесь, роутер дорезолвит сам).",
        "# Вставьте ВЕСЬ блок в терминал RouterOS.",
        "# ============================================================",
    ]
    lists: Dict[str, List[dict]] = {}
    prefixes: Dict[str, set] = {}
    for g in groups:
        for e in g["entries"]:
            lst = e["list"]
            lists.setdefault(lst, []).append(e)
            cm = re.match(r"^([A-Za-z0-9_]+):", e.get("comment", ""))
            if cm:
                prefixes.setdefault(lst, set()).add(cm.group(1))
    for lst, entries in lists.items():
        if not entries:
            continue
        cond = " or ".join(
            f'comment~"^{p}"' for p in sorted(prefixes.get(lst, set()))
        )
        if cond:
            out.append(f'/ip firewall address-list remove [find where list={lst} and ({cond})]')
        else:
            out.append(f'/ip firewall address-list remove [find where list={lst}]')
        out.append("/ip firewall address-list")
        for e in entries:
            ips = e.get("ips") or []
            comment = e.get("comment", "")
            if ips:
                for ip in ips:
                    out.append(
                        _entry_line(e, ip)
                    )
            else:
                out.append(
                    _entry_line(e, e["address"])
                )
        out.append("")
    return "\n".join(out)


def _norm_addr(address: str) -> str:
    """Нормализация адреса для сравнения ('1.2.3.4/32' == '1.2.3.4')."""
    a = (address or "").strip()
    if a.lower().endswith("/32"):
        a = a[:-3]
    return a


def _plan_push(groups: List[dict]) -> dict:
    """Читает текущие записи роутера и считает diff: что удалить (устаревшее
    пресета) и что добавить (недостающее). Без записи на роутер."""
    code, existing, err = mikrotik.rest("/ip/firewall/address-list")
    if code != 0:
        return {"ok": False, "error": err}
    existing = existing if isinstance(existing, list) else ([existing] if isinstance(existing, dict) else [])

    lists: Dict[str, List[dict]] = {}
    prefixes: Dict[str, set] = {}
    desired: List[dict] = []
    for g in groups:
        for e in g["entries"]:
            lst = e["list"]
            lists.setdefault(lst, []).append(e)
            cm = re.match(r"^([A-Za-z0-9_]+):", e.get("comment", ""))
            if cm:
                prefixes.setdefault(lst, set()).add(cm.group(1))
            ips = e.get("ips") or []
            if _CIDR_IP_RE.match(e["address"]):
                addrs = [e["address"]]
            elif ips:
                addrs = ips
            else:
                # FQDN без ips (NXDOMAIN/NODATA) в desired не попадает —
                # иначе «пустые добавить/удалить» и бесконечный синк.
                addrs = [e["address"]]
            for a in addrs:
                desired.append({"list": lst, "comment": e.get("comment", ""), "address": a, "disabled": "true" if e.get("disabled") else "false"})

    def key(row):
        return (_norm_addr(row.get("address", "")), row.get("list"), str(row.get("disabled", "false")).lower() in ("true", "yes"))
    desired_present = {key(a) for a in desired}
    present = {key(r) for r in existing if str(r.get("dynamic", "false")).lower() not in ("true", "yes")}

    to_remove = []
    for r in existing:
        lst = r.get("list")
        if lst not in lists:
            continue
        if str(r.get("dynamic", "false")).lower() in ("true", "yes"):
            continue
        if key(r) not in desired_present:
            to_remove.append(r)

    additions = []
    seen_add = set()
    for a in desired:
        identity = key(a)
        if identity in seen_add:
            continue
        seen_add.add(identity)
        if identity not in present:
            additions.append(a)

    return {"ok": True, "to_remove": to_remove, "additions": additions, "lists": lists}


def preview_push(groups: List[dict]) -> dict:
    """Предпросмотр apply: сколько удалить/добавить по каждому листу и сам diff."""
    plan = _plan_push(groups)
    if not plan["ok"]:
        return {
            "ok": False,
            "error": plan["error"],
            "remove": 0,
            "add": 0,
            "lists": [],
            "adds": [],
            "removes": [],
        }
    by_list: Dict[str, List[int]] = {}
    for r in plan["to_remove"]:
        lst = r.get("list")
        by_list.setdefault(lst, [0, 0])[0] += 1
    for a in plan["additions"]:
        by_list.setdefault(a["list"], [0, 0])[1] += 1
    return {
        "ok": True,
        "remove": len(plan["to_remove"]),
        "add": len(plan["additions"]),
        "lists": [{"list": k, "remove": v[0], "add": v[1]} for k, v in sorted(by_list.items())],
        "adds": [
            {"list": a["list"], "comment": a["comment"], "address": a["address"]}
            for a in plan["additions"]
        ],
        "removes": [
            {"list": r.get("list", ""), "comment": r.get("comment", ""), "address": r.get("address", "")}
            for r in plan["to_remove"]
        ],
    }


def _rest_retry(
    method: str, path: str, data: object = None, timeout: float = 10.0
) -> Tuple[int, object, str]:
    """REST-запрос с ретраями: слабый роутер отдаёт временные 401/таймауты."""
    last_err = ""
    last_code = 1
    for attempt in range(_PUSH_RETRY):
        last_code, res, err = mikrotik.rest(path, method=method, data=data, timeout=timeout)
        if last_code == 0:
            return last_code, res, ""
        last_err = err or f"code {last_code}"
        time.sleep(min(0.5 * (attempt + 1), 4.0))
    return last_code, res, last_err


def _verify_addr(payload: dict) -> bool:
    """Проверка, что запись (list, address) реально есть на роутере.
    Используется для идемпотентности: ошибка может быть из-за того, что
    запись уже добавили (дубль/потерянный ответ), а не из-за сбоя."""
    q = f"?list={urllib.parse.quote(payload['list'])}&address={urllib.parse.quote(payload['address'])}"
    code, res, _ = mikrotik.rest(f"/ip/firewall/address-list{q}", timeout=8.0)
    return code == 0 and bool(res)


def _push_worker(op: str, payload: dict) -> Tuple[bool, str]:
    if op == "remove":
        code, _, e = _rest_retry("DELETE", f"/ip/firewall/address-list/{payload['.id']}")
        if code == 0:
            return True, ""
        _, chk, _ = mikrotik.rest(f"/ip/firewall/address-list/{payload['.id']}", timeout=8.0)
        if chk is None:
            return True, ""
        return False, e
    code, _, e = _rest_retry(
        "PUT",
        "/ip/firewall/address-list",
        {"list": payload["list"], "comment": payload["comment"], "address": payload["address"], "disabled": payload.get("disabled", "false")},
    )
    if code == 0:
        return True, ""
    if _verify_addr(payload):
        return True, ""
    return False, e


def _apply_batch(
    items: List[dict], phase: str, report: Optional[Callable[[str, int, int, int], None]]
) -> Tuple[int, List[str]]:
    """Применяет список операций батчами по _PUSH_BATCH с ограниченным
    параллелизмом и паузой между батчами (не давим CPU роутера)."""
    ok_count = 0
    errors: List[str] = []
    done = 0
    total = len(items)
    for start in range(0, total, _PUSH_BATCH):
        chunk = items[start:start + _PUSH_BATCH]
        with concurrent.futures.ThreadPoolExecutor(max_workers=_PUSH_WORKERS) as ex:
            futures = {ex.submit(_push_worker, it["op"], it["payload"]): it for it in chunk}
            for f in concurrent.futures.as_completed(futures):
                it = futures[f]
                ok, err = f.result()
                done += 1
                if ok:
                    ok_count += 1
                else:
                    addr = it["payload"].get("address", "?")
                    errors.append(f"{addr}: {err or 'err'}")
        if report:
            report(phase, done, total, len(errors))
        if total - done > _PUSH_BATCH:
            time.sleep(_PUSH_PAUSE)
    return ok_count, errors


def push_to_mikrotik(
    groups: List[dict], report: Optional[Callable[[str, int, int], None]] = None
) -> Tuple[bool, str]:
    """Применить пресет адрес-листов прямо на MikroTik через REST API.

    Diff-инкремент: удаляет только устаревшие записи пресета, добавляет только
    недостающие. Батчинг + ретраи рассчитаны на слабый роутер.
    """
    plan = _plan_push(groups)
    if not plan["ok"]:
        return False, f"mikrotik: {plan['error'] or 'address-list read failed'}"

    to_remove = plan["to_remove"]
    additions = plan["additions"]

    removed = added = 0
    failed: List[str] = []

    if to_remove:
        removed, errs = _apply_batch([{"op": "remove", "payload": r} for r in to_remove], "remove", report)
        failed += errs
    if additions:
        time.sleep(_PUSH_PAUSE)
        added, errs = _apply_batch([{"op": "add", "payload": a} for a in additions], "add", report)
        failed += errs

    audit("addresslists_apply", f"removed={removed} added={added} failed={len(failed)}")
    if failed:
        return False, f"added {added}, removed {removed}; errors: {'; '.join(failed[:3])}"
    return True, f"applied: added {added}, removed {removed}"


def get_auto_sync_config() -> dict:
    return {
        "enabled": (get_setting(AUTO_SYNC_ENABLED, "0") or "0") == "1",
        "time": get_setting(AUTO_SYNC_TIME, "04:00") or "04:00",
        "last_run": get_setting(AUTO_SYNC_LAST, "") or "",
    }


def set_auto_sync_config(data: dict) -> Tuple[bool, str]:
    time = (data.get("time") or "04:00").strip()
    if not _HHMM_RE.match(time):
        return False, "неверный формат времени (HH:MM)"
    set_setting(AUTO_SYNC_ENABLED, "1" if data.get("enabled") else "0")
    set_setting(AUTO_SYNC_TIME, time)
    audit("addresslists_auto_sync_cfg", f"enabled={bool(data.get('enabled'))} time={time}")
    return True, "saved"


def run_auto_sync() -> Tuple[bool, str]:
    """Пересобрать листы (резолв доменов) и применить изменения на роутер.

    Снапшот резолва кэшируется, поэтому желаемый набор стабилен между
    прогонами. После применения диффа идёт verify-цикл: план перечитывается
    с тем же снапшотом, и остаток добивается (до SYNC_MAX_ROUNDS) — так синк
    доводится до сходимости, а не пересоздаёт записи от DNS-дрейфа каждый раз.
    """
    _job_update(
        running=True,
        started=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        finished=None,
        ok=None,
        message="",
        phase="resolve",
        progress=0.0,
        removed=0,
        added=0,
        failed=0,
        total_remove=0,
        total_add=0,
        rounds=0,
    )
    try:
        groups = resolve_groups()
        if not groups:
            return _finish_job(False, "нет групп для синхронизации")

        removed_total = added_total = failed_total = 0
        for round_num in range(1, SYNC_MAX_ROUNDS + 1):
            _job_update(phase="resolve", rounds=round_num)
            plan = _plan_push(groups)
            if not plan["ok"]:
                return _finish_job(False, plan["error"] or "mikrotik address-list read failed")
            if not plan["to_remove"] and not plan["additions"]:
                if round_num == 1:
                    audit("addresslists_auto_sync", "no changes")
                    return _finish_job(True, "uptodate: изменений нет")
                msg = f"converged: removed {removed_total}, added {added_total}"
                audit("addresslists_auto_sync", msg)
                return _finish_job(True, msg)

            total_remove = len(plan["to_remove"])
            total_add = len(plan["additions"])
            _job_update(phase="push", total_remove=total_remove, total_add=total_add)

            state = {
                "phase": None,
                "phase_failed": 0,
                "base_removed": removed_total,
                "base_added": added_total,
                "failed": failed_total,
            }

            def report(phase: str, done: int, total: int, failed: int) -> None:
                if phase == "remove":
                    state["removed"] = state["base_removed"] + done
                    progress = 0.5 * (done / total) if total else 0.5
                else:
                    state["added"] = state["base_added"] + done
                    progress = 0.5 + 0.5 * (done / total) if total else 0.5
                if state["phase"] is not None and phase != state["phase"]:
                    state["failed"] += state["phase_failed"]
                state["phase"] = phase
                state["phase_failed"] = failed
                _job_update(
                    phase="push",
                    progress=min(progress, 1.0),
                    removed=state.get("removed", removed_total),
                    added=state.get("added", added_total),
                    failed=state["failed"] + failed,
                )

            ok, msg = push_to_mikrotik(groups, report=report)
            removed_total = state.get("removed", removed_total)
            added_total = state.get("added", added_total)
            failed_total = state["failed"] + state["phase_failed"]
            _job_update(
                phase="verify",
                progress=1.0,
                removed=removed_total,
                added=added_total,
                failed=failed_total,
                rounds=round_num,
            )
            if ok and round_num < SYNC_MAX_ROUNDS:
                continue

            plan2 = _plan_push(groups)
            if plan2.get("ok") and not plan2["to_remove"] and not plan2["additions"]:
                msg = f"converged: removed {removed_total}, added {added_total}"
                audit("addresslists_auto_sync", msg)
                return _finish_job(True, msg)
            if round_num >= SYNC_MAX_ROUNDS:
                left_rm = len(plan2["to_remove"]) if plan2.get("ok") else -1
                left_add = len(plan2["additions"]) if plan2.get("ok") else -1
                audit(
                    "addresslists_auto_sync",
                    f"not converged after {SYNC_MAX_ROUNDS}: remove left {left_rm}, add left {left_add}",
                )
                return _finish_job(
                    False,
                    f"не сходится после {SYNC_MAX_ROUNDS} итераций: осталось remove={left_rm} add={left_add}",
                )
        return _finish_job(False, "unexpected")
    except Exception as e:  # noqa: BLE001
        return _finish_job(False, str(e) or "sync failed")


def _finish_job(ok: bool, message: str) -> Tuple[bool, str]:
    _job_update(
        running=False,
        finished=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ok=ok,
        message=message,
        phase="idle",
        progress=1.0,
    )
    return ok, message


def start_auto_sync() -> None:
    """Запускает авто-синк в фоне (не более одной задачи одновременно).

    Работает из планировщика и из HTTP-эндпоинта: стартует daemon-поток и
    возвращает управление сразу; прогресс — в get_auto_sync_status().
    """
    if get_auto_sync_status()["running"]:
        return
    threading.Thread(target=run_auto_sync, daemon=True).start()
