"""
调度服务
负责管理定时任务的调度
"""
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import Awaitable, Callable, List

from src.core.cron_utils import build_cron_trigger
from src.domain.models.task import Task
from src.services.process_service import ProcessService
from src.tenancy.context import current_tenant_id, tenant_scope

QueueStatusHook = Callable[[int, bool], Awaitable[None] | None]


class SchedulerService:
    """调度服务"""

    def __init__(
        self,
        process_service: ProcessService,
        max_concurrent_tasks: int = 1,
    ):
        if max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks 必须大于等于 1")
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.process_service = process_service
        self.max_concurrent_tasks = max_concurrent_tasks
        self._task_slots = asyncio.Semaphore(max_concurrent_tasks)
        self._queued_tasks: set[tuple[str, int]] = set()
        self._cancelled_queued_tasks: set[tuple[str, int]] = set()
        self._on_queue_changed: QueueStatusHook | None = None

    def set_queue_status_hook(
        self,
        *,
        on_queue_changed: QueueStatusHook | None = None,
    ) -> None:
        self._on_queue_changed = on_queue_changed

    async def _invoke_queue_hook(
        self,
        tenant_id: str,
        task_id: int,
        is_queued: bool,
    ) -> None:
        if self._on_queue_changed is None:
            return
        with tenant_scope(tenant_id):
            result = self._on_queue_changed(task_id, is_queued)
            if asyncio.iscoroutine(result):
                await result

    def _runtime_key(self, task_id: int, tenant_id: str | None = None) -> tuple[str, int]:
        return (tenant_id or current_tenant_id(required=False), task_id)

    def is_task_queued(self, task_id: int, tenant_id: str | None = None) -> bool:
        return self._runtime_key(task_id, tenant_id) in self._queued_tasks

    async def _set_task_queued(
        self,
        tenant_id: str,
        task_id: int,
        is_queued: bool,
    ) -> None:
        runtime_key = self._runtime_key(task_id, tenant_id)
        if is_queued:
            if runtime_key in self._queued_tasks:
                return
            self._cancelled_queued_tasks.discard(runtime_key)
            self._queued_tasks.add(runtime_key)
        else:
            if runtime_key not in self._queued_tasks:
                return
            self._queued_tasks.remove(runtime_key)
        await self._invoke_queue_hook(tenant_id, task_id, is_queued)

    async def cancel_queued_task(
        self,
        task_id: int,
        tenant_id: str | None = None,
    ) -> None:
        resolved_tenant = tenant_id or current_tenant_id()
        runtime_key = self._runtime_key(task_id, resolved_tenant)
        if runtime_key not in self._queued_tasks:
            return
        self._cancelled_queued_tasks.add(runtime_key)
        await self._set_task_queued(resolved_tenant, task_id, False)

    async def _cancel_queued_tasks_not_in(
        self,
        tenant_id: str,
        active_task_ids: set[int],
    ) -> None:
        queued_task_ids = [
            task_id
            for queued_tenant_id, task_id in self._queued_tasks
            if queued_tenant_id == tenant_id and task_id not in active_task_ids
        ]
        for task_id in queued_task_ids:
            await self.cancel_queued_task(task_id, tenant_id)

    def start(self):
        """启动调度器"""
        if not self.scheduler.running:
            self.scheduler.start()
            print("调度器已启动")

    def stop(self):
        """停止调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            print("调度器已停止")

    def _job_id(self, task_id: int, tenant_id: str | None = None) -> str:
        resolved_tenant = tenant_id or current_tenant_id()
        return f"tenant_{resolved_tenant}_task_{task_id}"

    def get_next_run_time(self, task_id: int):
        job = self.scheduler.get_job(self._job_id(task_id))
        if job is None:
            return None

        next_run_time = getattr(job, "next_run_time", None)
        if next_run_time is not None:
            return next_run_time

        trigger = getattr(job, "trigger", None)
        if trigger is None or not hasattr(trigger, "get_next_fire_time"):
            return None

        try:
            now = datetime.now(self.scheduler.timezone)
            return trigger.get_next_fire_time(None, now)
        except Exception:
            return None

    async def reload_jobs(self, tasks: List[Task], tenant_id: str | None = None):
        """重新加载所有定时任务"""
        resolved_tenant = tenant_id or current_tenant_id()
        print(f"正在重新加载租户 {resolved_tenant} 的定时任务...")
        prefix = f"tenant_{resolved_tenant}_task_"
        for job in self.scheduler.get_jobs():
            if job.id.startswith(prefix):
                self.scheduler.remove_job(job.id)

        active_task_ids: set[int] = set()
        for task in tasks:
            # 暂停的任务不添加到调度器
            if task.enabled and task.cron and not task.is_paused:
                if task.id is not None:
                    active_task_ids.add(task.id)
                try:
                    trigger = build_cron_trigger(
                        task.cron,
                        timezone=self.scheduler.timezone,
                    )
                    self.scheduler.add_job(
                        self._run_task,
                        trigger=trigger,
                        args=[resolved_tenant, task.id, task.task_name],
                        id=self._job_id(task.id, resolved_tenant),
                        name=f"Scheduled: {task.task_name}",
                        replace_existing=True,
                        max_instances=1,
                        coalesce=True,
                        misfire_grace_time=60,
                    )
                    print(f"  -> 已为任务 '{task.task_name}' 添加定时规则：'{task.cron}'")
                except ValueError as e:
                    print(f"  -> [警告] 任务 '{task.task_name}' 的 Cron 表达式无效：{e}")

        await self._cancel_queued_tasks_not_in(resolved_tenant, active_task_ids)
        print("定时任务加载完成")

    async def _run_task(self, tenant_id: str, task_id: int, task_name: str):
        """执行定时任务"""
        runtime_key = self._runtime_key(task_id, tenant_id)
        should_mark_queued = self._task_slots.locked()
        if should_mark_queued:
            print(f"定时任务触发：任务 '{task_name}' 正在等待运行槽位...")
            await self._set_task_queued(tenant_id, task_id, True)
        try:
            async with self._task_slots:
                if should_mark_queued:
                    await self._set_task_queued(tenant_id, task_id, False)
                if runtime_key in self._cancelled_queued_tasks:
                    print(f"定时任务已取消排队：任务 '{task_name}' 不再启动。")
                    return
                print(f"定时任务获得运行槽位：正在为任务 '{task_name}' 启动爬虫...")
                with tenant_scope(tenant_id):
                    is_started = await self.process_service.start_task(task_id, task_name)
                    if is_started:
                        await self.process_service.wait_for_task(task_id)
        finally:
            if should_mark_queued:
                await self._set_task_queued(tenant_id, task_id, False)
            self._cancelled_queued_tasks.discard(runtime_key)

    async def pause_task(self, task_id: int, task: Task):
        """暂停定时任务"""
        await self.cancel_queued_task(task_id)
        job_id = self._job_id(task_id)
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            print(f"定时任务已暂停：{task.task_name}")

    async def resume_task(self, task_id: int, task: Task):
        """恢复定时任务"""
        if not task.cron:
            raise ValueError("任务没有配置 cron 表达式")

        try:
            trigger = build_cron_trigger(
                task.cron,
                timezone=self.scheduler.timezone,
            )
            self.scheduler.add_job(
                self._run_task,
                trigger=trigger,
                args=[current_tenant_id(), task_id, task.task_name],
                id=self._job_id(task_id),
                name=f"Scheduled: {task.task_name}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
            print(f"定时任务已恢复：{task.task_name}")
        except ValueError as e:
            raise ValueError(f"Cron 表达式无效：{e}")
