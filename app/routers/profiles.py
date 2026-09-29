from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import profiles
from ..security import require_auth

router = APIRouter(prefix="/api/profiles", tags=["profiles"], dependencies=[Depends(require_auth)])


class ProfileIn(BaseModel):
    name: str
    username: str
    local_ip: str
    prefix: int = 24
    interface: str = "eth0"
    server_id: int
    backup_server_id: int | None = None
    enabled: bool = True


@router.get("")
def profile_list():
    return profiles.list_profiles()


@router.post("")
def profile_add(body: ProfileIn):
    ok, message, profile = profiles.create_profile(body.model_dump())
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message, "profile": profile}


@router.put("/{profile_id}")
def profile_update(profile_id: int, body: ProfileIn):
    ok, message, profile = profiles.update_profile(profile_id, body.model_dump())
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message, "profile": profile}


@router.delete("/{profile_id}")
def profile_delete(profile_id: int):
    ok, message = profiles.delete_profile(profile_id)
    if not ok:
        raise HTTPException(status_code=404, detail=message)
    return {"message": message}


@router.post("/apply")
def profile_apply():
    ok, message = profiles.apply_runtime()
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}
