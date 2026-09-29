import base64
import ipaddress
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import settings

WG_DIR = Path("/etc/wireguard")
WG_CONF = WG_DIR / "wg0.conf"
WG_INTERFACE = "wg0"
WG_SERVICE = "wg-quick@wg0"
TPROXY_SERVICE = "xray-tproxy"

_PUBKEY_RE = re.compile(r"^[A-Za-z0-9+/]{43}=$")


def _run(cmd: List[str], timeout: int = 15) -> Tuple[int, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, (res.stdout or res.stderr).strip()
    except FileNotFoundError:
        return 1, "binary not found"
    except subprocess.TimeoutExpired:
        return 1, "timeout"


def _is_active(unit: str) -> bool:
    code, out = _run(["systemctl", "is-active", unit])
    return code == 0 and out == "active"


def _iface_up() -> bool:
    code, _ = _run(["ip", "link", "show", WG_INTERFACE])
    return code == 0


def parse_conf(path: Path = WG_CONF) -> dict:
    data: Dict[str, dict] = {"interface": {}, "peers": []}
    if not path.exists():
        return data
    section: Optional[str] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            name = line[1:].rstrip("]").strip().lower()
            section = "interface" if name == "interface" else "peer"
            if section == "peer":
                data["peers"].append({})
            continue
        if "=" in line and section:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if section == "interface":
                data["interface"][key] = value
            elif section == "peer" and data["peers"]:
                data["peers"][-1][key] = value
    return data


def _wg_key(raw: str) -> Tuple[bool, str]:
    if not _PUBKEY_RE.match(raw or ""):
        return False, "invalid key: expected 44-char base64"
    try:
        base64.b64decode(raw, validate=True)
    except Exception:  # noqa: BLE001
        return False, "invalid key: not base64"
    return True, ""


def _cidr(raw: str) -> Tuple[bool, str]:
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ipaddress.ip_network(part, strict=False)
        except ValueError:
            return False, f"invalid ip/prefix: {part}"
    return True, ""


def _endpoint(raw: str) -> Tuple[bool, str]:
    if not raw:
        return True, ""
    if ":" not in raw:
        return False, "endpoint must be host:port"
    host, _, port = raw.rpartition(":")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host:
        return False, "endpoint missing host"
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        return False, "endpoint port invalid"
    return True, ""


def _to_wg_interface(data: dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    priv = (data.get("private_key") or "").strip()
    if priv:
        ok, err = _wg_key(priv)
        if not ok:
            raise ValueError(err)
        out["PrivateKey"] = priv
    address = (data.get("address") or "").strip()
    if address:
        for part in address.split(","):
            try:
                ipaddress.ip_interface(part.strip())
            except ValueError as e:
                raise ValueError(f"invalid interface address: {part}") from e
        out["Address"] = address
    port = data.get("listen_port")
    if port is not None:
        p = int(port)
        if not 1 <= p <= 65535:
            raise ValueError("listen port invalid")
        out["ListenPort"] = str(p)
    mtu = data.get("mtu")
    if mtu:
        out["MTU"] = str(int(mtu))
    return out


def _to_wg_peer(peer: dict) -> Dict[str, str]:
    pub = (peer.get("public_key") or "").strip()
    if not pub:
        raise ValueError("public_key required")
    ok, err = _wg_key(pub)
    if not ok:
        raise ValueError(err)
    out = {"PublicKey": pub}
    allowed = (peer.get("allowed_ips") or "").strip()
    if allowed:
        ok, err = _cidr(allowed)
        if not ok:
            raise ValueError(err)
        out["AllowedIPs"] = allowed
    endpoint = (peer.get("endpoint") or "").strip()
    if endpoint:
        ok, err = _endpoint(endpoint)
        if not ok:
            raise ValueError(err)
        out["Endpoint"] = endpoint
    ka = peer.get("persistent_keepalive")
    if ka is not None and str(ka) != "":
        k = int(ka)
        if not 0 <= k <= 65535:
            raise ValueError("persistent_keepalive invalid")
        if k:
            out["PersistentKeepalive"] = str(k)
    return out


def serialize(cfg: dict) -> str:
    iface = _to_wg_interface(cfg.get("interface", {}))
    if not iface.get("PrivateKey"):
        raise ValueError("interface private_key is required")
    if not iface.get("Address"):
        raise ValueError("interface address is required")
    lines = ["[Interface]"]
    order = ("PrivateKey", "Address", "ListenPort", "MTU")
    for key in order:
        if key in iface:
            lines.append(f"{key} = {iface[key]}")
    for peer in cfg.get("peers", []):
        lines.append("")
        lines.append("[Peer]")
        p = _to_wg_peer(peer)
        for key in ("PublicKey", "AllowedIPs", "Endpoint", "PersistentKeepalive"):
            if key in p:
                lines.append(f"{key} = {p[key]}")
    return "\n".join(lines) + "\n"


def _mask_private(raw: dict) -> dict:
    return raw


def _pubkey_from_private(private_key: str) -> str:
    try:
        res = subprocess.run(
            ["wg", "pubkey"], input=private_key, capture_output=True, text=True, timeout=15
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def read_status() -> dict:
    wg_bin = shutil.which("wg")
    conf_exists = WG_CONF.exists()
    cfg = parse_conf() if conf_exists else {"interface": {}, "peers": []}
    iface_up = _iface_up()

    private_key = cfg["interface"].get("PrivateKey", "")
    public_key = _pubkey_from_private(private_key) if conf_exists and private_key else ""

    dump: Dict[str, dict] = {}
    if wg_bin and iface_up:
        code, out = _run([wg_bin, "show", WG_INTERFACE, "dump"])
        if code == 0:
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) < 5:
                    continue
                dump[parts[0]] = {
                    "public_key": parts[0],
                    "endpoint": parts[2] or "",
                    "allowed_ips": parts[3] or "",
                    "last_handshake_sec": int(parts[4]) if parts[4].isdigit() else 0,
                    "rx_bytes": int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0,
                    "tx_bytes": int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 0,
                }

    interface = {
        "address": cfg["interface"].get("Address", ""),
        "listen_port": cfg["interface"].get("ListenPort", ""),
        "private_key_present": bool(cfg["interface"].get("PrivateKey")),
        "public_key": public_key,
    }
    peers = []
    for p in cfg["peers"]:
        pub = p.get("PublicKey", "")
        live = dump.get(pub, {})
        peers.append(
            {
                "public_key": pub,
                "endpoint": p.get("Endpoint", live.get("endpoint", "")),
                "allowed_ips": p.get("AllowedIPs", live.get("allowed_ips", "")),
                "persistent_keepalive": p.get("PersistentKeepalive", ""),
                "last_handshake_sec": live.get("last_handshake_sec", 0),
                "rx_bytes": live.get("rx_bytes", 0),
                "tx_bytes": live.get("tx_bytes", 0),
            }
        )

    return {
        "config_exists": conf_exists,
        "interface_up": iface_up,
        "services": {
            "wg_quick": "active" if _is_active(WG_SERVICE) else "inactive",
            "tproxy": "active" if _is_active(TPROXY_SERVICE) else "inactive",
        },
        "interface": interface,
        "peers": peers,
    }


def read_traffic() -> dict:
    wg_rx = wg_tx = 0
    wg_bin = shutil.which("wg")
    if wg_bin and _iface_up():
        code, out = _run([wg_bin, "show", WG_INTERFACE, "dump"])
        if code == 0:
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) < 8:
                    continue
                if parts[0] == "peer":
                    rx, tx = parts[6], parts[7]
                else:
                    rx, tx = parts[5], parts[6]
                if rx.isdigit():
                    wg_rx += int(rx)
                if tx.isdigit():
                    wg_tx += int(tx)

    proxy_pkts = proxy_bytes = 0
    code, out = _run(["iptables", "-t", "mangle", "-L", "XRAY", "-n", "-v", "-x"])
    if code == 0:
        for line in out.splitlines():
            if "TPROXY" in line:
                parts = line.split()
                if len(parts) >= 3 and parts[0].isdigit():
                    proxy_pkts = int(parts[0])
                    proxy_bytes = int(parts[1])

    return {
        "wg": {"rx_bytes": wg_rx, "tx_bytes": wg_tx},
        "proxied": {"pkts": proxy_pkts, "bytes": proxy_bytes},
    }


def _backup() -> Optional[Path]:
    if not WG_CONF.exists():
        return None
    WG_DIR.mkdir(parents=True, exist_ok=True)
    backup = WG_DIR / "wg0.conf.bak"
    backup.write_text(WG_CONF.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def _normalize_cfg(cfg: dict) -> dict:
    iface_src = cfg.get("interface", {})
    iface = {}
    for src, dst in (("PrivateKey", "private_key"), ("Address", "address"),
                     ("ListenPort", "listen_port"), ("MTU", "mtu")):
        v = iface_src.get(dst) or iface_src.get(src)
        if v:
            iface[dst] = v
    peers = []
    for p in cfg.get("peers", []):
        np = {}
        for src, dst in (("PublicKey", "public_key"), ("Endpoint", "endpoint"),
                         ("AllowedIPs", "allowed_ips"),
                         ("PersistentKeepalive", "persistent_keepalive")):
            v = p.get(dst) or p.get(src)
            if v is not None and v != "":
                np[dst] = v
        if np:
            peers.append(np)
    return {"interface": iface, "peers": peers}


def apply_config(data: dict) -> Tuple[bool, str]:
    if not shutil.which("wg"):
        return False, "wireguard-tools not installed"
    cfg = _normalize_cfg(data)
    if not cfg["interface"].get("private_key"):
        cfg["interface"]["private_key"] = _normalize_cfg(parse_conf())["interface"].get(
            "private_key", ""
        )

    backup = _backup()
    try:
        text = serialize(cfg)
    except ValueError as e:
        return False, str(e)

    WG_DIR.mkdir(parents=True, exist_ok=True)
    WG_CONF.write_text(text, encoding="utf-8")

    code, out = _run(["systemctl", "restart", WG_SERVICE])
    if code != 0 or not _is_active(WG_SERVICE):
        if backup and backup.exists():
            WG_CONF.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
            _run(["systemctl", "restart", WG_SERVICE])
        return False, f"wg-quick restart failed: {out}"
    return True, "config applied"
