"""Persistent reconciliation for VPN subscriptions."""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import crud, healthcheck, protocols
from .db import db

_sync_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def remember(url: str) -> int:
    host = urlsplit(url).hostname or "subscription"
    with db() as conn:
        conn.execute(
            "INSERT INTO server_subscriptions(url, host, created_at) VALUES(?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET enabled=1",
            (url, host[:255], _now()),
        )
        row = conn.execute("SELECT id FROM server_subscriptions WHERE url=?", (url,)).fetchone()
        return int(row["id"])


def mark_imported(subscription_id: int, added: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE server_subscriptions SET last_checked=?, last_added=?, last_error='' WHERE id=?",
            (_now(), added, subscription_id),
        )


def link_current_servers(subscription_id: int, items: list) -> None:
    """Associate currently imported feed entries with their catalog server records."""
    identities = {protocols.server_identity(item.model_dump()) for item in items}
    matches_by_identity = {}
    for server in crud.list_servers():
        identity = protocols.server_identity(server)
        if identity in identities:
            matches_by_identity.setdefault(identity, int(server["id"]))
    with db() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO subscription_servers(subscription_id, server_id) VALUES(?, ?)",
            [(subscription_id, server_id) for server_id in matches_by_identity.values()],
        )


def list_subscriptions() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, host, enabled, interval_seconds, last_checked, last_added, last_removed, last_retained, last_error "
            "FROM server_subscriptions ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def due_ids() -> list[int]:
    now = datetime.now(timezone.utc)
    with db() as conn:
        rows = conn.execute(
            "SELECT id, last_checked, interval_seconds FROM server_subscriptions WHERE enabled=1"
        ).fetchall()
    due = []
    for row in rows:
        try:
            last = datetime.fromisoformat(row["last_checked"])
        except (TypeError, ValueError):
            last = None
        if last is None or (now - last).total_seconds() >= int(row["interval_seconds"]):
            due.append(int(row["id"]))
    return due


def set_enabled(subscription_id: int, enabled: bool) -> bool:
    with db() as conn:
        cur = conn.execute(
            "UPDATE server_subscriptions SET enabled=? WHERE id=?",
            (int(enabled), subscription_id),
        )
        return cur.rowcount > 0


def delete(subscription_id: int) -> bool:
    with db() as conn:
        cur = conn.execute("DELETE FROM server_subscriptions WHERE id=?", (subscription_id,))
        return cur.rowcount > 0


def sync(subscription_id: int, *, force: bool = False) -> dict:
    # A process-wide lock prevents the scheduler and a manual click from reconciling
    # the same feed at once. Only servers linked to this subscription are eligible
    # for removal; active interface references are retained to protect routing.
    with _sync_lock:
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM server_subscriptions WHERE id=?", (subscription_id,)
            ).fetchone()
        if row is None:
            raise LookupError("subscription not found")
        if not row["enabled"] and not force:
            return {"added_count": 0, "skipped_count": 0, "disabled": True}

        try:
            parsed = protocols.parse_subscription_url(row["url"])
            if not parsed:
                raise ValueError("subscription contains no parseable servers")
            by_identity = {}
            for server in crud.list_servers():
                by_identity.setdefault(protocols.server_identity(server), server)
            created = []
            skipped = 0
            current_ids = set()
            for item in parsed:
                key = protocols.server_identity(item.model_dump())
                existing_server = by_identity.get(key)
                if existing_server:
                    skipped += 1
                    current_ids.add(int(existing_server["id"]))
                    continue
                server = crud.create_server(item.model_dump())
                by_identity[key] = server
                created.append(server)
                current_ids.add(int(server["id"]))

            with db() as conn:
                old_ids = {
                    int(r["server_id"])
                    for r in conn.execute(
                        "SELECT server_id FROM subscription_servers WHERE subscription_id=?",
                        (subscription_id,),
                    ).fetchall()
                }
                conn.executemany(
                    "INSERT OR IGNORE INTO subscription_servers(subscription_id, server_id) VALUES(?, ?)",
                    [(subscription_id, server_id) for server_id in current_ids],
                )

            # A successful, non-empty feed is the only condition under which old
            # subscription-owned servers can be removed. Failed/empty feeds never
            # reach this reconciliation path.
            removed_count = 0
            retained_count = 0
            absent_ids = old_ids - current_ids
            if absent_ids:
                from . import profiles

                in_use = {
                    int(server_id)
                    for profile in profiles._stored_profiles()
                    for server_id in (profile.get("server_id"), profile.get("backup_server_id"))
                    if server_id
                }
                for server_id in absent_ids:
                    with db() as conn:
                        owners = conn.execute(
                            "SELECT COUNT(*) AS n FROM subscription_servers WHERE server_id=?",
                            (server_id,),
                        ).fetchone()["n"]
                        if owners > 1:
                            conn.execute(
                                "DELETE FROM subscription_servers WHERE subscription_id=? AND server_id=?",
                                (subscription_id, server_id),
                            )
                            continue
                        if server_id in in_use:
                            retained_count += 1
                            continue
                        conn.execute(
                            "DELETE FROM subscription_servers WHERE subscription_id=? AND server_id=?",
                            (subscription_id, server_id),
                        )
                    if crud.delete_server(server_id):
                        removed_count += 1

            # Keep probe concurrency bounded so a large feed cannot flood Xray/curl.
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(healthcheck.check_server, created))
            with db() as conn:
                conn.execute(
                    "UPDATE server_subscriptions SET last_checked=?, last_added=?, last_removed=?, last_retained=?, last_error='' WHERE id=?",
                    (_now(), len(created), removed_count, retained_count, subscription_id),
                )
            return {
                "added_count": len(created),
                "skipped_count": skipped,
                "removed_count": removed_count,
                "retained_count": retained_count,
                "total": len(parsed),
            }
        except Exception as exc:
            # Avoid storing an exception that might include the secret subscription URL.
            message = str(exc)
            safe_error = "Подписка недоступна или содержит некорректные данные"
            if "no parseable servers" in message:
                safe_error = "В подписке не найдено серверов поддерживаемого формата"
            with db() as conn:
                conn.execute(
                    "UPDATE server_subscriptions SET last_checked=?, last_added=0, last_removed=0, last_retained=0, last_error=? WHERE id=?",
                    (_now(), safe_error, subscription_id),
                )
            raise RuntimeError(safe_error) from exc
