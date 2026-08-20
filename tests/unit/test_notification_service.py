import asyncio
from datetime import datetime

from src.domain.models.store_monitoring import (
    StoreItemChange,
    StoreItemLifecycle,
    StoreMonitoringDigest,
)
from src.infrastructure.external.notification_clients.base import NotificationClient
from src.infrastructure.external.notification_clients.feishu_client import FeishuClient
from src.infrastructure.external.notification_clients.webhook_client import WebhookClient
from src.services.notification_service import NotificationService


class _OkClient(NotificationClient):
    channel_key = "ok"
    display_name = "OK"

    async def send(self, product_data, reason):
        return None


class _FailClient(NotificationClient):
    channel_key = "fail"
    display_name = "FAIL"

    async def send(self, product_data, reason):
        raise RuntimeError("boom")


class _StoreDigestClient(NotificationClient):
    channel_key = "store"
    display_name = "STORE"

    def __init__(self):
        super().__init__(enabled=True)
        self.received_digest = None

    async def send(self, product_data, reason):
        return None

    async def send_store_digest(self, digest):
        self.received_digest = digest


def test_notification_service_collects_success_and_failure_results():
    service = NotificationService([_OkClient(enabled=True), _FailClient(enabled=True)])

    results = asyncio.run(
        service.send_notification({"商品标题": "Sony A7M4"}, "价格合适")
    )

    assert results["ok"]["success"] is True
    assert results["ok"]["message"] == "发送成功"
    assert results["fail"]["success"] is False
    assert results["fail"]["message"] == "boom"


def test_webhook_client_renders_json_templates(monkeypatch):
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

    def _fake_post(url, headers=None, json=None, data=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["data"] = data
        return _FakeResponse()

    monkeypatch.setattr("requests.post", _fake_post)

    client = WebhookClient(
        webhook_url="https://hooks.example.com/notify",
        webhook_method="POST",
        webhook_headers='{"Authorization":"Bearer token"}',
        webhook_content_type="JSON",
        webhook_query_parameters='{"task":"{{title}}"}',
        webhook_body='{"message":"{{content}}","link":"{{desktop_link}}"}',
        pcurl_to_mobile=False,
    )

    asyncio.run(
        client.send(
            {
                "商品标题": "Sony A7M4",
                "当前售价": "9999",
                "商品链接": "https://www.goofish.com/item/123",
            },
            "价格合适",
        )
    )

    assert "task=%F0%9F%9A%A8+%E6%96%B0%E6%8E%A8%E8%8D%90%21+Sony+A7M4" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["json"]["message"].startswith("价格: 9999")
    assert captured["json"]["link"] == "https://www.goofish.com/item/123"
    assert captured["data"] is None


def _build_store_digest(**overrides):
    values = {
        "store_id": "seller-1001",
        "store_name": "相机好物店",
        "task_name": "相机店铺监控",
        "discovered_count": 3,
        "succeeded_count": 2,
        "failed_count": 1,
        "changes": (
            StoreItemChange(
                item_id="item-1",
                title="Sony A7M4",
                previous_want_count=10,
                current_want_count=13,
                want_count_delta=3,
                previous_price="8999",
                current_price="8799",
                link="https://www.goofish.com/item?id=item-1",
            ),
        ),
        "monitored_at": datetime(2026, 8, 20, 10, 30, 0),
    }
    values.update(overrides)
    return StoreMonitoringDigest(**values)


def test_notification_service_sends_one_store_digest_to_each_client():
    client = _StoreDigestClient()
    service = NotificationService([client])
    digest = _build_store_digest()

    results = asyncio.run(service.send_store_digest(digest))

    assert client.received_digest is digest
    assert results["store"]["success"] is True


def test_feishu_client_builds_single_store_digest_card(monkeypatch):
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr("requests.post", _fake_post)
    client = FeishuClient("https://open.feishu.cn/webhook/test")

    asyncio.run(client.send_store_digest(_build_store_digest()))

    assert captured["json"]["msg_type"] == "interactive"
    card = captured["json"]["card"]
    assert len(card["elements"]) == 1
    content = card["elements"][0]["text"]["content"]
    assert "相机好物店" in content
    assert "发现 3 件 · 成功 2 件 · 失败 1 件" in content
    assert "Sony A7M4" in content
    assert "想要数：10 → 13（+3）" in content
    assert "价格：¥8999 → ¥8799" in content


def test_feishu_digest_explicitly_marks_initial_and_unchanged_runs():
    client = FeishuClient("https://open.feishu.cn/webhook/test")

    initial_card = client._build_store_digest_card(
        _build_store_digest(changes=(), is_initial_snapshot=True, failed_count=0)
    )
    unchanged_card = client._build_store_digest_card(
        _build_store_digest(changes=(), is_initial_snapshot=False, failed_count=0)
    )

    initial_content = initial_card["elements"][0]["text"]["content"]
    unchanged_content = unchanged_card["elements"][0]["text"]["content"]
    assert "首次监控，已建立数据基线" in initial_content
    assert "本轮没有需要展开的商品变化明细" in initial_content
    assert "未发现商品数据变化" in unchanged_content


def test_feishu_digest_marks_a_newly_discovered_product():
    client = FeishuClient("https://open.feishu.cn/webhook/test")
    new_item = StoreItemChange(
        item_id="new-item",
        title="新上架商品",
        previous_want_count=None,
        current_want_count=0,
        want_count_delta=None,
        current_price=10.0,
        link="https://www.goofish.com/item?id=new-item",
    )

    card = client._build_store_digest_card(
        _build_store_digest(
            changes=(new_item,),
            added_items=(
                StoreItemLifecycle(
                    item_id="new-item",
                    title="新上架商品",
                    link="https://www.goofish.com/item?id=new-item",
                ),
            ),
        )
    )

    content = card["elements"][0]["text"]["content"]
    assert "想要数：— → 0（首次纳入）" in content
    assert content.count("新上架商品") == 1


def test_feishu_store_digest_applies_length_limit():
    client = FeishuClient("https://open.feishu.cn/webhook/test")
    changes = tuple(
        StoreItemChange(
            item_id=f"item-{index}",
            title=f"商品 {index} " + ("很长的标题" * 50),
            previous_want_count=index,
            current_want_count=index + 1,
            want_count_delta=1,
            link=f"https://www.goofish.com/item?id={index}",
        )
        for index in range(500)
    )

    card = client._build_store_digest_card(_build_store_digest(changes=changes))

    content = card["elements"][0]["text"]["content"]
    assert len(content.encode("utf-8")) <= client.MAX_CARD_CONTENT_BYTES
    assert "因消息长度限制未展示" in content
