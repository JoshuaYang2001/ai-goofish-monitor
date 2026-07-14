"""Provision an isolated tenant and its first owner account."""

from __future__ import annotations

import argparse
import getpass

from src.services.auth_service import bootstrap_control_storage, create_tenant_with_owner


def main() -> None:
    parser = argparse.ArgumentParser(description="创建多租户闲鱼监控空间")
    parser.add_argument("--tenant-id", required=True, help="小写租户标识，例如 acme")
    parser.add_argument("--tenant-name", required=True, help="租户显示名称")
    parser.add_argument("--username", required=True, help="租户所有者登录名")
    parser.add_argument("--password", help="至少 8 位；省略时安全交互输入")
    args = parser.parse_args()

    password = args.password or getpass.getpass("租户所有者密码: ")
    bootstrap_control_storage()
    identity = create_tenant_with_owner(
        args.tenant_id,
        args.tenant_name,
        args.username,
        password,
    )
    print(f"租户创建成功: {identity.tenant_name} ({identity.tenant_id})")
    print(f"所有者账号: {identity.username}")


if __name__ == "__main__":
    main()
