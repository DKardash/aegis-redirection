from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import clear_data
from ..db import audit
from ..security import require_auth

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_auth)]
)


class ClearDataIn(BaseModel):
    sections: List[str] = []


class RetentionIn(BaseModel):
    days: int = 10


@router.get("/data-options")
async def data_options():
    return {"sections": clear_data.SECTIONS}


@router.post("/clear-data")
async def clear_data_endpoint(body: ClearDataIn):
    sections = [s for s in dict.fromkeys(body.sections)]
    valid = {s["name"] for s in clear_data.SECTIONS}
    unknown = [s for s in sections if s not in valid]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown sections: {', '.join(unknown)}")
    if not sections:
        raise HTTPException(status_code=400, detail="не выбраны разделы")

    results = {}
    for name in sections:
        try:
            results[name] = clear_data.clear_section(name)
        except Exception as e:  # noqa: BLE001
            results[name] = {"ok": False, "error": str(e)}
    audit("clear_data", f"sections={','.join(sections)}")
    return {"results": results}


@router.get("/backup-retention")
async def retention_get():
    return {"days": clear_data.get_retention_days()}


@router.post("/backup-retention")
async def retention_set(body: RetentionIn):
    ok, err = clear_data.set_retention_days(body.days)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"days": clear_data.get_retention_days()}


@router.post("/backup-retention/apply")
async def retention_apply():
    res = clear_data.cleanup_backups(clear_data.get_retention_days())
    audit("backup_cleanup", f"days={res['days']} removed={res['removed']}")
    return res
