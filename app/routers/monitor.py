import asyncio

from fastapi import APIRouter, Depends, HTTPException

from .. import crud, healthcheck, l2tp, monitor
from ..security import require_auth

router = APIRouter(
    prefix="/api/monitor", tags=["monitor"], dependencies=[Depends(require_auth)]
)


@router.get("/status")
async def monitor_status():
    l2tp_status = await asyncio.to_thread(l2tp.read_status)
    system, services, tunnel, public_ip = await asyncio.gather(
        asyncio.to_thread(monitor.read_system), asyncio.to_thread(monitor.read_services),
        asyncio.to_thread(monitor.read_tunnel), asyncio.to_thread(monitor.read_public_ip),
    )
    return {
        "system": system,
        "services": services,
        "tunnel": tunnel,
        "l2tp": {
            "sessions": l2tp_status["sessions"],
            "services": l2tp_status["services"],
        },
        "public_ip": public_ip,
    }


@router.get("/servers")
async def monitor_servers():
    servers = [s for s in crud.list_servers() if s.get("enabled")]

    async def probe(server: dict) -> dict:
        ok, latency, err = await asyncio.to_thread(healthcheck.tcp_check, server)
        return {
            "id": server["id"],
            "name": server["name"],
            "protocol": server.get("protocol", "vless"),
            "address": server["address"],
            "port": server["port"],
            "ok": ok,
            "latency_ms": latency,
            "error": err,
            "best_latency_ms": server.get("best_latency_ms"),
        }

    results = await asyncio.gather(*[probe(s) for s in servers])
    results.sort(key=lambda r: (not r["ok"], r["latency_ms"] if r["latency_ms"] is not None else 999999, r["id"]))
    return results


@router.get("/tunnel/check")
async def tunnel_check():
    return await asyncio.to_thread(monitor.check_tunnel)


@router.post("/tunnel/restart")
async def tunnel_restart():
    ok, err = await asyncio.to_thread(monitor.restart_tunnel)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"message": "tunnel restarted"}


@router.get("/traffic")
async def monitor_traffic(minutes: int = 60):
    minutes = min(max(minutes, 5), 720)
    return {
        "wg0": await asyncio.to_thread(monitor.traffic_series, "wg0", minutes),
        "ppp": await asyncio.to_thread(monitor.traffic_series, "ppp", minutes),
    }
