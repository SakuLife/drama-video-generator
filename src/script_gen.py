"""ステージ1: Gemini APIによるドラマ台本生成"""

import json
import logging
import random
from pathlib import Path

import google.generativeai as genai

from config.prompts import SCRIPT_GENERATION_PROMPT, THEME_SUGGESTION_PROMPT
from config.settings import DRAMA_GENRES, TARGET_SCENES

logger = logging.getLogger(__name__)


def suggest_themes(api_key: str, count: int = 5) -> list[dict]:
    """AIにドラマテーマを提案させる"""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    response = model.generate_content(
        THEME_SUGGESTION_PROMPT,
        generation_config=genai.GenerationConfig(
            temperature=1.0,
            response_mime_type="application/json",
        ),
    )

    themes = json.loads(response.text)
    logger.info(f"テーマ提案完了: {len(themes)}件")
    return themes[:count]


def generate_script(
    api_key: str,
    theme: str,
    output_dir: Path,
    target_scenes: int = TARGET_SCENES,
) -> dict:
    """ドラマ台本を生成してJSONで保存"""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = SCRIPT_GENERATION_PROMPT.format(
        theme=theme,
        target_scenes=target_scenes,
    )

    logger.info(f"台本生成開始: {theme}")
    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            temperature=0.8,
            response_mime_type="application/json",
        ),
    )

    script = json.loads(response.text)

    # バリデーション
    if "scenes" not in script:
        raise ValueError("台本にscenesが含まれていません")

    scene_count = len(script["scenes"])
    logger.info(f"台本生成完了: {scene_count}シーン")

    if scene_count < 30:
        logger.warning(f"シーン数が少なすぎます: {scene_count} (目標: {target_scenes})")

    # 保存
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / "script.json"
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"台本保存: {script_path}")

    return script


def auto_select_theme(api_key: str) -> str:
    """テーマを自動選択（AI提案 → ランダム選択）"""
    themes = suggest_themes(api_key)
    selected = random.choice(themes)
    logger.info(f"テーマ自動選択: {selected['title']}")
    return selected["title"]
