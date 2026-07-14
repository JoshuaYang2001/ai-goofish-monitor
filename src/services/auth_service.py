"""Central user authentication and tenant membership service."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from src.tenancy.paths import ensure_tenant_workspace, validate_tenant_id


CONTROL_DATABASE_PATH = os.getenv("CONTROL_DATABASE_FILE", "data/control.sqlite3")
ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "900"))
REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", "604800"))
PASSWORD_ITERATIONS = 600_000


@dataclass(frozen=True)
class Identity:
    user_id: int
    username: str
    tenant_id: str
    tenant_name: str
    role: str


@contextmanager
def control_connection() -> Iterator[sqlite3.Connection]:
    path = Path(CONTROL_DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def bootstrap_control_storage() -> None:
    with control_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_superadmin INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tenant_memberships (
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                role TEXT NOT NULL DEFAULT 'owner',
                PRIMARY KEY (tenant_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS refresh_sessions (
                jti_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_memberships_user ON tenant_memberships(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON refresh_sessions(user_id, tenant_id);
            """
        )
        conn.commit()

    default_tenant = os.getenv("DEFAULT_TENANT_ID", "default")
    default_name = os.getenv("DEFAULT_TENANT_NAME", "默认租户")
    default_user = os.getenv("WEB_USERNAME", "admin")
    default_password = os.getenv("WEB_PASSWORD", "admin123")
    create_tenant_with_owner(
        default_tenant,
        default_name,
        default_user,
        default_password,
        is_superadmin=True,
        if_not_exists=True,
    )


def create_tenant_with_owner(
    tenant_id: str,
    tenant_name: str,
    username: str,
    password: str,
    *,
    is_superadmin: bool = False,
    if_not_exists: bool = False,
) -> Identity:
    normalized_tenant_id = validate_tenant_id(tenant_id)
    normalized_username = username.strip()
    if len(normalized_username) < 3 or len(normalized_username) > 80:
        raise ValueError("用户名长度必须在 3 到 80 个字符之间")
    if len(password) < 8:
        raise ValueError("密码至少需要 8 个字符")

    now = int(time.time())
    with control_connection() as conn:
        existing_tenant = conn.execute(
            "SELECT id FROM tenants WHERE id = ?", (normalized_tenant_id,)
        ).fetchone()
        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?", (normalized_username,)
        ).fetchone()
        if (existing_tenant or existing_user) and not if_not_exists:
            raise ValueError("租户标识或用户名已存在")

        conn.execute(
            "INSERT OR IGNORE INTO tenants (id, name, status, created_at) VALUES (?, ?, 'active', ?)",
            (normalized_tenant_id, tenant_name.strip() or normalized_tenant_id, now),
        )
        if existing_user:
            user_id = int(existing_user["id"])
        else:
            cursor = conn.execute(
                """
                INSERT INTO users (username, password_hash, is_superadmin, status, created_at)
                VALUES (?, ?, ?, 'active', ?)
                """,
                (normalized_username, hash_password(password), int(is_superadmin), now),
            )
            user_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT OR IGNORE INTO tenant_memberships (tenant_id, user_id, role) VALUES (?, ?, 'owner')",
            (normalized_tenant_id, user_id),
        )
        row = conn.execute(
            """
            SELECT u.id AS user_id, u.username, t.id AS tenant_id, t.name AS tenant_name,
                   tm.role
            FROM users u
            JOIN tenant_memberships tm ON tm.user_id = u.id
            JOIN tenants t ON t.id = tm.tenant_id
            WHERE u.id = ? AND t.id = ?
            """,
            (user_id, normalized_tenant_id),
        ).fetchone()
        conn.commit()

    ensure_tenant_workspace(normalized_tenant_id)
    return Identity(**dict(row))


def register_tenant_member(
    admin_username: str,
    admin_password: str,
    username: str,
    password: str,
) -> Identity:
    """使用平台管理员或租户所有者凭证注册同租户普通成员。"""
    normalized_username = username.strip()
    if len(normalized_username) < 3 or len(normalized_username) > 80:
        raise ValueError("用户名长度必须在 3 到 80 个字符之间")
    if len(password) < 8:
        raise ValueError("密码至少需要 8 个字符")

    admin_identity = authenticate(admin_username, admin_password)
    if admin_identity is None:
        raise PermissionError("管理员账号、密码不正确或无注册权限")

    now = int(time.time())
    with control_connection() as conn:
        admin_row = conn.execute(
            """
            SELECT is_superadmin
            FROM users
            WHERE id = ? AND status = 'active'
            """,
            (admin_identity.user_id,),
        ).fetchone()
        is_authorized_admin = bool(
            admin_row
            and (
                bool(admin_row["is_superadmin"])
                or admin_identity.role == "owner"
            )
        )
        if not is_authorized_admin:
            raise PermissionError("管理员账号、密码不正确或无注册权限")

        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (normalized_username,),
        ).fetchone()
        if existing_user:
            raise ValueError("用户名已存在")

        try:
            cursor = conn.execute(
                """
                INSERT INTO users (
                    username, password_hash, is_superadmin, status, created_at
                ) VALUES (?, ?, 0, 'active', ?)
                """,
                (normalized_username, hash_password(password), now),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在") from exc
        user_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role)
            VALUES (?, ?, 'member')
            """,
            (admin_identity.tenant_id, user_id),
        )
        row = conn.execute(
            """
            SELECT u.id AS user_id, u.username, t.id AS tenant_id,
                   t.name AS tenant_name, tm.role
            FROM users u
            JOIN tenant_memberships tm ON tm.user_id = u.id
            JOIN tenants t ON t.id = tm.tenant_id
            WHERE u.id = ? AND t.id = ?
            """,
            (user_id, admin_identity.tenant_id),
        ).fetchone()
        conn.commit()

    return Identity(**dict(row))


def authenticate(username: str, password: str, tenant_id: str | None = None) -> Identity | None:
    params: list[object] = [username.strip()]
    tenant_filter = ""
    if tenant_id:
        tenant_filter = " AND t.id = ?"
        params.append(validate_tenant_id(tenant_id))
    with control_connection() as conn:
        row = conn.execute(
            f"""
            SELECT u.id AS user_id, u.username, u.password_hash,
                   t.id AS tenant_id, t.name AS tenant_name, tm.role
            FROM users u
            JOIN tenant_memberships tm ON tm.user_id = u.id
            JOIN tenants t ON t.id = tm.tenant_id
            WHERE u.username = ? AND u.status = 'active' AND t.status = 'active'
            {tenant_filter}
            ORDER BY t.created_at ASC
            LIMIT 1
            """,
            params,
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    payload = dict(row)
    payload.pop("password_hash")
    return Identity(**payload)


def issue_token_pair(identity: Identity) -> dict[str, object]:
    now = int(time.time())
    common = {
        "sub": identity.user_id,
        "username": identity.username,
        "tenant_id": identity.tenant_id,
        "tenant_name": identity.tenant_name,
        "role": identity.role,
        "iat": now,
    }
    access_token = _encode_token(
        {**common, "type": "access", "exp": now + ACCESS_TOKEN_TTL_SECONDS}
    )
    refresh_jti = secrets.token_urlsafe(32)
    refresh_token = _encode_token(
        {
            **common,
            "type": "refresh",
            "jti": refresh_jti,
            "exp": now + REFRESH_TOKEN_TTL_SECONDS,
        }
    )
    with control_connection() as conn:
        conn.execute(
            """
            INSERT INTO refresh_sessions (jti_hash, user_id, tenant_id, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                _hash_jti(refresh_jti),
                identity.user_id,
                identity.tenant_id,
                now + REFRESH_TOKEN_TTL_SECONDS,
            ),
        )
        conn.commit()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "tenant": {"id": identity.tenant_id, "name": identity.tenant_name},
        "user": {"id": identity.user_id, "username": identity.username, "role": identity.role},
    }


def verify_access_token(token: str) -> Identity:
    payload = _decode_token(token, expected_type="access")
    return _identity_from_payload(payload)


def rotate_refresh_token(token: str) -> dict[str, object]:
    payload = _decode_token(token, expected_type="refresh")
    jti_hash = _hash_jti(str(payload.get("jti", "")))
    now = int(time.time())
    with control_connection() as conn:
        row = conn.execute(
            """
            SELECT jti_hash FROM refresh_sessions
            WHERE jti_hash = ? AND revoked_at IS NULL AND expires_at > ?
            """,
            (jti_hash, now),
        ).fetchone()
        if not row:
            raise ValueError("刷新会话已失效")
        conn.execute(
            "UPDATE refresh_sessions SET revoked_at = ? WHERE jti_hash = ?",
            (now, jti_hash),
        )
        conn.commit()
    return issue_token_pair(_identity_from_payload(payload))


def revoke_refresh_token(token: str) -> None:
    payload = _decode_token(token, expected_type="refresh", allow_expired=True)
    with control_connection() as conn:
        conn.execute(
            "UPDATE refresh_sessions SET revoked_at = ? WHERE jti_hash = ?",
            (int(time.time()), _hash_jti(str(payload.get("jti", "")))),
        )
        conn.commit()


def list_tenants() -> list[dict[str, object]]:
    with control_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.name, t.status, t.created_at,
                   COUNT(tm.user_id) AS member_count
            FROM tenants t
            LEFT JOIN tenant_memberships tm ON tm.tenant_id = t.id
            GROUP BY t.id
            ORDER BY t.created_at ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _b64decode(salt), int(iterations)
        )
        return hmac.compare_digest(candidate, _b64decode(digest))
    except (TypeError, ValueError):
        return False


def _identity_from_payload(payload: dict[str, object]) -> Identity:
    user_id = int(payload["sub"])
    tenant_id = str(payload["tenant_id"])
    with control_connection() as conn:
        row = conn.execute(
            """
            SELECT u.id AS user_id, u.username, t.id AS tenant_id, t.name AS tenant_name,
                   tm.role
            FROM users u
            JOIN tenant_memberships tm ON tm.user_id = u.id
            JOIN tenants t ON t.id = tm.tenant_id
            WHERE u.id = ? AND t.id = ? AND u.status = 'active' AND t.status = 'active'
            """,
            (user_id, tenant_id),
        ).fetchone()
    if not row:
        raise ValueError("用户或租户已停用")
    return Identity(**dict(row))


def _encode_token(payload: dict[str, object]) -> str:
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    signing_input = f"{header}.{body}".encode()
    signature = hmac.new(_secret_key(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64encode(signature)}"


def _decode_token(
    token: str,
    *,
    expected_type: str,
    allow_expired: bool = False,
) -> dict[str, object]:
    try:
        header, body, signature = token.split(".", 2)
        signing_input = f"{header}.{body}".encode()
        expected = hmac.new(_secret_key(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            raise ValueError("Token 签名无效")
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Token 无效") from exc
    if payload.get("type") != expected_type:
        raise ValueError("Token 类型无效")
    if not allow_expired and int(payload.get("exp", 0)) <= int(time.time()):
        raise ValueError("Token 已过期")
    return payload


def _secret_key() -> bytes:
    configured = os.getenv("AUTH_SECRET_KEY")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("AUTH_SECRET_KEY 至少需要 32 个字符")
        return configured.encode()
    secret_path = Path(os.getenv("AUTH_SECRET_FILE", "data/auth_secret.key"))
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if not secret_path.exists():
        secret_path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        secret_path.chmod(0o600)
    return secret_path.read_text(encoding="utf-8").strip().encode()


def _hash_jti(jti: str) -> str:
    return hashlib.sha256(jti.encode()).hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
