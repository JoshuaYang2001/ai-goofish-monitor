"""Tenant-isolated filesystem layout."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from src.tenancy.context import DEFAULT_TENANT_ID, current_tenant_id


TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
TENANT_DIRECTORIES = (
    "data",
    "state",
    "logs",
    "images",
    "jsonl",
    "price_history",
)


def validate_tenant_id(tenant_id: str) -> str:
    normalized = str(tenant_id or "").strip().lower()
    if not TENANT_ID_PATTERN.fullmatch(normalized):
        raise ValueError("租户标识只能包含小写字母、数字、下划线或短横线")
    return normalized


def tenant_root(tenant_id: str | None = None) -> Path:
    resolved_id = validate_tenant_id(tenant_id or current_tenant_id(required=False))
    base = Path(os.getenv("TENANT_DATA_ROOT", "data/tenants"))
    return base / resolved_id


def tenant_path(relative_path: str, tenant_id: str | None = None) -> str:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("租户文件路径必须是安全的相对路径")
    return str(tenant_root(tenant_id) / relative)


def tenant_database_path(tenant_id: str | None = None) -> str:
    return tenant_path("data/app.sqlite3", tenant_id)


def ensure_tenant_workspace(tenant_id: str) -> Path:
    root = tenant_root(tenant_id)
    for directory in TENANT_DIRECTORIES:
        (root / directory).mkdir(parents=True, exist_ok=True)

    env_file = root / ".env"
    env_file.touch(exist_ok=True)

    if tenant_id == DEFAULT_TENANT_ID:
        _link_or_copy_legacy_workspace(root)
    return root


def _link_or_copy_legacy_workspace(root: Path) -> None:
    """Seed the default tenant from legacy files without deleting originals."""
    database_target = root / "data" / "app.sqlite3"
    legacy_database = Path(os.getenv("APP_DATABASE_FILE", "data/app.sqlite3"))
    if legacy_database.exists() and not database_target.exists():
        shutil.copy2(legacy_database, database_target)

    for filename in ("config.json", "xianyu_state.json"):
        source = Path(filename)
        target = root / filename
        if source.exists() and not target.exists():
            shutil.copy2(source, target)

    for directory in ("state", "logs", "jsonl", "images", "price_history"):
        source_dir = Path(directory)
        target_dir = root / directory
        if not source_dir.is_dir():
            continue
        for source in source_dir.iterdir():
            target = target_dir / source.name
            if source.is_file() and not target.exists():
                shutil.copy2(source, target)
