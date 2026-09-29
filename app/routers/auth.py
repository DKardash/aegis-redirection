from fastapi import APIRouter, Depends, HTTPException, Request

from ..schemas import ChangePasswordRequest, LoginRequest, MessageResponse, TokenResponse
from ..security import (
    change_admin_password,
    check_rate_limit,
    create_session,
    delete_token,
    require_auth,
    verify_credentials,
)
from ..db import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    check_rate_limit(request)
    if not verify_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = create_session()
    audit("login", body.username)
    return TokenResponse(token=token)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token:
        delete_token(token)
    return MessageResponse(message="ok")


@router.get("/me", response_model=MessageResponse, dependencies=[Depends(require_auth)])
async def me():
    return MessageResponse(message="ok")


@router.post(
    "/password",
    response_model=MessageResponse,
    dependencies=[Depends(require_auth)],
)
async def change_password(body: ChangePasswordRequest):
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="подтверждение пароля не совпадает")
    ok, message = change_admin_password(body.current_password, body.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    audit("admin_password_change", "all sessions revoked")
    return MessageResponse(message=message)
