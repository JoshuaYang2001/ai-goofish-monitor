"""
指标追踪服务
负责记录和追踪商品价格/想要数变化
"""
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from src.infrastructure.persistence.sqlite_connection import sqlite_connection


class MetricsTrackingService:
    """指标追踪服务"""

    def record_metrics(
        self,
        item_id: str,
        title: str,
        price: Optional[float],
        price_display: Optional[str],
        want_count: Optional[int],
        browse_count: Optional[int],
        seller_id: Optional[str],
        link: Optional[str],
        task_name: str = "",
    ) -> bool:
        """
        记录每次成功采集的商品指标快照。

        完整快照可以区分“数值未变化”与“采集失败”。
        Returns: True 表示实际创建了记录，False 表示写入失败或重复。
        """
        with sqlite_connection() as conn:
            snapshot_time = datetime.now().isoformat()

            try:
                conn.execute(
                    """
                    INSERT INTO item_metrics_history (
                        task_name, item_id, title, snapshot_time, price, price_display,
                        want_count, browse_count, seller_id, link
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_name,
                        item_id,
                        title[:200],  # 限制标题长度
                        snapshot_time,
                        price,
                        price_display,
                        want_count,
                        browse_count,
                        seller_id,
                        link,
                    ),
                )
                conn.commit()
                return True
            except Exception as e:
                # 忽略重复记录（UNIQUE 约束冲突）
                if "UNIQUE constraint failed" not in str(e):
                    print(f"记录指标历史失败：{e}")
                return False

    def get_price_history(
        self, item_id: str, days: int = 30
    ) -> List[Dict[str, Optional[float]]]:
        """获取价格历史"""
        with sqlite_connection() as conn:
            cursor = conn.execute(
                """
                SELECT snapshot_time, price, price_display
                FROM item_metrics_history
                WHERE item_id = ?
                ORDER BY snapshot_time DESC
                LIMIT ?
                """,
                (item_id, days * 24 * 60),  # 假设最多每分钟一条记录
            )
            rows = cursor.fetchall()
            return [
                {
                    "time": row["snapshot_time"],
                    "price": row["price"],
                    "price_display": row["price_display"],
                }
                for row in rows
            ]

    def get_want_count_history(
        self, item_id: str, days: int = 30
    ) -> List[Dict[str, Optional[int]]]:
        """获取想要数历史"""
        with sqlite_connection() as conn:
            cursor = conn.execute(
                """
                SELECT snapshot_time, want_count
                FROM item_metrics_history
                WHERE item_id = ?
                ORDER BY snapshot_time DESC
                LIMIT ?
                """,
                (item_id, days * 24 * 60),
            )
            rows = cursor.fetchall()
            return [
                {"time": row["snapshot_time"], "want_count": row["want_count"]}
                for row in rows
            ]

    def detect_price_change(
        self, item_id: str, threshold_percent: float = 0.0
    ) -> Optional[Dict]:
        """
        检测价格变化
        Args:
            item_id: 商品 ID
            threshold_percent: 价格变化百分比阈值（0 表示任意变化）
        Returns:
            价格变化信息，如果没有变化或未达到阈值则返回 None
        """
        with sqlite_connection() as conn:
            cursor = conn.execute(
                """
                SELECT price, price_display, snapshot_time
                FROM item_metrics_history
                WHERE item_id = ? AND price IS NOT NULL
                ORDER BY snapshot_time DESC
                LIMIT 2
                """,
                (item_id,),
            )
            rows = cursor.fetchall()
            if len(rows) < 2:
                return None

            current = rows[0]
            previous = rows[1]

            current_price = current["price"]
            previous_price = previous["price"]

            if current_price == previous_price:
                return None

            change_amount = current_price - previous_price
            change_percent = (change_amount / previous_price) * 100 if previous_price else 0

            if abs(change_percent) < threshold_percent:
                return None

            return {
                "item_id": item_id,
                "current_price": current_price,
                "previous_price": previous_price,
                "change_amount": change_amount,
                "change_percent": change_percent,
                "is_price_drop": change_amount < 0,
                "current_price_display": current["price_display"],
            }

    def detect_want_count_change(
        self, item_id: str, threshold: int = 1
    ) -> Optional[Dict]:
        """
        检测想要数变化
        Args:
            item_id: 商品 ID
            threshold: 想要数变化阈值
        Returns:
            想要数变化信息，如果没有变化或未达到阈值则返回 None
        """
        with sqlite_connection() as conn:
            cursor = conn.execute(
                """
                SELECT want_count, snapshot_time
                FROM item_metrics_history
                WHERE item_id = ? AND want_count IS NOT NULL
                ORDER BY snapshot_time DESC
                LIMIT 2
                """,
                (item_id,),
            )
            rows = cursor.fetchall()
            if len(rows) < 2:
                return None

            current = rows[0]
            previous = rows[1]

            current_want = current["want_count"]
            previous_want = previous["want_count"]

            change = current_want - previous_want

            if abs(change) < threshold:
                return None

            return {
                "item_id": item_id,
                "current_want_count": current_want,
                "previous_want_count": previous_want,
                "change_amount": change,
                "is_increasing": change > 0,
            }

    def get_last_snapshot(self, item_id: str) -> Optional[Dict]:
        """获取最新的指标快照"""
        with sqlite_connection() as conn:
            cursor = conn.execute(
                """
                SELECT price, price_display, want_count, browse_count, snapshot_time
                FROM item_metrics_history
                WHERE item_id = ?
                ORDER BY snapshot_time DESC
                LIMIT 1
                """,
                (item_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "price": row["price"],
                    "price_display": row["price_display"],
                    "want_count": row["want_count"],
                    "browse_count": row["browse_count"],
                    "snapshot_time": row["snapshot_time"],
                }
            return None

    def get_change_overview(
        self,
        interval_hours: List[int],
        *,
        task_name: Optional[str] = None,
        search: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """按时间窗口汇总每个商品的价格和想要数变化。"""
        intervals = sorted({int(hours) for hours in interval_hours})
        if not intervals or any(hours < 1 or hours > 720 for hours in intervals):
            raise ValueError("时间间隔必须在 1 到 720 小时之间")
        if len(intervals) > 8:
            raise ValueError("最多同时查询 8 个时间间隔")

        current_time = now or datetime.now()
        normalized_search = (search or "").strip().lower()

        with sqlite_connection() as conn:
            current_task_rows = conn.execute(
                """
                SELECT DISTINCT task_name
                FROM tasks
                WHERE TRIM(task_name) <> ''
                """
            ).fetchall()

            metric_rows = conn.execute(
                """
                SELECT task_name, item_id, title, snapshot_time, price, price_display,
                       want_count, browse_count, seller_id, link
                FROM item_metrics_history
                ORDER BY task_name ASC, item_id ASC, snapshot_time ASC
                """
            ).fetchall()

            task_rows = conn.execute(
                """
                SELECT DISTINCT snapshots.item_id, snapshots.task_name
                FROM price_snapshots AS snapshots
                INNER JOIN tasks ON tasks.task_name = snapshots.task_name
                WHERE TRIM(snapshots.task_name) <> ''
                """
            ).fetchall()

        current_task_names = {
            str(row["task_name"])
            for row in current_task_rows
        }
        tasks_by_item: Dict[str, set[str]] = {}
        for row in task_rows:
            tasks_by_item.setdefault(str(row["item_id"]), set()).add(
                str(row["task_name"])
            )

        histories: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        for row in metric_rows:
            item_id = str(row["item_id"])
            stored_task_name = str(row["task_name"] or "")
            if stored_task_name:
                candidate_tasks = (
                    [stored_task_name]
                    if stored_task_name in current_task_names
                    else []
                )
            else:
                candidate_tasks = sorted(tasks_by_item.get(item_id, set()))
            for candidate_task in candidate_tasks:
                if task_name and candidate_task != task_name:
                    continue
                histories.setdefault((candidate_task, item_id), []).append(dict(row))

        summaries: Dict[str, Dict[str, Any]] = {
            str(hours): {
                "hours": hours,
                "want_change": 0,
                "price_change": 0.0,
                "want_changed_items": 0,
                "price_changed_items": 0,
                "available_items": 0,
            }
            for hours in intervals
        }
        items: List[Dict[str, Any]] = []

        for (item_task_name, item_id), history in histories.items():
            latest = history[-1]
            if normalized_search and normalized_search not in " ".join(
                [item_id, str(latest.get("title") or ""), item_task_name]
            ).lower():
                continue

            changes: Dict[str, Dict[str, Any]] = {}
            latest_time = datetime.fromisoformat(str(latest["snapshot_time"]))
            for hours in intervals:
                cutoff = current_time - timedelta(hours=hours)
                baseline: Optional[Dict[str, Any]] = None
                for snapshot in history:
                    snapshot_time = datetime.fromisoformat(str(snapshot["snapshot_time"]))
                    if snapshot_time <= cutoff:
                        baseline = snapshot
                    else:
                        break

                if baseline is None or latest_time <= cutoff:
                    interval_key = str(hours)
                    changes[interval_key] = {
                        "hours": hours,
                        "available": False,
                        "baseline_time": None,
                        "baseline_price": None,
                        "baseline_want_count": None,
                        "price_change": None,
                        "want_change": None,
                    }
                    continue

                current_price = latest.get("price")
                baseline_price = baseline.get("price")
                price_change = (
                    round(float(current_price) - float(baseline_price), 2)
                    if current_price is not None and baseline_price is not None
                    else None
                )
                current_want = latest.get("want_count")
                baseline_want = baseline.get("want_count")
                want_change = (
                    int(current_want) - int(baseline_want)
                    if current_want is not None and baseline_want is not None
                    else None
                )

                interval_key = str(hours)
                changes[interval_key] = {
                    "hours": hours,
                    "available": True,
                    "baseline_time": baseline["snapshot_time"],
                    "baseline_price": baseline_price,
                    "baseline_want_count": baseline_want,
                    "price_change": price_change,
                    "want_change": want_change,
                }
                summaries[interval_key]["available_items"] += 1
                if price_change is not None:
                    summaries[interval_key]["price_change"] += price_change
                    if price_change != 0:
                        summaries[interval_key]["price_changed_items"] += 1
                if want_change is not None:
                    summaries[interval_key]["want_change"] += want_change
                    if want_change != 0:
                        summaries[interval_key]["want_changed_items"] += 1

            items.append(
                {
                    "item_id": item_id,
                    "task_name": item_task_name,
                    "title": latest.get("title"),
                    "link": latest.get("link"),
                    "seller_id": latest.get("seller_id"),
                    "snapshot_time": latest.get("snapshot_time"),
                    "price": latest.get("price"),
                    "price_display": latest.get("price_display"),
                    "want_count": latest.get("want_count"),
                    "browse_count": latest.get("browse_count"),
                    "changes": changes,
                }
            )

        for summary in summaries.values():
            summary["price_change"] = round(float(summary["price_change"]), 2)
            summary["tracked_items"] = len(items)

        return {
            "generated_at": current_time.isoformat(),
            "interval_hours": intervals,
            "task_names": sorted({item["task_name"] for item in items if item["task_name"]}),
            "summaries": summaries,
            "items": items,
        }

    def get_total_want_count_for_task(self, task_name: str) -> Optional[int]:
        """获取任务下所有商品的当前总想要数"""
        with sqlite_connection() as conn:
            # 首先获取所有相关的 item_id
            cursor = conn.execute(
                """
                SELECT DISTINCT item_id FROM (
                    SELECT item_id, MAX(snapshot_time) as latest_time
                    FROM item_metrics_history
                    WHERE item_id IN (
                        SELECT DISTINCT item_id FROM price_snapshots WHERE keyword = ?
                    )
                    GROUP BY item_id
                ) latest
                """,
                (task_name,),
            )
            rows = cursor.fetchall()
            if not rows:
                return None

            item_ids = [row["item_id"] for row in rows]
            placeholders = ",".join("?" * len(item_ids))
            cursor = conn.execute(
                f"""
                SELECT SUM(want_count) as total
                FROM (
                    SELECT im.item_id, im.want_count
                    FROM item_metrics_history im
                    INNER JOIN (
                        SELECT item_id, MAX(snapshot_time) as max_time
                        FROM item_metrics_history
                        WHERE item_id IN ({placeholders})
                        GROUP BY item_id
                    ) latest ON im.item_id = latest.item_id AND im.snapshot_time = latest.max_time
                )
                """,
                tuple(item_ids),
            )
            row = cursor.fetchone()
            return row["total"] if row else None

    def get_price_diff_for_task(self, task_name: str, since: Optional[str] = None) -> Optional[float]:
        """获取任务下所有商品的价格变化（本次 - 上次，只在本次有新记录时返回）

        Args:
            task_name: 任务名称
            since: 可选，只计算此时间之后创建的记录（ISO 格式）
        """
        from datetime import datetime, timedelta

        with sqlite_connection() as conn:
            # 获取所有相关的 item_id
            cursor = conn.execute(
                """
                SELECT DISTINCT item_id FROM price_snapshots WHERE keyword = ?
                """,
                (task_name,),
            )
            rows = cursor.fetchall()
            if not rows:
                return None

            item_ids = [row["item_id"] for row in rows]
            if not item_ids:
                return None

            # 计算 5 分钟前的时间（用于判断是否是本次爬取新创建的记录）
            now = datetime.now()
            five_minutes_ago = (now - timedelta(minutes=5)).isoformat()

            # 如果提供了 since 参数，使用它作为时间下限
            time_lower_bound = since if since else five_minutes_ago

            # 计算每个商品的最新和上次价格差异
            total_diff = 0.0
            has_new_record = False  # 标记本次爬取是否有新记录
            count = 0
            for item_id in item_ids:
                # 获取最新价格和时间
                cursor = conn.execute(
                    """
                    SELECT price, snapshot_time FROM item_metrics_history
                    WHERE item_id = ? AND price IS NOT NULL
                    ORDER BY snapshot_time DESC LIMIT 1
                    """,
                    (item_id,),
                )
                current_row = cursor.fetchone()
                if not current_row:
                    continue

                current_price = current_row["price"]
                current_time = current_row["snapshot_time"]

                # 如果最新记录不是在时间下限之后创建的，说明本次爬取没有新变化
                if current_time < time_lower_bound:
                    continue

                # 标记本次爬取有新记录
                has_new_record = True

                # 获取上次价格（直接取上一条记录）
                cursor = conn.execute(
                    """
                    SELECT price FROM item_metrics_history
                    WHERE item_id = ? AND price IS NOT NULL
                    ORDER BY snapshot_time DESC LIMIT 1 OFFSET 1
                    """,
                    (item_id,),
                )
                prev_row = cursor.fetchone()
                if not prev_row or prev_row["price"] is None:
                    # 没有上次价格，使用当前价格作为基准（避免首次记录时计算错误）
                    prev_price = current_price
                else:
                    prev_price = prev_row["price"]

                total_diff += (current_price - prev_price)
                count += 1

            # 只有当本次爬取实际产生了新记录时，才返回价格差异
            if has_new_record and count > 0:
                return round(total_diff / count, 2)
            return None

    def get_want_count_diff_for_task(self, task_name: str, since: Optional[str] = None) -> Optional[int]:
        """获取任务下所有商品的想要数变化（本次 - 上次，只在本次有新记录时返回）

        Args:
            task_name: 任务名称
            since: 可选，只计算此时间之后创建的记录（ISO 格式）
        """
        from datetime import datetime, timedelta

        with sqlite_connection() as conn:
            # 获取所有相关的 item_id
            cursor = conn.execute(
                """
                SELECT DISTINCT item_id FROM price_snapshots WHERE keyword = ?
                """,
                (task_name,),
            )
            rows = cursor.fetchall()
            if not rows:
                return None

            item_ids = [row["item_id"] for row in rows]
            if not item_ids:
                return None

            # 计算 5 分钟前的时间（用于判断是否是本次爬取新创建的记录）
            now = datetime.now()
            five_minutes_ago = (now - timedelta(minutes=5)).isoformat()

            # 如果提供了 since 参数，使用它作为时间下限
            time_lower_bound = since if since else five_minutes_ago

            # 计算每个商品的最新和上次想要数差异
            total_diff = 0
            has_new_record = False  # 标记本次爬取是否有新记录
            count = 0
            for item_id in item_ids:
                # 获取最新想要数和时间
                cursor = conn.execute(
                    """
                    SELECT want_count, snapshot_time FROM item_metrics_history
                    WHERE item_id = ? AND want_count IS NOT NULL
                    ORDER BY snapshot_time DESC LIMIT 1
                    """,
                    (item_id,),
                )
                current_row = cursor.fetchone()
                if not current_row:
                    continue

                current_want = current_row["want_count"]
                current_time = current_row["snapshot_time"]

                # 如果最新记录不是在时间下限之后创建的，说明本次爬取没有新变化
                if current_time < time_lower_bound:
                    continue

                # 标记本次爬取有新记录
                has_new_record = True

                # 获取上次想要数（直接取上一条记录）
                cursor = conn.execute(
                    """
                    SELECT want_count FROM item_metrics_history
                    WHERE item_id = ? AND want_count IS NOT NULL
                    ORDER BY snapshot_time DESC LIMIT 1 OFFSET 1
                    """,
                    (item_id,),
                )
                prev_row = cursor.fetchone()
                if not prev_row or prev_row["want_count"] is None:
                    # 没有上次想要数，使用当前值作为基准（避免首次记录时计算错误）
                    prev_want = current_want
                else:
                    prev_want = prev_row["want_count"]

                total_diff += (current_want - prev_want)
                count += 1

            # 只有当本次爬取实际产生了新记录时，才返回想要数差异
            if has_new_record and count > 0:
                return total_diff
            return None

    def compare_with_latest(
        self,
        item_id: str,
        current_price: Optional[float],
        current_price_display: Optional[str],
        current_want_count: Optional[int],
        want_count_threshold: int = 1,
    ) -> Optional[Dict]:
        """
        将当前值与数据库最新记录比较，返回变化信息（用于通知推送）
        Args:
            item_id: 商品 ID
            current_price: 当前价格（数值）
            current_price_display: 当前价格显示文本
            current_want_count: 当前想要数
            want_count_threshold: 想要数变化显示阈值
        Returns:
            包含变化显示的字典，无历史记录或无变化时返回 None
        """
        with sqlite_connection() as conn:
            # 获取最新一条记录作为"上次"的值
            cursor = conn.execute(
                """
                SELECT price, price_display, want_count, snapshot_time
                FROM item_metrics_history
                WHERE item_id = ?
                ORDER BY snapshot_time DESC
                LIMIT 1
                """,
                (item_id,),
            )
            row = cursor.fetchone()

            if row is None:
                # 没有历史记录，首次爬取，返回 None
                return None

            result = {}

            # 价格变化
            previous_price = row["price"]
            if current_price is not None and previous_price is not None:
                price_diff = current_price - previous_price
                if price_diff != 0:
                    display = current_price_display or f"{current_price:.2f}"
                    if price_diff > 0:
                        result["price_change_display"] = f"↑ {price_diff:.2f} ({display})"
                    else:
                        result["price_change_display"] = f"↓ {abs(price_diff):.2f} ({display})"

            # 想要数变化
            previous_want = row["want_count"]
            if current_want_count is not None and previous_want is not None:
                want_diff = current_want_count - previous_want
                if abs(want_diff) > want_count_threshold:
                    if want_diff > 0:
                        result["want_count_change_display"] = f"↑ {want_diff} ({current_want_count}想要)"
                    else:
                        result["want_count_change_display"] = f"↓ {abs(want_diff)} ({current_want_count}想要)"

            if not result:
                return None

            return result

    def get_price_and_want_count_changes(self, item_id: str, want_count_threshold: int = 1) -> Optional[Dict]:
        """
        获取单个商品的价格和想要数变化信息（用于通知推送）
        Args:
            item_id: 商品 ID
            want_count_threshold: 想要数变化显示阈值（默认>1 才显示）
        Returns:
            包含价格和想要数变化显示的字典，首次爬取或无变化时返回 None
        """
        with sqlite_connection() as conn:
            # 获取最近两条记录
            cursor = conn.execute(
                """
                SELECT price, price_display, want_count, snapshot_time
                FROM item_metrics_history
                WHERE item_id = ?
                ORDER BY snapshot_time DESC
                LIMIT 2
                """,
                (item_id,),
            )
            rows = cursor.fetchall()

            if len(rows) < 2:
                # 首次爬取，没有历史记录对比，返回 None
                return None

            current = rows[0]
            previous = rows[1]

            result = {}

            # 价格变化（只要有变化就显示）
            current_price = current["price"]
            previous_price = previous["price"]
            current_price_display = current["price_display"] or "N/A"

            if current_price is not None and previous_price is not None:
                price_diff = current_price - previous_price
                if price_diff != 0:
                    if price_diff > 0:
                        result["price_change_display"] = f"↑ {price_diff:.2f} ({current_price_display})"
                    else:
                        result["price_change_display"] = f"↓ {abs(price_diff):.2f} ({current_price_display})"

            # 想要数变化（只有变化量超过阈值才显示）
            current_want = current["want_count"]
            previous_want = previous["want_count"]

            if current_want is not None and previous_want is not None:
                want_diff = current_want - previous_want
                if abs(want_diff) > want_count_threshold:
                    if want_diff > 0:
                        result["want_count_change_display"] = f"↑ {want_diff} ({current_want}想要)"
                    else:
                        result["want_count_change_display"] = f"↓ {abs(want_diff)} ({current_want}想要)"

            # 如果没有任何变化，返回 None
            if not result:
                return None

            return result


# 全局服务实例
_metrics_service: Optional[MetricsTrackingService] = None


def get_metrics_service() -> MetricsTrackingService:
    """获取指标追踪服务实例"""
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = MetricsTrackingService()
    return _metrics_service
