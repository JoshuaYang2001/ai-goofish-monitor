"""
进程管理服务
负责管理爬虫进程的启动和停止
"""

import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path
from datetime import datetime
from typing import Awaitable, Callable, Dict, TextIO

from src.api.routes import websocket
from src.config import get_state_file
from src.failure_guard import FailureGuard
from src.infrastructure.persistence.sqlite_task_repository import find_task_by_name_sync
from src.utils import build_task_log_path
from src.infrastructure.config.env_manager import env_manager
from src.tenancy.context import current_tenant_id, tenant_scope
from src.tenancy.paths import tenant_path
from src.tenancy.paths import tenant_root
from src.services.notification_service import build_notification_service

STOP_TIMEOUT_SECONDS = 20
SPIDER_DEBUG_LIMIT_ENV = "SPIDER_DEBUG_LIMIT"
LifecycleHook = Callable[[int], Awaitable[None] | None]


class ProcessService:
    """进程管理服务"""

    def __init__(self):
        self.processes: Dict[tuple[str, int], asyncio.subprocess.Process] = {}
        self.log_paths: Dict[tuple[str, int], str] = {}
        self.log_handles: Dict[tuple[str, int], TextIO] = {}
        self.task_names: Dict[tuple[str, int], str] = {}
        self.exit_watchers: Dict[tuple[str, int], asyncio.Task] = {}
        self.expected_stops: set[tuple[str, int]] = set()
        self.failure_guard = FailureGuard()
        self._failure_guards: Dict[str, FailureGuard] = {}
        self._on_started: LifecycleHook | None = None
        self._on_stopped: LifecycleHook | None = None

    def set_lifecycle_hooks(
        self,
        *,
        on_started: LifecycleHook | None = None,
        on_stopped: LifecycleHook | None = None,
    ) -> None:
        self._on_started = on_started
        self._on_stopped = on_stopped

    async def _invoke_hook(self, hook: LifecycleHook | None, task_id: int) -> None:
        if hook is None:
            return
        result = hook(task_id)
        if asyncio.iscoroutine(result):
            await result

    def _resolve_cookie_path(self, task_name: str) -> str | None:
        """Best-effort cookie/state path for a task."""
        try:
            task = find_task_by_name_sync(task_name)
            if task and isinstance(task.account_state_file, str) and task.account_state_file.strip():
                configured = task.account_state_file.strip()
                if configured.startswith("state/"):
                    return tenant_path(configured)
                return configured
        except Exception:
            pass

        state_file = get_state_file()
        return state_file if os.path.exists(state_file) else None

    def _runtime_key(self, task_id: int, tenant_id: str | None = None) -> tuple[str, int]:
        return (tenant_id or current_tenant_id(required=False), task_id)

    def is_running(self, task_id: int) -> bool:
        """检查任务是否正在运行"""
        process = self.processes.get(self._runtime_key(task_id))
        return process is not None and process.returncode is None

    async def _drain_finished_process(self, task_id: int) -> None:
        runtime_key = self._runtime_key(task_id)
        process = self.processes.get(runtime_key)
        if process is None or process.returncode is None:
            return

        watcher = self.exit_watchers.get(runtime_key)
        if watcher is not None:
            await asyncio.shield(watcher)
            return

        self._cleanup_runtime(runtime_key, process)
        await self._invoke_hook(self._on_stopped, task_id)

    def _open_log_file(self, task_id: int, task_name: str) -> tuple[str, TextIO]:
        os.makedirs(tenant_path("logs"), exist_ok=True)
        log_file_path = build_task_log_path(task_id, task_name)
        log_file_handle = open(log_file_path, "a", encoding="utf-8")
        return log_file_path, log_file_handle

    def _build_spawn_command(self, task_name: str) -> list[str]:
        try:
            current_tenant_id()
            script_path = str(Path(__file__).resolve().parents[2] / "spider_v2.py")
        except RuntimeError:
            script_path = "spider_v2.py"
        command = [
            sys.executable,
            "-u",
            script_path,
            "--task-name",
            task_name,
        ]
        debug_limit = str(os.getenv(SPIDER_DEBUG_LIMIT_ENV, "")).strip()
        if debug_limit.isdigit() and int(debug_limit) > 0:
            command.extend(["--debug-limit", debug_limit])
        return command

    async def _spawn_process(
        self,
        task_name: str,
        log_file_handle: TextIO,
    ) -> asyncio.subprocess.Process:
        preexec_fn = os.setsid if sys.platform != "win32" else None
        child_env = os.environ.copy()
        child_env.update(env_manager.read_env())
        child_env["TENANT_ID"] = current_tenant_id(required=False)
        child_env["TENANT_DATA_ROOT"] = str(
            Path(os.getenv("TENANT_DATA_ROOT", "data/tenants")).resolve()
        )
        project_root = str(Path(__file__).resolve().parents[2])
        existing_python_path = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = (
            f"{project_root}{os.pathsep}{existing_python_path}"
            if existing_python_path
            else project_root
        )
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        return await asyncio.create_subprocess_exec(
            *self._build_spawn_command(task_name),
            stdout=log_file_handle,
            stderr=log_file_handle,
            preexec_fn=preexec_fn,
            env=child_env,
            cwd=str(tenant_root().resolve()),
        )

    def _register_runtime(
        self,
        runtime_key: tuple[str, int],
        task_id: int,
        task_name: str,
        process: asyncio.subprocess.Process,
        log_file_path: str,
        log_file_handle: TextIO,
    ) -> None:
        self.processes[runtime_key] = process
        self.log_paths[runtime_key] = log_file_path
        self.log_handles[runtime_key] = log_file_handle
        self.task_names[runtime_key] = task_name
        self.exit_watchers[runtime_key] = asyncio.create_task(
            self._watch_process_exit(process, runtime_key, task_id)
        )

    async def start_task(self, task_id: int, task_name: str) -> bool:
        """启动任务进程"""
        runtime_key = self._runtime_key(task_id)
        await self._drain_finished_process(task_id)
        if self.is_running(task_id):
            print(f"任务 '{task_name}' (ID: {task_id}) 已在运行中")
            return False

        tenant_id = current_tenant_id(required=False)
        if tenant_id == "default" and tenant_id not in self._failure_guards:
            self._failure_guards[tenant_id] = self.failure_guard
        failure_guard = self._failure_guards.setdefault(
            tenant_id,
            FailureGuard(path=tenant_path("logs/task-failure-guard.json")),
        )
        decision = failure_guard.should_skip_start(
            task_name,
            cookie_path=self._resolve_cookie_path(task_name),
        )
        if decision.skip:
            await self._notify_skip(task_name, decision, failure_guard.threshold)
            return False

        log_file_path = ""
        log_file_handle = None
        try:
            log_file_path, log_file_handle = self._open_log_file(task_id, task_name)
            process = await self._spawn_process(task_name, log_file_handle)
        except Exception as exc:
            self._close_log_handle(log_file_handle)
            print(f"启动任务 '{task_name}' 失败: {exc}")
            return False

        self._register_runtime(runtime_key, task_id, task_name, process, log_file_path, log_file_handle)
        print(f"启动任务 '{task_name}' (PID: {process.pid})")
        await self._invoke_hook(self._on_started, task_id)
        return True

    async def _notify_skip(self, task_name: str, decision, threshold: int) -> None:
        print(
            f"[FailureGuard] 跳过启动任务 '{task_name}'，已暂停重试 "
            f"(连续失败 {decision.consecutive_failures}/{threshold})"
        )
        if not decision.should_notify:
            return
        try:
            await build_notification_service().send_notification(
                {
                    "商品标题": f"[任务暂停] {task_name}",
                    "当前售价": "N/A",
                    "商品链接": "#",
                },
                "任务处于暂停状态，将跳过执行。\n"
                f"原因: {decision.reason}\n"
                f"连续失败: {decision.consecutive_failures}/{threshold}\n"
                f"暂停到: {decision.paused_until.strftime('%Y-%m-%d %H:%M:%S') if decision.paused_until else 'N/A'}\n"
                "修复方法: 更新登录态/cookies文件后会自动恢复。",
            )
        except Exception as exc:
            print(f"发送任务暂停通知失败: {exc}")

    async def _watch_process_exit(
        self,
        process: asyncio.subprocess.Process,
        runtime_key: tuple[str, int],
        task_id: int,
    ) -> None:
        await process.wait()
        tenant_id = runtime_key[0]
        with tenant_scope(tenant_id):
            await self._handle_process_exit(process, runtime_key, task_id)

    async def _handle_process_exit(
        self,
        process: asyncio.subprocess.Process,
        runtime_key: tuple[str, int],
        task_id: int,
    ) -> None:
        task_name = self.task_names.get(runtime_key, "Unknown")

        # 尝试获取商品数量（从日志文件或结果文件）
        items_count = 0
        want_count_total = 0
        want_count_diff = 0
        price_diff = None
        log_path = self.log_paths.get(runtime_key)
        if log_path:
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    full_content = f.read()

                    # 只解析本次运行的日志（最后一个 "--- 开始执行监控任务 ---" 之后的内容）
                    import re
                    run_markers = list(re.finditer(r"--- 开始执行监控任务 ---", full_content))
                    if run_markers:
                        # 取最后一个开始标记之后的内容
                        last_marker_pos = run_markers[-1].start()
                        content = full_content[last_marker_pos:]
                    else:
                        content = full_content

                    # 优先识别店铺监控的稳定汇总行，再兼容关键词/商品 ID 旧日志。
                    store_matches = re.findall(
                        r"店铺在售商品 \d+ 件，成功采集 (\d+) 件",
                        content,
                    )
                    if store_matches:
                        items_count = int(store_matches[-1])
                    else:
                        partial_store_matches = re.findall(
                            r"店铺监控部分失败：成功 (\d+)/\d+",
                            content,
                        )
                        if partial_store_matches:
                            items_count = int(partial_store_matches[-1])
                        else:
                            matches = re.findall(r"推荐了 (\d+) 个商品", content)
                            if matches:
                                items_count = int(matches[-1])
                            else:
                                # 商品 ID 监控模式使用处理数作为完成数量
                                matches = re.findall(r"共处理了 (\d+) 个商品", content)
                                if matches:
                                    items_count = int(matches[-1])

                    # 提取想要数汇总信息（只取本次运行的值）
                    want_matches = re.findall(r"想要数：(\d+)", content)
                    if want_matches:
                        want_count_total = int(want_matches[-1])  # 只取本次运行的值
                        # 从日志中提取上次的想要数
                        prev_want_matches = re.findall(r"上次想要数：(\d+)", content)
                        if prev_want_matches:
                            prev_want = int(prev_want_matches[-1])
                            want_count_diff = want_count_total - prev_want

                    # 提取价格变化信息（只解析本次运行的日志）
                    # 匹配格式：价格变化：¥+4.0 或 价格变化：¥-2.5 或 价格变化：¥3.0
                    price_matches = re.findall(r"价格变化：¥([+-]?[\d.]+)", content)
                    if price_matches:
                        # 只取本次运行的最后一次价格变化
                        last_price_change = price_matches[-1]
                        price_diff = round(float(last_price_change), 2)
            except Exception:
                pass

        # 发送 WebSocket 通知
        was_expected_stop = runtime_key in self.expected_stops
        self.expected_stops.discard(runtime_key)
        notification_data = {
            "task_id": task_id,
            "task_name": task_name,
            "completed_at": datetime.now().isoformat(),
            "items_count": items_count,
            "success": process.returncode == 0,
            "returncode": process.returncode,
            "stopped": was_expected_stop,
        }
        if want_count_total > 0:
            notification_data["want_count_total"] = want_count_total
            if want_count_diff != 0:
                notification_data["want_count_diff"] = want_count_diff
        if price_diff is not None and price_diff != 0:
            notification_data["price_diff"] = price_diff

        if process.returncode == 0:
            event_name = "task_completed"
        elif was_expected_stop:
            event_name = "task_stopped"
        else:
            event_name = "task_failed"
        await websocket.broadcast_message(event_name, notification_data)

        self._cleanup_runtime(runtime_key, process)
        await self._invoke_hook(self._on_stopped, task_id)

    def _cleanup_runtime(
        self,
        runtime_key: tuple[str, int],
        process: asyncio.subprocess.Process,
    ) -> None:
        if self.processes.get(runtime_key) is not process:
            return
        self.processes.pop(runtime_key, None)
        self.log_paths.pop(runtime_key, None)
        self.task_names.pop(runtime_key, None)
        self._close_log_handle(self.log_handles.pop(runtime_key, None))
        self.exit_watchers.pop(runtime_key, None)

    def _close_log_handle(self, log_handle: TextIO | None) -> None:
        if log_handle is None:
            return
        with contextlib.suppress(Exception):
            log_handle.close()

    def _append_stop_marker(self, log_path: str | None) -> None:
        if not log_path:
            return
        try:
            timestamp = datetime.now().strftime(" %Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"[{timestamp}] !!! 任务已被终止 !!!\n")
        except Exception as exc:
            print(f"写入任务终止标记失败: {exc}")

    async def stop_task(self, task_id: int) -> bool:
        """停止任务进程"""
        await self._drain_finished_process(task_id)
        runtime_key = self._runtime_key(task_id)
        process = self.processes.get(runtime_key)
        if process is None:
            print(f"任务 ID {task_id} 没有正在运行的进程")
            return False
        if process.returncode is not None:
            await self._await_exit_watcher(task_id)
            print(f"任务进程 {process.pid} (ID: {task_id}) 已退出，略过停止")
            return False

        try:
            self.expected_stops.add(runtime_key)
            await self._terminate_process(process, task_id)
            self._append_stop_marker(self.log_paths.get(runtime_key))
            await self._await_exit_watcher(task_id)
            print(f"任务进程 {process.pid} (ID: {task_id}) 已终止")
            return True
        except ProcessLookupError:
            self.expected_stops.discard(runtime_key)
            print(f"进程 (ID: {task_id}) 已不存在")
            return False
        except Exception as exc:
            self.expected_stops.discard(runtime_key)
            print(f"停止任务进程 (ID: {task_id}) 时出错: {exc}")
            return False

    async def _terminate_process(
        self,
        process: asyncio.subprocess.Process,
        task_id: int,
    ) -> None:
        if sys.platform != "win32":
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()

        try:
            await asyncio.wait_for(process.wait(), timeout=STOP_TIMEOUT_SECONDS)
            return
        except asyncio.TimeoutError:
            print(
                f"任务进程 {process.pid} (ID: {task_id}) 未在 "
                f"{STOP_TIMEOUT_SECONDS} 秒内退出，准备强制终止..."
            )

        if sys.platform != "win32":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
        await process.wait()

    async def _await_exit_watcher(self, task_id: int) -> None:
        watcher = self.exit_watchers.get(self._runtime_key(task_id))
        if watcher is None:
            return
        await asyncio.shield(watcher)

    async def wait_for_task(self, task_id: int) -> None:
        """等待任务子进程退出，供调度器在此期间持续占用并发槽位。"""
        await self._await_exit_watcher(task_id)

    def reindex_after_delete(self, deleted_task_id: int) -> None:
        """删除任务后同步重排运行时索引，避免任务下标漂移。"""
        tenant_id = current_tenant_id(required=False)
        self.processes = self._reindex_mapping(self.processes, tenant_id, deleted_task_id)
        self.log_paths = self._reindex_mapping(self.log_paths, tenant_id, deleted_task_id)
        self.log_handles = self._reindex_mapping(self.log_handles, tenant_id, deleted_task_id)
        self.task_names = self._reindex_mapping(self.task_names, tenant_id, deleted_task_id)
        self.exit_watchers = self._reindex_mapping(self.exit_watchers, tenant_id, deleted_task_id)

    def _reindex_mapping(self, mapping, tenant_id: str, deleted_task_id: int):
        reindexed = {}
        legacy_keys = all(isinstance(key, int) for key in mapping)
        for runtime_key, value in mapping.items():
            if legacy_keys:
                task_id = runtime_key
                if task_id == deleted_task_id:
                    continue
                next_task_id = task_id - 1 if task_id > deleted_task_id else task_id
                reindexed[next_task_id] = value
                continue
            key_tenant, task_id = runtime_key
            if key_tenant != tenant_id:
                reindexed[runtime_key] = value
                continue
            if task_id == deleted_task_id:
                continue
            next_task_id = task_id - 1 if task_id > deleted_task_id else task_id
            reindexed[(tenant_id, next_task_id)] = value
        return reindexed

    async def stop_all(self) -> None:
        """停止所有任务进程"""
        runtime_keys = list(self.processes.keys())
        for tenant_id, task_id in runtime_keys:
            with tenant_scope(tenant_id):
                await self.stop_task(task_id)
