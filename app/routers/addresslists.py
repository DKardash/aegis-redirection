import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import addresslists
from ..security import require_auth

router = APIRouter(
    prefix="/api/addresslists", tags=["addresslists"], dependencies=[Depends(require_auth)]
)


class RawIn(BaseModel):
    text: str


class AutoSyncIn(BaseModel):
    enabled: bool = False
    time: str = "04:00"


@router.get("/raw")
async def get_raw():
    return {"text": addresslists.read_raw()}


@router.post("/raw")
async def save_raw(body: RawIn):
    ok, err = addresslists.save_raw(body.text)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"message": "saved", "groups": addresslists.parse_groups()}


@router.get("/groups")
async def get_groups():
    return addresslists.parse_groups()


@router.post("/resolve")
async def resolve():
    groups = await asyncio.to_thread(addresslists.resolve_groups)
    return {
        "groups": groups,
        "rsc": addresslists.build_ip_rsc(groups),
    }


@router.post("/sync-script")
async def sync_script():
    groups = await asyncio.to_thread(addresslists.resolve_groups)
    return {
        "script": addresslists.build_sync_script(groups),
    }


@router.post("/apply")
async def apply():
    groups = await asyncio.to_thread(addresslists.resolve_groups)
    ok, msg = await asyncio.to_thread(addresslists.push_to_mikrotik, groups)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/preview")
async def preview():
    groups = await asyncio.to_thread(addresslists.resolve_groups)
    return await asyncio.to_thread(addresslists.preview_push, groups)


@router.get("/backups")
async def backups():
    return addresslists.list_backups()


@router.get("/backups/{name}")
async def get_backup(name: str):
    ok, text = addresslists.get_backup(name)
    if not ok:
        raise HTTPException(status_code=404, detail=text)
    return {"name": name, "text": text}


@router.post("/backups/{name}/restore")
async def restore(name: str):
    ok, msg = addresslists.restore_backup(name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.get("/auto-sync")
async def auto_sync_get():
    return addresslists.get_auto_sync_config()


@router.post("/auto-sync")
async def auto_sync_set(body: AutoSyncIn):
    ok, msg = addresslists.set_auto_sync_config({"enabled": body.enabled, "time": body.time})
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, **addresslists.get_auto_sync_config()}


@router.post("/auto-sync/run")
async def auto_sync_run():
    addresslists.start_auto_sync()
    return {"message": "sync started", **addresslists.get_auto_sync_status()}


@router.get("/auto-sync/status")
async def auto_sync_status():
    return addresslists.get_auto_sync_status()
