import asyncio

import pytest

from src import scraper


def test_item_id_batch_propagates_risk_control_and_records_failure(monkeypatch):
    recorded_failures = []

    async def fail_to_load_item(_item_id: str):
        raise scraper.RiskControlError("FAIL_SYS_USER_VALIDATE")

    async def record_failure(task_config: dict, reason: str, *, cookie_path: str):
        recorded_failures.append((task_config["task_name"], reason, cookie_path))

    monkeypatch.setattr(scraper, "scrape_item_by_id", fail_to_load_item)
    monkeypatch.setattr(scraper, "_notify_task_failure", record_failure)
    monkeypatch.setattr(scraper, "get_state_file", lambda: "state/acc_1.json")

    with pytest.raises(scraper.RiskControlError, match="FAIL_SYS_USER_VALIDATE"):
        asyncio.run(
            scraper.scrape_items_by_id_batch(
                item_ids=["1001", "1002"],
                task_config={
                    "task_name": "指定商品监控",
                    "keyword": "指定商品监控",
                    "keyword_rules": ["1001", "1002"],
                },
            )
        )

    assert recorded_failures == [
        ("指定商品监控", "FAIL_SYS_USER_VALIDATE", "state/acc_1.json")
    ]


def test_item_id_batch_fails_when_no_items_are_collected(monkeypatch):
    recorded_failures = []

    async def missing_item(_item_id: str):
        return None

    async def record_failure(task_config: dict, reason: str, *, cookie_path: str):
        recorded_failures.append((task_config["task_name"], reason, cookie_path))

    async def skip_delay(_minimum: float, _maximum: float):
        return None

    monkeypatch.setattr(scraper, "scrape_item_by_id", missing_item)
    monkeypatch.setattr(scraper, "_notify_task_failure", record_failure)
    monkeypatch.setattr(scraper, "get_state_file", lambda: "state/acc_1.json")
    monkeypatch.setattr(scraper, "random_sleep", skip_delay)

    with pytest.raises(RuntimeError, match="0/2"):
        asyncio.run(
            scraper.scrape_items_by_id_batch(
                item_ids=["1001", "1002"],
                task_config={
                    "task_name": "指定商品监控",
                    "keyword": "指定商品监控",
                    "keyword_rules": ["1001", "1002"],
                },
            )
        )

    assert recorded_failures[0][0] == "指定商品监控"
    assert "1001, 1002" in recorded_failures[0][1]
