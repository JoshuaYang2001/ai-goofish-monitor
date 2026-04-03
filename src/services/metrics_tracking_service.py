"""
指标追踪服务
负责记录和追踪商品价格/想要数变化
"""
import json
from datetime import datetime
from typing import Dict, List, Optional
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
    ) -> None:
        """记录商品指标快照"""
        with sqlite_connection() as conn:
            snapshot_time = datetime.now().isoformat()
            try:
                conn.execute(
                    """
                    INSERT INTO item_metrics_history (
                        item_id, title, snapshot_time, price, price_display,
                        want_count, browse_count, seller_id, link
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
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
            except Exception as e:
                # 忽略重复记录（UNIQUE 约束冲突）
                if "UNIQUE constraint failed" not in str(e):
                    print(f"记录指标历史失败：{e}")

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


# 全局服务实例
_metrics_service: Optional[MetricsTrackingService] = None


def get_metrics_service() -> MetricsTrackingService:
    """获取指标追踪服务实例"""
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = MetricsTrackingService()
    return _metrics_service
