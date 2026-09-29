import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import mikrotik
from ..security import require_auth

router = APIRouter(
    prefix="/api/mikrotik", tags=["mikrotik"], dependencies=[Depends(require_auth)]
)


class MikrotikIn(BaseModel):
    host: str = ""
    port: int = 8728
    username: str = ""
    password: str = ""
    use_ssl: bool = False
    auto_failover: bool = False
    failover_interval: int = 30


class ModeIn(BaseModel):
    mode: str = ""
    force: bool = False


class AddressListIn(BaseModel):
    list: str = ""
    address: str = ""
    comment: str = ""


class AddressListUpdate(BaseModel):
    comment: Optional[str] = None
    disabled: Optional[bool] = None


class AddressListImportIn(BaseModel):
    text: str


class RouterBackupIn(BaseModel):
    enabled: bool = False
    time: str = "03:00"


class ClientVpnIn(BaseModel):
    ip: str
    enabled: bool = True


@router.get("/config")
async def get_config():
    cfg = mikrotik.get_mt_config()
    cfg["password"] = "****" if cfg["password"] else ""
    return cfg


@router.get("/mode")
async def get_mode():
    return await asyncio.to_thread(mikrotik.get_tunnel_mode)


@router.post("/mode")
async def set_mode(body: ModeIn):
    ok, msg = await asyncio.to_thread(mikrotik.set_tunnel_mode, body.mode, body.force)
    if not ok:
        if msg.startswith("tunnel_down:"):
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, **await asyncio.to_thread(mikrotik.get_tunnel_mode)}


@router.get("/address-list")
async def get_al_list(list: Optional[str] = None):
    ok, data = await asyncio.to_thread(mikrotik.get_address_list, list)
    if not ok:
        raise HTTPException(status_code=400, detail=data.get("error", "ошибка MikroTik"))
    return data


@router.post("/address-list")
async def add_al_entry(body: AddressListIn):
    ok, msg = await asyncio.to_thread(
        mikrotik.add_address_list, body.list, body.address, body.comment
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.patch("/address-list/{item_id}")
async def update_al_entry(item_id: str, body: AddressListUpdate):
    ok, msg = await asyncio.to_thread(
        mikrotik.update_address_list, item_id, body.comment, body.disabled
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.delete("/address-list/{item_id}")
async def delete_al_entry(item_id: str):
    ok, msg = await asyncio.to_thread(mikrotik.delete_address_list, item_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/address-list/import")
async def import_al_entries(body: AddressListImportIn):
    ok, msg = await asyncio.to_thread(mikrotik.import_address_list, body.text)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.get("/address-list/export")
async def export_al_entries(list: Optional[str] = None):
    from ..addresslists import _entry_line, parse_groups
    managed_lists = {e['list'] for g in parse_groups() for e in g['entries']}
    ok, data = await asyncio.to_thread(mikrotik.get_address_list, list)
    if not ok:
        raise HTTPException(status_code=400, detail=data.get("error", "ошибка MikroTik"))
    lines = []
    for e in data.get("entries", []):
        if mikrotik._is_true(e.get("dynamic")) or e.get("list") not in managed_lists:
            continue
        lines.append(_entry_line({**e, "disabled": mikrotik._is_true(e.get("disabled"))}, e["address"]))
    return {"text": "\n".join(lines), "count": len(lines)}


@router.get("/routes")
async def routes():
    return await asyncio.to_thread(mikrotik.get_routes)


@router.post("/config")
async def set_config(body: MikrotikIn):
    ok, err = mikrotik.set_mt_config(
        {
            "host": body.host,
            "port": body.port,
            "username": body.username,
            "password": body.password,
            "use_ssl": body.use_ssl,
            "auto_failover": body.auto_failover,
            "failover_interval": body.failover_interval,
        }
    )
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"message": err}


@router.post("/test")
async def test_conn():
    return await asyncio.to_thread(mikrotik.test_connection)


@router.get("/status")
async def status():
    return await asyncio.to_thread(mikrotik.read_status)


@router.get("/config-backups")
async def config_backups():
    return mikrotik.list_router_backups()


@router.get("/config-backups/schedule")
async def config_backup_schedule_get():
    return mikrotik.get_router_backup_config()


@router.post("/config-backups/schedule")
async def config_backup_schedule_set(body: RouterBackupIn):
    ok, msg = mikrotik.set_router_backup_config({"enabled": body.enabled, "time": body.time})
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, **mikrotik.get_router_backup_config()}


@router.get("/config-backups/export")
async def config_backup_export():
    ok, text = await asyncio.to_thread(mikrotik.export_router_config)
    if not ok:
        raise HTTPException(status_code=400, detail=text)
    name = f"router-config-{datetime.now().strftime('%Y%m%d%H%M%S')}.rsc"
    return {"name": name, "text": text}


@router.get("/config-backups/{name}")
async def config_backup(name: str):
    ok, text = mikrotik.get_router_backup(name)
    if not ok:
        raise HTTPException(status_code=404, detail=text)
    return {"name": name, "text": text}


@router.post("/config-backups/now")
async def config_backup_now():
    ok, msg = await asyncio.to_thread(mikrotik.backup_router_config)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.get("/client-vpn")
async def client_vpn_list():
    return await asyncio.to_thread(mikrotik.list_client_vpn)


@router.post("/client-vpn")
async def client_vpn_set(body: ClientVpnIn):
    ok, msg = await asyncio.to_thread(mikrotik.set_client_vpn, body.ip, body.enabled)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, **await asyncio.to_thread(mikrotik.list_client_vpn)}


@router.delete("/client-vpn/{ip}")
async def client_vpn_del(ip: str):
    ok, msg = await asyncio.to_thread(mikrotik.delete_client_vpn, ip)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, **await asyncio.to_thread(mikrotik.list_client_vpn)}
