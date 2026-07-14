"""
通知配置工厂
"""
from src.infrastructure.config.settings import NotificationSettings

from .feishu_client import FeishuClient
from .bark_client import BarkClient
from .gotify_client import GotifyClient
from .ntfy_client import NtfyClient
from .telegram_client import TelegramClient
from .webhook_client import WebhookClient
from .wecom_bot_client import WeComBotClient


def build_notification_clients(settings: NotificationSettings):
    pcurl_to_mobile = settings.pcurl_to_mobile
    return [
        NtfyClient(settings.ntfy_topic_url, pcurl_to_mobile=pcurl_to_mobile),
        GotifyClient(settings.gotify_url, settings.gotify_token, pcurl_to_mobile=pcurl_to_mobile),
        BarkClient(settings.bark_url, pcurl_to_mobile=pcurl_to_mobile),
        WeComBotClient(settings.wx_bot_url, pcurl_to_mobile=pcurl_to_mobile),
        TelegramClient(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            settings.telegram_api_base_url,
            pcurl_to_mobile=pcurl_to_mobile,
        ),
        WebhookClient(
            settings.webhook_url,
            settings.webhook_method,
            settings.webhook_headers,
            settings.webhook_content_type,
            settings.webhook_query_parameters,
            settings.webhook_body,
            pcurl_to_mobile=pcurl_to_mobile,
        ),
        FeishuClient(settings.feishu_webhook_url, pcurl_to_mobile=pcurl_to_mobile),
    ]
