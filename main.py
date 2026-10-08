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

    script_path = output_dir / "script.json"

    # この回に試す条件（声など）。再開しても同じ条件で続けるよう output_dir に保存される
    from src.experiment import choose_variant

    variant = choose_variant(output_dir)
    logger.info(f"今回の条件: {variant}")

    try:
        # === ステージ1: 台本生成 ===
        if stage in (None, "script"):
            from src.script_gen import auto_select_theme, generate_script

            # 台本があれば作り直さない。作り直すと、生成済みの画像は前の台本のもの
            # なのに台本だけ新しくなり、絵と話が食い違った動画が黙って完成する。
            # （画像・音声と同じく「生成済みはスキップ」で揃える）
            if script_path.exists() and stage != "script":
                script = json.loads(script_path.read_text(encoding="utf-8"))
                logger.info(
                    f"台本は生成済みのため再利用します（{len(script['scenes'])}シーン）: {script_path}"
                )
                if theme:
                    logger.warning(
                        f"指定された --theme は無視されます（既存の台本を使うため）: {theme[:40]}。"
                        "作り直すなら script.json を消すか --output-dir を分けてください。"
                    )
            else:
                if not theme:
                    if auto:
                        theme = auto_select_theme(gemini_key)
                    else:
                        raise RuntimeError("--theme または --auto を指定してください")

                script = generate_script(
                    api_key=gemini_key,
                    theme=theme,
                    output_dir=output_dir,
                    target_scenes=target_scenes,
                )
                logger.info(f"台本生成完了: {len(script['scenes'])}シーン")
                # 分析でテーマ別にも比べられるよう、元のテーマを台本に残す
                script["theme"] = theme
                script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

            if stage == "script":
                return

        # 台本読み込み（途中ステージから再開時）
        if stage and stage != "script":
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
                # センシティブ判定で弾かれたプロンプトの書き直しに使う
                gemini_key=gemini_key,
            )
            logger.info(f"画像生成完了: {len(image_paths)}枚")

            if stage == "image":
                return

        # === ステージ3: 音声生成 ===
        if stage in (None, "voice"):
            from src.voice_gen import ensure_voicevox, generate_all_voices

            if not ensure_voicevox(voicevox_url):
                raise RuntimeError("VOICEVOXを起動できませんでした")

            # 🔴 読み上げはかなで（漢字を VOICEVOX に渡さない）。ズレ0件を確かめた読みだけ使う。
            #    作れなければ ReadingsPending＝夜中に再試行（漢字のまま出すことはしない・2026-10-08 本社決定）
            from src.reading import prepare_readings

            readings = prepare_readings(script, output_dir, variant["speaker_id"])
            audio_results = generate_all_voices(
                script=script,
                output_dir=output_dir,
                voicevox_url=voicevox_url,
                speaker_id=variant["speaker_id"],
                readings=readings,
            )
            logger.info(f"音声生成完了: {len(audio_results)}件")

            if stage == "voice":
                return

        # 音声メタデータ読み込み（途中再開時）
        if stage and stage not in ("script", "image", "voice"):
            from src.voice_gen import load_audio_results

            audio_results = load_audio_results(script, output_dir)

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

            from src.experiment import description_with_credits, record_upload
            from src.youtube_uploader import upload_video

            # 動画の実体チェック（壊れ・無音・短すぎ）は upload_video 側の verify_video が行う
            video_path = output_dir / "video.mp4"
            thumbnail_path = output_dir / "thumbnail.jpg"

            result = upload_video(
                video_path=video_path,
                title=script["title"],
                # 末尾にフィクションの断りと VOICEVOX のクレジット（利用規約で必須）を付ける
                description=description_with_credits(script.get("description", ""), variant),
                tags=script.get("tags", []),
                thumbnail_path=thumbnail_path if thumbnail_path.exists() else None,
                client_id=yt_client_id,
                client_secret=yt_client_secret,
                refresh_token=yt_refresh_token,
            )

            logger.info(f"YouTube投稿完了: {result['url']}")

            # 分析用に「この回の条件」を残す（scripts/analyze.py が条件ごとに再生数を比べる）
            record_upload(
                result=result,
                script=script,
                variant=variant,
                output_dir=output_dir,
                duration_sec=sum(r["duration"] for r in audio_results),
            )

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
        from src.reading import ReadingsPending

        if isinstance(e, ReadingsPending):
            # 失敗ではなく「後で」。夜中の drama_reading_retry が続きから作る
            logger.warning(f"読みが今は作れないため、夜中に再試行します: {e}")
            if discord_webhook:
                notify_error(discord_webhook, "読み作り（あとで再試行）", f"{output_dir.name}: {str(e)[:300]}")
            raise
        logger.error(f"パイプラインエラー: {e}")
        logger.error(traceback.format_exc())
        if discord_webhook:
            notify_error(discord_webhook, stage or "pipeline", str(e))
        raise


def resume_pending() -> int:
    """読み作りが止まった回（readings_pending.json がある出力先）を続きから作って投稿する

    drama_reading_retry（07:00 から3時間ごと・本番 drama_daily は 04:00）が呼ぶ。本社決定（2026-10-08）:
    18時の公開に間に合わなければ（16時を過ぎた・印から22時間以上）その日は作らず、Discord に1行。
    """
    from src.experiment import slot_filled
    from src.reading import PENDING_FILE, ReadingsPending
    from src.youtube_uploader import get_publish_time

    logger = logging.getLogger(__name__)
    pending = sorted(GENERATED_DIR.glob(f"*/{PENDING_FILE}"))
    if not pending:
        return 0
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    now = datetime.now(JST)
    rc = 0
    for marker in pending:
        out_dir = marker.parent
        since = datetime.fromisoformat(json.loads(marker.read_text(encoding="utf-8"))["since"]).replace(tzinfo=JST)
        if now.hour >= 16 or now - since > timedelta(hours=22) or slot_filled(get_publish_time()):
            marker.unlink()
            msg = f"{out_dir.name}: 読みが公開までに揃わなかったので、この回は作りません（読み間違いを出さないため）"
            logger.warning(msg)
            if webhook:
                notify_error(webhook, "ドラマ動画（この回は休み）", msg)
            continue
        logger.info(f"読み作りを再試行: {out_dir.name}")
        try:
            run_pipeline(upload=True, output_dir=out_dir)
        except ReadingsPending:
            rc = 7  # まだ作れない＝次の再試行へ
        except Exception:
            rc = 1
    return rc


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
        help=f"生成シーン数（デフォルト: {TARGET_SCENES}＝約13分。動作確認は少なめに）",
    )
    parser.add_argument("--output-dir", type=str, help="出力先を明示指定（検証用）")
    parser.add_argument("--force", action="store_true", help="今日すでに投稿済みでも作って投稿する")
    parser.add_argument(
        "--resume-pending", action="store_true",
        help="読み作りが止まった回を続きから作る（drama_reading_retry 用。無ければ何もしない）",
    )

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

    if args.resume_pending:
        sys.exit(resume_pending())

    # 1日1本のガード（タスクはログオン時にも起動する＝再起動した日に2本目を投稿しないため）。
    # 終了コード9＝「次の公開枠はもう埋まっている」。2026-10-08 に「今日投稿したか」から「次の枠が埋まっているか」へ
    # （夜中の再試行で投稿すると uploaded_at が翌日になり、翌日の本番が誤って止まるため）
    if args.upload and not args.force:
        from src.experiment import slot_filled
        from src.youtube_uploader import get_publish_time

        if slot_filled(get_publish_time()):
            logging.getLogger(__name__).info("次の公開枠はもう予約済みなので何もしません（追加で出すなら --force）")
            sys.exit(9)

    # テーマが要るのは台本を作るときだけ。以降のステージは保存済みscript.jsonから再開する。
    if args.stage in (None, "script") and not args.theme and not args.auto:
        parser.error("--theme または --auto を指定してください（--suggest-themes でテーマ候補表示）")

    from src.reading import ReadingsPending

    try:
        run_pipeline(
            theme=args.theme,
            stage=args.stage,
            auto=args.auto,
            upload=args.upload,
            target_scenes=args.scenes,
            output_dir=Path(args.output_dir) if args.output_dir else None,
        )
    except ReadingsPending:
        sys.exit(7)  # 終了コード7＝読み待ち（run_daily.bat はすぐには再実行しない＝上限は時間でしか戻らない）


if __name__ == "__main__":
    main()
