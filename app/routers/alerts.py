import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import alerts
from ..security import require_auth

router = APIRouter(
    prefix="/api/alerts", tags=["alerts"], dependencies=[Depends(require_auth)]
)


class AlertsIn(BaseModel):
    enabled: bool = False
    interval: int = 60
    auto_restart: bool = True
    tg_token: str = ""
    tg_chat: str = ""
    disk_threshold: int = 90
    router_cpu_threshold: int = 90
    source_ip: str = ""


@router.get("/config")
async def get_config():
    cfg = alerts.get_alerts_config()
    cfg["tg_token"] = alerts.mask_token(cfg["tg_token"])
    cfg["tg_chat"] = alerts.mask_chat(cfg["tg_chat"])
    cfg["source_ips"] = await asyncio.to_thread(alerts.source_ips)
    return cfg


@router.post("/config")
async def set_config(body: AlertsIn):
    data = {
        "enabled": body.enabled,
        "interval": body.interval,
        "auto_restart": body.auto_restart,
        "tg_token": body.tg_token,
        "tg_chat": body.tg_chat,
        "disk_threshold": body.disk_threshold,
        "router_cpu_threshold": body.router_cpu_threshold,
        "source_ip": body.source_ip,
    }
    ok, err = alerts.set_alerts_config(data)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"message": err}


@router.post("/test")
async def test_alert():
    ok, err = await alerts.send_telegram("Xray Gateway: test alert")
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"message": "test alert sent"}


@router.get("/tg-status")
async def tg_status():
    cfg = alerts.get_alerts_config()
    if not cfg["tg_token"]:
        return {
            "ok": False,
            "configured": False,
            "bot_username": "",
            "error": "telegram not configured",
            "chat_configured": bool(cfg["tg_chat"]),
            "chat_masked": "",
        }
    ok, info = await asyncio.to_thread(alerts.tg_get_me, cfg["tg_token"])
    return {
        "ok": ok,
        "configured": True,
        "bot_username": info if ok else "",
        "error": "" if ok else info,
        "chat_configured": bool(cfg["tg_chat"]),
        "chat_masked": alerts.mask_chat(cfg["tg_chat"]),
    }


@router.post("/tg-resolve")
async def tg_resolve():
    cfg = alerts.get_alerts_config()
    if not cfg["tg_token"]:
        raise HTTPException(status_code=400, detail="telegram not configured")
    ok, res = await asyncio.to_thread(alerts.tg_get_updates, cfg["tg_token"])
    if not ok:
        raise HTTPException(status_code=400, detail=res)
    return {"chats": res}


@router.post("/check")
async def run_check():
    return {"checks": await alerts.watchdog_tick()}
