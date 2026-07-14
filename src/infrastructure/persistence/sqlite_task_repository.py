"""
基于 SQLite 的任务仓储实现。
"""
from __future__ import annotations

import asyncio
import json
from typing import List, Optional

from src.domain.models.task import Task
from src.domain.repositories.task_repository import TaskRepository
from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.tenancy.context import DEFAULT_TENANT_ID, current_tenant_id, has_tenant_context
from src.tenancy.paths import tenant_path


def _row_to_task(row) -> Task:
    payload = dict(row)
    payload["enabled"] = bool(payload["enabled"])
    payload["personal_only"] = bool(payload["personal_only"])
    payload["free_shipping"] = bool(payload["free_shipping"])
    payload["is_running"] = bool(payload["is_running"])
    payload["is_paused"] = bool(payload.get("is_paused", 0))
    payload["task_type"] = payload.get("task_type", "keyword")
    payload["item_id_list"] = json.loads(payload.pop("item_id_list_json") or "[]")
    payload["keyword_rules"] = json.loads(payload.pop("keyword_rules_json") or "[]")
    return Task(**payload)


def find_task_by_name_sync(task_name: str) -> Task | None:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE task_name = ? ORDER BY id ASC LIMIT 1",
            (task_name,),
        ).fetchone()
    return _row_to_task(row) if row else None


class SqliteTaskRepository(TaskRepository):
    """基于 SQLite 的任务仓储"""

    def __init__(
        self,
        db_path: str | None = None,
        legacy_config_file: str | None = "config.json",
    ):
        self.db_path = db_path
        tenant_id = current_tenant_id(required=False)
        if legacy_config_file == "config.json" and has_tenant_context():
            self.legacy_config_file = (
                tenant_path("config.json", tenant_id)
                if tenant_id == DEFAULT_TENANT_ID
                else None
            )
        else:
            self.legacy_config_file = legacy_config_file

    async def find_all(self) -> List[Task]:
        return await asyncio.to_thread(self._find_all_sync)

    async def find_by_id(self, task_id: int) -> Optional[Task]:
        return await asyncio.to_thread(self._find_by_id_sync, task_id)

    async def save(self, task: Task) -> Task:
        return await asyncio.to_thread(self._save_sync, task)

    async def delete(self, task_id: int) -> bool:
        return await asyncio.to_thread(self._delete_sync, task_id)

    def _find_all_sync(self) -> List[Task]:
        bootstrap_sqlite_storage(
            self.db_path,
            legacy_config_file=self.legacy_config_file,
        )
        with sqlite_connection(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY id ASC").fetchall()
        return [_row_to_task(row) for row in rows]

    def _find_by_id_sync(self, task_id: int) -> Optional[Task]:
        bootstrap_sqlite_storage(
            self.db_path,
            legacy_config_file=self.legacy_config_file,
        )
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def _save_sync(self, task: Task) -> Task:
        bootstrap_sqlite_storage(
            self.db_path,
            legacy_config_file=self.legacy_config_file,
        )
        with sqlite_connection(self.db_path) as conn:
            task_id = task.id
            if task_id is None:
                task_id = self._next_task_id(conn)
            else:
                existing = conn.execute(
                    "SELECT task_name FROM tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if existing and str(existing["task_name"]) != task.task_name:
                    self._rename_task_data(
                        conn,
                        old_name=str(existing["task_name"]),
                        new_name=task.task_name,
                    )
            payload = self._task_values(task.model_copy(update={"id": task_id}))
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    id, task_name, task_type, enabled, keyword, item_id_list_json,
                    max_pages, personal_only, min_price, max_price, cron, account_state_file,
                    account_strategy, free_shipping, new_publish_option, region,
                    keyword_rules_json, is_running, is_paused
                ) VALUES (
                    :id, :task_name, :task_type, :enabled, :keyword, :item_id_list_json,
                    :max_pages, :personal_only, :min_price, :max_price, :cron, :account_state_file,
                    :account_strategy, :free_shipping, :new_publish_option, :region,
                    :keyword_rules_json, :is_running, :is_paused
                )
                """,
                payload,
            )
            conn.commit()
        return task.model_copy(update={"id": task_id})

    def _delete_sync(self, task_id: int) -> bool:
        bootstrap_sqlite_storage(
            self.db_path,
            legacy_config_file=self.legacy_config_file,
        )
        with sqlite_connection(self.db_path) as conn:
            task_row = conn.execute(
                "SELECT task_name FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if task_row is None:
                return False

            task_name = str(task_row["task_name"])
            conn.execute("DELETE FROM result_items WHERE task_name = ?", (task_name,))
            conn.execute("DELETE FROM price_snapshots WHERE task_name = ?", (task_name,))
            conn.execute(
                "DELETE FROM item_metrics_history WHERE task_name = ?",
                (task_name,),
            )
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
        return cursor.rowcount > 0

    def _rename_task_data(self, conn, *, old_name: str, new_name: str) -> None:
        """任务改名时同步结构化历史数据，避免结果列表失去名称。"""
        for table_name in (
            "result_items",
            "price_snapshots",
            "item_metrics_history",
        ):
            conn.execute(
                f"UPDATE {table_name} SET task_name = ? WHERE task_name = ?",
                (new_name, old_name),
            )

    def _next_task_id(self, conn) -> int:
        row = conn.execute("SELECT COALESCE(MAX(id), -1) AS max_id FROM tasks").fetchone()
        return int(row["max_id"]) + 1

    def _task_values(self, task: Task) -> dict:
        values = task.model_dump()
        values["enabled"] = int(task.enabled)
        values["personal_only"] = int(task.personal_only)
        values["free_shipping"] = int(task.free_shipping)
        values["is_running"] = int(task.is_running)
        values["is_paused"] = int(task.is_paused)
        values["task_type"] = values.get("task_type", "keyword")
        values["item_id_list_json"] = json.dumps(task.item_id_list or [], ensure_ascii=False)
        values["keyword_rules_json"] = json.dumps(task.keyword_rules or [], ensure_ascii=False)
        values.pop("keyword_rules", None)
        values.pop("item_id_list", None)
        return values
