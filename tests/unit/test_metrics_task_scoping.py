from datetime import datetime

from src.infrastructure.persistence.sqlite_connection import init_schema, sqlite_connection
from src.services.metrics_tracking_service import MetricsTrackingService


def test_metric_comparison_uses_task_scoped_baseline_and_detects_plus_one(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "metrics.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))
    with sqlite_connection() as connection:
        init_schema(connection)

    service = MetricsTrackingService()
    shared = {
        "item_id": "same-item",
        "title": "同一商品",
        "price": 100.0,
        "price_display": "100",
        "browse_count": 1,
        "seller_id": "seller",
        "link": "https://www.goofish.com/item?id=same-item",
    }
    assert service.record_metrics(task_name="店铺 A", want_count=10, **shared)
    assert service.record_metrics(task_name="店铺 B", want_count=100, **shared)

    changes = service.compare_with_latest(
        item_id="same-item",
        current_price=100.0,
        current_price_display="100",
        current_want_count=11,
        want_count_threshold=1,
        task_name="店铺 A",
    )

    assert changes is not None
    assert changes["previous_want_count"] == 10
    assert changes["current_want_count"] == 11
    assert changes["want_count_change_amount"] == 1
    assert service.get_last_snapshot(
        "same-item", task_name="店铺 B"
    )["want_count"] == 100


def test_change_overview_hides_inactive_store_members(tmp_path, monkeypatch):
    database_path = tmp_path / "store-members.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))
    snapshot_time = datetime(2026, 8, 20, 12, 0, 0)
    with sqlite_connection() as connection:
        init_schema(connection)
        connection.execute(
            """
            INSERT INTO tasks (
                id, task_name, task_type, enabled, store_id, max_pages,
                personal_only, account_strategy, free_shipping,
                keyword_rules_json, is_running
            ) VALUES (1, '店铺组', 'store', 1, '90001', 1, 1, 'auto', 1, '[]', 0)
            """
        )
        for item_id, is_active in (("active-item", 1), ("sold-item", 0)):
            connection.execute(
                """
                INSERT INTO store_monitor_items (
                    task_name, store_id, item_id, title, is_active,
                    first_seen_at, last_seen_at
                ) VALUES ('店铺组', '90001', ?, ?, ?, ?, ?)
                """,
                (item_id, item_id, is_active, snapshot_time.isoformat(), snapshot_time.isoformat()),
            )
            connection.execute(
                """
                INSERT INTO item_metrics_history (
                    task_name, item_id, title, snapshot_time, price, want_count
                ) VALUES ('店铺组', ?, ?, ?, 10, 1)
                """,
                (item_id, item_id, snapshot_time.isoformat()),
            )
        connection.commit()

    overview = MetricsTrackingService().get_change_overview(
        [1], now=datetime(2026, 8, 20, 12, 30, 0)
    )

    assert [item["item_id"] for item in overview["items"]] == ["active-item"]
