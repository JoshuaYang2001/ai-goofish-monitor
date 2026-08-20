"""SQLite outbox for reliable store-digest delivery."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Iterable

from src.domain.models.store_monitoring import (
    StoreItemChange,
    StoreItemLifecycle,
    StoreMonitoringDigest,
)
from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection


@dataclass(frozen=True, slots=True)
class PendingStoreDigest:
    id: int
    event_key: str
    digest: StoreMonitoringDigest
    pending_channels: tuple[str, ...]
    attempts: int


def _serialize_digest(digest: StoreMonitoringDigest) -> str:
    payload = asdict(digest)
    payload["monitored_at"] = digest.monitored_at.isoformat()
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_digest(payload_json: str) -> StoreMonitoringDigest:
    payload = json.loads(payload_json)
    payload["monitored_at"] = datetime.fromisoformat(payload["monitored_at"])
    payload["changes"] = tuple(
        StoreItemChange(**item) for item in payload.get("changes") or []
    )
    payload["added_items"] = tuple(
        StoreItemLifecycle(**item) for item in payload.get("added_items") or []
    )
    payload["removed_items"] = tuple(
        StoreItemLifecycle(**item) for item in payload.get("removed_items") or []
    )
    return StoreMonitoringDigest(**payload)


def enqueue_store_digest(
    *,
    event_key: str,
    digest: StoreMonitoringDigest,
    channel_keys: Iterable[str],
) -> bool:
    channels = tuple(dict.fromkeys(str(key) for key in channel_keys if str(key)))
    if not channels:
        return False
    bootstrap_sqlite_storage()
    timestamp = datetime.now().isoformat()
    with sqlite_connection() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO store_notification_outbox (
                event_key, task_name, payload_json, pending_channels_json,
                attempts, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (
                event_key,
                digest.task_name,
                _serialize_digest(digest),
                json.dumps(channels, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
    return bool(cursor.rowcount)


def persist_store_run(
    *,
    metric_observations: Iterable[dict[str, Any]],
    event_key: str,
    digest: StoreMonitoringDigest | None,
    channel_keys: Iterable[str],
    store_membership: dict[str, Any] | None = None,
) -> None:
    """Atomically persist membership, metric baselines and their notification.

    Keeping these writes in one transaction prevents a process restart from
    swallowing either a metric change or an added/removed-item event before its
    digest is durably queued.
    """
    observations = list(metric_observations)
    channels = tuple(dict.fromkeys(str(key) for key in channel_keys if str(key)))
    membership = dict(store_membership) if store_membership is not None else None
    membership_items = list(membership.get("items") or []) if membership else []
    if membership is not None:
        membership_task_name = str(membership.get("task_name") or "").strip()
        membership_store_id = str(membership.get("store_id") or "").strip()
        if not membership_task_name or not membership_store_id:
            raise ValueError("店铺成员快照缺少 task_name 或 store_id")
    else:
        membership_task_name = ""
        membership_store_id = ""
    bootstrap_sqlite_storage()
    timestamp = datetime.now().isoformat()
    with sqlite_connection() as connection:
        if membership is not None:
            observed_at = str(membership.get("observed_at") or timestamp)
            connection.execute(
                "UPDATE store_monitor_items SET is_active = 0 WHERE task_name = ?",
                (membership_task_name,),
            )
            for item in membership_items:
                item_id = str(item.get("item_id") or "").strip()
                if not item_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO store_monitor_items (
                        task_name, store_id, item_id, title, is_active,
                        first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(task_name, item_id) DO UPDATE SET
                        store_id = excluded.store_id,
                        title = excluded.title,
                        is_active = 1,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        membership_task_name,
                        membership_store_id,
                        item_id,
                        str(item.get("title") or ""),
                        observed_at,
                        observed_at,
                    ),
                )
        for observation in observations:
            connection.execute(
                """
                INSERT INTO item_metrics_history (
                    task_name, item_id, title, snapshot_time, price, price_display,
                    want_count, browse_count, seller_id, link
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation["task_name"],
                    observation["item_id"],
                    str(observation.get("title") or "")[:200],
                    observation["snapshot_time"],
                    observation.get("price"),
                    observation.get("price_display"),
                    observation.get("want_count"),
                    observation.get("browse_count"),
                    observation.get("seller_id"),
                    observation.get("link"),
                ),
            )
        if digest is not None and channels:
            connection.execute(
                """
                INSERT OR IGNORE INTO store_notification_outbox (
                    event_key, task_name, payload_json, pending_channels_json,
                    attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    event_key,
                    digest.task_name,
                    _serialize_digest(digest),
                    json.dumps(channels, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        connection.commit()


def list_pending_store_digests(
    *,
    task_name: str,
    limit: int = 20,
) -> list[PendingStoreDigest]:
    bootstrap_sqlite_storage()
    with sqlite_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, event_key, task_name, payload_json,
                   pending_channels_json, attempts
            FROM store_notification_outbox
            WHERE task_name = ?
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (task_name, max(1, int(limit))),
        ).fetchall()
    pending_digests = []
    for row in rows:
        digest = _deserialize_digest(str(row["payload_json"]))
        # Task renames update the indexed outbox column atomically with other task
        # data. Treat that column as authoritative so a queued notification never
        # resurfaces the stale name embedded in its original JSON payload.
        digest = replace(digest, task_name=str(row["task_name"]))
        pending_digests.append(
            PendingStoreDigest(
                id=int(row["id"]),
                event_key=str(row["event_key"]),
                digest=digest,
                pending_channels=tuple(
                    json.loads(row["pending_channels_json"] or "[]")
                ),
                attempts=int(row["attempts"] or 0),
            )
        )
    return pending_digests


def update_store_digest_delivery(
    *,
    record_id: int,
    failed_channels: Iterable[str],
    last_error: str | None,
) -> None:
    channels = tuple(
        dict.fromkeys(str(key) for key in failed_channels if str(key))
    )
    bootstrap_sqlite_storage()
    with sqlite_connection() as connection:
        if not channels:
            connection.execute(
                "DELETE FROM store_notification_outbox WHERE id = ?",
                (record_id,),
            )
        else:
            connection.execute(
                """
                UPDATE store_notification_outbox
                SET pending_channels_json = ?, attempts = attempts + 1,
                    last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(channels, ensure_ascii=False),
                    last_error,
                    datetime.now().isoformat(),
                    record_id,
                ),
            )
        connection.commit()
