import pytest

from src.domain.models.task import Task, TaskCreate, TaskUpdate


def build_task(**updates) -> Task:
    payload = {
        "id": 1,
        "task_name": "Sony A7M4",
        "enabled": True,
        "keyword": "sony a7m4",
        "keyword_rules": ["sony a7m4"],
        "max_pages": 2,
        "personal_only": True,
        "is_running": False,
    }
    payload.update(updates)
    return Task(**payload)


def test_task_can_start_and_stop():
    task = build_task()

    assert task.can_start() is True
    assert task.can_stop() is False

    running = task.model_copy(update={"is_running": True})
    assert running.can_start() is False
    assert running.can_stop() is True


def test_task_apply_update():
    task = build_task()
    updated = task.apply_update(TaskUpdate(enabled=False, max_pages=5))

    assert updated.enabled is False
    assert updated.max_pages == 5
    assert updated.task_name == task.task_name


def test_legacy_keyword_groups_are_flattened_to_keyword_rules():
    task = Task(
        id=1,
        task_name="Sony A7M4",
        enabled=True,
        keyword="sony a7m4",
        keyword_rule_groups=[
            {"name": "组1", "include_keywords": ["a7m4", "验货宝"]},
            {"name": "组2", "include_keywords": ["全画幅", "a7m4"]},
        ],
    )

    assert task.keyword_rules == ["a7m4", "验货宝", "全画幅"]


def test_create_defaults_keyword_rules_to_search_keyword():
    request = TaskCreate(task_name="Sony A7M4", keyword="sony a7m4")

    assert request.keyword_rules == ["sony a7m4"]


def test_create_infers_fixed_account_strategy_from_state_file():
    request = TaskCreate(
        task_name="Sony A7M4",
        keyword="sony a7m4",
        account_state_file="state/acc_1.json",
    )

    assert request.account_strategy == "fixed"


def test_create_requires_state_file_for_fixed_account_strategy():
    with pytest.raises(ValueError, match="固定账号模式下必须选择账号"):
        TaskCreate(
            task_name="Sony A7M4",
            keyword="sony a7m4",
            account_strategy="fixed",
        )


def test_item_id_create_deduplicates_ids_and_uses_direct_rules():
    request = TaskCreate(
        task_name="指定商品",
        task_type="item_id",
        item_id_list=["123456", "987654", "123456"],
    )

    assert request.item_id_list == ["123456", "987654"]
    assert request.keyword_rules == ["123456", "987654"]


@pytest.mark.parametrize(
    ("raw_store_id", "expected_store_id"),
    [
        (" 2206814873475 ", "2206814873475"),
        (
            "https://www.goofish.com/personal?userId=2206814873475&tab=items",
            "2206814873475",
        ),
        (
            "https://example.test/redirect?url=https%3A%2F%2Fwww.goofish.com%2Fpersonal%3FuserId%3D2206814873475",
            "2206814873475",
        ),
    ],
)
def test_store_create_normalizes_numeric_id_or_profile_url(
    raw_store_id,
    expected_store_id,
):
    request = TaskCreate(
        task_name="相机店铺监控",
        task_type="store",
        store_id=raw_store_id,
        store_name="  相机铺子  ",
    )

    assert request.store_id == expected_store_id
    assert request.store_name == "相机铺子"
    assert request.keyword_rules == []


def test_store_create_requires_valid_store_id():
    with pytest.raises(ValueError, match="必须提供店铺 ID"):
        TaskCreate(task_name="无店铺 ID", task_type="store")

    with pytest.raises(ValueError, match="店铺 ID 必须是数字"):
        TaskCreate(
            task_name="错误店铺 URL",
            task_type="store",
            store_id="https://www.goofish.com/personal",
        )
