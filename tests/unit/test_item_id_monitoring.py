import asyncio
import sqlite3
from types import SimpleNamespace

from src.config import DETAIL_API_URL_PATTERN
from src.scraper import _navigate_and_wait_for_detail_response
from src.services.result_storage_service import save_result_record


class _FakeDetailExpectation:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.value = self._build_response()

    async def _build_response(self):
        return SimpleNamespace(ok=True)

    async def __aenter__(self):
        self.events.append("listener_registered")
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _FakeDetailPage:
    def __init__(self) -> None:
        self.events: list[str] = []

    def expect_response(self, predicate, *, timeout: int):
        assert predicate(SimpleNamespace(url=f"https://{DETAIL_API_URL_PATTERN}/1.0/"))
        assert timeout == 50000
        return _FakeDetailExpectation(self.events)

    async def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        assert self.events == ["listener_registered"]
        assert url == "https://www.goofish.com/item?id=1006399488224"
        assert wait_until == "domcontentloaded"
        assert timeout == 60000
        self.events.append("navigation_started")


def test_item_detail_listener_is_registered_before_navigation():
    page = _FakeDetailPage()

    response = asyncio.run(
        _navigate_and_wait_for_detail_response(
            page, "https://www.goofish.com/item?id=1006399488224"
        )
    )

    assert response.ok is True
    assert page.events == ["listener_registered", "navigation_started"]


def test_item_id_result_is_persisted_with_spaced_field_name(tmp_path, monkeypatch):
    database_path = tmp_path / "app.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_DATABASE_FILE", str(database_path))
    monkeypatch.delenv("TENANT_ID", raising=False)

    record = {
        "搜索关键字": "迅雷",
        "任务名称": "迅雷",
        "爬取时间": "2026-07-14T20:45:00",
        "商品信息": {
            "商品 ID": "1006399488224",
            "商品标题": "测试商品",
            "商品链接": "https://www.goofish.com/item?id=1006399488224",
            "当前售价": "99.00",
        },
        "match_result": {
            "analysis_source": "direct",
            "is_recommended": True,
            "keyword_hit_count": 1,
        },
    }

    assert asyncio.run(save_result_record(record, "迅雷")) is True

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT item_id FROM result_items WHERE task_name = ?", ("迅雷",)
        ).fetchone()

    assert row == ("1006399488224",)
