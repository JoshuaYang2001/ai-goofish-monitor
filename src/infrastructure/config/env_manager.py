"""
环境变量管理器
负责读取和更新 .env 文件，并在读取时回退到运行时环境变量
"""
import os
import re
from typing import Dict, List, Optional
from pathlib import Path

from dotenv import dotenv_values
from src.tenancy.context import current_tenant_id
from src.tenancy.paths import tenant_path


_PLAIN_ENV_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_./:-]+$")


class EnvManager:
    """环境变量管理器"""

    def __init__(self, env_file: str = ".env"):
        self._default_env_file = Path(env_file)
        self._env_file_override: Path | None = None
        self._ensure_env_file_exists()

    @property
    def env_file(self) -> Path:
        if getattr(self, "_env_file_override", None) is not None:
            return self._env_file_override
        try:
            return Path(tenant_path(".env", current_tenant_id()))
        except RuntimeError:
            return self._default_env_file

    @env_file.setter
    def env_file(self, value: str | Path) -> None:
        self._env_file_override = Path(value)

    def _ensure_env_file_exists(self):
        """确保 .env 文件存在"""
        if not self.env_file.exists():
            self.env_file.touch()

    def read_env(self) -> Dict[str, str]:
        """读取所有环境变量"""
        if not self.env_file.exists():
            return {}

        loaded = dotenv_values(self.env_file, encoding="utf-8")
        return {
            key: value
            for key, value in loaded.items()
            if key and value is not None
        }

    def get_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """获取单个环境变量的值；租户文件优先于共享运行时配置。"""
        try:
            current_tenant_id()
            tenant_value = self.read_env().get(key)
            if tenant_value is not None:
                return tenant_value
        except RuntimeError:
            pass
        runtime_value = os.getenv(key)
        if runtime_value is not None:
            return runtime_value

        env_vars = self.read_env()
        return env_vars.get(key, default)

    def update_values(self, updates: Dict[str, str]) -> bool:
        """批量更新环境变量"""
        return self.apply_changes(updates=updates)

    def apply_changes(
        self,
        updates: Dict[str, str],
        deletions: List[str] | None = None,
    ) -> bool:
        """批量更新并删除环境变量"""
        try:
            existing_vars = self.read_env()
            existing_vars.update(updates)
            for key in deletions or []:
                existing_vars.pop(key, None)
            return self._write_env(existing_vars)
        except Exception as e:
            print(f"更新环境变量失败: {e}")
            return False

    def set_value(self, key: str, value: str) -> bool:
        """设置单个环境变量"""
        return self.update_values({key: value})

    def delete_keys(self, keys: List[str]) -> bool:
        """删除指定的环境变量"""
        try:
            existing_vars = self.read_env()
            for key in keys:
                existing_vars.pop(key, None)
            return self._write_env(existing_vars)
        except Exception as e:
            print(f"删除环境变量失败: {e}")
            return False

    def _write_env(self, env_vars: Dict[str, str]) -> bool:
        """写入环境变量到文件"""
        try:
            self.env_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.env_file, 'w', encoding='utf-8') as f:
                for key, value in env_vars.items():
                    f.write(f"{key}={self._serialize_value(value)}\n")
            return True
        except Exception as e:
            print(f"写入 .env 文件失败: {e}")
            return False

    def _serialize_value(self, value: str) -> str:
        text = str(value)
        if text == "":
            return ""
        if _PLAIN_ENV_VALUE_PATTERN.fullmatch(text):
            return text
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'


# 全局实例
env_manager = EnvManager()
