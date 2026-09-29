from fastapi import APIRouter, Depends

from .. import profiles, xray
from ..schemas import HealthOut, StatusOut
from ..security import require_auth

router = APIRouter(prefix="/api", tags=["status"], dependencies=[Depends(require_auth)])


@router.get("/status")
def status():
    rows = profiles.list_profiles()
    enabled = [p for p in rows if p.get("enabled")]
    return {
        "profiles": rows,
        "enabled_count": len(enabled),
        "healthy_count": sum(p["health"] == "ok" and p["service"] == "active" for p in enabled),
        "backup_count": sum(bool(p["on_backup"]) for p in enabled),
        "xray_config_valid": xray.current_config() is not None,
        "xray_process": xray.process_active(),
    }


@router.get("/audit", response_model=list[dict])
async def audit_log(limit: int = 50, action: str = ""):
    from ..db import db

    limit = min(max(limit, 1), 500)
    with db() as conn:
        if action:
            rows = conn.execute(
                "SELECT ts, action, detail FROM audit_log WHERE action LIKE ? ORDER BY id DESC LIMIT ?",
                (action + "%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ts, action, detail FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
