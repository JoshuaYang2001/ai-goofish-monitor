import asyncio
import json
import sqlite3

from src.api.routes import tasks as task_routes
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository


def test_create_list_update_delete_task(api_client, api_context, sample_task_payload):
    response = api_client.post("/api/tasks/", json=sample_task_payload)
    assert response.status_code == 200
    created = response.json()["task"]
    assert created["task_name"] == sample_task_payload["task_name"]
    assert created["next_run_at"] == "2026-03-19T08:15:00+08:00"

    response = api_client.get("/api/tasks")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["keyword"] == sample_task_payload["keyword"]
    assert tasks[0]["next_run_at"] == "2026-03-19T08:15:00+08:00"

    response = api_client.patch("/api/tasks/0", json={"enabled": False})
    assert response.status_code == 200
    updated = response.json()["task"]
    assert updated["enabled"] is False
    assert updated["next_run_at"] is None

    response = api_client.delete("/api/tasks/0")
    assert response.status_code == 200

    response = api_client.get("/api/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_start_stop_task_updates_status(api_client, api_context, sample_task_payload):
    response = api_client.post("/api/tasks/", json=sample_task_payload)
    assert response.status_code == 200

    response = api_client.post("/api/tasks/start/0")
    assert response.status_code == 200

    response = api_client.get("/api/tasks/0")
    assert response.status_code == 200
    assert response.json()["is_running"] is True

    response = api_client.post("/api/tasks/stop/0")
    assert response.status_code == 200

    response = api_client.get("/api/tasks/0")
    assert response.status_code == 200
    assert response.json()["is_running"] is False

    process_service = api_context["process_service"]
    assert process_service.started == [(0, sample_task_payload["task_name"])]
    assert process_service.stopped == [0]


def test_create_item_id_task_directly_keeps_all_unique_ids(api_client):
    response = api_client.post(
        "/api/tasks/",
        json={
            "task_name": "指定商品监控",
            "task_type": "item_id",
            "item_id_list": ["123456", "987654", "123456"],
            "cron": "*/15 * * * *",
        },
    )

    assert response.status_code == 200
    task = response.json()["task"]
    assert task["item_id_list"] == ["123456", "987654"]
    assert task["keyword_rules"] == ["123456", "987654"]


def test_create_update_and_reload_store_task(api_client, api_context):
    response = api_client.post(
        "/api/tasks/",
        json={
            "task_name": "全店商品监控",
            "task_type": "store",
            "store_id": "https://www.goofish.com/personal?userId=2206814873475",
            "store_name": "相机铺子",
            "cron": "*/15 * * * *",
        },
    )

    assert response.status_code == 200
    task = response.json()["task"]
    assert task["task_type"] == "store"
    assert task["store_id"] == "2206814873475"
    assert task["store_name"] == "相机铺子"
    assert task["keyword_rules"] == []

    update_response = api_client.patch(
        "/api/tasks/0",
        json={
            "store_id": "https://www.goofish.com/personal?uid=99887766",
            "store_name": "新店名",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["task"]["store_id"] == "99887766"

    repository = SqliteTaskRepository(
        db_path=api_context["db_path"],
        legacy_config_file=None,
    )
    persisted = asyncio.run(repository.find_by_id(0))
    assert persisted is not None
    assert persisted.task_type == "store"
    assert persisted.store_id == "99887766"
    assert persisted.store_name == "新店名"


def test_store_task_rejects_missing_or_invalid_store_id(api_client):
    missing_response = api_client.post(
        "/api/tasks/",
        json={"task_name": "无店铺", "task_type": "store"},
    )
    assert missing_response.status_code == 422

    invalid_response = api_client.post(
        "/api/tasks/",
        json={
            "task_name": "错误店铺",
            "task_type": "store",
            "store_id": "https://www.goofish.com/personal",
        },
    )
    assert invalid_response.status_code == 422


def test_create_task_accepts_cron_alias(api_client, sample_task_payload):
    payload = dict(sample_task_payload)
    payload["cron"] = "@daily"

    response = api_client.post("/api/tasks/", json=payload)

    assert response.status_code == 200
    assert response.json()["task"]["cron"] == "0 0 * * *"


def test_create_task_rejects_fixed_account_strategy_without_state_file(api_client, sample_task_payload):
    payload = dict(sample_task_payload)
    payload["account_strategy"] = "fixed"

    response = api_client.post("/api/tasks/", json=payload)

    assert response.status_code == 422


def test_create_task_accepts_rotate_account_strategy(api_client, sample_task_payload):
    payload = dict(sample_task_payload)
    payload["account_strategy"] = "rotate"

    response = api_client.post("/api/tasks/", json=payload)

    assert response.status_code == 200
    task = response.json()["task"]
    assert task["account_strategy"] == "rotate"


def test_update_task_accepts_six_field_cron_expression(api_client, sample_task_payload):
    create_response = api_client.post("/api/tasks/", json=sample_task_payload)
    assert create_response.status_code == 200

    response = api_client.patch("/api/tasks/0", json={"cron": "0 0 8 * * *"})

    assert response.status_code == 200

    task_response = api_client.get("/api/tasks/0")
    assert task_response.status_code == 200
    assert task_response.json()["cron"] == "0 0 8 * * *"


def test_create_task_rejects_invalid_cron_expression(api_client, sample_task_payload):
    payload = dict(sample_task_payload)
    payload["cron"] = "every day at 8"

    response = api_client.post("/api/tasks/", json=payload)

    assert response.status_code == 422


def test_create_and_update_task_reject_cron_shorter_than_15_minutes(
    api_client, sample_task_payload
):
    payload = dict(sample_task_payload)
    payload["cron"] = "*/5 * * * *"

    create_response = api_client.post("/api/tasks/", json=payload)
    assert create_response.status_code == 422
    assert "15 分钟" in create_response.text

    assert api_client.post("/api/tasks/", json=sample_task_payload).status_code == 200
    update_response = api_client.patch("/api/tasks/0", json={"cron": "*/10 * * * *"})
    assert update_response.status_code == 422
    assert "15 分钟" in update_response.text


def test_create_task_rejects_when_task_limit_is_reached(
    api_client,
    sample_task_payload,
    monkeypatch,
):
    monkeypatch.setattr(task_routes.app_settings, "max_tasks", 2)

    for index in range(2):
        payload = dict(sample_task_payload)
        payload["task_name"] = f"Sony A7M4 {index}"
        payload["keyword"] = f"sony a7m4 {index}"
        payload["keyword_rules"] = [payload["keyword"]]
        assert api_client.post("/api/tasks/", json=payload).status_code == 200

    payload = dict(sample_task_payload)
    payload["task_name"] = "Sony A7M4 limit"
    payload["keyword"] = "sony a7m4 limit"
    payload["keyword_rules"] = [payload["keyword"]]

    response = api_client.post("/api/tasks/", json=payload)

    assert response.status_code == 400
    assert "最多只能创建 2 条任务" in response.json()["detail"]


def test_delete_task_stops_runtime_and_reindexes_process_state(
    api_client,
    api_context,
    sample_task_payload,
):
    second_payload = dict(sample_task_payload)
    second_payload["task_name"] = "Sony A7CR"
    second_payload["keyword"] = "sony a7cr"
    second_payload["keyword_rules"] = ["sony a7cr"]

    assert api_client.post("/api/tasks/", json=sample_task_payload).status_code == 200
    assert api_client.post("/api/tasks/", json=second_payload).status_code == 200
    assert api_client.post("/api/tasks/start/0").status_code == 200

    response = api_client.delete("/api/tasks/0")

    assert response.status_code == 200
    process_service = api_context["process_service"]
    assert process_service.stopped == [0]
    assert process_service.reindexed == []


def test_rename_task_updates_store_membership_and_notification_outbox(
    api_client,
    api_context,
    sample_task_payload,
):
    assert api_client.post("/api/tasks/", json=sample_task_payload).status_code == 200

    old_task_name = sample_task_payload["task_name"]
    new_task_name = "Sony A7M4 店铺监控"
    snapshot_time = "2026-07-15T10:00:00"
    with sqlite3.connect(api_context["db_path"]) as connection:
        connection.execute(
            """
            INSERT INTO store_monitor_items (
                task_name, store_id, item_id, title, is_active,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (old_task_name, "100", "200", "测试商品", snapshot_time, snapshot_time),
        )
        connection.execute(
            """
            INSERT INTO store_notification_outbox (
                event_key, task_name, payload_json, pending_channels_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "store-run:rename-test",
                old_task_name,
                json.dumps({"task_name": old_task_name}, ensure_ascii=False),
                '["feishu"]',
                snapshot_time,
                snapshot_time,
            ),
        )
        connection.commit()

    response = api_client.patch("/api/tasks/0", json={"task_name": new_task_name})

    assert response.status_code == 200
    with sqlite3.connect(api_context["db_path"]) as connection:
        member_task_name = connection.execute(
            "SELECT task_name FROM store_monitor_items WHERE item_id = ?",
            ("200",),
        ).fetchone()[0]
        outbox_task_name = connection.execute(
            "SELECT task_name FROM store_notification_outbox WHERE event_key = ?",
            ("store-run:rename-test",),
        ).fetchone()[0]
    assert member_task_name == new_task_name
    assert outbox_task_name == new_task_name


def test_delete_task_cascades_only_its_results_and_history(
    api_client,
    api_context,
    sample_task_payload,
):
    second_payload = dict(sample_task_payload)
    second_payload["task_name"] = "另一个 Sony 任务"

    assert api_client.post("/api/tasks/", json=sample_task_payload).status_code == 200
    assert api_client.post("/api/tasks/", json=second_payload).status_code == 200

    with sqlite3.connect(api_context["db_path"]) as connection:
        for index, task_name in enumerate(("Sony A7M4", "另一个 Sony 任务"), start=1):
            record = {
                "搜索关键字": "sony a7m4",
                "任务名称": task_name,
                "爬取时间": f"2026-07-15T10:0{index}:00",
                "商品信息": {"商品ID": str(index), "商品标题": task_name},
            }
            connection.execute(
                """
                INSERT INTO result_items (
                    result_filename, keyword, task_name, crawl_time,
                    link_unique_key, is_recommended, keyword_hit_count, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "sony_a7m4_full_data.jsonl",
                    "sony a7m4",
                    task_name,
                    record["爬取时间"],
                    f"item:{index}",
                    0,
                    0,
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                INSERT INTO price_snapshots (
                    keyword_slug, keyword, task_name, snapshot_time, snapshot_day,
                    run_id, item_id, price, tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "sony_a7m4",
                    "sony a7m4",
                    task_name,
                    record["爬取时间"],
                    "2026-07-15",
                    f"run-{index}",
                    str(index),
                    1000 + index,
                    "[]",
                ),
            )
            connection.execute(
                """
                INSERT INTO item_metrics_history (
                    task_name, item_id, title, snapshot_time, price, want_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_name, str(index), task_name, record["爬取时间"], 1000 + index, index),
            )
            connection.execute(
                """
                INSERT INTO store_monitor_items (
                    task_name, store_id, item_id, title, is_active,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    task_name,
                    str(index),
                    str(index),
                    task_name,
                    record["爬取时间"],
                    record["爬取时间"],
                ),
            )
            connection.execute(
                """
                INSERT INTO store_notification_outbox (
                    event_key, task_name, payload_json, pending_channels_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"store-run:delete-test:{index}",
                    task_name,
                    json.dumps({"task_name": task_name}, ensure_ascii=False),
                    '["feishu"]',
                    record["爬取时间"],
                    record["爬取时间"],
                ),
            )
        connection.commit()

    response = api_client.delete("/api/tasks/0")

    assert response.status_code == 200
    with sqlite3.connect(api_context["db_path"]) as connection:
        for table_name in (
            "result_items",
            "price_snapshots",
            "item_metrics_history",
            "store_monitor_items",
            "store_notification_outbox",
        ):
            task_names = {
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT task_name FROM {table_name}"
                ).fetchall()
            }
            assert task_names == {"另一个 Sony 任务"}


def test_task_schema_migration_preserves_monitoring_fields(tmp_path):
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                task_name TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                keyword TEXT,
                legacy_analysis TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO tasks VALUES (3, '旧任务', 1, 'MacBook', 'retired')"
        )
        connection.commit()

    repository = SqliteTaskRepository(
        db_path=str(database_path),
        legacy_config_file=None,
    )
    tasks = asyncio.run(repository.find_all())

    assert len(tasks) == 1
    assert tasks[0].id == 3
    assert tasks[0].keyword == "MacBook"
    assert tasks[0].keyword_rules == ["MacBook"]

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
    assert "legacy_analysis" not in columns
    assert "item_id_list_json" in columns
    assert "store_id" in columns
    assert "store_name" in columns
