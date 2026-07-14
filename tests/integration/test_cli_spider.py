import asyncio
import importlib
import json
import sys
import types


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
