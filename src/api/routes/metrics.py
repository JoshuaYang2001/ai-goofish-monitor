"""
指标历史查询 API
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from src.services.metrics_tracking_service import get_metrics_service

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/changes")
async def get_metric_changes(
    interval: List[int] = Query(
        default=[1, 3, 6, 12, 24, 48, 72],
        description="统计时间窗口（小时），可重复传入",
    ),
    task_name: Optional[str] = Query(default=None, description="按监控任务筛选"),
    search: Optional[str] = Query(default=None, max_length=100, description="按商品标题或 ID 搜索"),
):
    """获取当前租户各商品在指定时间窗口内的价格和想要数变化。"""
    try:
        return get_metrics_service().get_change_overview(
            interval,
            task_name=task_name,
            search=search,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/item/{item_id}/price-history")
async def get_price_history(
    item_id: str,
    days: int = Query(default=30, ge=1, le=90, description="查询天数"),
):
    """获取商品价格历史"""
    service = get_metrics_service()
    history = service.get_price_history(item_id, days=days)
    return {"item_id": item_id, "days": days, "history": history}


@router.get("/item/{item_id}/want-history")
async def get_want_history(
    item_id: str,
    days: int = Query(default=30, ge=1, le=90, description="查询天数"),
):
    """获取商品想要数历史"""
    service = get_metrics_service()
    history = service.get_want_count_history(item_id, days=days)
    return {"item_id": item_id, "days": days, "history": history}


@router.get("/item/{item_id}/latest")
async def get_latest_snapshot(item_id: str):
    """获取商品最新指标快照"""
    service = get_metrics_service()
    snapshot = service.get_last_snapshot(item_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="商品指标记录不存在")
    return {"item_id": item_id, "snapshot": snapshot}
