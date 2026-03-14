"""YouTube自動アップロード"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config.settings import YT_CATEGORY_ID, YT_DEFAULT_TAGS, YT_MADE_FOR_KIDS, YT_PUBLISH_HOUR_JST

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def get_credentials(client_id: str, client_secret: str, refresh_token: str) -> Credentials:
    """OAuth認証情報を構築"""
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )


def get_publish_time(publish_hour: int = YT_PUBLISH_HOUR_JST) -> str:
    """次の公開予定時刻を計算（JST → UTC ISO形式）"""
    now_jst = datetime.now(JST)
    publish_jst = now_jst.replace(hour=publish_hour, minute=0, second=0, microsecond=0)

    # 既に過ぎていたら翌日
    if publish_jst <= now_jst:
        publish_jst += timedelta(days=1)

    # UTC変換してISO形式
    publish_utc = publish_jst.astimezone(timezone.utc)
    return publish_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str] | None = None,
    thumbnail_path: Path | None = None,
    client_id: str = "",
    client_secret: str = "",
    refresh_token: str = "",
    publish_at: str | None = None,
    category_id: str = YT_CATEGORY_ID,
) -> dict:
    """動画をYouTubeにアップロード"""
    if tags is None:
        tags = YT_DEFAULT_TAGS.copy()

    creds = get_credentials(client_id, client_secret, refresh_token)
    youtube = build("youtube", "v3", credentials=creds)

    # 公開設定
    if publish_at is None:
        publish_at = get_publish_time()

    body = {
        "snippet": {
            "title": title[:100],  # YouTube上限100文字
            "description": description,
            "tags": tags[:30],  # 上限30個
            "categoryId": category_id,
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": YT_MADE_FOR_KIDS,
        },
    }

    logger.info(f"アップロード開始: {title}")
    logger.info(f"公開予定: {publish_at}")

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            logger.info(f"アップロード進捗: {progress}%")

    video_id = response["id"]
    logger.info(f"アップロード完了: https://youtu.be/{video_id}")

    # サムネイル設定
    if thumbnail_path and thumbnail_path.exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
            ).execute()
            logger.info("サムネイル設定完了")
        except Exception as e:
            logger.warning(f"サムネイル設定失敗: {e}")

    return {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "publish_at": publish_at,
    }
