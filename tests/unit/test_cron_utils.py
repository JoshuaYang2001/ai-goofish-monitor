from src.core.cron_utils import build_cron_trigger, validate_cron_expression


def test_validate_cron_expression_normalizes_alias():
    assert validate_cron_expression("@daily") == "0 0 * * *"


def test_validate_cron_expression_accepts_six_fields():
    assert validate_cron_expression("0 0 8 * * *") == "0 0 8 * * *"


def test_validate_cron_expression_rejects_intervals_shorter_than_15_minutes():
    for expression in ("*/5 * * * *", "*/10 * * * *", "*/30 * * * * *"):
        try:
            validate_cron_expression(expression)
        except ValueError as exc:
            assert "15 分钟" in str(exc)
        else:
            raise AssertionError(f"应该拒绝过高频率：{expression}")


def test_validate_cron_expression_accepts_15_minute_boundary():
    assert validate_cron_expression("*/15 * * * *") == "*/15 * * * *"


def test_build_cron_trigger_accepts_alias_and_timezone():
    trigger = build_cron_trigger("@hourly", timezone="Asia/Shanghai")

    assert trigger is not None
    assert str(trigger.timezone) == "Asia/Shanghai"


def test_validate_cron_expression_rejects_invalid_value():
    try:
        validate_cron_expression("not-a-cron")
    except ValueError as exc:
        assert "支持 5 段" in str(exc)
        return

    raise AssertionError("非法 cron 应该抛出 ValueError")
