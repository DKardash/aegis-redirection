"""Persistent, append-only sync for imported VPN subscriptions."""
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


def list_subscriptions() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, host, enabled, interval_seconds, last_checked, last_added, last_error "
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
    # A process-wide lock prevents the scheduler and a manual click from importing
    # the same feed at once. Server records remain append-only; nothing is removed
    # or overwritten when a provider changes its subscription.
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
            existing = {protocols.server_identity(s) for s in crud.list_servers()}
            created = []
            skipped = 0
            for item in parsed:
                key = protocols.server_identity(item.model_dump())
                if key in existing:
                    skipped += 1
                    continue
                server = crud.create_server(item.model_dump())
                existing.add(key)
                created.append(server)

            # Keep probe concurrency bounded so a large feed cannot flood Xray/curl.
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(healthcheck.check_server, created))
            with db() as conn:
                conn.execute(
                    "UPDATE server_subscriptions SET last_checked=?, last_added=?, last_error='' WHERE id=?",
                    (_now(), len(created), subscription_id),
                )
            return {
                "added_count": len(created),
                "skipped_count": skipped,
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
                    "UPDATE server_subscriptions SET last_checked=?, last_added=0, last_error=? WHERE id=?",
                    (_now(), safe_error, subscription_id),
                )
            raise RuntimeError(safe_error) from exc
