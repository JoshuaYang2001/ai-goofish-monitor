"""
调度服务
负责管理定时任务的调度
"""
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import List

from src.core.cron_utils import build_cron_trigger
from src.domain.models.task import Task
from src.services.process_service import ProcessService
from src.tenancy.context import current_tenant_id, tenant_scope


class SchedulerService:
    """调度服务"""

    def __init__(self, process_service: ProcessService):
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.process_service = process_service

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

        for task in tasks:
            # 暂停的任务不添加到调度器
            if task.enabled and task.cron and not task.is_paused:
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
                        replace_existing=True
                    )
                    print(f"  -> 已为任务 '{task.task_name}' 添加定时规则：'{task.cron}'")
                except ValueError as e:
                    print(f"  -> [警告] 任务 '{task.task_name}' 的 Cron 表达式无效：{e}")

        print("定时任务加载完成")

    async def _run_task(self, tenant_id: str, task_id: int, task_name: str):
        """执行定时任务"""
        print(f"定时任务触发：正在为任务 '{task_name}' 启动爬虫...")
        with tenant_scope(tenant_id):
            await self.process_service.start_task(task_id, task_name)

    async def pause_task(self, task_id: int, task: Task):
        """暂停定时任务"""
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
                replace_existing=True
            )
            print(f"定时任务已恢复：{task.task_name}")
        except ValueError as e:
            raise ValueError(f"Cron 表达式无效：{e}")
