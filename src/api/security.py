"""FastAPI authentication dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.services.auth_service import Identity, verify_access_token
from src.tenancy.context import reset_tenant_id, set_tenant_id


bearer_scheme = HTTPBearer(auto_error=False)


async def current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Identity:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少登录凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def tenant_identity(
    identity: Identity = Depends(current_identity),
) -> AsyncIterator[Identity]:
    token = set_tenant_id(identity.tenant_id)
    try:
        yield identity
    finally:
        reset_tenant_id(token)


async def require_superadmin(
    identity: Identity = Depends(current_identity),
) -> Identity:
    from src.services.auth_service import control_connection

    with control_connection() as conn:
        row = conn.execute(
            "SELECT is_superadmin FROM users WHERE id = ?", (identity.user_id,)
        ).fetchone()
    if not row or not bool(row["is_superadmin"]):
        raise HTTPException(status_code=403, detail="需要平台管理员权限")
    return identity
