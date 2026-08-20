"""
SQLite 启动初始化与旧文件迁移。
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from src.infrastructure.persistence.sqlite_connection import init_schema, sqlite_connection
from src.infrastructure.persistence.storage_names import (
    build_result_filename,
    normalize_keyword_from_filename,
    normalize_keyword_slug,
)
from src.tenancy.context import DEFAULT_TENANT_ID, current_tenant_id, has_tenant_context
from src.tenancy.paths import tenant_path


BOOTSTRAP_LOCK = threading.Lock()
LEGACY_CONFIG_FILE = "config.json"
LEGACY_RESULT_DIR = "jsonl"
LEGACY_PRICE_HISTORY_DIR = "price_history"
TASKS_BOOTSTRAP_KEY = "bootstrap:legacy_tasks"
RESULTS_BOOTSTRAP_KEY = "bootstrap:legacy_results"
SNAPSHOTS_BOOTSTRAP_KEY = "bootstrap:legacy_price_snapshots"


def bootstrap_sqlite_storage(
    db_path: str | None = None,
    *,
    legacy_config_file: str | None = LEGACY_CONFIG_FILE,
    legacy_result_dir: str = LEGACY_RESULT_DIR,
    legacy_price_history_dir: str = LEGACY_PRICE_HISTORY_DIR,
) -> None:
    tenant_id = current_tenant_id(required=False)
    if has_tenant_context() and legacy_config_file == LEGACY_CONFIG_FILE:
        legacy_config_file = (
            tenant_path(LEGACY_CONFIG_FILE, tenant_id)
            if tenant_id == DEFAULT_TENANT_ID
            else None
        )
    if has_tenant_context() and legacy_result_dir == LEGACY_RESULT_DIR:
        legacy_result_dir = tenant_path(LEGACY_RESULT_DIR, tenant_id)
    if has_tenant_context() and legacy_price_history_dir == LEGACY_PRICE_HISTORY_DIR:
        legacy_price_history_dir = tenant_path(LEGACY_PRICE_HISTORY_DIR, tenant_id)
    with BOOTSTRAP_LOCK:
        with sqlite_connection(db_path) as conn:
            init_schema(conn)
            _migrate_tasks_schema(conn)
            _migrate_metrics_schema(conn)
            _import_tasks_if_needed(conn, legacy_config_file)
            _import_results_if_needed(conn, legacy_result_dir)
            _import_price_snapshots_if_needed(conn, legacy_price_history_dir)
            _backfill_metric_task_names(conn)
            _purge_retired_analysis_data(conn)


def _migrate_tasks_schema(conn) -> None:
    """移除旧分析字段，同时完整保留监控任务的业务配置。"""
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(tasks)")}
    expected_columns = {
        "id",
        "task_name",
        "task_type",
        "enabled",
        "keyword",
        "item_id_list_json",
        "store_id",
        "store_name",
        "max_pages",
        "personal_only",
        "min_price",
        "max_price",
        "cron",
        "account_state_file",
        "account_strategy",
        "free_shipping",
        "new_publish_option",
        "region",
        "keyword_rules_json",
        "is_running",
        "is_paused",
    }
    if columns == expected_columns:
        return

    def select_value(name: str, fallback: str) -> str:
        return name if name in columns else f"{fallback} AS {name}"

    conn.execute("ALTER TABLE tasks RENAME TO tasks_before_rule_migration")
    conn.execute(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            task_name TEXT NOT NULL,
            task_type TEXT NOT NULL DEFAULT 'keyword',
            enabled INTEGER NOT NULL,
            keyword TEXT,
            item_id_list_json TEXT NOT NULL DEFAULT '[]',
            store_id TEXT,
            store_name TEXT,
            max_pages INTEGER NOT NULL,
            personal_only INTEGER NOT NULL,
            min_price TEXT,
            max_price TEXT,
            cron TEXT,
            account_state_file TEXT,
            account_strategy TEXT NOT NULL,
            free_shipping INTEGER NOT NULL,
            new_publish_option TEXT,
            region TEXT,
            keyword_rules_json TEXT NOT NULL,
            is_running INTEGER NOT NULL,
            is_paused INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    select_columns = [
        select_value("id", "NULL"),
        select_value("task_name", "''"),
        select_value("task_type", "'keyword'"),
        select_value("enabled", "1"),
        select_value("keyword", "''"),
        select_value("item_id_list_json", "'[]'"),
        select_value("store_id", "NULL"),
        select_value("store_name", "NULL"),
        select_value("max_pages", "3"),
        select_value("personal_only", "1"),
        select_value("min_price", "NULL"),
        select_value("max_price", "NULL"),
        select_value("cron", "NULL"),
        select_value("account_state_file", "NULL"),
        select_value("account_strategy", "'auto'"),
        select_value("free_shipping", "1"),
        select_value("new_publish_option", "NULL"),
        select_value("region", "NULL"),
        select_value("keyword_rules_json", "'[]'"),
        select_value("is_running", "0"),
        select_value("is_paused", "0"),
    ]
    conn.execute(
        """
        INSERT INTO tasks (
            id, task_name, task_type, enabled, keyword, item_id_list_json, store_id, store_name,
            max_pages, personal_only, min_price, max_price, cron,
            account_state_file, account_strategy, free_shipping,
            new_publish_option, region, keyword_rules_json, is_running, is_paused
        )
        SELECT
        """
        + ", ".join(select_columns)
        + " FROM tasks_before_rule_migration"
    )
    conn.execute("DROP TABLE tasks_before_rule_migration")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_name ON tasks(task_name)")
    conn.commit()


def _migrate_metrics_schema(conn) -> None:
    """为指标历史补充任务归属，旧库可原地升级。"""
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(item_metrics_history)")
    }
    if "task_name" not in columns:
        conn.execute(
            "ALTER TABLE item_metrics_history "
            "ADD COLUMN task_name TEXT NOT NULL DEFAULT ''"
        )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_metrics_task_item_time
        ON item_metrics_history(task_name, item_id, snapshot_time DESC)
        """
    )
    conn.commit()


def _backfill_metric_task_names(conn) -> None:
    """尽可能用已有价格快照补齐旧指标记录的任务名称。"""
    conn.execute(
        """
        UPDATE item_metrics_history
        SET task_name = COALESCE(
            (
                SELECT snapshots.task_name
                FROM price_snapshots AS snapshots
                WHERE snapshots.item_id = item_metrics_history.item_id
                  AND TRIM(snapshots.task_name) <> ''
                ORDER BY snapshots.snapshot_time DESC, snapshots.id DESC
                LIMIT 1
            ),
            ''
        )
        WHERE TRIM(task_name) = ''
        """
    )
    conn.commit()


def _purge_retired_analysis_data(conn) -> None:
    """清理旧版本保存的模型开关和分析结果，避免继续通过 API 暴露。"""
    conn.execute("DELETE FROM app_settings WHERE key = ?", ("ai_enabled",))
    rows = conn.execute("SELECT id, raw_json FROM result_items").fetchall()
    for row in rows:
        try:
            record = json.loads(row["raw_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if "ai_analysis" not in record:
            continue
        record.pop("ai_analysis", None)
        match_result = record.get("match_result") or {
            "is_recommended": False,
            "reason": "历史记录未经过当前规则匹配",
            "analysis_source": "keyword",
            "keyword_hit_count": 0,
        }
        record["match_result"] = match_result
        conn.execute(
            """
            UPDATE result_items
            SET raw_json = ?, is_recommended = ?, analysis_source = ?, keyword_hit_count = ?
            WHERE id = ?
            """,
            (
                json.dumps(record, ensure_ascii=False),
                _as_int(match_result.get("is_recommended", False)),
                match_result.get("analysis_source") or "keyword",
                int(match_result.get("keyword_hit_count") or 0),
                row["id"],
            ),
        )
    conn.commit()


def _table_is_empty(conn, table_name: str) -> bool:
    row = conn.execute(f"SELECT COUNT(1) AS total FROM {table_name}").fetchone()
    return row is None or int(row["total"]) == 0


def _load_json_file(path: Path):
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    return json.loads(content)


def _import_tasks_if_needed(conn, legacy_config_file: str | None) -> None:
    if _bootstrap_completed(conn, TASKS_BOOTSTRAP_KEY):
        return
    if not _table_is_empty(conn, "tasks"):
        _mark_bootstrap_completed(conn, TASKS_BOOTSTRAP_KEY)
        conn.commit()
        return
    if legacy_config_file is None:
        _mark_bootstrap_completed(conn, TASKS_BOOTSTRAP_KEY)
        conn.commit()
        return
    path = Path(legacy_config_file)
    tasks = _load_json_file(path)
    if not isinstance(tasks, list):
        _mark_bootstrap_completed(conn, TASKS_BOOTSTRAP_KEY)
        conn.commit()
        return

    for index, raw_task in enumerate(tasks):
        if not isinstance(raw_task, dict):
            continue
        task_type = raw_task.get("task_type", "keyword")
        item_id_list = raw_task.get("item_id_list") or []
        keyword = str(raw_task.get("keyword") or "").strip()
        keyword_rules = raw_task.get("keyword_rules") or item_id_list or ([keyword] if keyword else [])
        conn.execute(
            """
            INSERT INTO tasks (
                id, task_name, task_type, enabled, keyword, item_id_list_json, store_id, store_name,
                max_pages, personal_only, min_price, max_price, cron, account_state_file,
                account_strategy, free_shipping, new_publish_option, region,
                keyword_rules_json, is_running
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                index,
                raw_task.get("task_name", ""),
                task_type,
                _as_int(raw_task.get("enabled", True)),
                keyword,
                json.dumps(item_id_list, ensure_ascii=False),
                raw_task.get("store_id"),
                raw_task.get("store_name"),
                int(raw_task.get("max_pages", 1) or 1),
                _as_int(raw_task.get("personal_only", False)),
                raw_task.get("min_price"),
                raw_task.get("max_price"),
                raw_task.get("cron"),
                raw_task.get("account_state_file"),
                raw_task.get("account_strategy", "auto"),
                _as_int(raw_task.get("free_shipping", True)),
                raw_task.get("new_publish_option"),
                raw_task.get("region"),
                json.dumps(keyword_rules, ensure_ascii=False),
                _as_int(raw_task.get("is_running", False)),
            ),
        )
    _mark_bootstrap_completed(conn, TASKS_BOOTSTRAP_KEY)
    conn.commit()


def _import_results_if_needed(conn, legacy_result_dir: str) -> None:
    if _bootstrap_completed(conn, RESULTS_BOOTSTRAP_KEY):
        return
    if not _table_is_empty(conn, "result_items"):
        _mark_bootstrap_completed(conn, RESULTS_BOOTSTRAP_KEY)
        conn.commit()
        return
    result_dir = Path(legacy_result_dir)
    if not result_dir.exists():
        _mark_bootstrap_completed(conn, RESULTS_BOOTSTRAP_KEY)
        conn.commit()
        return

    for path in sorted(result_dir.glob("*.jsonl")):
        filename = path.name
        keyword = normalize_keyword_from_filename(filename)
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    continue
                _insert_result_record(conn, record, keyword=keyword, filename=filename)
    _mark_bootstrap_completed(conn, RESULTS_BOOTSTRAP_KEY)
    conn.commit()


def _import_price_snapshots_if_needed(conn, legacy_price_history_dir: str) -> None:
    if _bootstrap_completed(conn, SNAPSHOTS_BOOTSTRAP_KEY):
        return
    if not _table_is_empty(conn, "price_snapshots"):
        _mark_bootstrap_completed(conn, SNAPSHOTS_BOOTSTRAP_KEY)
        conn.commit()
        return
    history_dir = Path(legacy_price_history_dir)
    if not history_dir.exists():
        _mark_bootstrap_completed(conn, SNAPSHOTS_BOOTSTRAP_KEY)
        conn.commit()
        return

    for path in sorted(history_dir.glob("*_history.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    continue
                _insert_price_snapshot(conn, record)
    _mark_bootstrap_completed(conn, SNAPSHOTS_BOOTSTRAP_KEY)
    conn.commit()


def _insert_result_record(conn, record: dict, *, keyword: str, filename: str) -> None:
    item = record.get("商品信息", {}) or {}
    analysis = record.get("match_result", {}) or {}
    link = str(item.get("商品链接") or "")
    if link:
        link_unique_key = link.split("&", 1)[0]
    else:
        item_id = str(item.get("商品ID") or "").strip()
        if item_id:
            link_unique_key = f"item:{item_id}"
        else:
            link_unique_key = "hash:" + hashlib.sha1(
                json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
    final_keyword = str(record.get("搜索关键字") or keyword)
    result_filename = filename or build_result_filename(final_keyword)
    keyword_hit_count = analysis.get("keyword_hit_count", 0)
    try:
        keyword_hit_count = int(keyword_hit_count)
    except (TypeError, ValueError):
        keyword_hit_count = 0

    conn.execute(
        """
        INSERT OR IGNORE INTO result_items (
            result_filename, keyword, task_name, crawl_time, publish_time, price,
            price_display, item_id, title, link, link_unique_key, seller_nickname,
            is_recommended, analysis_source, keyword_hit_count, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result_filename,
            final_keyword,
            record.get("任务名称", ""),
            record.get("爬取时间", ""),
            item.get("发布时间"),
            _parse_price(item.get("当前售价")),
            item.get("当前售价"),
            item.get("商品ID"),
            item.get("商品标题"),
            link,
            link_unique_key,
            (record.get("卖家信息", {}) or {}).get("卖家昵称") or item.get("卖家昵称"),
            _as_int(analysis.get("is_recommended", False)),
            analysis.get("analysis_source"),
            keyword_hit_count,
            json.dumps(record, ensure_ascii=False),
        ),
    )


def _insert_price_snapshot(conn, record: dict) -> None:
    keyword = str(record.get("keyword") or "")
    slug = str(record.get("keyword_slug") or normalize_keyword_slug(keyword))
    conn.execute(
        """
        INSERT OR IGNORE INTO price_snapshots (
            keyword_slug, keyword, task_name, snapshot_time, snapshot_day, run_id,
            item_id, title, price, price_display, tags_json, region, seller,
            publish_time, link
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            slug,
            keyword,
            record.get("task_name", ""),
            record.get("snapshot_time", ""),
            record.get("snapshot_day", ""),
            record.get("run_id", ""),
            record.get("item_id", ""),
            record.get("title", ""),
            _parse_price(record.get("price")),
            record.get("price_display"),
            json.dumps(record.get("tags") or [], ensure_ascii=False),
            record.get("region"),
            record.get("seller"),
            record.get("publish_time"),
            record.get("link"),
        ),
    )


def _as_int(value) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if value is None:
        return 0
    return 1 if str(value).strip().lower() in {"1", "true", "yes", "on"} else 0


def _parse_price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)

    text = str(value).strip().replace("¥", "").replace(",", "")
    if not text or text in {"价格异常", "暂无", "-", "N/A"}:
        return None
    if text.endswith("万"):
        text = str(float(text[:-1]) * 10000)
    try:
        return round(float(text), 2)
    except (TypeError, ValueError):
        return None


def _bootstrap_completed(conn, key: str) -> bool:
    row = conn.execute(
        "SELECT value FROM app_metadata WHERE key = ?",
        (key,),
    ).fetchone()
    return row is not None


def _mark_bootstrap_completed(conn, key: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO app_metadata(key, value)
        VALUES (?, 'done')
        """,
        (key,),
    )
