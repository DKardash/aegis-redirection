from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import l2tp
from ..security import require_auth

router = APIRouter(
    prefix="/api/l2tp", tags=["l2tp"], dependencies=[Depends(require_auth)]
)


class L2tpConfigIn(BaseModel):
    local_ip: str = "10.100.77.195"
    listen_addr: str = ""
    pool_start: str = ""
    pool_end: str = ""
    username: str = ""
    password: str = ""
    psk: str = ""


class L2tpUserIn(BaseModel):
    username: str
    password: str


@router.get("/status")
async def l2tp_status():
    return l2tp.read_status()


@router.post("/config")
async def l2tp_config(body: L2tpConfigIn):
    ok, err = l2tp.apply_config(body.model_dump())
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"message": "ok", "status": l2tp.read_status()}


@router.post("/restart")
async def l2tp_restart():
    ok, err = l2tp.restart()
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"message": "ok", "status": l2tp.read_status()}


@router.get("/users")
async def l2tp_users():
    return l2tp.list_users()


@router.post("/users")
async def l2tp_user_add(body: L2tpUserIn):
    ok, err = l2tp.add_user(body.username, body.password)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"message": "ok", "users": l2tp.list_users()}


@router.delete("/users/{username}")
async def l2tp_user_del(username: str):
    ok, err = l2tp.delete_user(username)
    if not ok:
        raise HTTPException(status_code=404, detail=err)
    return {"message": "ok", "users": l2tp.list_users()}
