import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from .. import crud, healthcheck, profiles, protocols, subscriptions, xray
from ..config import settings
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


class BulkCheckRequest(BaseModel):
    test: bool = True
    health: bool = True


def _to_out(s: dict) -> ServerOut:
    return ServerOut(**s)


@router.get("", response_model=list[ServerOut])
async def list_servers():
    return [_to_out(s) for s in crud.list_servers()]


async def _check_one(server: dict, do_test: bool, do_health: bool) -> dict:
    res = {
        "server_id": server["id"],
        "name": server["name"],
        "protocol": server.get("protocol", "vless"),
        "address": server["address"],
        "port": server["port"],
    }
    if do_test:
        try:
            config = xray.build_config(server, inbound=settings.inbound_mode)
            ok, err = await asyncio.to_thread(xray.test_config, config)
            res["config_ok"] = ok
            res["config_error"] = None if ok else err
        except ValueError as e:
            res["config_ok"] = False
            res["config_error"] = str(e)
    if do_health:
        ok, latency, err = await asyncio.to_thread(healthcheck.check_server, server, False)
        res["health_ok"] = ok
        res["health_latency_ms"] = latency
        res["health_error"] = err
    return res


async def check_imported(servers: list[dict]):
    # Small batches also bound executor queue pressure for large subscriptions.
    for start in range(0, len(servers), 3):
        await asyncio.gather(*[asyncio.to_thread(healthcheck.check_server, s) for s in servers[start:start + 3]])


_bulk_task = None


@router.post("/check", response_model=list[dict])
async def bulk_check(body: BulkCheckRequest):
    global _bulk_task
    if _bulk_task is None or _bulk_task.done():
        _bulk_task = asyncio.create_task(_bulk_check(body))
    return await asyncio.shield(_bulk_task)


async def _bulk_check(body: BulkCheckRequest):
    servers = [s for s in crud.list_servers() if s.get("enabled")]
    results = []
    for start in range(0, len(servers), 3):
        results.extend(await asyncio.gather(*[_check_one(s, body.test, body.health) for s in servers[start:start + 3]]))
    if body.health:
        for server, r in zip(servers, results):
            crud.set_health(
                server["id"],
                r["health_ok"],
                r.get("health_latency_ms"),
                r.get("health_error") or "",
            )
    ok_health = sum(1 for r in results if r.get("health_ok"))
    ok_config = sum(1 for r in results if r.get("config_ok"))
    audit(
        "bulk_check",
        f"servers={len(results)} config_ok={ok_config} health_ok={ok_health}",
    )
    return results


@router.post("", response_model=ServerOut, status_code=201)
async def create_server(body: ServerCreate, background: BackgroundTasks):
    data = body.model_dump()
    server = crud.create_server(data)
    audit("server_create", server["name"])
    background.add_task(check_imported, [server])
    return _to_out(server)


@router.post("/import", response_model=ServerOut, status_code=201)
async def import_server(body: ImportRequest, background: BackgroundTasks):
    try:
        parsed = protocols.parse_share_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    server = crud.create_server(parsed.model_dump())
    audit("server_import", f"{server['protocol']} {server['name']}")
    background.add_task(check_imported, [server])
    return _to_out(server)


class ImportSubscriptionRequest(BaseModel):
    url: str
    skip_existing: bool = True
    remember_subscription: bool = False


@router.post("/import-subscription", response_model=dict)
async def import_subscription(body: ImportSubscriptionRequest, background: BackgroundTasks):
    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="expected subscription URL (http/https)")
    try:
        parsed = await asyncio.to_thread(protocols.parse_subscription_url, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"subscription fetch failed: {e}") from e
    if not parsed:
        raise HTTPException(status_code=400, detail="subscription contains no parseable servers")

    existing = {protocols.server_identity(s) for s in crud.list_servers()}
    created, skipped = [], []
    to_check = []
    for p in parsed:
        key = protocols.server_identity(p.model_dump())
        if body.skip_existing and key in existing:
            skipped.append(p.name)
            continue
        s = crud.create_server(p.model_dump())
        existing.add(key)
        created.append(s["name"])
        to_check.append(s)
    background.add_task(check_imported, to_check)
    subscription_id = subscriptions.remember(url) if body.remember_subscription else None
    if body.remember_subscription:
        subscriptions.mark_imported(subscription_id, len(created))
        subscriptions.link_current_servers(subscription_id, parsed)
    host = urlsplit(url).hostname or "subscription"
    audit(
        "subscription_import",
        f"host={host} created={len(created)} skipped={len(skipped)} total={len(parsed)} saved={bool(subscription_id)}",
    )
    return {
        "total": len(parsed),
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "subscription_id": subscription_id,
    }


class SubscriptionEnabledRequest(BaseModel):
    enabled: bool


@router.get("/subscriptions", response_model=list[dict])
async def list_server_subscriptions():
    # Raw URLs are intentionally not returned: subscription links often contain tokens.
    return subscriptions.list_subscriptions()


@router.post("/subscriptions/{subscription_id:int}/sync", response_model=dict)
async def sync_server_subscription(subscription_id: int):
    try:
        result = await asyncio.to_thread(subscriptions.sync, subscription_id, force=True)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    audit(
        "subscription_sync",
        f"id={subscription_id} added={result['added_count']} removed={result['removed_count']} retained={result['retained_count']}",
    )
    return result


@router.put("/subscriptions/{subscription_id:int}", response_model=dict)
async def set_server_subscription(subscription_id: int, body: SubscriptionEnabledRequest):
    if not subscriptions.set_enabled(subscription_id, body.enabled):
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"ok": True, "enabled": body.enabled}


@router.delete("/subscriptions/{subscription_id:int}", response_model=MessageResponse)
async def delete_server_subscription(subscription_id: int):
    if not subscriptions.delete(subscription_id):
        raise HTTPException(status_code=404, detail="subscription not found")
    # Existing servers are deliberately left untouched.
    return MessageResponse(message="subscription removed; imported servers kept")


@router.get("/{server_id:int}", response_model=ServerOut)
async def get_server(server_id: int):
    server = crud.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    return _to_out(server)


@router.put("/{server_id}", response_model=ServerOut)
@profiles.serialized
def update_server(server_id: int, body: ServerUpdate):
    old = crud.get_server(server_id)
    refs = [p for p in profiles._stored_profiles() if server_id in (p["server_id"], p.get("backup_server_id"))]
    if refs and not body.enabled:
        raise HTTPException(status_code=409, detail="Сначала замените сервер в использующих его интерфейсах")
    server = crud.update_server(server_id, body.model_dump())
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    if refs:
        ok, error = xray.apply_config(profiles.build_full_config())
        if not ok:
            crud.update_server(server_id, old)
            raise HTTPException(status_code=400, detail=error)
    audit("server_update", server["name"])
    return _to_out(server)


@router.delete("/{server_id}", response_model=MessageResponse)
@profiles.serialized
def delete_server(server_id: int):
    server = crud.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    refs = [p["local_ip"] for p in profiles._stored_profiles() if server_id in (p["server_id"], p.get("backup_server_id"))]
    if refs:
        raise HTTPException(status_code=409, detail="Сервер используется интерфейсами: " + ", ".join(refs) + ". Сначала замените его в настройках интерфейса.")
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
        config = xray.build_config(server, inbound=settings.inbound_mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    ok, err = await asyncio.to_thread(xray.test_config, config)
    if not ok:
        raise HTTPException(status_code=400, detail=f"config invalid: {err}")
    audit("server_test", server["name"])
    return MessageResponse(message="config valid")


@router.post("/{server_id}/healthcheck", response_model=HealthOut)
async def run_healthcheck(server_id: int):
    server = crud.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="server not found")
    ok, latency, err = await asyncio.to_thread(healthcheck.check_server, server)
    audit("healthcheck", f"server={server['name']} ok={ok}")
    return HealthOut(server_id=server_id, ok=ok, latency_ms=latency, error=err)


@router.post("/{server_id}/activate", response_model=ActivateResponse)
async def activate(server_id: int):
    raise HTTPException(status_code=410, detail="Выбор рабочего сервера перенесён в раздел «Интерфейсы»")


@router.post("/failover/run", response_model=MessageResponse)
async def run_failover_now():
    msg = await asyncio.to_thread(profiles.failover_tick)
    return MessageResponse(message=msg)


@router.get("/best", response_model=dict)
async def best_server():
    enabled = [s for s in crud.list_servers() if s.get("enabled") and s.get("last_health") == "ok"]
    if not enabled:
        return {"found": False, "server_id": None, "message": "no reachable server"}
    reachable = enabled
    if not reachable:
        return {"found": False, "server_id": None, "message": "no reachable server"}
    best = min(
        reachable,
        key=lambda s: (
            s.get("best_latency_ms") is None,
            s.get("best_latency_ms") if s.get("best_latency_ms") is not None else s.get("probe_latency_ms", 999999),
            s.get("priority", 100),
            s["id"],
        ),
    )
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
    raise HTTPException(status_code=410, detail="Настройте основной и резервный сервер в разделе «Интерфейсы»")
