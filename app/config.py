import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


class Settings:
    database_path: Path = Path(_get("DATABASE_PATH", str(BASE_DIR / "data" / "gateway.db")))
    backups_dir: Path = Path(_get("BACKUPS_DIR", str(BASE_DIR / "backups")))
    generated_dir: Path = Path(_get("GENERATED_DIR", str(BASE_DIR / "generated")))
    log_path: Path = Path(_get("LOG_PATH", str(BASE_DIR / "logs" / "manager.log")))

    admin_username: str = _get("ADMIN_USERNAME", "admin")
    admin_password: str = _get("ADMIN_PASSWORD", "")
    session_secret: str = _get("SESSION_SECRET", "change-me")

    xray_config_path: Path = Path(_get("XRAY_CONFIG_PATH", "/etc/xray/config.json"))
    xray_staging_path: Path = Path(_get("XRAY_STAGING_PATH", str(BASE_DIR / "generated" / "config.json")))
    xray_test_cmd: str = _get("XRAY_TEST_CMD", "xray -test -config")
    xray_reload_cmd: str = _get("XRAY_RELOAD_CMD", "systemctl restart xray")

    tproxy_port: int = int(_get("XRAY_TPROXY_PORT", "12345"))
    socks_port: int = int(_get("XRAY_SOCKS_PORT", "1080"))
    http_port: int = int(_get("XRAY_HTTP_PORT", "8080"))
    inbound_mode: str = _get("XRAY_INBOUND_MODE", "proxy")

    healthcheck_timeout: float = float(_get("HEALTHCHECK_TIMEOUT", "10"))
    healthcheck_interval: int = int(_get("HEALTHCHECK_INTERVAL", "60"))
    healthcheck_proxy_url: str = _get("HEALTHCHECK_PROXY_URL", "")
    healthcheck_target: str = _get("HEALTHCHECK_TARGET", "https://ifconfig.me")
    healthcheck_expected_ip: str = _get("HEALTHCHECK_EXPECTED_IP", "")

    rate_limit_max: int = int(_get("RATE_LIMIT_MAX", "20"))
    rate_limit_window: int = int(_get("RATE_LIMIT_WINDOW", "60"))

    @property
    def requires_password(self) -> bool:
        return bool(self.admin_password)


settings = Settings()
