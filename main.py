"""ドラマ動画自動生成パイプライン - エントリーポイント"""

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import GENERATED_DIR, LOGS_DIR, TARGET_SCENES
from src.notifier import notify_error, notify_success

JST = timezone(timedelta(hours=9))

# ロギング設定
def setup_logging() -> None:
    """ログ設定"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"run_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def get_output_dir() -> Path:
    """日付ベースの出力ディレクトリを作成"""
    date_str = datetime.now(JST).strftime("%Y%m%d")
    output_dir = GENERATED_DIR / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def run_pipeline(
    theme: str | None = None,
    stage: str | None = None,
    auto: bool = False,
    upload: bool = False,
) -> None:
    """メインパイプライン実行"""
    logger = logging.getLogger(__name__)

    # 環境変数取得
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    kieai_key = os.getenv("KIEAI_API_KEY", "")
    voicevox_url = os.getenv("VOICEVOX_URL", "http://localhost:50021")
    discord_webhook = os.getenv("DISCORD_WEBHOOK_URL", "")

    output_dir = get_output_dir()
    logger.info(f"出力先: {output_dir}")

    try:
        # === ステージ1: 台本生成 ===
        if stage in (None, "script"):
            from src.script_gen import auto_select_theme, generate_script

            if not theme:
                if auto:
                    theme = auto_select_theme(gemini_key)
                else:
                    logger.error("--theme または --auto を指定してください")
                    return

            script = generate_script(
                api_key=gemini_key,
                theme=theme,
                output_dir=output_dir,
                target_scenes=TARGET_SCENES,
            )
            logger.info(f"台本生成完了: {len(script['scenes'])}シーン")

            if stage == "script":
                return

        # 台本読み込み（途中ステージから再開時）
        if stage and stage != "script":
            script_path = output_dir / "script.json"
            if not script_path.exists():
                logger.error(f"台本が見つかりません: {script_path}")
                return
            script = json.loads(script_path.read_text(encoding="utf-8"))

        # === ステージ2: 画像生成 ===
        if stage in (None, "image"):
            from src.image_gen import generate_all_images

            image_paths = generate_all_images(
                api_key=kieai_key,
                script=script,
                output_dir=output_dir,
            )
            logger.info(f"画像生成完了: {len(image_paths)}枚")

            if stage == "image":
                return

        # === ステージ3: 音声生成 ===
        if stage in (None, "voice"):
            from src.voice_gen import check_voicevox_available, generate_all_voices

            if not check_voicevox_available(voicevox_url):
                logger.error("VOICEVOXが起動していません。先にVOICEVOXを起動してください。")
                return

            audio_results = generate_all_voices(
                script=script,
                output_dir=output_dir,
                voicevox_url=voicevox_url,
            )
            logger.info(f"音声生成完了: {len(audio_results)}件")

            if stage == "voice":
                return

        # 音声メタデータ読み込み（途中再開時）
        if stage and stage not in ("script", "image", "voice"):
            audio_dir = output_dir / "audio"
            from src.voice_gen import get_audio_duration

            audio_results = []
            for scene in script["scenes"]:
                audio_path = audio_dir / f"scene_{scene['id']:03d}.wav"
                if audio_path.exists():
                    duration = get_audio_duration(audio_path)
                    audio_results.append(
                        {"scene_id": scene["id"], "path": audio_path, "duration": duration}
                    )

        # === ステージ4: 動画合成 ===
        if stage in (None, "video"):
            from src.video_edit import compose_video

            # BGMファイル検索
            from config.settings import BGM_DIR

            bgm_files = list(BGM_DIR.glob("*.mp3")) + list(BGM_DIR.glob("*.wav"))
            bgm_path = bgm_files[0] if bgm_files else None

            video_path = compose_video(
                script=script,
                audio_results=audio_results,
                output_dir=output_dir,
                bgm_path=bgm_path,
            )
            logger.info(f"動画合成完了: {video_path}")

            # サムネイル生成
            from src.thumbnail_gen import generate_thumbnail

            first_image = output_dir / "images" / "scene_001.png"
            if first_image.exists():
                thumb_text = script.get("title", "ドラマ")[:15]
                generate_thumbnail(
                    scene_image_path=first_image,
                    text=thumb_text,
                    output_path=output_dir / "thumbnail.jpg",
                )

            if stage == "video":
                return

        # === ステージ5: YouTubeアップロード ===
        if stage in (None, "upload") or upload:
            yt_client_id = os.getenv("YT_CLIENT_ID", "")
            yt_client_secret = os.getenv("YT_CLIENT_SECRET", "")
            yt_refresh_token = os.getenv("YT_REFRESH_TOKEN", "")

            if not all([yt_client_id, yt_client_secret, yt_refresh_token]):
                logger.warning("YouTube認証情報が設定されていません。アップロードをスキップ。")
                return

            from src.youtube_uploader import upload_video

            video_path = output_dir / "video.mp4"
            thumbnail_path = output_dir / "thumbnail.jpg"

            result = upload_video(
                video_path=video_path,
                title=script["title"],
                description=script.get("description", ""),
                tags=script.get("tags", []),
                thumbnail_path=thumbnail_path if thumbnail_path.exists() else None,
                client_id=yt_client_id,
                client_secret=yt_client_secret,
                refresh_token=yt_refresh_token,
            )

            logger.info(f"YouTube投稿完了: {result['url']}")

            # Discord通知
            if discord_webhook:
                notify_success(
                    webhook_url=discord_webhook,
                    title=script["title"],
                    video_url=result["url"],
                    duration_min=sum(r["duration"] for r in audio_results) / 60,
                )

    except Exception as e:
        logger.error(f"パイプラインエラー: {e}")
        logger.error(traceback.format_exc())
        if discord_webhook:
            notify_error(discord_webhook, stage or "pipeline", str(e))
        raise


def main() -> None:
    """CLI エントリーポイント"""
    parser = argparse.ArgumentParser(description="ドラマ動画自動生成")
    parser.add_argument("--theme", type=str, help="ドラマのテーマ/タイトル")
    parser.add_argument("--auto", action="store_true", help="テーマをAI自動選択")
    parser.add_argument(
        "--stage",
        choices=["script", "image", "voice", "video", "upload"],
        help="特定ステージのみ実行",
    )
    parser.add_argument("--upload", action="store_true", help="YouTube自動アップロード")
    parser.add_argument("--suggest-themes", action="store_true", help="テーマ候補を表示")

    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)

    if args.suggest_themes:
        from src.script_gen import suggest_themes

        gemini_key = os.getenv("GEMINI_API_KEY", "")
        themes = suggest_themes(gemini_key)
        print("\n=== テーマ候補 ===")
        for i, t in enumerate(themes, 1):
            print(f"\n{i}. {t['title']}")
            print(f"   ジャンル: {t['genre']}")
            print(f"   あらすじ: {t['synopsis']}")
        return

    if not args.theme and not args.auto:
        parser.error("--theme または --auto を指定してください（--suggest-themes でテーマ候補表示）")

    run_pipeline(
        theme=args.theme,
        stage=args.stage,
        auto=args.auto,
        upload=args.upload,
    )


if __name__ == "__main__":
    main()
