import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import addresslists, alerts, clear_data, failover, mikrotik, monitor, profiles, xray
from .config import settings
from .db import audit, get_setting, init_db, set_setting
from .routers import addresslists as addresslists_router, alerts as alerts_router, admin as admin_router, auth, l2tp, mikrotik as mikrotik_router, monitor as monitor_router, profiles as profiles_router, servers, status
from .routers import updates as updates_router

logger = logging.getLogger("xray-gateway")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def setup_logging() -> None:
    """Логирование в файл (ротация 5×5 МБ) + в stdout."""
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    root.setLevel(logging.INFO)
    try:
        settings.log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            settings.log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(fh)
    except Exception as e:  # noqa: BLE001
        logger.warning("log file disabled: %s", e)


setup_logging()


async def _failover_loop() -> None:
    while True:
        try:
            msg = await asyncio.to_thread(profiles.failover_tick)
            logger.info("failover: %s", msg)
        except Exception as e:  # noqa: BLE001
            logger.error("failover error: %s", e)
        await asyncio.sleep(30)


async def _traffic_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(monitor.sample_traffic)
        except Exception as e:  # noqa: BLE001
            logger.error("traffic sample error: %s", e)
        await asyncio.sleep(10)


def _scheduled_tick() -> None:
    """Авто-обновление адрес-листов и авто-бэкап конфига роутера."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hm = now.strftime("%H:%M")

    cfg = addresslists.get_auto_sync_config()
    if cfg["enabled"] and hm >= cfg["time"] and (get_setting(addresslists.AUTO_SYNC_LAST, "") or "") != today:
        addresslists.start_auto_sync()
        set_setting(addresslists.AUTO_SYNC_LAST, today)
        logger.info("auto-sync: scheduled background run")

    rcfg = mikrotik.get_router_backup_config()
    if rcfg["enabled"] and hm >= rcfg["time"] and (get_setting(mikrotik.ROUTER_BACKUP_LAST, "") or "") != today:
        ok, msg = mikrotik.backup_router_config()
        set_setting(mikrotik.ROUTER_BACKUP_LAST, today)
        logger.info("router-backup: %s", msg)


async def _schedule_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(_scheduled_tick)
        except Exception as e:  # noqa: BLE001
            logger.error("schedule tick error: %s", e)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        await asyncio.to_thread(profiles.restore_runtime)
    except Exception as e:  # noqa: BLE001
        logger.error("profile runtime restore failed: %s", e)
        raise
    try:
        await asyncio.to_thread(clear_data.cleanup_backups, clear_data.get_retention_days())
        logger.info("backup cleanup: applied retention=%s days", clear_data.get_retention_days())
    except Exception as e:  # noqa: BLE001
        logger.warning("backup cleanup failed: %s", e)
    task = asyncio.create_task(_failover_loop())
    app.state.failover_task = task
    wd_task = asyncio.create_task(alerts.watchdog_loop())
    app.state.watchdog_task = wd_task
    tr_task = asyncio.create_task(_traffic_loop())
    app.state.traffic_task = tr_task
    sch_task = asyncio.create_task(_schedule_loop())
    app.state.schedule_task = sch_task
    yield
    for name in ("failover_task", "watchdog_task", "traffic_task", "schedule_task"):
        task = getattr(app.state, name, None)
        if task:
            task.cancel()


app = FastAPI(title="Routing Control", lifespan=lifespan)


@app.get('/api/healthz')
def readiness():
    version_path = Path(__file__).resolve().parent.parent / 'VERSION'
    return {'ok': xray.current_config() is not None and xray.process_active(),
            'version': version_path.read_text().strip() if version_path.exists() else 'legacy'}

app.include_router(auth.router)
app.include_router(servers.router)
app.include_router(status.router)
app.include_router(l2tp.router)
app.include_router(monitor_router.router)
app.include_router(addresslists_router.router)
app.include_router(alerts_router.router)
app.include_router(mikrotik_router.router)
app.include_router(profiles_router.router)
app.include_router(admin_router.router)
app.include_router(updates_router.router)

app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


@app.get("/")
async def index():
    return FileResponse(str(WEB_DIR / "static" / "index.html"))
