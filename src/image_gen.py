"""ステージ2: Nano Banana (KIEAI) によるシーン画像生成"""

import logging
import time
from pathlib import Path

import requests

from config.settings import IMAGE_HEIGHT, IMAGE_WIDTH

logger = logging.getLogger(__name__)

KIEAI_API_URL = "https://api.kieai.com/v1"


def generate_image(
    api_key: str,
    prompt: str,
    output_path: Path,
    width: int = IMAGE_WIDTH,
    height: int = IMAGE_HEIGHT,
    retries: int = 3,
) -> Path:
    """Nano Banana APIで画像を1枚生成"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # タスク作成
    payload = {
        "model": "nano-banana",
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_images": 1,
    }

    for attempt in range(retries):
        try:
            # タスク送信
            resp = requests.post(
                f"{KIEAI_API_URL}/images/generations",
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()

            # タスクIDで結果をポーリング
            task_id = result.get("task_id")
            if task_id:
                image_url = _poll_task(headers, task_id)
            else:
                # 直接URLが返る場合
                image_url = result["data"][0]["url"]

            # 画像ダウンロード
            img_resp = requests.get(image_url, timeout=60)
            img_resp.raise_for_status()

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(img_resp.content)
            logger.info(f"画像保存: {output_path.name}")
            return output_path

        except Exception as e:
            logger.warning(f"画像生成リトライ {attempt + 1}/{retries}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def _poll_task(headers: dict, task_id: str, timeout: int = 120) -> str:
    """タスク完了をポーリングして画像URLを取得"""
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(
            f"{KIEAI_API_URL}/images/tasks/{task_id}",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        status = result.get("status")
        if status == "completed":
            return result["data"][0]["url"]
        elif status == "failed":
            raise RuntimeError(f"画像生成失敗: {result.get('error', 'unknown')}")

        time.sleep(3)

    raise TimeoutError(f"画像生成タイムアウト: task_id={task_id}")


def generate_all_images(
    api_key: str,
    script: dict,
    output_dir: Path,
    delay: float = 1.0,
) -> list[Path]:
    """台本の全シーン画像を生成"""
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    image_paths = []
    scenes = script["scenes"]
    total = len(scenes)

    for i, scene in enumerate(scenes):
        image_path = images_dir / f"scene_{scene['id']:03d}.png"

        # 既に生成済みならスキップ
        if image_path.exists():
            logger.info(f"スキップ（生成済み）: {image_path.name}")
            image_paths.append(image_path)
            continue

        prompt = scene["image_prompt"]
        logger.info(f"画像生成 [{i + 1}/{total}]: {prompt[:60]}...")

        generate_image(api_key, prompt, image_path)
        image_paths.append(image_path)

        # レート制限対策
        if i < total - 1:
            time.sleep(delay)

    logger.info(f"全画像生成完了: {len(image_paths)}枚")
    return image_paths
