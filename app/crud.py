from datetime import datetime, timezone
from typing import List, Optional

from .db import db

ACTIVE_KEY = "active_server_id"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def row_to_server(row) -> dict:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    d["best_latency_ms"] = None
    return d


def _with_best_latency(server: Optional[dict]) -> Optional[dict]:
    if server is None:
        return None
    server["best_latency_ms"] = best_latency(server["id"])
    return server


def list_servers() -> List[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM servers ORDER BY priority, id").fetchall()
        return [_with_best_latency(row_to_server(r)) for r in rows]


def get_server(server_id: int) -> Optional[dict]:
    with db() as conn:
        row = conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
        return _with_best_latency(row_to_server(row)) if row else None


def best_latency(server_id: int) -> Optional[float]:
    with db() as conn:
        row = conn.execute(
            "SELECT MIN(latency_ms) AS m FROM health_checks WHERE server_id=? AND ok=1",
            (server_id,),
        ).fetchone()
        return row["m"] if row and row["m"] is not None else None


def create_server(data: dict) -> dict:
    now = _now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO servers(name, address, port, uuid, protocol, flow, network, security, "
            "sni, reality_public_key, reality_short_id, fingerprint, path, mode, service_name, "
            "alpn, host, enabled, priority, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["name"], data["address"], data["port"], data["uuid"],
                data["protocol"], data["flow"], data["network"], data["security"], data["sni"],
                data["reality_public_key"], data["reality_short_id"], data["fingerprint"],
                data["path"], data["mode"], data["service_name"], data["alpn"], data["host"],
                1 if data["enabled"] else 0, data["priority"], now, now,
            ),
        )
        return get_server(cur.lastrowid)


def update_server(server_id: int, data: dict) -> Optional[dict]:
    now = _now()
    with db() as conn:
        cur = conn.execute(
            "UPDATE servers SET name=?, address=?, port=?, uuid=?, protocol=?, flow=?, network=?, "
            "security=?, sni=?, reality_public_key=?, reality_short_id=?, fingerprint=?, path=?, "
            "mode=?, service_name=?, alpn=?, host=?, enabled=?, priority=?, updated_at=? WHERE id=?",
            (
                data["name"], data["address"], data["port"], data["uuid"],
                data["protocol"], data["flow"], data["network"], data["security"], data["sni"],
                data["reality_public_key"], data["reality_short_id"], data["fingerprint"],
                data["path"], data["mode"], data["service_name"], data["alpn"], data["host"],
                1 if data["enabled"] else 0, data["priority"], now, server_id,
            ),
        )
        if cur.rowcount == 0:
            return None
        return get_server(server_id)


def delete_server(server_id: int) -> bool:
    with db() as conn:
        conn.execute("DELETE FROM health_checks WHERE server_id = ?", (server_id,))
        cur = conn.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        return cur.rowcount > 0


def set_health(server_id: int, ok: bool, latency_ms: Optional[float], error: str) -> None:
    now = _now()
    with db() as conn:
        updated = conn.execute(
            "UPDATE servers SET last_health=?, last_health_at=? WHERE id=?",
            ("ok" if ok else "fail", now, server_id),
        )
        if updated.rowcount == 0:
            return
        conn.execute(
            "INSERT INTO health_checks(server_id, ts, ok, latency_ms, error) "
            "VALUES(?,?,?,?,?)",
            (server_id, now, 1 if ok else 0, latency_ms, error[:500]),
        )
