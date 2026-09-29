from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import wireguard
from ..db import audit
from ..security import require_auth

router = APIRouter(
    prefix="/api/wg", tags=["wireguard"], dependencies=[Depends(require_auth)]
)


class PeerIn(BaseModel):
    public_key: str
    endpoint: Optional[str] = ""
    allowed_ips: Optional[str] = ""
    persistent_keepalive: Optional[str] = ""


class InterfaceIn(BaseModel):
    address: str
    listen_port: Optional[int] = None


def _current() -> dict:
    return wireguard.parse_conf()


def _apply(cfg: dict, action: str, detail: str) -> dict:
    ok, err = wireguard.apply_config(cfg)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    audit(action, detail)
    return {"message": "ok", "status": wireguard.read_status()}


@router.get("/status")
async def wg_status():
    return wireguard.read_status()


@router.get("/traffic")
async def wg_traffic():
    return wireguard.read_traffic()


@router.post("/peer")
async def add_peer(body: PeerIn):
    cfg = _current()
    peers = cfg["peers"]
    new_peer = {
        "public_key": body.public_key.strip(),
        "endpoint": (body.endpoint or "").strip(),
        "allowed_ips": (body.allowed_ips or "").strip(),
        "persistent_keepalive": (body.persistent_keepalive or "").strip(),
    }
    replaced = False
    for p in peers:
        if p.get("PublicKey", "").lower() == new_peer["public_key"].lower():
            p.update(new_peer)
            replaced = True
            break
    if not replaced:
        peers.append(new_peer)
    return _apply(cfg, "wg_peer_set", new_peer["public_key"])


@router.delete("/peer/{public_key}")
async def del_peer(public_key: str):
    cfg = _current()
    before = len(cfg["peers"])
    cfg["peers"] = [
        p for p in cfg["peers"] if p.get("PublicKey", "").lower() != public_key.lower()
    ]
    if len(cfg["peers"]) == before:
        raise HTTPException(status_code=404, detail="peer not found")
    return _apply(cfg, "wg_peer_del", public_key)


@router.post("/interface")
async def set_interface(body: InterfaceIn):
    cfg = _current()
    cfg["interface"]["Address"] = body.address.strip()
    if body.listen_port:
        cfg["interface"]["ListenPort"] = str(body.listen_port)
    return _apply(cfg, "wg_interface", f"address={body.address}")


@router.post("/restart")
async def restart_wg():
    code, out = wireguard._run(["systemctl", "restart", wireguard.WG_SERVICE])
    if code != 0 or not wireguard._is_active(wireguard.WG_SERVICE):
        raise HTTPException(status_code=400, detail=f"restart failed: {out}")
    audit("wg_restart", wireguard.WG_SERVICE)
    return {"message": "restarted", "status": wireguard.read_status()}
