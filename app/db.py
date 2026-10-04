import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from time import time
from typing import Optional

from .config import settings

_local = threading.local()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(settings.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    settings.generated_dir.mkdir(parents=True, exist_ok=True)

    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                port INTEGER NOT NULL DEFAULT 443,
                uuid TEXT NOT NULL,
                protocol TEXT NOT NULL DEFAULT 'vless',
                flow TEXT NOT NULL DEFAULT 'xtls-rprx-vision',
                network TEXT NOT NULL DEFAULT 'tcp',
                security TEXT NOT NULL DEFAULT 'reality',
                sni TEXT NOT NULL DEFAULT '',
                reality_public_key TEXT NOT NULL DEFAULT '',
                reality_short_id TEXT NOT NULL DEFAULT '',
                fingerprint TEXT NOT NULL DEFAULT 'chrome',
                path TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT 'auto',
                service_name TEXT NOT NULL DEFAULT '',
                alpn TEXT NOT NULL DEFAULT 'h2,http/1.1',
                host TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 100,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_health TEXT,
                last_health_at TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS server_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                host TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                interval_seconds INTEGER NOT NULL DEFAULT 3600,
                last_checked TEXT,
                last_added INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                expires_at REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL REFERENCES servers(id),
                ts TEXT NOT NULL,
                ok INTEGER NOT NULL,
                latency_ms REAL,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT
            );

            CREATE TABLE IF NOT EXISTS traffic_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                iface TEXT NOT NULL,
                rx INTEGER NOT NULL,
                tx INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_traffic_ts ON traffic_samples(ts);
            """
        )

        columns = [r[1] for r in conn.execute("PRAGMA table_info(servers)").fetchall()]
        for col, ddl in {
            "protocol": "ALTER TABLE servers ADD COLUMN protocol TEXT NOT NULL DEFAULT 'vless'",
            "path": "ALTER TABLE servers ADD COLUMN path TEXT NOT NULL DEFAULT ''",
            "mode": "ALTER TABLE servers ADD COLUMN mode TEXT NOT NULL DEFAULT 'auto'",
            "service_name": "ALTER TABLE servers ADD COLUMN service_name TEXT NOT NULL DEFAULT ''",
            "alpn": "ALTER TABLE servers ADD COLUMN alpn TEXT NOT NULL DEFAULT 'h2,http/1.1'",
            "host": "ALTER TABLE servers ADD COLUMN host TEXT NOT NULL DEFAULT ''",
        }.items():
            if col not in columns:
                conn.execute(ddl)


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def save_session(token: str, expires_at: float) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions(token, expires_at, created_at) VALUES(?, ?, ?) "
            "ON CONFLICT(token) DO UPDATE SET expires_at = excluded.expires_at",
            (token, expires_at, _now()),
        )
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time(),))


def load_session(token: str) -> Optional[float]:
    with db() as conn:
        row = conn.execute(
            "SELECT expires_at FROM sessions WHERE token = ? AND expires_at > ?",
            (token, time()),
        ).fetchone()
        return row["expires_at"] if row else None


def delete_session(token: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def delete_all_sessions() -> None:
    with db() as conn:
        conn.execute("DELETE FROM sessions")


def audit(action: str, detail: str = "") -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO audit_log(ts, action, detail) VALUES(?, ?, ?)",
            (_now(), action, detail),
        )


def add_traffic_sample(ts: str, iface: str, rx: int, tx: int) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO traffic_samples(ts, iface, rx, tx) VALUES(?, ?, ?, ?)",
            (ts, iface, rx, tx),
        )


def get_traffic_samples(iface: str, since: str, limit: int = 1000) -> list:
    with db() as conn:
        rows = conn.execute(
            "SELECT ts, iface, rx, tx FROM traffic_samples "
            "WHERE iface = ? AND ts >= ? ORDER BY ts ASC LIMIT ?",
            (iface, since, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def purge_traffic_samples(before: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM traffic_samples WHERE ts < ?", (before,))
