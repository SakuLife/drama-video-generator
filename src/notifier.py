"""Discord通知"""

import logging

import requests

logger = logging.getLogger(__name__)


def send_discord_notification(
    webhook_url: str,
    title: str,
    message: str,
    color: int = 0x00FF00,
    fields: list[dict] | None = None,
) -> None:
    """Discord Webhookで通知を送信"""
    if not webhook_url:
        return

    embed = {
        "title": title,
        "description": message,
        "color": color,
    }
    if fields:
        embed["fields"] = fields

    payload = {"embeds": [embed]}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Discord通知送信完了")
    except Exception as e:
        logger.warning(f"Discord通知失敗: {e}")


def notify_success(webhook_url: str, title: str, video_url: str, duration_min: float) -> None:
    """成功通知"""
    send_discord_notification(
        webhook_url=webhook_url,
        title="ドラマ動画 生成完了",
        message=f"**{title}**",
        color=0x00FF00,
        fields=[
            {"name": "URL", "value": video_url, "inline": True},
            {"name": "尺", "value": f"{duration_min:.1f}分", "inline": True},
        ],
    )


def notify_error(webhook_url: str, stage: str, error: str) -> None:
    """エラー通知"""
    send_discord_notification(
        webhook_url=webhook_url,
        title=f"ドラマ動画 エラー: {stage}",
        message=f"```\n{error[:1000]}\n```",
        color=0xFF0000,
    )
