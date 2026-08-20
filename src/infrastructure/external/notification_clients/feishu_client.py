"""
飞书机器人通知客户端
"""
import asyncio
from typing import Dict

import requests

from src.domain.models.store_monitoring import StoreItemChange, StoreMonitoringDigest

from .base import NotificationClient


class FeishuClient(NotificationClient):
    """飞书机器人通知客户端"""

    channel_key = "feishu"
    display_name = "飞书"
    MAX_CARD_CONTENT_BYTES = 18_000

    def __init__(self, webhook_url: str | None = None, pcurl_to_mobile: bool = True):
        super().__init__(enabled=bool(webhook_url), pcurl_to_mobile=pcurl_to_mobile)
        self.webhook_url = webhook_url

    async def send(self, product_data: Dict, reason: str) -> None:
        if not self.is_enabled():
            raise RuntimeError("飞书 未启用")

        message = self._build_message(product_data, reason)

        # 飞书富文本消息格式
        content = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "template": "blue",
                "title": {
                    "content": "🔔 闲鱼监控通知",
                    "tag": "plain_text"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": f"**商品标题**: {message.title}\n{message.content}",
                        "tag": "lark_md"
                    }
                }
            ]
        }

        payload = {
            "msg_type": "interactive",
            "card": content
        }

        await self._post_payload(payload)

    async def send_store_digest(self, digest: StoreMonitoringDigest) -> None:
        """Send all changes from one store run in a single interactive card."""
        if not self.is_enabled():
            raise RuntimeError("飞书 未启用")

        await self._post_payload(
            {
                "msg_type": "interactive",
                "card": self._build_store_digest_card(digest),
            }
        )

    def _build_store_digest_card(self, digest: StoreMonitoringDigest) -> dict:
        status = self._build_digest_status(digest)
        store_name = self._escape_text(digest.display_name, max_length=120)
        header_store_name = self._plain_text(digest.display_name, max_length=120)
        store_id = self._escape_text(digest.store_id, max_length=120)
        task_name = self._escape_text(digest.task_name, max_length=120)
        content_parts = [
            f"**监控组（店铺）**：{store_name}",
            f"**店铺 ID**：{store_id}",
            f"**监控任务**：{task_name}",
            (
                "**本次扫描**："
                f"发现 {digest.discovered_count} 件 · "
                f"成功 {digest.succeeded_count} 件 · "
                f"失败 {digest.failed_count} 件"
            ),
            f"**监控时间**：{digest.monitored_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**状态**：{status}",
        ]

        if digest.changes:
            content_parts.append("---\n**商品变化明细**")
            included_count = 0
            for index, change in enumerate(digest.changes, start=1):
                change_block = self._build_change_block(index, change)
                remaining_count = digest.change_count - included_count
                length_notice = f"另有 {remaining_count} 条变化因消息长度限制未展示。"
                projected = "\n\n".join([*content_parts, change_block, length_notice])
                if len(projected.encode("utf-8")) > self.MAX_CARD_CONTENT_BYTES:
                    break
                content_parts.append(change_block)
                included_count += 1

            omitted_count = digest.change_count - included_count
            if omitted_count:
                content_parts.append(
                    f"另有 {omitted_count} 条变化因消息长度限制未展示。"
                )
        else:
            content_parts.append("---\n本轮没有需要展开的商品变化明细。")

        changed_item_ids = {change.item_id for change in digest.changes}
        # 新上架商品的首次想要数已在变化明细中以“首次纳入”
        # 展示，这里只补充没有指标明细的新增项，避免同一商品重复两次。
        added_items_without_metric_detail = tuple(
            item for item in digest.added_items if item.item_id not in changed_item_ids
        )
        self._append_lifecycle_section(
            content_parts,
            title="新上架 / 重新纳入",
            items=added_items_without_metric_detail,
        )
        self._append_lifecycle_section(
            content_parts,
            title="已下架 / 已售出",
            items=digest.removed_items,
        )

        content = "\n\n".join(content_parts)
        # The per-field caps above should keep this path unreachable, but retain a
        # hard ceiling so unexpected input can never create an oversized card.
        content = self._truncate_utf8(content, self.MAX_CARD_CONTENT_BYTES)

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "orange" if digest.failed_count else "blue",
                "title": {
                    "content": f"🏪 店铺监控汇总 · {header_store_name}",
                    "tag": "plain_text",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": content, "tag": "lark_md"},
                }
            ],
        }

    @staticmethod
    def _build_digest_status(digest: StoreMonitoringDigest) -> str:
        if digest.is_initial_snapshot:
            return "首次监控，已建立数据基线"
        if digest.update_count == 0:
            return "本轮监控完成，未发现商品数据变化"
        return (
            f"指标变化 {digest.change_count} 件 · "
            f"新增 {len(digest.added_items)} 件 · "
            f"下架 {len(digest.removed_items)} 件"
        )

    def _append_lifecycle_section(self, content_parts, *, title: str, items) -> None:
        if not items:
            return
        max_items = 30
        lines = [f"---\n**{title}（{len(items)} 件）**"]
        for item in items[:max_items]:
            item_title = self._escape_text(item.title or item.item_id, max_length=120)
            item_id = self._escape_text(item.item_id, max_length=80)
            link = self._safe_link(item.link)
            if link:
                lines.append(f"- [{item_title}]({link}) · `{item_id}`")
            else:
                lines.append(f"- {item_title} · `{item_id}`")
        if len(items) > max_items:
            lines.append(f"- 另有 {len(items) - max_items} 件未展开")
        content_parts.append("\n".join(lines))

    def _build_change_block(self, index: int, change: StoreItemChange) -> str:
        title = self._escape_text(change.title or change.item_id, max_length=160)
        item_id = self._escape_text(change.item_id, max_length=120)
        link = self._safe_link(change.link)
        heading = f"**{index}. {title}**"
        if link:
            heading = f"**{index}. [{title}]({link})**"

        previous_want = self._display_value(change.previous_want_count)
        current_want = self._display_value(change.current_want_count)
        if change.previous_want_count is None:
            delta = "首次纳入"
        elif change.want_count_delta is None:
            delta = "无可用差值"
        else:
            delta = f"{change.want_count_delta:+d}"
        lines = [
            heading,
            f"商品 ID：{item_id}",
            f"想要数：{previous_want} → {current_want}（{delta}）",
        ]
        if change.previous_price is not None or change.current_price is not None:
            previous_price = self._escape_text(
                self._display_value(change.previous_price), max_length=80
            )
            current_price = self._escape_text(
                self._display_value(change.current_price), max_length=80
            )
            lines.append(f"价格：¥{previous_price} → ¥{current_price}")
        return "\n".join(lines)

    @staticmethod
    def _display_value(value: object | None) -> str:
        if value is None or value == "":
            return "—"
        return str(value)

    @staticmethod
    def _escape_text(value: object, max_length: int) -> str:
        text = str(value).replace("\r", " ").replace("\n", " ").strip()
        text = text.replace("\\", "\\\\")
        for character in ("*", "_", "[", "]", "(", ")", "`", "~"):
            text = text.replace(character, f"\\{character}")
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 1]}…"

    @staticmethod
    def _plain_text(value: object, max_length: int) -> str:
        text = str(value).replace("\r", " ").replace("\n", " ").strip()
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 1]}…"

    @staticmethod
    def _truncate_utf8(value: str, max_bytes: int) -> str:
        encoded = value.encode("utf-8")
        if len(encoded) <= max_bytes:
            return value
        return encoded[:max_bytes].decode("utf-8", errors="ignore")

    @staticmethod
    def _safe_link(link: str | None) -> str | None:
        if not link:
            return None
        normalized = link.strip()
        if not normalized.startswith(("https://", "http://")):
            return None
        return normalized[:2_000].replace(" ", "%20").replace(")", "%29")

    async def _post_payload(self, payload: dict) -> None:
        headers = {"Content-Type": "application/json"}
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=10,
            ),
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code", 0) != 0:
            raise RuntimeError(f"飞书返回错误：{result.get('msg', '未知错误')}")
