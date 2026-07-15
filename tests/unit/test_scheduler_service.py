import asyncio

from src.services.scheduler_service import SchedulerService


class _BlockingProcessService:
    def __init__(self):
        self.started: list[tuple[int, str]] = []
        self._finished: dict[int, asyncio.Event] = {}

    async def start_task(self, task_id: int, task_name: str) -> bool:
        self.started.append((task_id, task_name))
        self._finished[task_id] = asyncio.Event()
        return True

    async def wait_for_task(self, task_id: int) -> None:
        await self._finished[task_id].wait()

    def finish(self, task_id: int) -> None:
        self._finished[task_id].set()


def test_scheduled_tasks_wait_for_available_concurrency_slot():
    async def run_scenario():
        process_service = _BlockingProcessService()
        scheduler_service = SchedulerService(
            process_service,  # type: ignore[arg-type]
            max_concurrent_tasks=1,
        )

        first_run = asyncio.create_task(
            scheduler_service._run_task("default", 0, "task-a")
        )
        while process_service.started != [(0, "task-a")]:
            await asyncio.sleep(0)

        second_run = asyncio.create_task(
            scheduler_service._run_task("default", 1, "task-b")
        )
        await asyncio.sleep(0)

        assert process_service.started == [(0, "task-a")]

        process_service.finish(0)
        while process_service.started != [(0, "task-a"), (1, "task-b")]:
            await asyncio.sleep(0)

        process_service.finish(1)
        await asyncio.gather(first_run, second_run)

    asyncio.run(run_scenario())


def test_scheduled_task_reports_queued_status_while_waiting():
    async def run_scenario():
        process_service = _BlockingProcessService()
        scheduler_service = SchedulerService(
            process_service,  # type: ignore[arg-type]
            max_concurrent_tasks=1,
        )
        queue_events: list[tuple[int, bool]] = []
        scheduler_service.set_queue_status_hook(
            on_queue_changed=lambda task_id, is_queued: queue_events.append(
                (task_id, is_queued)
            )
        )

        first_run = asyncio.create_task(
            scheduler_service._run_task("default", 0, "task-a")
        )
        while process_service.started != [(0, "task-a")]:
            await asyncio.sleep(0)

        second_run = asyncio.create_task(
            scheduler_service._run_task("default", 1, "task-b")
        )
        while not scheduler_service.is_task_queued(1, "default"):
            await asyncio.sleep(0)

        assert queue_events == [(1, True)]

        process_service.finish(0)
        while process_service.started != [(0, "task-a"), (1, "task-b")]:
            await asyncio.sleep(0)

        assert not scheduler_service.is_task_queued(1, "default")
        assert queue_events == [(1, True), (1, False)]

        process_service.finish(1)
        await asyncio.gather(first_run, second_run)

    asyncio.run(run_scenario())


def test_cancelled_queued_task_does_not_start_after_slot_is_available():
    async def run_scenario():
        process_service = _BlockingProcessService()
        scheduler_service = SchedulerService(
            process_service,  # type: ignore[arg-type]
            max_concurrent_tasks=1,
        )
        queue_events: list[tuple[int, bool]] = []
        scheduler_service.set_queue_status_hook(
            on_queue_changed=lambda task_id, is_queued: queue_events.append(
                (task_id, is_queued)
            )
        )

        first_run = asyncio.create_task(
            scheduler_service._run_task("default", 0, "task-a")
        )
        while process_service.started != [(0, "task-a")]:
            await asyncio.sleep(0)

        second_run = asyncio.create_task(
            scheduler_service._run_task("default", 1, "task-b")
        )
        while not scheduler_service.is_task_queued(1, "default"):
            await asyncio.sleep(0)

        await scheduler_service.cancel_queued_task(1, "default")
        assert not scheduler_service.is_task_queued(1, "default")
        assert queue_events == [(1, True), (1, False)]

        process_service.finish(0)
        await asyncio.gather(first_run, second_run)

        assert process_service.started == [(0, "task-a")]

    asyncio.run(run_scenario())


def test_scheduler_rejects_invalid_concurrency_limit():
    process_service = _BlockingProcessService()

    try:
        SchedulerService(
            process_service,  # type: ignore[arg-type]
            max_concurrent_tasks=0,
        )
    except ValueError as exc:
        assert "大于等于 1" in str(exc)
    else:
        raise AssertionError("无效的并发限制应该被拒绝")
