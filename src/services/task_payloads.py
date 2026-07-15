"""
任务接口响应序列化辅助。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from src.domain.models.task import Task


def serialize_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _is_task_queued(scheduler_service, task_id: int) -> bool:
    checker = getattr(scheduler_service, "is_task_queued", None)
    if not callable(checker):
        return False
    return bool(checker(task_id))


def serialize_task(task: Task, scheduler_service) -> dict[str, Any]:
    payload = task.model_dump()
    next_run_time = None
    is_queued = False
    if task.id is not None and scheduler_service is not None:
        next_run_time = scheduler_service.get_next_run_time(task.id)
        is_queued = _is_task_queued(scheduler_service, task.id)
    payload["next_run_at"] = serialize_timestamp(next_run_time)
    payload["is_queued"] = is_queued
    return payload


def serialize_tasks(tasks: list[Task], scheduler_service) -> list[dict[str, Any]]:
    return [serialize_task(task, scheduler_service) for task in tasks]
