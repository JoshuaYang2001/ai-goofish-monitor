"""
监控数据清理服务。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection


MONITORING_RETENTION_TABLES = {
    "price_snapshots": "snapshot_time",
    "item_metrics_history": "snapshot_time",
}


def cleanup_monitoring_data(
    *,
    keep_days: int = 20,
    now: datetime | None = None,
    db_path: str | None = None,
) -> dict[str, int]:
    if keep_days < 1:
        print(f"监控数据清理已跳过：保留天数配置无效 ({keep_days})")
        return {}

    if db_path is None:
        bootstrap_sqlite_storage()

    cutoff = (now or datetime.now()) - timedelta(days=keep_days)
    cutoff_text = cutoff.isoformat()
    removed_counts: dict[str, int] = {}

    with sqlite_connection(db_path) as conn:
        for table_name, time_column in MONITORING_RETENTION_TABLES.items():
            cursor = conn.execute(
                f"DELETE FROM {table_name} WHERE {time_column} < ?",
                (cutoff_text,),
            )
            removed_counts[table_name] = int(cursor.rowcount or 0)
        conn.commit()

    total_removed = sum(removed_counts.values())
    if total_removed:
        print(
            f"监控数据清理完成：已删除 {total_removed} 条超过 {keep_days} 天的历史记录。"
        )

    return removed_counts
