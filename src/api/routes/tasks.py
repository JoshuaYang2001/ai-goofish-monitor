"""
任务管理路由
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import os
from src.api.dependencies import (
    get_process_service,
    get_scheduler_service,
    get_task_service,
)
from src.services.task_service import TaskService
from src.services.process_service import ProcessService
from src.services.scheduler_service import SchedulerService
from src.services.task_payloads import serialize_task, serialize_tasks
from src.domain.models.task import TaskCreate, TaskUpdate
from src.utils import resolve_task_log_path
from src.services.account_strategy_service import normalize_account_strategy
from src.api.routes import websocket
from src.infrastructure.config.settings import settings as app_settings
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

async def _reload_scheduler_if_needed(
    task_service: TaskService,
    scheduler_service: SchedulerService,
):
    tasks = await task_service.get_all_tasks()
    await scheduler_service.reload_jobs(tasks)


def _has_keyword_rules(rules) -> bool:
    return bool(rules and len(rules) > 0)


def _validate_final_account_strategy(existing_task, task_update: TaskUpdate) -> None:
    account_state_file = (
        task_update.account_state_file
        if task_update.account_state_file is not None
        else existing_task.account_state_file
    )
    account_strategy = normalize_account_strategy(
        task_update.account_strategy,
        account_state_file,
    )
    task_update.account_strategy = account_strategy
    if account_strategy == "fixed" and not account_state_file:
        raise HTTPException(status_code=400, detail="固定账号模式下必须选择账号。")
@router.get("", response_model=List[dict])
async def get_tasks(
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """获取所有任务"""
    tasks = await service.get_all_tasks()
    return serialize_tasks(tasks, scheduler_service)
@router.get("/{task_id}", response_model=dict)
async def get_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """获取单个任务"""
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    return serialize_task(task, scheduler_service)
@router.post("/", response_model=dict)
async def create_task(
    task_create: TaskCreate,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """创建新任务"""
    existing_tasks = await service.get_all_tasks()
    if len(existing_tasks) >= app_settings.max_tasks:
        raise HTTPException(
            status_code=400,
            detail=f"监控任务数量已达上限，最多只能创建 {app_settings.max_tasks} 条任务",
        )
    task = await service.create_task(task_create)
    await _reload_scheduler_if_needed(service, scheduler_service)
    await websocket.broadcast_message("tasks_updated", {"id": task.id, "action": "created"})
    return {"message": "任务创建成功", "task": serialize_task(task, scheduler_service)}
@router.patch("/{task_id}", response_model=dict)
async def update_task(
    task_id: int,
    task_update: TaskUpdate,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """更新任务"""
    try:
        existing_task = await service.get_task(task_id)
        if not existing_task:
            raise HTTPException(status_code=404, detail="任务未找到")
        _validate_final_account_strategy(existing_task, task_update)

        final_task_type = task_update.task_type or existing_task.task_type
        if final_task_type == "item_id":
            final_item_ids = task_update.item_id_list or existing_task.item_id_list
            if not final_item_ids:
                raise HTTPException(status_code=400, detail="商品 ID 监控至少需要一个商品 ID。")
            task_update.keyword_rules = list(dict.fromkeys(final_item_ids))
        else:
            final_keyword = task_update.keyword or existing_task.keyword
            final_rules = task_update.keyword_rules or existing_task.keyword_rules
            task_update.keyword_rules = final_rules or ([final_keyword] if final_keyword else [])
            if not _has_keyword_rules(task_update.keyword_rules):
                raise HTTPException(status_code=400, detail="关键词监控至少需要一个匹配关键词。")
        task = await service.update_task(task_id, task_update)
        await _reload_scheduler_if_needed(service, scheduler_service)
        await websocket.broadcast_message("tasks_updated", {"id": task_id, "action": "updated"})
        return {"message": "任务更新成功", "task": serialize_task(task, scheduler_service)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
@router.delete("/{task_id}", response_model=dict)
async def delete_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """删除任务"""
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")

    await process_service.stop_task(task_id)
    success = await service.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务未找到")
    await _reload_scheduler_if_needed(service, scheduler_service)
    await websocket.broadcast_message("tasks_updated", {"id": task_id, "action": "deleted"})
    await websocket.broadcast_message("results_updated", {"task_id": task_id, "action": "deleted"})

    try:
        log_file_path = resolve_task_log_path(task_id, task.task_name)
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
    except Exception as e:
        print(f"删除任务日志文件时出错: {e}")
    return {"message": "任务删除成功"}
@router.post("/start/{task_id}", response_model=dict)
async def start_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """启动单个任务"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    if not task.enabled:
        raise HTTPException(status_code=400, detail="任务已被禁用，无法启动")
    if task.is_running:
        raise HTTPException(status_code=400, detail="任务已在运行中")
    is_task_queued = getattr(scheduler_service, "is_task_queued", None)
    if callable(is_task_queued) and is_task_queued(task_id):
        raise HTTPException(status_code=400, detail="任务已在定时队列中，请等待当前爬虫完成")
    success = await process_service.start_task(task_id, task.task_name)
    if not success:
        raise HTTPException(status_code=500, detail="启动任务失败")
    return {"message": f"任务 '{task.task_name}' 已启动"}
@router.post("/stop/{task_id}", response_model=dict)
async def stop_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
):
    """停止单个任务"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    await process_service.stop_task(task_id)
    return {"message": f"任务ID {task_id} 已发送停止信号"}



@router.post("/pause/{task_id}", response_model=dict)
async def pause_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """暂停定时任务"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    if not task.enabled:
        raise HTTPException(status_code=400, detail="任务已禁用，无需暂停")
    if task.is_running:
        raise HTTPException(status_code=400, detail="请先停止正在运行的任务")
    if task.is_paused:
        raise HTTPException(status_code=400, detail="任务已处于暂停状态")

    # 更新任务状态
    await task_service.update_task(task_id, TaskUpdate(is_paused=True))
    # 从调度器移除
    await scheduler_service.pause_task(task_id, task)
    # 广播 WebSocket 消息
    await websocket.broadcast_message("task_paused_changed", {"id": task_id, "is_paused": True})

    return {"message": f"任务 '{task.task_name}' 已暂停"}


@router.post("/resume/{task_id}", response_model=dict)
async def resume_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """恢复定时任务"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    if not task.is_paused:
        raise HTTPException(status_code=400, detail="任务未处于暂停状态")
    if not task.cron:
        raise HTTPException(status_code=400, detail="任务没有配置 cron 表达式")

    # 更新任务状态
    await task_service.update_task(task_id, TaskUpdate(is_paused=False))
    # 重新添加到调度器
    await scheduler_service.resume_task(task_id, task)
    # 广播 WebSocket 消息
    await websocket.broadcast_message("task_paused_changed", {"id": task_id, "is_paused": False})

    return {"message": f"任务 '{task.task_name}' 已恢复"}
