from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import auth
from src.services import auth_service


def _build_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        auth_service,
        "CONTROL_DATABASE_PATH",
        str(tmp_path / "control.sqlite3"),
    )
    monkeypatch.setattr(auth_service, "PASSWORD_ITERATIONS", 1_000)
    monkeypatch.setenv("TENANT_DATA_ROOT", str(tmp_path / "tenants"))
    monkeypatch.setenv("DEFAULT_TENANT_ID", "default")
    monkeypatch.setenv("DEFAULT_TENANT_NAME", "默认租户")
    monkeypatch.setenv("WEB_USERNAME", "admin")
    monkeypatch.setenv("WEB_PASSWORD", "Admin-2026")
    auth_service.bootstrap_control_storage()

    app = FastAPI()
    app.include_router(auth.router)
    return TestClient(app)


def _registration_payload(**updates) -> dict:
    payload = {
        "admin_username": "admin",
        "admin_password": "Admin-2026",
        "username": "new-member",
        "password": "Member-2026",
    }
    payload.update(updates)
    return payload


def test_superadmin_credentials_create_isolated_account(
    tmp_path,
    monkeypatch,
):
    with _build_client(tmp_path, monkeypatch) as client:
        response = client.post("/auth/register", json=_registration_payload())

        assert response.status_code == 201
        assert response.json()["user"]["username"] == "new-member"
        assert response.json()["user"]["role"] == "owner"
        assert response.json()["tenant"]["id"].startswith("user-")
        assert response.json()["tenant"]["name"] == "new-member 的账户"
        assert (tmp_path / "tenants" / response.json()["tenant"]["id"]).is_dir()

        login_response = client.post(
            "/auth/login",
            json={"username": "new-member", "password": "Member-2026"},
        )
        assert login_response.status_code == 200
        assert login_response.json()["user"]["role"] == "owner"
        assert login_response.json()["tenant"] == response.json()["tenant"]


def test_registration_rejects_invalid_admin_credentials(tmp_path, monkeypatch):
    with _build_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/auth/register",
            json=_registration_payload(admin_password="wrong-password"),
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "管理员账号、密码不正确或无注册权限"


def test_new_account_owner_can_authorize_another_isolated_account(tmp_path, monkeypatch):
    with _build_client(tmp_path, monkeypatch) as client:
        assert client.post(
            "/auth/register",
            json=_registration_payload(),
        ).status_code == 201

        response = client.post(
            "/auth/register",
            json=_registration_payload(
                admin_username="new-member",
                admin_password="Member-2026",
                username="another-member",
            ),
        )

        assert response.status_code == 201
        assert response.json()["tenant"]["id"] != "default"


def test_tenant_owner_creates_account_outside_owned_tenant(tmp_path, monkeypatch):
    with _build_client(tmp_path, monkeypatch) as client:
        auth_service.create_tenant_with_owner(
            "customer",
            "客户租户",
            "customer-owner",
            "Owner-2026",
        )

        response = client.post(
            "/auth/register",
            json=_registration_payload(
                admin_username="customer-owner",
                admin_password="Owner-2026",
                username="customer-member",
            ),
        )

        assert response.status_code == 201
        assert response.json()["tenant"]["id"].startswith("user-")
        assert response.json()["tenant"]["id"] != "customer"
        assert response.json()["user"]["role"] == "owner"


def test_bootstrap_migrates_legacy_member_to_empty_personal_tenant(tmp_path, monkeypatch):
    with _build_client(tmp_path, monkeypatch):
        identity = auth_service.register_tenant_member(
            "admin",
            "Admin-2026",
            "legacy-user",
            "Legacy-2026",
        )
        with auth_service.control_connection() as conn:
            conn.execute("DELETE FROM tenant_memberships WHERE user_id = ?", (identity.user_id,))
            conn.execute(
                "INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES ('default', ?, 'member')",
                (identity.user_id,),
            )
            conn.commit()

        auth_service.bootstrap_control_storage()
        migrated = auth_service.authenticate("legacy-user", "Legacy-2026")

        assert migrated is not None
        assert migrated.tenant_id == f"user-{identity.user_id}"
        assert migrated.role == "owner"
        assert (tmp_path / "tenants" / migrated.tenant_id / ".env").exists()


def test_registration_rejects_duplicate_username(tmp_path, monkeypatch):
    with _build_client(tmp_path, monkeypatch) as client:
        assert client.post(
            "/auth/register",
            json=_registration_payload(),
        ).status_code == 201

        response = client.post(
            "/auth/register",
            json=_registration_payload(),
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "用户名已存在"


def test_registration_validates_new_account_password(tmp_path, monkeypatch):
    with _build_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/auth/register",
            json=_registration_payload(password="short"),
        )

        assert response.status_code == 422
