import json
import shutil
import subprocess
import tempfile
import shlex
import threading
from datetime import datetime
from typing import Dict, Optional, Tuple

from .config import settings

APPLY_LOCK = threading.RLock()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _alpn_list(server: Dict) -> Optional[list]:
    alpn = (server.get("alpn") or "").strip()
    if not alpn:
        return None
    return [p.strip() for p in alpn.split(",") if p.strip()]


def _reality(server: Dict, network: str) -> Dict:
    if network not in ("tcp", "xhttp", "ws", "grpc"):
        raise ValueError("reality supports tcp/xhttp/ws/grpc transports")
    return {
        "security": "reality",
        "realitySettings": {
            "serverName": server["sni"],
            "fingerprint": server["fingerprint"],
            "publicKey": server["reality_public_key"],
            "shortId": server["reality_short_id"],
        },
    }


def _tls(server: Dict) -> Dict:
    tls = {"serverName": server["sni"] or server["address"]}
    if server.get("fingerprint"):
        tls["fingerprint"] = server["fingerprint"]
    alpn = _alpn_list(server)
    if alpn:
        tls["alpn"] = alpn
    return {"security": "tls", "tlsSettings": tls}


def _transport(server: Dict) -> Dict:
    network = server["network"]
    security = server["security"]
    stream: Dict = {"network": network}

    if security == "reality":
        stream.update(_reality(server, network))
    elif security == "tls":
        stream.update(_tls(server))
    else:
        stream["security"] = "none"

    host = server.get("host") or server.get("sni") or ""
    path = server.get("path") or "/"

    if network == "ws":
        ws = {"path": path}
        if host:
            ws["headers"] = {"Host": host}
        stream["wsSettings"] = ws
    elif network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": server.get("service_name") or "grpc",
        }
        if host:
            stream["grpcSettings"]["authority"] = host
    elif network == "xhttp":
        xh = {"path": path, "mode": server.get("mode") or "auto"}
        if host:
            xh["host"] = host
        stream["xhttpSettings"] = xh
    elif network == "kcp":
        stream["kcpSettings"] = {"header": {"type": "none"}}
    elif network == "http":
        stream["httpSettings"] = {"host": [host or "cloudflare.com"], "path": path}

    return stream


def _vless_outbound(server: Dict, tag: str = "vless-main") -> Dict:
    network = server["network"]
    flow = server.get("flow") or ""
    if network != "tcp":
        flow = ""
    return {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": server["address"],
                    "port": server["port"],
                    "users": [
                        {
                            "id": server["uuid"],
                            "encryption": "none",
                            "flow": flow,
                        }
                    ],
                }
            ]
        },
        "streamSettings": _transport(server),
    }


def _trojan_outbound(server: Dict, tag: str = "trojan-main") -> Dict:
    return {
        "tag": tag,
        "protocol": "trojan",
        "settings": {
            "servers": [
                {
                    "address": server["address"],
                    "port": server["port"],
                    "password": server["uuid"],
                }
            ]
        },
        "streamSettings": _transport(server),
    }


def _hysteria_outbound(server: Dict, tag: str = "hysteria-main") -> Dict:
    return {
        "tag": tag,
        "protocol": "hysteria",
        "settings": {
            "version": 2,
            "address": server["address"],
            "port": server["port"],
        },
        "streamSettings": {
            "network": "hysteria",
            "security": "tls",
            "tlsSettings": {
                "serverName": server["sni"] or server["address"],
                "fingerprint": server["fingerprint"] or "chrome",
                "allowInsecure": False,
            },
            "hysteriaSettings": {
                "version": 2,
                "auth": server["uuid"],
                "udpIdleTimeout": 60,
            },
        },
    }


def _inbounds(inbound: str) -> list:
    sniffing = {"enabled": True, "destOverride": ["http", "tls", "quic"]}
    if inbound == "tproxy":
        return [
            {
                "tag": "tproxy-in",
                "port": settings.tproxy_port,
                "protocol": "dokodemo-door",
                "settings": {"network": "tcp,udp", "followRedirect": True},
                "sniffing": sniffing,
                "streamSettings": {"sockopt": {"tproxy": "tproxy"}},
            }
        ]
    result = [
        {
            "tag": "socks-in",
            "listen": "0.0.0.0",
            "port": settings.socks_port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
            "sniffing": sniffing,
        },
        {
            "tag": "http-in",
            "listen": "0.0.0.0",
            "port": settings.http_port,
            "protocol": "http",
            "sniffing": sniffing,
        },
    ]
    if inbound == "both":
        result.append(
            {
                "tag": "tproxy-in",
                "port": settings.tproxy_port,
                "protocol": "dokodemo-door",
                "settings": {"network": "tcp,udp", "followRedirect": True},
                "sniffing": sniffing,
                "streamSettings": {"sockopt": {"tproxy": "tproxy"}},
            }
        )
    return result


def build_config(server: Dict, inbound: str = "proxy") -> dict:
    protocol = server.get("protocol", "vless")

    if protocol == "hysteria2":
        main = _hysteria_outbound(server)
    elif protocol == "trojan":
        main = _trojan_outbound(server)
    elif protocol == "vless":
        main = _vless_outbound(server)
    else:
        raise ValueError(f"unsupported protocol: {protocol}")

    config = {
        "log": {
            "loglevel": "warning",
            "access": "/var/log/xray/access.log",
            "error": "/var/log/xray/error.log",
        },
        "inbounds": _inbounds(inbound),
        "outbounds": [
            main,
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "network": "tcp,udp",
                    "outboundTag": main["tag"],
                }
            ],
        },
    }
    return config


def _server_outbound(server: Dict, tag: str) -> Dict:
    protocol = server.get("protocol", "vless")
    if protocol == "hysteria2":
        return _hysteria_outbound(server, tag)
    if protocol == "trojan":
        return _trojan_outbound(server, tag)
    if protocol == "vless":
        return _vless_outbound(server, tag)
    raise ValueError(f"unsupported protocol: {protocol}")


def build_multi_config(default_server: Optional[Dict], profiles: list[dict]) -> dict:
    """Основной выход + отдельные TPROXY inbound/outbound для PPP-профилей."""
    config = build_config(default_server, inbound=settings.inbound_mode) if default_server else {
        "log": {"loglevel": "warning"},
        "inbounds": _inbounds("tproxy"),
        "outbounds": [{"tag": "block", "protocol": "blackhole"}],
        "routing": {"domainStrategy": "AsIs", "rules": [
            {"type": "field", "network": "tcp,udp", "outboundTag": "block"}
        ]},
    }
    sniffing = {"enabled": True, "destOverride": ["http", "tls", "quic"]}
    profile_rules = []
    profile_outbounds = []
    for profile in profiles:
        profile_id = int(profile["id"])
        inbound_tag = f"tproxy-profile-{profile_id}"
        outbound_tag = f"profile-{profile_id}"
        config["inbounds"].append(
            {
                "tag": inbound_tag,
                "port": int(profile["tproxy_port"]),
                "protocol": "dokodemo-door",
                "settings": {"network": "tcp,udp", "followRedirect": True},
                "sniffing": sniffing,
                "streamSettings": {"sockopt": {"tproxy": "tproxy"}},
            }
        )
        profile_outbounds.append(
            _server_outbound(profile["server"], outbound_tag) if profile.get("server")
            else {"tag": outbound_tag, "protocol": "blackhole"}
        )
        profile_rules.append(
            {
                "type": "field",
                "inboundTag": [inbound_tag],
                "network": "tcp,udp",
                "outboundTag": outbound_tag,
            }
        )
    # Специфичные правила должны идти раньше общего правила основного выхода.
    config["outbounds"] = profile_outbounds + config["outbounds"]
    config["routing"]["rules"] = profile_rules + config["routing"]["rules"]
    return config


def write_staging(config: Dict) -> str:
    settings.generated_dir.mkdir(parents=True, exist_ok=True)
    path = settings.xray_staging_path
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    return str(path)


def test_config(config: Dict) -> Tuple[bool, str]:
    if not settings.xray_test_cmd:
        return True, ""
    try:
        with tempfile.TemporaryDirectory(prefix="xray-config-test-") as folder:
            from pathlib import Path
            staging = Path(folder) / "config.json"
            staging.write_text(json.dumps(config), encoding="utf-8")
            cmd = shlex.split(settings.xray_test_cmd) + [str(staging)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return False, "xray binary not found"
    except subprocess.TimeoutExpired:
        return False, "xray -test timed out"
    if res.returncode != 0:
        return False, (res.stderr or res.stdout).strip()[-2000:]
    return True, ""


def _backup_current() -> None:
    if not settings.xray_config_path.exists():
        return
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.backups_dir / f"config.{_timestamp()}.json"
    shutil.copy2(settings.xray_config_path, dest)


def reload() -> Tuple[bool, str]:
    if not settings.xray_reload_cmd:
        return True, ""
    try:
        res = subprocess.run(
            settings.xray_reload_cmd.split(), capture_output=True, text=True, timeout=60
        )
    except FileNotFoundError:
        return False, "reload command not found"
    except subprocess.TimeoutExpired:
        return False, "reload timed out"
    if res.returncode != 0:
        return False, (res.stderr or res.stdout).strip()[-2000:]
    return True, ""


def apply_config(config: Dict) -> Tuple[bool, str]:
    with APPLY_LOCK:
        return _apply_config_locked(config)


def _apply_config_locked(config: Dict) -> Tuple[bool, str]:
    if current_config() == config and process_active():
        return True, ""
    ok, err = test_config(config)
    if not ok:
        return False, f"xray -test: {err}"

    _backup_current()
    old = current_config()
    settings.xray_config_path.parent.mkdir(parents=True, exist_ok=True)
    settings.xray_config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))

    ok, err = reload()
    if not ok:
        if old is not None:
            settings.xray_config_path.write_text(json.dumps(old, indent=2, ensure_ascii=False))
            reload()
        return False, f"reload failed, rolled back: {err}"
    return True, ""


def current_config() -> Optional[dict]:
    if not settings.xray_config_path.exists():
        return None
    try:
        return json.loads(settings.xray_config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def process_active() -> bool:
    try:
        res = subprocess.run(
            ["systemctl", "is-active", "xray"], capture_output=True, text=True, timeout=15
        )
        return res.returncode == 0 and res.stdout.strip() == "active"
    except FileNotFoundError:
        return False
