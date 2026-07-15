from datetime import datetime, timedelta

from src.infrastructure.persistence.sqlite_connection import init_schema, sqlite_connection
from src.services.monitoring_data_cleanup_service import cleanup_monitoring_data


def _insert_monitoring_rows(db_path, *, old_time: str, recent_time: str) -> None:
    with sqlite_connection(str(db_path)) as conn:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO result_items (
                result_filename, keyword, task_name, crawl_time, link_unique_key,
                is_recommended, keyword_hit_count, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("old.jsonl", "old", "old-task", old_time, "old-link", 0, 0, "{}"),
        )
        conn.execute(
            """
            INSERT INTO result_items (
                result_filename, keyword, task_name, crawl_time, link_unique_key,
                is_recommended, keyword_hit_count, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("recent.jsonl", "recent", "recent-task", recent_time, "recent-link", 0, 0, "{}"),
        )
        conn.execute(
            """
            INSERT INTO price_snapshots (
                keyword_slug, keyword, task_name, snapshot_time, snapshot_day,
                run_id, item_id, price, tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("old", "old", "old-task", old_time, old_time[:10], "run-old", "item-old", 1, "[]"),
        )
        conn.execute(
            """
            INSERT INTO price_snapshots (
                keyword_slug, keyword, task_name, snapshot_time, snapshot_day,
                run_id, item_id, price, tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "recent",
                "recent",
                "recent-task",
                recent_time,
                recent_time[:10],
                "run-recent",
                "item-recent",
                1,
                "[]",
            ),
        )
        conn.execute(
            """
            INSERT INTO item_metrics_history (
                item_id, title, snapshot_time
            ) VALUES (?, ?, ?)
            """,
            ("item-old", "old", old_time),
        )
        conn.execute(
            """
            INSERT INTO item_metrics_history (
                item_id, title, snapshot_time
            ) VALUES (?, ?, ?)
            """,
            ("item-recent", "recent", recent_time),
        )
        conn.commit()


def _count_rows(db_path, table_name: str) -> int:
    with sqlite_connection(str(db_path)) as conn:
        row = conn.execute(f"SELECT COUNT(1) AS total FROM {table_name}").fetchone()
    return int(row["total"])


def test_cleanup_monitoring_data_keeps_results_and_prunes_metric_history(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    now = datetime(2026, 7, 15, 12, 0, 0)
    old_time = (now - timedelta(days=21)).isoformat()
    recent_time = (now - timedelta(days=19)).isoformat()
    _insert_monitoring_rows(db_path, old_time=old_time, recent_time=recent_time)

    removed = cleanup_monitoring_data(keep_days=20, now=now, db_path=str(db_path))

    assert removed == {
        "price_snapshots": 1,
        "item_metrics_history": 1,
    }
    assert _count_rows(db_path, "result_items") == 2
    assert _count_rows(db_path, "price_snapshots") == 1
    assert _count_rows(db_path, "item_metrics_history") == 1
