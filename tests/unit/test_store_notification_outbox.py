from datetime import datetime

import pytest

from src.domain.models.store_monitoring import (
    StoreItemChange,
    StoreItemLifecycle,
    StoreMonitoringDigest,
)
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.services.store_notification_outbox import (
    enqueue_store_digest,
    list_pending_store_digests,
    persist_store_run,
    update_store_digest_delivery,
)


def _configure_database(tmp_path, monkeypatch):
    database_path = tmp_path / "store-outbox.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))
    monkeypatch.delenv("TENANT_ID", raising=False)
    return database_path


def _build_digest(task_name: str = "旧店铺任务") -> StoreMonitoringDigest:
    return StoreMonitoringDigest(
        store_id="seller-1001",
        store_name="相机好物店",
        task_name=task_name,
        discovered_count=5,
        succeeded_count=4,
        failed_count=1,
        changes=(
            StoreItemChange(
                item_id="item-changed",
                title="想要数变化商品",
                previous_want_count=10,
                current_want_count=13,
                want_count_delta=3,
                previous_price=8999.0,
                current_price="8799",
                link="https://www.goofish.com/item?id=item-changed",
            ),
        ),
        added_items=(
            StoreItemLifecycle(
                item_id="item-added",
                title="新上架商品",
                link="https://www.goofish.com/item?id=item-added",
            ),
        ),
        removed_items=(
            StoreItemLifecycle(
                item_id="item-removed",
                title="下架商品",
                link="https://www.goofish.com/item?id=item-removed",
            ),
        ),
        is_initial_snapshot=True,
        monitored_at=datetime(2026, 8, 20, 10, 30, 45),
    )


def test_outbox_round_trips_digest_lifecycle_fields(tmp_path, monkeypatch):
    _configure_database(tmp_path, monkeypatch)
    digest = _build_digest()

    assert enqueue_store_digest(
        event_key="run-lifecycle",
        digest=digest,
        channel_keys=("feishu",),
    )

    pending = list_pending_store_digests(task_name=digest.task_name)
    assert len(pending) == 1
    restored = pending[0].digest
    assert restored == digest
    assert restored.monitored_at == datetime(2026, 8, 20, 10, 30, 45)
    assert restored.changes[0].want_count_delta == 3
    assert restored.added_items[0].item_id == "item-added"
    assert restored.removed_items[0].item_id == "item-removed"


def test_failed_delivery_stays_pending_then_success_deletes_it(
    tmp_path, monkeypatch
):
    _configure_database(tmp_path, monkeypatch)
    digest = _build_digest()
    assert enqueue_store_digest(
        event_key="run-retry",
        digest=digest,
        channel_keys=("feishu",),
    )
    record = list_pending_store_digests(task_name=digest.task_name)[0]

    update_store_digest_delivery(
        record_id=record.id,
        failed_channels=("feishu",),
        last_error="飞书暂时不可用",
    )

    after_failure = list_pending_store_digests(task_name=digest.task_name)
    assert len(after_failure) == 1
    assert after_failure[0].pending_channels == ("feishu",)
    assert after_failure[0].attempts == 1

    update_store_digest_delivery(
        record_id=after_failure[0].id,
        failed_channels=(),
        last_error=None,
    )

    assert list_pending_store_digests(task_name=digest.task_name) == []


def test_partial_delivery_keeps_only_failed_channel(tmp_path, monkeypatch):
    _configure_database(tmp_path, monkeypatch)
    digest = _build_digest()
    assert enqueue_store_digest(
        event_key="run-partial",
        digest=digest,
        channel_keys=("feishu", "wecom"),
    )
    record = list_pending_store_digests(task_name=digest.task_name)[0]

    # Simulate Feishu succeeding while WeCom remains unavailable.
    update_store_digest_delivery(
        record_id=record.id,
        failed_channels=("wecom",),
        last_error="wecom: timeout",
    )

    pending = list_pending_store_digests(task_name=digest.task_name)
    assert len(pending) == 1
    assert pending[0].pending_channels == ("wecom",)
    assert pending[0].attempts == 1


def test_database_task_name_overrides_stale_payload_after_rename(
    tmp_path, monkeypatch
):
    _configure_database(tmp_path, monkeypatch)
    digest = _build_digest(task_name="旧店铺任务")
    assert enqueue_store_digest(
        event_key="run-before-rename",
        digest=digest,
        channel_keys=("feishu",),
    )

    # The task repository renames this indexed column together with task history;
    # payload_json intentionally remains the immutable original event payload.
    with sqlite_connection() as connection:
        connection.execute(
            """
            UPDATE store_notification_outbox
            SET task_name = ?
            WHERE task_name = ?
            """,
            ("新店铺任务", "旧店铺任务"),
        )
        connection.commit()

    assert list_pending_store_digests(task_name="旧店铺任务") == []
    pending = list_pending_store_digests(task_name="新店铺任务")
    assert len(pending) == 1
    assert pending[0].digest.task_name == "新店铺任务"

    with sqlite_connection() as connection:
        payload_json = connection.execute(
            """
            SELECT payload_json
            FROM store_notification_outbox
            WHERE event_key = 'run-before-rename'
            """
        ).fetchone()["payload_json"]
    assert '"task_name": "旧店铺任务"' in payload_json


def test_store_membership_metrics_and_outbox_roll_back_together(
    tmp_path, monkeypatch
):
    _configure_database(tmp_path, monkeypatch)
    persist_store_run(
        metric_observations=(),
        event_key="baseline-membership",
        digest=None,
        channel_keys=(),
        store_membership={
            "task_name": "店铺组",
            "store_id": "1001",
            "items": [{"item_id": "old-item", "title": "旧商品"}],
        },
    )

    with pytest.raises(KeyError):
        persist_store_run(
            # 缺少 item_id 会在成员变更已执行后触发异常，用于
            # 验证整个事务（含 active/inactive）都会回滚。
            metric_observations=(
                {
                    "task_name": "店铺组",
                    "title": "不完整指标",
                    "snapshot_time": "2026-08-20T12:00:00",
                },
            ),
            event_key="failed-atomic-run",
            digest=_build_digest(task_name="店铺组"),
            channel_keys=("feishu",),
            store_membership={
                "task_name": "店铺组",
                "store_id": "1001",
                "items": [{"item_id": "new-item", "title": "新商品"}],
            },
        )

    with sqlite_connection() as connection:
        members = connection.execute(
            """
            SELECT item_id, is_active
            FROM store_monitor_items
            WHERE task_name = '店铺组'
            ORDER BY item_id
            """
        ).fetchall()
        outbox_count = connection.execute(
            "SELECT COUNT(*) AS total FROM store_notification_outbox"
        ).fetchone()["total"]
        metric_count = connection.execute(
            "SELECT COUNT(*) AS total FROM item_metrics_history"
        ).fetchone()["total"]

    assert [(row["item_id"], row["is_active"]) for row in members] == [
        ("old-item", 1)
    ]
    assert outbox_count == 0
    assert metric_count == 0
