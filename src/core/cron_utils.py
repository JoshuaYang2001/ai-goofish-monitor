"""
Cron 解析与校验工具。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from apscheduler.triggers.cron import CronTrigger

CRON_ALIASES = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

CRON_FORMAT_HINT = (
    "Cron 表达式无效。支持 5 段（分 时 日 月 周）、"
    "6 段（秒 分 时 日 月 周）和常见别名（@hourly/@daily/@weekly/@monthly/@yearly）。"
    "示例：*/15 * * * *、0 8 * * *、0 0 8 * * *、@daily。"
)
MINIMUM_CRON_INTERVAL = timedelta(minutes=15)
CRON_INTERVAL_HINT = "监控任务的执行间隔不能小于 15 分钟。"
CRON_INTERVAL_SAMPLE_COUNT = 64


def normalize_cron_expression(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    normalized = " ".join(str(value).strip().split())
    if not normalized:
        return None

    return CRON_ALIASES.get(normalized.lower(), normalized)


def build_cron_trigger(
    expression: str,
    *,
    timezone=None,
) -> CronTrigger:
    normalized = normalize_cron_expression(expression)
    if normalized is None:
        raise ValueError(CRON_FORMAT_HINT)

    parts = normalized.split()
    trigger: CronTrigger
    try:
        if len(parts) == 5:
            trigger = CronTrigger.from_crontab(normalized, timezone=timezone)
        elif len(parts) == 6:
            second, minute, hour, day, month, day_of_week = parts
            trigger = CronTrigger(
                second=second,
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=timezone,
            )
        else:
            raise ValueError(CRON_FORMAT_HINT)
    except ValueError as exc:
        if str(exc) == CRON_FORMAT_HINT:
            raise
        raise ValueError(CRON_FORMAT_HINT) from exc

    _validate_minimum_interval(trigger)
    return trigger


def _validate_minimum_interval(trigger: CronTrigger) -> None:
    reference_time = datetime(2026, 1, 1, tzinfo=trigger.timezone)
    previous_fire_time = None
    current_time = reference_time

    for _ in range(CRON_INTERVAL_SAMPLE_COUNT):
        next_fire_time = trigger.get_next_fire_time(previous_fire_time, current_time)
        if next_fire_time is None:
            return
        if (
            previous_fire_time is not None
            and next_fire_time - previous_fire_time < MINIMUM_CRON_INTERVAL
        ):
            raise ValueError(CRON_INTERVAL_HINT)
        previous_fire_time = next_fire_time
        current_time = next_fire_time


def validate_cron_expression(value: Optional[str]) -> Optional[str]:
    normalized = normalize_cron_expression(value)
    if normalized is None:
        return None

    build_cron_trigger(normalized)
    return normalized
