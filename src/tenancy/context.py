"""Request and worker-local tenant context."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator


DEFAULT_TENANT_ID = "default"
_tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    user_id: int | None = None
    username: str | None = None
    role: str | None = None


def current_tenant_id(*, required: bool = True) -> str:
    tenant_id = _tenant_id_var.get() or os.getenv("TENANT_ID")
    if tenant_id:
        return tenant_id
    if required:
        raise RuntimeError("当前操作缺少租户上下文")
    return DEFAULT_TENANT_ID


def has_tenant_context() -> bool:
    return bool(_tenant_id_var.get() or os.getenv("TENANT_ID"))


def set_tenant_id(tenant_id: str) -> Token:
    normalized = str(tenant_id or "").strip()
    if not normalized:
        raise ValueError("tenant_id 不能为空")
    return _tenant_id_var.set(normalized)


def reset_tenant_id(token: Token) -> None:
    _tenant_id_var.reset(token)


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[None]:
    token = set_tenant_id(tenant_id)
    try:
        yield
    finally:
        reset_tenant_id(token)
