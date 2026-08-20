import asyncio
import importlib
import json
import sys
import types

import pytest


def test_cli_runs_single_named_task(tmp_path, load_json_fixture, monkeypatch):
    fake_scraper = types.ModuleType("src.scraper")

    async def placeholder_scrape(task_config, debug_limit):
        return 0

    fake_scraper.scrape_xianyu = placeholder_scrape
    monkeypatch.setitem(sys.modules, "src.scraper", fake_scraper)
    sys.modules.pop("spider_v2", None)

    spider_v2 = importlib.import_module("spider_v2")
    config_data = load_json_fixture("config.sample.json")

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    called = []

    def mock_get_state_file():
        return str(state_path)

    monkeypatch.setattr(spider_v2, "get_state_file", mock_get_state_file)

    async def fake_scrape_xianyu(task_config, debug_limit):
        called.append(task_config)
        return 1

    monkeypatch.setattr(spider_v2, "scrape_xianyu", fake_scrape_xianyu)
    monkeypatch.setattr(sys, "argv", ["spider_v2.py", "--config", str(config_path), "--task-name", "Sony A7M4"])

    asyncio.run(spider_v2.main())

    assert [task["task_name"] for task in called] == ["Sony A7M4"]
    assert called[0]["keyword_rules"] == ["sony a7m4"]


def test_cli_defaults_keyword_rules_to_search_keyword(tmp_path, load_json_fixture, monkeypatch):
    fake_scraper = types.ModuleType("src.scraper")

    async def placeholder_scrape(task_config, debug_limit):
        return 0

    fake_scraper.scrape_xianyu = placeholder_scrape
    monkeypatch.setitem(sys.modules, "src.scraper", fake_scraper)
    sys.modules.pop("spider_v2", None)

    spider_v2 = importlib.import_module("spider_v2")
    config_data = load_json_fixture("config.sample.json")
    config_data[0]["enabled"] = True
    config_data[0]["keyword_rules"] = []

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    def mock_get_state_file():
        return str(state_path)

    monkeypatch.setattr(spider_v2, "get_state_file", mock_get_state_file)

    captured = []

    async def fake_scrape_xianyu(task_config, debug_limit):
        captured.append(task_config)
        return 1

    monkeypatch.setattr(spider_v2, "scrape_xianyu", fake_scrape_xianyu)
    monkeypatch.setattr(sys, "argv", ["spider_v2.py", "--config", str(config_path), "--task-name", "Sony A7M4"])

    asyncio.run(spider_v2.main())

    assert len(captured) == 1
    assert captured[0]["keyword_rules"] == ["sony a7m4"]


def test_cli_exits_with_failure_when_item_id_task_raises(tmp_path, monkeypatch):
    fake_scraper = types.ModuleType("src.scraper")

    async def placeholder_scrape(task_config, debug_limit):
        return 0

    async def failed_item_scrape(item_ids, task_config, debug_limit):
        raise RuntimeError("FAIL_SYS_USER_VALIDATE")

    fake_scraper.scrape_xianyu = placeholder_scrape
    fake_scraper.scrape_items_by_id_batch = failed_item_scrape
    monkeypatch.setitem(sys.modules, "src.scraper", fake_scraper)
    sys.modules.pop("spider_v2", None)

    spider_v2 = importlib.import_module("spider_v2")
    monkeypatch.setattr(spider_v2, "scrape_items_by_id_batch", failed_item_scrape)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "task_name": "指定商品监控",
                    "task_type": "item_id",
                    "enabled": True,
                    "item_id_list": ["1001"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(spider_v2, "get_state_file", lambda: str(state_path))
    monkeypatch.setattr(
        sys,
        "argv",
        ["spider_v2.py", "--config", str(config_path), "--task-name", "指定商品监控"],
    )

    with pytest.raises(RuntimeError, match="监控任务执行失败"):
        asyncio.run(spider_v2.main())


def test_cli_dispatches_store_monitoring_task(tmp_path, monkeypatch):
    fake_scraper = types.ModuleType("src.scraper")
    captured = []

    async def placeholder_scrape(task_config, debug_limit):
        return 0

    async def fake_store_scrape(store_id, task_config, debug_limit):
        captured.append((store_id, task_config, debug_limit))
        return {
            "processed_count": 2,
            "discovered_count": 2,
            "failed_count": 0,
            "changed_count": 1,
        }

    fake_scraper.scrape_xianyu = placeholder_scrape
    fake_scraper.scrape_store_by_id = fake_store_scrape
    monkeypatch.setitem(sys.modules, "src.scraper", fake_scraper)
    sys.modules.pop("spider_v2", None)
    spider_v2 = importlib.import_module("spider_v2")
    monkeypatch.setattr(spider_v2, "scrape_store_by_id", fake_store_scrape)

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "task_name": "示例店铺",
                    "task_type": "store",
                    "store_id": "https://www.goofish.com/personal?userId=90001",
                    "enabled": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(spider_v2, "get_state_file", lambda: str(state_path))
    monkeypatch.setattr(
        sys,
        "argv",
        ["spider_v2.py", "--config", str(config_path), "--task-name", "示例店铺"],
    )

    asyncio.run(spider_v2.main())

    assert len(captured) == 1
    assert captured[0][0] == "90001"
    assert captured[0][1]["store_id"] == "90001"
