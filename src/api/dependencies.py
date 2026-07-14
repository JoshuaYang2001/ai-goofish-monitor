"""
FastAPI 依赖注入
提供服务实例的创建和管理
"""
from fastapi import Depends
from src.services.task_service import TaskService
from src.services.notification_service import NotificationService, build_notification_service
from src.services.process_service import ProcessService
from src.services.scheduler_service import SchedulerService
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository


# 全局 ProcessService 实例（将在 app.py 中设置）
_process_service_instance = None
_scheduler_service_instance = None


def set_process_service(service: ProcessService):
    """设置全局 ProcessService 实例"""
    global _process_service_instance
    _process_service_instance = service


def set_scheduler_service(service: SchedulerService):
    """设置全局 SchedulerService 实例"""
    global _scheduler_service_instance
    _scheduler_service_instance = service


# 服务依赖注入
def get_task_service() -> TaskService:
    """获取任务管理服务实例"""
    repository = SqliteTaskRepository()
    return TaskService(repository)


def get_notification_service() -> NotificationService:
    """获取通知服务实例"""
    return build_notification_service()


def get_process_service() -> ProcessService:
    """获取进程管理服务实例"""
    if _process_service_instance is None:
        raise RuntimeError("ProcessService 未初始化")
    return _process_service_instance


def get_scheduler_service() -> SchedulerService:
    """获取调度服务实例"""
    if _scheduler_service_instance is None:
        raise RuntimeError("SchedulerService 未初始化")
    return _scheduler_service_instance
