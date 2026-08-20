"""商品规则匹配分发器，将资料采集、指标记录、通知和落盘移出抓取主链路。"""
import asyncio
import copy
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from src.keyword_rule_engine import build_search_text, evaluate_keyword_rules
from src.services.metrics_tracking_service import get_metrics_service


SellerLoader = Callable[[str], Awaitable[dict]]
Notifier = Callable[[dict, str], Awaitable[None]]
Saver = Callable[[dict, str], Awaitable[bool]]


def parse_metric_count(value: object) -> Optional[int]:
    """解析闲鱼返回的计数字段，兼容数字、带文案和“万”单位。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = (
        str(value)
        .replace("想要", "")
        .replace("浏览", "")
        .replace("人", "")
        .replace(",", "")
        .strip()
    )
    if not text or text.lower() in {"nan", "none", "-"}:
        return None
    try:
        if text.endswith("万"):
            return int(float(text[:-1]) * 10000)
        return int(float(text))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ItemAnalysisJob:
    keyword: str
    task_name: str
    keyword_rules: tuple[str, ...]
    final_record: dict
    seller_id: Optional[str]
    zhima_credit_text: Optional[str]
    registration_duration_text: str


class ItemAnalysisDispatcher:
    """用受控并发处理商品分析和落盘。"""

    def __init__(
        self,
        *,
        concurrency: int,
        seller_loader: SellerLoader,
        notifier: Notifier,
        saver: Saver,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._seller_loader = seller_loader
        self._notifier = notifier
        self._saver = saver
        self._tasks: set[asyncio.Task] = set()
        self.completed_count = 0

    def submit(self, job: ItemAnalysisJob) -> None:
        task = asyncio.create_task(self._process_with_limit(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def join(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks))

    async def _process_with_limit(self, job: ItemAnalysisJob) -> None:
        async with self._semaphore:
            await self._process_job(job)

    async def _process_job(self, job: ItemAnalysisJob) -> None:
        record = copy.deepcopy(job.final_record)
        item_data = record.get("商品信息", {}) or {}
        record["卖家信息"] = await self._load_seller_info(job)
        record["match_result"] = self._build_match_result(job, record)
        if await self._saver(record, job.keyword):
            self.completed_count += 1

        # 解析当前价格和想要数（用于比较和记录）
        item_id = str(item_data.get("商品 ID") or item_data.get("商品ID") or "")
        price_raw = item_data.get("当前售价")
        want_count_raw = item_data.get("想要人数", item_data.get("“想要”人数"))
        browse_count_raw = item_data.get("浏览量")

        # 解析价格为数值
        price_value = None
        if price_raw is not None:
            try:
                price_value = float(str(price_raw).replace("¥", "").strip())
            except (ValueError, TypeError):
                price_value = None

        # 解析想要数为整数
        want_count_value = parse_metric_count(want_count_raw)
        browse_count_value = parse_metric_count(browse_count_raw)

        # 先比较当前值和数据库最新记录（写入之前）
        if item_id:
            metrics_service = get_metrics_service()
            changes = metrics_service.compare_with_latest(
                item_id=item_id,
                current_price=price_value,
                current_price_display=str(price_raw) if price_raw is not None else None,
                current_want_count=want_count_value,
                task_name=job.task_name,
            )
            # 设置或清除变化字段
            if changes and "price_change_display" in changes:
                item_data["price_change_display"] = changes["price_change_display"]
            else:
                item_data.pop("price_change_display", None)
            if changes and "want_count_change_display" in changes:
                item_data["want_count_change_display"] = changes["want_count_change_display"]
            else:
                item_data.pop("want_count_change_display", None)

        # 记录指标快照（价格、想要数）
        if item_id:
            try:
                metrics_service = get_metrics_service()
                metrics_service.record_metrics(
                    task_name=job.task_name,
                    item_id=item_id,
                    title=item_data.get("商品标题", "")[:200],
                    price=price_value,
                    price_display=str(price_raw) if price_raw is not None else None,
                    want_count=want_count_value,
                    browse_count=browse_count_value,
                    seller_id=item_data.get("卖家 ID"),
                    link=item_data.get("商品链接"),
                )
            except Exception as e:
                print(f"   [指标] 记录指标快照失败：{e}")

        await self._notify_if_recommended(item_data, record["match_result"])

    async def _load_seller_info(self, job: ItemAnalysisJob) -> dict:
        seller_info = {}
        if job.seller_id:
            try:
                seller_info = await self._seller_loader(job.seller_id)
            except Exception as exc:
                print(f"   [卖家] 采集卖家 {job.seller_id} 信息失败：{exc}")
        merged = copy.deepcopy(seller_info or {})
        merged["卖家芝麻信用"] = job.zhima_credit_text
        merged["卖家注册时长"] = job.registration_duration_text
        return merged

    def _build_match_result(self, job: ItemAnalysisJob, record: dict) -> dict:
        item_data = record.get("商品信息", {}) or {}
        item_id = str(item_data.get("商品 ID") or item_data.get("商品ID") or "")
        if item_id and item_id in job.keyword_rules:
            return {
                "analysis_source": "direct",
                "is_recommended": True,
                "reason": "指定商品 ID 监控",
                "keyword_hit_count": 1,
                "matched_keywords": [item_id],
            }
        search_text = build_search_text(record)
        return evaluate_keyword_rules(list(job.keyword_rules), search_text)

    async def _notify_if_recommended(self, item_data: dict, analysis_result: dict) -> None:
        if not analysis_result.get("is_recommended"):
            return
        try:
            await self._notifier(item_data, analysis_result.get("reason", "无"))
        except Exception as exc:
            print(f"   [通知] 发送推荐通知失败：{exc}")
