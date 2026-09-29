from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import crud, failover, healthcheck, protocols, xray
from ..db import audit
from ..schemas import (
    ActivateResponse,
    HealthOut,
    MessageResponse,
    ServerCreate,
    ServerOut,
    ServerUpdate,
)
from ..security import require_auth

router = APIRouter(
    prefix="/api/servers", tags=["servers"], dependencies=[Depends(require_auth)]
)


class ImportRequest(BaseModel):
    url: str


def _to_out(s: dict) -> ServerOut:
    return ServerOut(**s)


@router.get("", response_model=list[ServerOut])
async def list_servers():
    return [_to_out(s) for s in crud.list_servers()]


@router.post("", response_model=ServerOut, status_code=201)
async def create_server(body: ServerCreate):
    data = body.model_dump()
    server = crud.create_server(data)
    audit("server_create", server["name"])
    return _to_out(server)


@router.post("/import", response_model=ServerOut, status_code=201)
async def import_server(body: ImportRequest):
    try:
        parsed = protocols.parse_share_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    server = crud.create_server(parsed.model_dump())
    audit("server_import", f"{server['protocol']} {server['name']}")
    return _to_out(server)


@router.get("/{server_id}", response_model=ServerOut)
async def get_server(server_id: int):
    server = crud.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    return _to_out(server)


@router.put("/{server_id}", response_model=ServerOut)
async def update_server(server_id: int, body: ServerUpdate):
    server = crud.update_server(server_id, body.model_dump())
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    audit("server_update", server["name"])
    return _to_out(server)


@router.delete("/{server_id}", response_model=MessageResponse)
async def delete_server(server_id: int):
    server = crud.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    crud.delete_server(server_id)
    audit("server_delete", server["name"])
    return MessageResponse(message="deleted")


@router.get("/{server_id}/vless-url", response_model=dict)
async def server_vless_url(server_id: int):
    server = crud.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    return {"url": protocols.build_share_url(server)}


@router.post("/{server_id}/test", response_model=MessageResponse)
async def test_server(server_id: int):
    server = crud.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    try:
        config = xray.build_config(server)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    ok, err = xray.test_config(config)
    if not ok:
        raise HTTPException(status_code=400, detail=f"config invalid: {err}")
    audit("server_test", server["name"])
    return MessageResponse(message="config valid")


@router.post("/{server_id}/healthcheck", response_model=HealthOut)
async def run_healthcheck(server_id: int):
    server = crud.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    ok, latency, err = healthcheck.check_server(server)
    audit("healthcheck", f"server={server['name']} ok={ok}")
    return HealthOut(server_id=server_id, ok=ok, latency_ms=latency, error=err)


@router.post("/{server_id}/activate", response_model=ActivateResponse)
async def activate(server_id: int):
    ok, msg = failover.activate_server(server_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return ActivateResponse(activated=True, server_id=server_id, message=msg)


@router.post("/failover/run", response_model=MessageResponse)
async def run_failover_now():
    msg = failover.run_failover()
    return MessageResponse(message=msg)


@router.get("/best", response_model=dict)
async def best_server():
    best = failover.find_best()
    if not best:
        return {"found": False, "server_id": None, "message": "no reachable server"}
    return {
        "found": True,
        "server_id": best["id"],
        "name": best["name"],
        "protocol": best["protocol"],
        "address": best["address"],
        "best_latency_ms": best.get("best_latency_ms"),
        "probe_latency_ms": best.get("probe_latency_ms"),
    }


@router.post("/failover/best", response_model=MessageResponse)
async def switch_to_best_now():
    ok, msg = failover.activate_best()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return MessageResponse(message=msg)
