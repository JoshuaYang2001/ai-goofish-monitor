"""Authentication and tenant provisioning routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.security import current_identity, require_superadmin
from src.services.auth_service import (
    Identity,
    authenticate,
    create_tenant_with_owner,
    issue_token_pair,
    list_tenants,
    register_tenant_member,
    revoke_refresh_token,
    rotate_refresh_token,
)


router = APIRouter(prefix="/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_id: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class RegisterRequest(BaseModel):
    admin_username: str = Field(min_length=3, max_length=80)
    admin_password: str = Field(min_length=1, max_length=256)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=256)


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=63)
    tenant_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=256)


@router.post("/login")
async def login(payload: LoginRequest):
    identity = authenticate(payload.username, payload.password, payload.tenant_id)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名、密码或租户不正确",
        )
    return issue_token_pair(identity)


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest):
    try:
        identity = register_tenant_member(
            payload.admin_username,
            payload.admin_password,
            payload.username,
            payload.password,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "message": "账号注册成功",
        "user": {
            "id": identity.user_id,
            "username": identity.username,
            "role": identity.role,
        },
        "tenant": {"id": identity.tenant_id, "name": identity.tenant_name},
    }


@router.post("/refresh")
async def refresh(payload: RefreshRequest):
    try:
        return rotate_refresh_token(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/logout", status_code=204)
async def logout(payload: RefreshRequest):
    try:
        revoke_refresh_token(payload.refresh_token)
    except ValueError:
        pass
    return None


@router.get("/me")
async def me(identity: Identity = Depends(current_identity)):
    return {
        "user": {
            "id": identity.user_id,
            "username": identity.username,
            "role": identity.role,
        },
        "tenant": {"id": identity.tenant_id, "name": identity.tenant_name},
    }


@admin_router.get("/tenants")
async def get_tenants(_: Identity = Depends(require_superadmin)):
    return {"tenants": list_tenants()}


@admin_router.post("/tenants", status_code=201)
async def create_tenant(
    payload: TenantCreateRequest,
    _: Identity = Depends(require_superadmin),
):
    try:
        identity = create_tenant_with_owner(
            payload.tenant_id,
            payload.tenant_name,
            payload.username,
            payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "tenant": {"id": identity.tenant_id, "name": identity.tenant_name},
        "owner": {"id": identity.user_id, "username": identity.username},
    }
