"""
通知服务
统一管理所有通知渠道
"""
import asyncio
import logging
from typing import Dict, Iterable, List

from src.domain.models.store_monitoring import StoreMonitoringDigest
from src.infrastructure.external.notification_clients.base import NotificationClient
from src.infrastructure.external.notification_clients.factory import build_notification_clients
from src.services.notification_config_service import load_notification_settings
from src.infrastructure.config.settings import NotificationSettings

logger = logging.getLogger(__name__)


class NotificationService:
    """通知服务"""

    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒

    def __init__(self, clients: List[NotificationClient]):
        self.clients = [client for client in clients if client.is_enabled()]

    async def send_notification(
        self,
        product_data: Dict,
        reason: str,
    ) -> Dict[str, Dict[str, str | bool]]:
        """
        发送通知到所有启用的渠道

        Returns:
            各渠道发送结果，包含成功状态和消息
        """
        if not self.clients:
            return {}

        tasks = [
            self._send_with_retry(client, product_data, reason)
            for client in self.clients
        ]
        results = await asyncio.gather(*tasks)
        return {result["channel"]: result for result in results}

    async def send_test_notification(self) -> Dict[str, Dict[str, str | bool]]:
        test_product = {
            "商品标题": "[测试通知] 闲鱼智能监控",
            "当前售价": "0",
            "商品链接": "https://www.goofish.com/",
        }
        return await self.send_notification(
            test_product,
            "这是一条测试通知，用于验证推送渠道是否可用。",
        )

    async def send_store_digest(
        self,
        digest: StoreMonitoringDigest,
        *,
        channel_keys: Iterable[str] | None = None,
    ) -> Dict[str, Dict[str, str | bool]]:
        """Send one store-run digest to every enabled channel."""
        selected_channels = set(channel_keys) if channel_keys is not None else None
        clients = [
            client
            for client in self.clients
            if selected_channels is None or client.channel_key in selected_channels
        ]
        if not clients:
            return {}

        tasks = [
            self._send_store_digest_with_retry(client, digest)
            for client in clients
        ]
        results = await asyncio.gather(*tasks)
        return {result["channel"]: result for result in results}

    def enabled_channel_keys(self) -> tuple[str, ...]:
        return tuple(client.channel_key for client in self.clients)

    async def _send_store_digest_with_retry(
        self,
        client: NotificationClient,
        digest: StoreMonitoringDigest,
    ) -> Dict[str, str | bool]:
        """Send a grouped store notification using the standard retry policy."""
        last_error = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                await client.send_store_digest(digest)
                return {
                    "channel": client.channel_key,
                    "label": client.display_name,
                    "success": True,
                    "message": "发送成功",
                }
            except Exception as exc:
                last_error = exc
                if attempt < self.MAX_RETRIES:
                    logger.warning(
                        "店铺汇总通知发送失败 (%s), 第 %s 次重试，延迟 %s 秒：%s",
                        client.channel_key,
                        attempt,
                        self.RETRY_DELAY,
                        exc,
                    )
                    await asyncio.sleep(self.RETRY_DELAY * attempt)
                else:
                    logger.error(
                        "店铺汇总通知发送失败 (%s), 已达到最大重试次数：%s",
                        client.channel_key,
                        exc,
                    )

        return {
            "channel": client.channel_key,
            "label": client.display_name,
            "success": False,
            "message": str(last_error),
        }

    async def _send_with_retry(
        self,
        client: NotificationClient,
        product_data: Dict,
        reason: str,
    ) -> Dict[str, str | bool]:
        """带重试机制的发送方法"""
        last_error = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                await client.send(product_data, reason)
                return {
                    "channel": client.channel_key,
                    "label": client.display_name,
                    "success": True,
                    "message": "发送成功",
                }
            except Exception as exc:
                last_error = exc
                if attempt < self.MAX_RETRIES:
                    logger.warning(
                        f"通知发送失败 ({client.channel_key}), 第 {attempt} 次重试，延迟 {self.RETRY_DELAY} 秒：{exc}"
                    )
                    await asyncio.sleep(self.RETRY_DELAY * attempt)  # 指数退避
                else:
                    logger.error(
                        f"通知发送失败 ({client.channel_key}), 已达到最大重试次数：{exc}"
                    )

        return {
            "channel": client.channel_key,
            "label": client.display_name,
            "success": False,
            "message": str(last_error),
        }

    async def _send_with_result(
        self,
        client: NotificationClient,
        product_data: Dict,
        reason: str,
    ) -> Dict[str, str | bool]:
        """（旧方法，保留以兼容）无重试的发送方法"""
        try:
            await client.send(product_data, reason)
            return {
                "channel": client.channel_key,
                "label": client.display_name,
                "success": True,
                "message": "发送成功",
            }
        except Exception as exc:
            return {
                "channel": client.channel_key,
                "label": client.display_name,
                "success": False,
                "message": str(exc),
            }


def build_notification_service(
    settings: NotificationSettings | None = None,
) -> NotificationService:
    notification_settings = settings or load_notification_settings()
    return NotificationService(build_notification_clients(notification_settings))
