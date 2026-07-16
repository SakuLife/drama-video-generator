"""ステージ2: Nano Banana (KIEAI) によるシーン画像生成

APIの実装は本社の共有クライアント（_shared/skills/kieai）に委譲する。
エンドポイント仕様・ポーリング形式はそちらが正（自前実装で二重管理しない）。
"""

import logging
import os
import sys
import time
from pathlib import Path

from PIL import Image

# PythonSystem（本社ルート）をパスに追加して共有スキルを読む
_COMPANY_ROOT = Path(__file__).resolve().parents[2]
if str(_COMPANY_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPANY_ROOT))

from _shared.skills.kieai import KieAIClient, KieAITaskFailed, download_file  # noqa: E402

from src.script_gen import rewrite_image_prompt  # noqa: E402

from config.settings import (  # noqa: E402
    IMAGE_ASPECT_RATIO,
    IMAGE_MAX_CONSECUTIVE_FAILURES,
    IMAGE_MAX_WAIT,
    IMAGE_MODEL,
    IMAGE_POLL_INTERVAL,
    IMAGE_RESOLUTION,
    IMAGE_RETRIES,
)

logger = logging.getLogger(__name__)


def _download_atomic(url: str, output_path: Path) -> None:
    """一時ファイルに落としてから正式名にリネームする

    直接書き込むと、途中で落ちたとき壊れたPNGが正式名で残る。
    次回実行は「生成済み」と見なしてスキップし、動画合成で初めて壊れて気付くことになる。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".part")

    download_file(url, str(tmp_path))

    # 壊れた画像を掴まないよう、正式名にする前に開けることを確かめる
    try:
        with Image.open(tmp_path) as img:
            img.verify()
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"ダウンロードした画像が壊れています: {e}") from e

    os.replace(tmp_path, output_path)


def _is_valid_image(path: Path) -> bool:
    """再開時に「生成済み」と見なしてよい画像か（壊れていれば作り直す）"""
    if not path.exists():
        return False
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        logger.warning(f"壊れた画像を検出。作り直します: {path.name}")
        return False


def generate_image(
    api_key: str,
    prompt: str,
    output_path: Path,
    retries: int = IMAGE_RETRIES,
    model: str = IMAGE_MODEL,
    gemini_key: str = "",
) -> Path:
    """Nano Banana APIで画像を1枚生成して保存する

    Args:
        api_key: KIEAI APIキー
        prompt: 画像生成プロンプト（英語）
        output_path: 保存先
        retries: 失敗時のリトライ回数
        model: "nano-banana"（2クレジット/枚）or "nano-banana-pro"（8-16クレジット/枚）

    Returns:
        保存した画像のパス
    """
    client = KieAIClient(api_key=api_key)

    # 生成は課金対象。ダウンロードだけ失敗したときに作り直すと二重課金になるため、
    # 一度URLが取れたら以降のリトライでは生成をやり直さない。
    image_url: str | None = None
    current_prompt = prompt
    softened = 0

    for attempt in range(retries):
        try:
            if image_url is None:
                if model == "nano-banana-pro":
                    image_url = client.generate_nanobanana_pro(
                        prompt=current_prompt,
                        aspect_ratio=IMAGE_ASPECT_RATIO,
                        resolution=IMAGE_RESOLUTION,
                        max_wait=IMAGE_MAX_WAIT,
                        poll_interval=IMAGE_POLL_INTERVAL,
                    )
                else:
                    image_url = client.generate_nanobanana(
                        prompt=current_prompt,
                        aspect_ratio=IMAGE_ASPECT_RATIO,
                        max_wait=IMAGE_MAX_WAIT,
                        poll_interval=IMAGE_POLL_INTERVAL,
                    )

            _download_atomic(image_url, output_path)
            logger.info(f"画像保存: {output_path.name}")
            return output_path

        except KieAITaskFailed as e:
            # センシティブ判定は同じプロンプトで作り直しても必ず同じ結果になる。
            # リトライではなく、表現を穏当に書き直してから作り直す。
            if e.is_sensitive and gemini_key:
                softened += 1
                logger.warning(
                    f"センシティブ判定のため書き直します（{output_path.name} / {softened}回目）"
                )
                current_prompt = rewrite_image_prompt(gemini_key, current_prompt, attempt=softened)
                if attempt >= retries - 1:
                    raise
                continue

            logger.warning(f"画像生成リトライ {attempt + 1}/{retries}: {e}")
            if attempt >= retries - 1:
                raise
            time.sleep(2**attempt)

        except Exception as e:
            logger.warning(f"画像生成リトライ {attempt + 1}/{retries}: {e}")
            if attempt >= retries - 1:
                raise
            time.sleep(2**attempt)


def generate_all_images(
    api_key: str,
    script: dict,
    output_dir: Path,
    delay: float = 1.0,
    model: str = IMAGE_MODEL,
    gemini_key: str = "",
) -> list[Path]:
    """台本の全シーン画像を生成する（生成済みはスキップ＝再開可能）

    Args:
        gemini_key: センシティブ判定で弾かれたプロンプトの書き直しに使う。
            未指定だと書き直せず、そのシーンは失敗として扱う。
    """
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    image_paths = []
    failed: list[tuple[int, str]] = []
    consecutive_failures = 0
    scenes = script["scenes"]
    total = len(scenes)

    for i, scene in enumerate(scenes):
        image_path = images_dir / f"scene_{scene['id']:03d}.png"

        # 既に生成済みならスキップ（クレジットの無駄打ちを防ぐ）
        if _is_valid_image(image_path):
            logger.info(f"スキップ（生成済み）: {image_path.name}")
            image_paths.append(image_path)
            continue

        prompt = scene["image_prompt"]
        logger.info(f"画像生成 [{i + 1}/{total}]: {prompt[:60]}...")

        # 1枚の失敗で残り全部を諦めない。失敗は覚えておいて最後にまとめて報告し、
        # 成功したぶんは残す（再実行時はスキップされるので焼き直しにならない）。
        try:
            generate_image(api_key, prompt, image_path, model=model, gemini_key=gemini_key)
            image_paths.append(image_path)
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            failed.append((scene["id"], str(e)[:120]))
            logger.error(f"画像生成に失敗 scene_{scene['id']:03d}（続行します）: {e}")

            # クレジット切れ等、続けても無駄なときは打ち切る
            if consecutive_failures >= IMAGE_MAX_CONSECUTIVE_FAILURES:
                raise RuntimeError(
                    f"画像生成が{consecutive_failures}回連続で失敗しました。"
                    f"APIキー・クレジット残高を確認してください。最後のエラー: {e}"
                ) from e

        # レート制限対策
        if i < total - 1:
            time.sleep(delay)

    logger.info(f"画像生成: 成功{len(image_paths)}枚 / 失敗{len(failed)}枚（全{total}シーン）")

    if failed:
        # 歯抜けのまま動画にすると欠けたシーンの動画が完成品として出てしまう。
        # 成功したぶんは保存済みなので、再実行すれば失敗分だけ作り直される。
        ids = ", ".join(f"scene_{sid:03d}" for sid, _ in failed[:10])
        raise RuntimeError(
            f"{len(failed)}枚の画像を生成できませんでした（{ids}）。"
            "同じコマンドで再実行すれば、失敗した分だけ作り直します。"
        )

    return image_paths
