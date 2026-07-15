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
# 中央シークレット（_shared/secrets/.env）で未設定キーを穴埋め（ローカル.env優先）
load_dotenv(Path(__file__).resolve().parents[1] / "_shared" / "secrets" / ".env")

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

# load_dotenv後・sys.path追加後でないと読めないため、意図的にここでimportする
from config.settings import GENERATED_DIR, LOGS_DIR, TARGET_SCENES  # noqa: E402
from src.notifier import notify_error, notify_success  # noqa: E402

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
    target_scenes: int = TARGET_SCENES,
    output_dir: Path | None = None,
) -> None:
    """メインパイプライン実行"""
    logger = logging.getLogger(__name__)

    # 環境変数取得
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    kieai_key = os.getenv("KIEAI_API_KEY", "")
    voicevox_url = os.getenv("VOICEVOX_URL", "http://localhost:50021")
    discord_webhook = os.getenv("DISCORD_WEBHOOK_URL", "")

    if output_dir is None:
        output_dir = get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
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
                target_scenes=target_scenes,
            )
            logger.info(f"台本生成完了: {len(script['scenes'])}シーン")

            if stage == "script":
                return

        # 台本読み込み（途中ステージから再開時）
        if stage and stage != "script":
            script_path = output_dir / "script.json"
            if not script_path.exists():
                raise RuntimeError(f"台本が見つかりません: {script_path}")
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
            from src.voice_gen import ensure_voicevox, generate_all_voices

            if not ensure_voicevox(voicevox_url):
                raise RuntimeError("VOICEVOXを起動できませんでした")

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

            # サムネイル生成（惹句はAIに作らせる。タイトルの機械切りは文が途中で切れる）
            from src.script_gen import generate_thumbnail_text
            from src.thumbnail_gen import generate_thumbnail

            first_scene_id = script["scenes"][0]["id"]
            first_image = output_dir / "images" / f"scene_{first_scene_id:03d}.png"
            if first_image.exists():
                thumb_text = generate_thumbnail_text(gemini_key, script.get("title", "ドラマ"))
                generate_thumbnail(
                    scene_image_path=first_image,
                    text=thumb_text,
                    output_path=output_dir / "thumbnail.jpg",
                )
            else:
                logger.warning(f"サムネ用の画像がないためスキップ: {first_image}")

            if stage == "video":
                return

        # === ステージ5: YouTubeアップロード ===
        # 投稿は明示指定（--upload / --stage upload）のときだけ。事故投稿を防ぐ。
        if upload or stage == "upload":
            yt_client_id = os.getenv("YT_CLIENT_ID", "")
            yt_client_secret = os.getenv("YT_CLIENT_SECRET", "")
            yt_refresh_token = os.getenv("YT_REFRESH_TOKEN", "")

            if not all([yt_client_id, yt_client_secret, yt_refresh_token]):
                raise RuntimeError(
                    "YouTube認証情報（YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN）が未設定です。"
                    "発行: python ../_shared/secrets/mint_youtube_token.py --target 3_drama --client-secrets <json>"
                )

            from src.youtube_uploader import upload_video

            video_path = output_dir / "video.mp4"
            if not video_path.exists():
                raise RuntimeError(f"アップロードする動画がありません: {video_path}")
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

        elif stage is None:
            # 投稿なしの通し実行＝ローカル完成を通知
            logger.info(f"完成（未投稿）: {output_dir / 'video.mp4'}")
            if discord_webhook:
                notify_success(
                    webhook_url=discord_webhook,
                    title=script["title"],
                    video_url=str(output_dir / "video.mp4"),
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
    parser.add_argument(
        "--scenes",
        type=int,
        default=TARGET_SCENES,
        help=f"生成シーン数（デフォルト: {TARGET_SCENES}＝約30分。動作確認は少なめに）",
    )
    parser.add_argument("--output-dir", type=str, help="出力先を明示指定（検証用）")

    args = parser.parse_args()

    setup_logging()

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

    # テーマが要るのは台本を作るときだけ。以降のステージは保存済みscript.jsonから再開する。
    if args.stage in (None, "script") and not args.theme and not args.auto:
        parser.error("--theme または --auto を指定してください（--suggest-themes でテーマ候補表示）")

    run_pipeline(
        theme=args.theme,
        stage=args.stage,
        auto=args.auto,
        upload=args.upload,
        target_scenes=args.scenes,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )


if __name__ == "__main__":
    main()
