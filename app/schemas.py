from typing import Optional

from pydantic import BaseModel, Field, field_validator

SUPPORTED_PROTOCOLS = ("vless", "trojan", "hysteria2")
SUPPORTED_NETWORK = ("tcp", "ws", "grpc", "xhttp", "kcp", "http", "quic", "hysteria")
SUPPORTED_SECURITY = ("reality", "tls", "none")


class ServerBase(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(default=443, ge=1, le=65535)
    uuid: str = Field(min_length=1, max_length=64)
    protocol: str = "vless"
    flow: str = "xtls-rprx-vision"
    network: str = "tcp"
    security: str = "reality"
    sni: str = ""
    reality_public_key: str = ""
    reality_short_id: str = ""
    fingerprint: str = "chrome"
    path: str = ""
    mode: str = "auto"
    service_name: str = ""
    alpn: str = "h2,http/1.1"
    host: str = ""
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=9999)

    @field_validator("address")
    @classmethod
    def _address(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("address required")
        return v

    @field_validator("reality_short_id")
    @classmethod
    def _short_id(cls, v: str) -> str:
        v = v.strip()
        if v and len(v) > 16:
            raise ValueError("shortId too long")
        return v

    @field_validator("protocol")
    @classmethod
    def _protocol(cls, v: str) -> str:
        if v not in SUPPORTED_PROTOCOLS:
            raise ValueError(f"unsupported protocol: {v}")
        return v

    @field_validator("network")
    @classmethod
    def _network(cls, v: str) -> str:
        if v not in SUPPORTED_NETWORK:
            raise ValueError(f"unsupported network: {v}")
        return v

    @field_validator("security")
    @classmethod
    def _security(cls, v: str) -> str:
        if v not in SUPPORTED_SECURITY:
            raise ValueError(f"unsupported security: {v}")
        return v


class ServerCreate(ServerBase):
    pass


class ServerUpdate(ServerBase):
    pass


class ServerOut(ServerBase):
    id: int
    created_at: str
    updated_at: str
    last_health: Optional[str] = None
    last_health_at: Optional[str] = None
    best_latency_ms: Optional[float] = None
    latest_latency_ms: Optional[float] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class TokenResponse(BaseModel):
    token: str


class MessageResponse(BaseModel):
    message: str


class ActivateResponse(BaseModel):
    activated: bool
    server_id: Optional[int] = None
    server_name: Optional[str] = None
    message: str = ""


class HealthOut(BaseModel):
    server_id: int
    ok: bool
    latency_ms: Optional[float] = None
    error: str = ""


class StatusOut(BaseModel):
    active_server_id: Optional[int] = None
    active_server_name: Optional[str] = None
    xray_config_valid: bool
    xray_process: bool
    health: Optional[HealthOut] = None
