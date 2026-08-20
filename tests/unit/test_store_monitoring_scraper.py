import asyncio

from src import scraper
from src.domain.models.store_monitoring import StoreMonitoringDigest
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.services.store_notification_outbox import (
    list_pending_store_digests,
    persist_store_run,
)


def test_active_store_items_keeps_only_unique_on_sale_products():
    cards = [
        {
            "cardData": {
                "id": "1001",
                "itemStatus": "0",
                "title": "在售商品",
                "wantCnt": "0人想要",
                "priceInfo": {"price": "12.5"},
                "picInfo": {"picUrl": "https://img.example/1001.jpg"},
            }
        },
        {"cardData": {"id": "1001", "itemStatus": 0, "title": "重复"}},
        {"cardData": {"id": "1002", "itemStatus": 1, "title": "已售"}},
        {"cardData": {"id": "1003", "itemStatus": 0, "title": "另一件"}},
    ]

    items = scraper._active_store_items(cards)

    assert [item["item_id"] for item in items] == ["1001", "1003"]
    assert items[0]["want_count"] == "0人想要"
    assert scraper.parse_metric_count(items[0]["want_count"]) == 0
    assert items[0]["price"] == "12.5"


def test_store_membership_preview_is_persisted_with_store_run(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "config-mode.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))
    monkeypatch.delenv("TENANT_ID", raising=False)

    first_sync = scraper._inspect_store_monitor_items(
        task_name="店铺组",
        items=[{"item_id": "1001", "title": "商品一"}],
    )
    persist_store_run(
        metric_observations=(),
        event_key="membership-run-1",
        digest=None,
        channel_keys=(),
        store_membership={
            "task_name": "店铺组",
            "store_id": "90001",
            "items": [{"item_id": "1001", "title": "商品一"}],
        },
    )
    second_sync = scraper._inspect_store_monitor_items(
        task_name="店铺组",
        items=[{"item_id": "1002", "title": "商品二"}],
    )
    persist_store_run(
        metric_observations=(),
        event_key="membership-run-2",
        digest=None,
        channel_keys=(),
        store_membership={
            "task_name": "店铺组",
            "store_id": "90001",
            "items": [{"item_id": "1002", "title": "商品二"}],
        },
    )

    with sqlite_connection() as connection:
        rows = connection.execute(
            """
            SELECT item_id, is_active
            FROM store_monitor_items
            WHERE task_name = '店铺组'
            ORDER BY item_id
            """
        ).fetchall()
    assert [(row["item_id"], row["is_active"]) for row in rows] == [
        ("1001", 0),
        ("1002", 1),
    ]
    assert first_sync == {
        "is_first_inventory": True,
        "added_items": [{"item_id": "1001", "title": "商品一"}],
        "removed_items": [],
    }
    assert second_sync == {
        "is_first_inventory": False,
        "added_items": [{"item_id": "1002", "title": "商品二"}],
        "removed_items": [{"item_id": "1001", "title": "商品一"}],
    }


def test_store_inventory_rejects_mtop_failure_instead_of_treating_it_as_empty():
    class FakeResponse:
        url = "https://h5api.m.goofish.com/mtop.idle.web.xyh.item.list/1.0/"
        ok = True
        status = 200

        async def json(self):
            return {
                "ret": ["FAIL_SYS_SESSION_EXPIRED::登录过期"],
                "data": {},
            }

    class FakePage:
        url = "https://www.goofish.com/personal?userId=90001"

        def on(self, _event, handler):
            self.handler = handler

        def remove_listener(self, _event, _handler):
            return None

        async def goto(self, *_args, **_kwargs):
            await self.handler(FakeResponse())

        async def evaluate(self, *_args, **_kwargs):
            return None

        async def close(self):
            return None

    class FakeContext:
        async def new_page(self):
            return FakePage()

    try:
        asyncio.run(
            scraper.scrape_store_inventory(
                FakeContext(),
                "90001",
                page_timeout_seconds=1,
            )
        )
    except RuntimeError as exc:
        assert "FAIL_SYS_SESSION_EXPIRED" in str(exc)
    else:
        raise AssertionError("错误的 MTop 响应不应被当成空店铺")


def test_store_notification_queue_retries_only_failed_channels(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "notification-retry.sqlite3"
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))
    monkeypatch.delenv("TENANT_ID", raising=False)
    digest = StoreMonitoringDigest(
        store_id="90001",
        task_name="店铺组",
        discovered_count=1,
        succeeded_count=1,
        failed_count=0,
    )

    class FakeNotificationService:
        def __init__(self, successful_channels):
            self.successful_channels = set(successful_channels)
            self.requested_channels = []

        def enabled_channel_keys(self):
            return ("feishu", "webhook")

        async def send_store_digest(self, _digest, *, channel_keys):
            requested = tuple(channel_keys)
            self.requested_channels.append(requested)
            return {
                channel: {
                    "success": channel in self.successful_channels,
                    "message": "ok" if channel in self.successful_channels else "timeout",
                }
                for channel in requested
            }

    first_service = FakeNotificationService({"feishu"})
    first_failures = asyncio.run(
        scraper._queue_and_deliver_store_notifications(
            notification_service=first_service,
            task_name="店铺组",
            event_key="store-run-1",
            digest=digest,
        )
    )

    assert first_failures == ["webhook"]
    assert first_service.requested_channels == [("feishu", "webhook")]
    pending = list_pending_store_digests(task_name="店铺组")
    assert len(pending) == 1
    assert pending[0].pending_channels == ("webhook",)

    retry_service = FakeNotificationService({"webhook"})
    retry_failures = asyncio.run(
        scraper._queue_and_deliver_store_notifications(
            notification_service=retry_service,
            task_name="店铺组",
            event_key="store-run-2",
            digest=None,
        )
    )

    assert retry_failures == []
    assert retry_service.requested_channels == [("webhook",)]
    assert list_pending_store_digests(task_name="店铺组") == []


def test_store_run_aggregates_changes_into_one_digest(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    sent_digests = []
    recorded_metrics = []
    saved_records = []
    market_snapshots = []
    detail_attempts = []

    class FakePage:
        async def goto(self, *_args, **_kwargs):
            return None

        async def evaluate(self, *_args, **_kwargs):
            return None

        async def close(self):
            return None

    class FakeContext:
        async def new_page(self):
            return FakePage()

    class FakeBrowser:
        async def new_context(self, **_kwargs):
            return FakeContext()

        async def close(self):
            return None

    class FakeChromium:
        async def launch(self, **_kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightContextManager:
        async def __aenter__(self):
            return FakePlaywright()

        async def __aexit__(self, *_args):
            return None

    class FakeMetricsService:
        def get_last_snapshot(self, item_id, *, task_name=None):
            if item_id == "1001":
                return {"want_count": 10, "price": 100.0}
            return None

        def compare_with_latest(self, **kwargs):
            if kwargs["item_id"] == "1001":
                return {
                    "previous_want_count": 10,
                    "current_want_count": 12,
                    "want_count_change_amount": 2,
                    "want_count_change_display": "↑ 2 (12想要)",
                }
            return None

        def record_metrics(self, **kwargs):
            recorded_metrics.append(kwargs)
            return True

    class FakeNotificationService:
        def enabled_channel_keys(self):
            return ("feishu",)

    async def fake_inventory(_context, store_id, **_kwargs):
        return {
            "store_id": store_id,
            "store_name": "示例店铺",
            "items": [
                {
                    "item_id": "1001",
                    "title": "旧商品",
                    "price": "100",
                    "want_count": 12,
                    "browse_count": 30,
                    "image_url": None,
                },
                {
                    "item_id": "1002",
                    "title": "新商品",
                    "price": "50",
                    "want_count": 3,
                    "browse_count": 8,
                    "image_url": None,
                },
                {
                    "item_id": "1003",
                    "title": "详情回退商品",
                    "price": "25",
                    "want_count": None,
                    "browse_count": None,
                    "image_url": None,
                },
                {
                    "item_id": "1004",
                    "title": "瞬时异常商品",
                    "price": "30",
                    "want_count": None,
                    "browse_count": None,
                    "image_url": None,
                },
            ],
        }

    async def fake_detail(_context, item_id):
        detail_attempts.append(item_id)
        if item_id == "1004" and detail_attempts.count(item_id) == 1:
            raise RuntimeError("瞬时 JSON 解析失败")
        if detail_attempts.count(item_id) == 1:
            return {
                "item_id": item_id,
                "商品 ID": item_id,
                "商品标题": "详情回退商品",
                "当前售价": "25",
                "商品链接": f"https://www.goofish.com/item?id={item_id}",
                "想要人数": None,
                "卖家 ID": "90001",
            }
        return {
            "item_id": item_id,
            "商品 ID": item_id,
            "商品标题": (
                "瞬时异常商品" if item_id == "1004" else "详情回退商品"
            ),
            "当前售价": "30" if item_id == "1004" else "25",
            "商品链接": f"https://www.goofish.com/item?id={item_id}",
            "想要人数": 5,
            "浏览量": 9,
            "卖家 ID": "90001",
            "商品图片列表": [],
        }

    async def fake_save(record, keyword):
        saved_records.append((record, keyword))
        return True

    async def no_delay(_minimum, _maximum):
        return None

    async def no_context_setup(_context):
        return None

    async def capture_digest(**kwargs):
        return []

    def capture_persisted_run(**kwargs):
        recorded_metrics.extend(kwargs["metric_observations"])
        if kwargs["digest"] is not None:
            sent_digests.append(kwargs["digest"])

    monkeypatch.setattr(
        scraper, "async_playwright", lambda: FakePlaywrightContextManager()
    )
    monkeypatch.setattr(
        scraper,
        "_resolve_store_runtime",
        lambda _config: (str(state_path), None),
    )
    monkeypatch.setattr(scraper, "_load_context_state", lambda _path: ({}, {}))
    monkeypatch.setattr(
        scraper, "_install_store_context_guards", no_context_setup
    )
    monkeypatch.setattr(scraper, "scrape_store_inventory", fake_inventory)
    monkeypatch.setattr(scraper, "_scrape_item_by_id_in_context", fake_detail)
    monkeypatch.setattr(scraper, "save_to_jsonl", fake_save)
    monkeypatch.setattr(
        scraper,
        "record_market_snapshots",
        lambda **kwargs: market_snapshots.append(kwargs),
    )
    monkeypatch.setattr(
        scraper, "build_notification_service", lambda: FakeNotificationService()
    )
    monkeypatch.setattr(scraper, "random_sleep", no_delay)
    monkeypatch.setattr(scraper, "_persist_discovered_store_name", lambda **_kwargs: None)
    monkeypatch.setattr(
        scraper,
        "_inspect_store_monitor_items",
        lambda **_kwargs: {
            "is_first_inventory": True,
            "added_items": [
                {"item_id": "1001", "title": "旧商品"},
                {"item_id": "1002", "title": "新商品"},
                {"item_id": "1003", "title": "详情回退商品"},
                {"item_id": "1004", "title": "瞬时异常商品"},
            ],
            "removed_items": [],
        },
    )
    monkeypatch.setattr(
        scraper, "_queue_and_deliver_store_notifications", capture_digest
    )
    monkeypatch.setattr(
        "src.services.store_notification_outbox.persist_store_run",
        capture_persisted_run,
    )
    monkeypatch.setattr(scraper.FAILURE_GUARD, "record_success", lambda _name: None)
    monkeypatch.setattr(
        "src.services.metrics_tracking_service.get_metrics_service",
        lambda: FakeMetricsService(),
    )

    result = asyncio.run(
        scraper.scrape_store_by_id(
            store_id="90001",
            task_config={"task_name": "示例店铺监控", "store_id": "90001"},
        )
    )

    assert result == {
        "processed_count": 4,
        "discovered_count": 4,
        "failed_count": 0,
        "changed_count": 4,
        "store_name": "示例店铺",
    }
    assert len(sent_digests) == 1
    digest = sent_digests[0]
    assert digest.store_name == "示例店铺"
    assert digest.is_initial_snapshot is False
    assert [change.item_id for change in digest.changes] == [
        "1001",
        "1002",
        "1003",
        "1004",
    ]
    assert digest.changes[0].want_count_delta == 2
    assert digest.changes[1].previous_want_count is None
    assert detail_attempts == ["1003", "1003", "1004", "1004"]
    assert len(recorded_metrics) == 4
    assert len(saved_records) == 4
    assert len(market_snapshots) == 4
