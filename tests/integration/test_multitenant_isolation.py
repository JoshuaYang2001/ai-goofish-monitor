from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes import accounts, auth, settings, tasks
from src.api.security import tenant_identity
from src.infrastructure.config.env_manager import env_manager
from src.services import auth_service
from src.services.auth_service import bootstrap_control_storage, create_tenant_with_owner


class _Scheduler:
    async def reload_jobs(self, _tasks):
        return None

    def get_next_run_time(self, _task_id):
        return None


def test_tenant_tasks_accounts_and_notifications_are_isolated(tmp_path, monkeypatch):
    tenant_root = tmp_path / "tenants"
    monkeypatch.setattr(auth_service, "CONTROL_DATABASE_PATH", str(tmp_path / "control.sqlite3"))
    monkeypatch.setenv("TENANT_DATA_ROOT", str(tenant_root))
    monkeypatch.setenv("AUTH_SECRET_FILE", str(tmp_path / "auth-secret"))
    monkeypatch.setattr(env_manager, "_env_file_override", None)

    bootstrap_control_storage()
    create_tenant_with_owner("tenant-a", "客户甲", "owner-a", "TenantA-2026")
    create_tenant_with_owner("tenant-b", "客户乙", "owner-b", "TenantB-2026")

    app = FastAPI()
    app.include_router(auth.router)
    protected = [Depends(tenant_identity)]
    app.include_router(tasks.router, dependencies=protected)
    app.include_router(accounts.router, dependencies=protected)
    app.include_router(settings.router, dependencies=protected)
    app.dependency_overrides[dependencies.get_scheduler_service] = lambda: _Scheduler()

    with TestClient(app) as client:
        def login(username: str, password: str) -> dict:
            response = client.post(
                "/auth/login",
                json={"username": username, "password": password},
            )
            assert response.status_code == 200
            return response.json()

        session_a = login("owner-a", "TenantA-2026")
        session_b = login("owner-b", "TenantB-2026")
        token_a = session_a["access_token"]
        token_b = session_b["access_token"]

        rotated = client.post(
            "/auth/refresh",
            json={"refresh_token": session_a["refresh_token"]},
        )
        assert rotated.status_code == 200
        assert client.post(
            "/auth/refresh",
            json={"refresh_token": session_a["refresh_token"]},
        ).status_code == 401
        rotated_session = rotated.json()
        token_a = rotated_session["access_token"]

        def headers(token: str) -> dict[str, str]:
            return {"Authorization": f"Bearer {token}"}

        for token, name, keyword in (
            (token_a, "甲的监控", "mac-a"),
            (token_b, "乙的监控", "camera-b"),
        ):
            response = client.post(
                "/api/tasks/",
                headers=headers(token),
                json={
                    "task_name": name,
                    "keyword": keyword,
                    "keyword_rules": [keyword],
                },
            )
            assert response.status_code == 200
            assert response.json()["task"]["id"] == 0

        assert [item["task_name"] for item in client.get("/api/tasks", headers=headers(token_a)).json()] == ["甲的监控"]
        assert [item["task_name"] for item in client.get("/api/tasks", headers=headers(token_b)).json()] == ["乙的监控"]
        assert client.get("/api/tasks").status_code == 401

        for token, marker in ((token_a, "tenant-a-cookie"), (token_b, "tenant-b-cookie")):
            response = client.post(
                "/api/accounts",
                headers=headers(token),
                json={"name": "primary", "content": f'{{"marker":"{marker}"}}'},
            )
            assert response.status_code == 200

        assert "tenant-a-cookie" in client.get("/api/accounts/primary", headers=headers(token_a)).json()["content"]
        assert "tenant-b-cookie" in client.get("/api/accounts/primary", headers=headers(token_b)).json()["content"]

        webhook_a = "https://open.feishu.cn/open-apis/bot/v2/hook/tenant-a"
        webhook_b = "https://open.feishu.cn/open-apis/bot/v2/hook/tenant-b"
        assert client.put(
            "/api/settings/notifications",
            headers=headers(token_a),
            json={"FEISHU_WEBHOOK_URL": webhook_a},
        ).status_code == 200
        assert client.put(
            "/api/settings/notifications",
            headers=headers(token_b),
            json={"FEISHU_WEBHOOK_URL": webhook_b},
        ).status_code == 200

    assert webhook_a in (tenant_root / "tenant-a" / ".env").read_text(encoding="utf-8")
    assert webhook_b not in (tenant_root / "tenant-a" / ".env").read_text(encoding="utf-8")
    assert webhook_b in (tenant_root / "tenant-b" / ".env").read_text(encoding="utf-8")
    assert (tenant_root / "tenant-a" / "data" / "app.sqlite3").exists()
    assert (tenant_root / "tenant-b" / "data" / "app.sqlite3").exists()


def test_non_default_tenant_does_not_inherit_global_feishu_webhook(
    tmp_path,
    monkeypatch,
):
    tenant_root = tmp_path / "tenants"
    monkeypatch.setattr(auth_service, "CONTROL_DATABASE_PATH", str(tmp_path / "control.sqlite3"))
    monkeypatch.setenv("TENANT_DATA_ROOT", str(tenant_root))
    monkeypatch.setenv("AUTH_SECRET_FILE", str(tmp_path / "auth-secret"))
    monkeypatch.setenv(
        "FEISHU_WEBHOOK_URL",
        "https://open.feishu.cn/open-apis/bot/v2/hook/global-admin",
    )
    monkeypatch.setattr(env_manager, "_env_file_override", None)

    bootstrap_control_storage()
    create_tenant_with_owner("tenant-b", "客户乙", "owner-b", "TenantB-2026")

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(settings.router, dependencies=[Depends(tenant_identity)])

    with TestClient(app) as client:
        login_response = client.post(
            "/auth/login",
            json={"username": "owner-b", "password": "TenantB-2026"},
        )
        token = login_response.json()["access_token"]
        response = client.get(
            "/api/settings/notifications",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["FEISHU_WEBHOOK_URL_SET"] is False
    assert "feishu" not in response.json()["CONFIGURED_CHANNELS"]


def test_registered_account_starts_with_empty_tasks_and_own_webhook(
    tmp_path,
    monkeypatch,
):
    tenant_root = tmp_path / "tenants"
    monkeypatch.setattr(auth_service, "CONTROL_DATABASE_PATH", str(tmp_path / "control.sqlite3"))
    monkeypatch.setattr(auth_service, "PASSWORD_ITERATIONS", 1_000)
    monkeypatch.setenv("TENANT_DATA_ROOT", str(tenant_root))
    monkeypatch.setenv("AUTH_SECRET_FILE", str(tmp_path / "auth-secret"))
    monkeypatch.setenv("WEB_USERNAME", "admin")
    monkeypatch.setenv("WEB_PASSWORD", "Admin-2026")
    monkeypatch.setattr(env_manager, "_env_file_override", None)
    bootstrap_control_storage()

    app = FastAPI()
    app.include_router(auth.router)
    protected = [Depends(tenant_identity)]
    app.include_router(tasks.router, dependencies=protected)
    app.include_router(settings.router, dependencies=protected)
    app.dependency_overrides[dependencies.get_scheduler_service] = lambda: _Scheduler()

    with TestClient(app) as client:
        admin_login = client.post(
            "/auth/login",
            json={"username": "admin", "password": "Admin-2026"},
        ).json()
        admin_headers = {
            "Authorization": f"Bearer {admin_login['access_token']}"
        }
        assert client.post(
            "/api/tasks/",
            headers=admin_headers,
            json={
                "task_name": "管理员的监控",
                "keyword": "admin-item",
                "keyword_rules": ["admin-item"],
            },
        ).status_code == 200
        assert client.put(
            "/api/settings/notifications",
            headers=admin_headers,
            json={
                "FEISHU_WEBHOOK_URL": (
                    "https://open.feishu.cn/open-apis/bot/v2/hook/admin-only"
                )
            },
        ).status_code == 200

        registration = client.post(
            "/auth/register",
            json={
                "admin_username": "admin",
                "admin_password": "Admin-2026",
                "username": "fresh-user",
                "password": "Fresh-2026",
            },
        )
        assert registration.status_code == 201
        assert registration.json()["tenant"]["id"] != "default"

        fresh_login = client.post(
            "/auth/login",
            json={"username": "fresh-user", "password": "Fresh-2026"},
        ).json()
        fresh_headers = {
            "Authorization": f"Bearer {fresh_login['access_token']}"
        }

        assert client.get("/api/tasks", headers=fresh_headers).json() == []
        notification_settings = client.get(
            "/api/settings/notifications",
            headers=fresh_headers,
        ).json()
        assert notification_settings["FEISHU_WEBHOOK_URL_SET"] is False
        assert "feishu" not in notification_settings["CONFIGURED_CHANNELS"]
