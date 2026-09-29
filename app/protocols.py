import base64
from typing import Dict, List, Tuple
from urllib.parse import parse_qs, unquote, urlencode, urlunsplit

from .schemas import ServerCreate

SUPPORTED_SECURITY = ("reality", "tls", "none")
SUBSCRIPTION_UA = "curl/8.5.0"


def _split_host_port(value: str) -> Tuple[str, int]:
    value = value.strip()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        port_str = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, port_str = value.partition(":")
    if not host:
        raise ValueError("missing host")
    try:
        port = int(port_str) if port_str else 443
    except ValueError:
        raise ValueError("invalid port") from None
    if not (1 <= port <= 65535):
        raise ValueError("invalid port")
    return host, port


def _qs(query: str) -> Dict[str, str]:
    return {k: v[0] for k, v in parse_qs(query).items()}


def fetch_subscription(url: str, timeout: float = 30.0) -> str:
    """Скачивает подписку по URL, возвращает текст."""
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": SUBSCRIPTION_UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def decode_subscription(content: str) -> List[str]:
    """Разбивает содержимое подписки на строки share-ссылок (base64 разворачивается)."""
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    if len(lines) == 1 and not lines[0].startswith(("vless://", "trojan://", "hysteria2://", "hy2://")):
        try:
            decoded = base64.b64decode(lines[0]).decode("utf-8", errors="replace")
            lines = [l.strip() for l in decoded.splitlines() if l.strip()]
        except Exception:
            pass
    return lines


def parse_subscription_url(raw: str) -> List[ServerCreate]:
    """Загружает подписку по URL и парсит все серверы внутри."""
    content = fetch_subscription(raw)
    servers = []
    for line in decode_subscription(content):
        try:
            servers.append(parse_share_url(line))
        except ValueError:
            continue
    return servers


def parse_share_url(raw: str) -> ServerCreate:
    raw = raw.strip()
    scheme = raw.split("://", 1)[0].lower()
    if scheme == "vless":
        return parse_vless_url(raw)
    if scheme == "trojan":
        return parse_trojan_url(raw)
    if scheme in ("hysteria2", "hy2"):
        return parse_hysteria2_url(raw)
    raise ValueError(f"unsupported protocol: {scheme or '?'}")


def parse_vless_url(raw: str) -> ServerCreate:
    if not raw.lower().startswith("vless://"):
        raise ValueError("not a VLESS URL")
    rest = raw[len("vless://"):]
    if "@" not in rest:
        raise ValueError("missing @uuid@host")
    user_part, _, rest = rest.partition("@")
    uuid, _, _ = user_part.partition(":")
    rest, _, fragment = rest.partition("#")
    rest, _, query = rest.partition("?")

    address, port = _split_host_port(rest)
    qs = _qs(query)
    _check_security(qs.get("security", "reality"))

    name = unquote(fragment or "") or address
    return ServerCreate(
        name=name[:64],
        address=address,
        port=port,
        uuid=uuid,
        protocol="vless",
        flow=qs.get("flow", "xtls-rprx-vision"),
        network=qs.get("type", "tcp"),
        security=qs.get("security", "reality"),
        sni=qs.get("sni", ""),
        reality_public_key=qs.get("pbk", ""),
        reality_short_id=qs.get("sid", ""),
        fingerprint=qs.get("fp", "chrome"),
        path=qs.get("path", ""),
        mode=qs.get("mode", "auto"),
        service_name=qs.get("serviceName", qs.get("service", "")),
        alpn=qs.get("alpn", "h2,http/1.1"),
        host=qs.get("host", qs.get("authority", "")),
        enabled=True,
        priority=100,
    )


def parse_trojan_url(raw: str) -> ServerCreate:
    if not raw.lower().startswith("trojan://"):
        raise ValueError("not a Trojan URL")
    rest = raw[len("trojan://"):]
    if "@" not in rest:
        raise ValueError("missing @password@host")
    password, _, rest = rest.partition("@")
    rest, _, fragment = rest.partition("#")
    rest, _, query = rest.partition("?")

    address, port = _split_host_port(rest)
    qs = _qs(query)
    security = qs.get("security", "tls")
    _check_security(security)

    name = unquote(fragment or "") or address
    return ServerCreate(
        name=name[:64],
        address=address,
        port=port,
        uuid=password,
        protocol="trojan",
        flow="",
        network=qs.get("type", "tcp"),
        security=security,
        sni=qs.get("sni", address),
        reality_public_key=qs.get("pbk", ""),
        reality_short_id=qs.get("sid", ""),
        fingerprint=qs.get("fp", "chrome"),
        path=qs.get("path", ""),
        mode=qs.get("mode", "auto"),
        service_name=qs.get("serviceName", qs.get("service", "")),
        alpn=qs.get("alpn", "h2,http/1.1"),
        host=qs.get("host", qs.get("authority", "")),
        enabled=True,
        priority=100,
    )


def parse_hysteria2_url(raw: str) -> ServerCreate:
    lowered = raw.lower()
    if lowered.startswith("hysteria2://"):
        rest = raw[len("hysteria2://"):]
    elif lowered.startswith("hy2://"):
        rest = raw[len("hy2://"):]
    else:
        raise ValueError("not a Hysteria2 URL")

    if "@" in rest:
        password, _, rest = rest.partition("@")
    else:
        raise ValueError("missing @password@host")

    rest, _, fragment = rest.partition("#")
    rest, _, query = rest.partition("?")
    rest = rest.rstrip("/")

    address, port = _split_host_port(rest)
    qs = _qs(query)

    name = unquote(fragment or "") or address
    return ServerCreate(
        name=name[:64],
        address=address,
        port=port,
        uuid=password,
        protocol="hysteria2",
        flow="",
        network="hysteria",
        security="tls",
        sni=qs.get("sni", address),
        reality_public_key="",
        reality_short_id="",
        fingerprint=qs.get("fp", "chrome"),
        path="",
        mode="auto",
        service_name="",
        alpn="h2,http/1.1",
        host="",
        enabled=True,
        priority=100,
    )


def _check_security(security: str) -> None:
    if security not in SUPPORTED_SECURITY:
        raise ValueError(f"unsupported security: {security}")


def build_share_url(server: dict) -> str:
    protocol = server.get("protocol", "vless")
    if protocol == "vless":
        return _build_vless_url(server)
    if protocol == "trojan":
        return _build_trojan_url(server)
    if protocol == "hysteria2":
        return _build_hysteria2_url(server)
    raise ValueError(f"unsupported protocol: {protocol}")


def _netloc(server: dict) -> str:
    host = server["address"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{server['port']}"


def _build_vless_url(server: dict) -> str:
    qs = {
        "encryption": "none",
        "security": server["security"],
        "type": server["network"],
    }
    if server.get("flow"):
        qs["flow"] = server["flow"]
    if server.get("sni"):
        qs["sni"] = server["sni"]
    if server.get("fingerprint"):
        qs["fp"] = server["fingerprint"]
    if server.get("reality_public_key"):
        qs["pbk"] = server["reality_public_key"]
    if server.get("reality_short_id"):
        qs["sid"] = server["reality_short_id"]
    if server.get("path"):
        qs["path"] = server["path"]
    if server.get("service_name"):
        qs["serviceName"] = server["service_name"]
    if (server.get("mode") or "auto") != "auto":
        qs["mode"] = server["mode"]
    if server.get("alpn") and server.get("alpn") != "h2,http/1.1":
        qs["alpn"] = server["alpn"]
    if server.get("host"):
        qs["host"] = server["host"]
    return urlunsplit(
        ("vless", f"{server['uuid']}:none@{_netloc(server)}", "", urlencode(qs), server["name"])
    )


def _build_trojan_url(server: dict) -> str:
    qs = {
        "type": server["network"],
        "security": server["security"],
    }
    if server.get("sni"):
        qs["sni"] = server["sni"]
    if server.get("fingerprint"):
        qs["fp"] = server["fingerprint"]
    if server.get("reality_public_key"):
        qs["pbk"] = server["reality_public_key"]
    if server.get("reality_short_id"):
        qs["sid"] = server["reality_short_id"]
    if server.get("alpn") and server.get("alpn") != "h2,http/1.1":
        qs["alpn"] = server["alpn"]
    return urlunsplit(
        ("trojan", f"{server['uuid']}@{_netloc(server)}", "", urlencode(qs), server["name"])
    )


def _build_hysteria2_url(server: dict) -> str:
    qs = {}
    if server.get("sni"):
        qs["sni"] = server["sni"]
    return urlunsplit(
        ("hysteria2", f"{server['uuid']}@{_netloc(server)}", "", urlencode(qs), server["name"])
    )
