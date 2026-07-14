from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import metrics
from src.infrastructure.persistence.sqlite_connection import init_schema, sqlite_connection
from src.services.metrics_tracking_service import MetricsTrackingService


def test_change_overview_uses_requested_time_windows(tmp_path, monkeypatch):
    database_path = tmp_path / "metrics.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))
    now = datetime(2026, 7, 14, 12, 0, 0)

    with sqlite_connection() as conn:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO price_snapshots (
                keyword_slug, keyword, task_name, snapshot_time, snapshot_day,
                run_id, item_id, title, price, price_display, tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "iphone",
                "iPhone 15",
                "手机监控",
                now.isoformat(),
                now.date().isoformat(),
                "run-1",
                "123456",
                "iPhone 15",
                4800,
                "¥4800",
                "[]",
            ),
        )
        for hours_ago, price, want_count in ((50, 5200, 10), (25, 5000, 20), (2, 4800, 36)):
            conn.execute(
                """
                INSERT INTO item_metrics_history (
                    item_id, title, snapshot_time, price, price_display,
                    want_count, seller_id, link
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "123456",
                    "iPhone 15",
                    (now - timedelta(hours=hours_ago)).isoformat(),
                    price,
                    f"¥{price}",
                    want_count,
                    "seller-1",
                    "https://example.test/123456",
                ),
            )
        conn.commit()

    overview = MetricsTrackingService().get_change_overview([24, 48], now=now)

    assert overview["interval_hours"] == [24, 48]
    assert overview["task_names"] == ["手机监控"]
    assert overview["summaries"]["24"]["want_change"] == 16
    assert overview["summaries"]["48"]["want_change"] == 26
    assert overview["summaries"]["24"]["price_change"] == -200.0
    assert overview["summaries"]["48"]["price_change"] == -400.0
    assert overview["items"][0]["changes"]["48"]["baseline_want_count"] == 10


def test_change_overview_filters_by_title_or_item_id(tmp_path, monkeypatch):
    database_path = tmp_path / "metrics.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))

    with sqlite_connection() as conn:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO item_metrics_history (
                item_id, title, snapshot_time, price, want_count
            ) VALUES ('9988', '机械键盘', '2026-07-14T10:00:00', 399, 8)
            """
        )
        conn.commit()

    service = MetricsTrackingService()
    assert len(service.get_change_overview([24], search="键盘")["items"]) == 1
    assert len(service.get_change_overview([24], search="9988")["items"]) == 1
    assert service.get_change_overview([24], search="相机")["items"] == []


def test_changes_route_accepts_repeated_interval_parameters(tmp_path, monkeypatch):
    database_path = tmp_path / "metrics.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))
    with sqlite_connection() as conn:
        init_schema(conn)

    app = FastAPI()
    app.include_router(metrics.router)

    with TestClient(app) as client:
        missing_task_response = client.get(
            "/api/metrics/changes?interval=24&interval=48"
        )
        response = client.get(
            "/api/metrics/changes?interval=24&interval=48&task_name=手机监控"
        )

    assert missing_task_response.status_code == 422
    assert response.status_code == 200
    assert response.json()["interval_hours"] == [24, 48]


def test_change_overview_only_aggregates_selected_task(tmp_path, monkeypatch):
    database_path = tmp_path / "metrics-by-task.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))
    now = datetime(2026, 7, 14, 12, 0, 0)

    with sqlite_connection() as conn:
        init_schema(conn)
        for task_name, item_id, start_price, end_price in (
            ("相机监控", "camera-1", 5000, 4800),
            ("手机监控", "phone-1", 4000, 3500),
        ):
            for hours_ago, price, want_count in (
                (25, start_price, 10),
                (1, end_price, 20),
            ):
                conn.execute(
                    """
                    INSERT INTO item_metrics_history (
                        task_name, item_id, title, snapshot_time, price, want_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_name,
                        item_id,
                        item_id,
                        (now - timedelta(hours=hours_ago)).isoformat(),
                        price,
                        want_count,
                    ),
                )
        conn.commit()

    overview = MetricsTrackingService().get_change_overview(
        [24],
        task_name="相机监控",
        now=now,
    )

    assert overview["task_names"] == ["相机监控"]
    assert [item["item_id"] for item in overview["items"]] == ["camera-1"]
    assert overview["summaries"]["24"]["want_change"] == 10
    assert overview["summaries"]["24"]["price_change"] == -200.0
