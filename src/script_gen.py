"""ステージ1: Gemini APIによるドラマ台本生成"""

import json
import logging
import random
from pathlib import Path

import google.generativeai as genai

from config.prompts import (
    IMAGE_PROMPT_SOFTEN_ESCALATION,
    IMAGE_PROMPT_SOFTEN_PROMPT,
    SCRIPT_GENERATION_PROMPT,
    THEME_SUGGESTION_PROMPT,
    THUMBNAIL_TEXT_PROMPT,
)
from config.settings import (
    SCRIPT_MAX_OUTPUT_TOKENS,
    SCRIPT_MODEL,
    TARGET_SCENES,
    THEME_MAX_OUTPUT_TOKENS,
    THEME_MODEL,
)

logger = logging.getLogger(__name__)

# 台本の各シーンに最低限必要なキー（欠けると後段の画像/音声で落ちる）
REQUIRED_SCENE_KEYS = ("id", "narration", "image_prompt")


def _generate_json(
    model_name: str,
    prompt: str,
    temperature: float,
    max_output_tokens: int,
    retries: int = 3,
) -> dict | list:
    """GeminiにJSONを生成させて辞書/配列で返す

    応答が出力上限で切れると壊れたJSONが返ってJSONDecodeErrorになる。
    原因を明示しつつ、一時的なブレなら作り直せるようリトライする。
    """
    model = genai.GenerativeModel(model_name)
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                    max_output_tokens=max_output_tokens,
                ),
            )

            reason = response.candidates[0].finish_reason.name
            if reason == "MAX_TOKENS":
                raise ValueError(
                    f"出力が上限({max_output_tokens}トークン)で切れました。JSONとして不完全です。"
                )
            if reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                raise ValueError(f"生成が異常終了しました: finish_reason={reason}")

            return json.loads(response.text)

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.warning(f"JSON生成リトライ {attempt + 1}/{retries}（{model_name}）: {e}")

    raise RuntimeError(f"JSON生成に{retries}回失敗しました（{model_name}）: {last_error}")


def suggest_themes(api_key: str, count: int = 5) -> list[dict]:
    """AIにドラマテーマを提案させる"""
    genai.configure(api_key=api_key)

    themes = _generate_json(
        model_name=THEME_MODEL,
        prompt=THEME_SUGGESTION_PROMPT,
        temperature=1.0,
        max_output_tokens=THEME_MAX_OUTPUT_TOKENS,
    )

    if not isinstance(themes, list) or not themes:
        raise ValueError(f"テーマ候補が配列で返りませんでした: {type(themes).__name__}")
    for t in themes:
        if not t.get("title"):
            raise ValueError("テーマ候補にtitleがありません")

    logger.info(f"テーマ提案完了: {len(themes)}件")
    return themes[:count]


def _validate_script(script: dict, target_scenes: int) -> None:
    """台本の構造を検証する（後段で落ちるより先にここで落とす）"""
    if "scenes" not in script or not isinstance(script["scenes"], list):
        raise ValueError("台本にscenes配列が含まれていません")
    if not script.get("title"):
        raise ValueError("台本にtitleが含まれていません")

    scenes = script["scenes"]
    if not scenes:
        raise ValueError("シーンが0件です")

    for i, scene in enumerate(scenes):
        missing = [k for k in REQUIRED_SCENE_KEYS if not scene.get(k)]
        if missing:
            raise ValueError(f"シーン{i + 1}に必須キーがありません: {missing}")

    # idの重複はファイル名衝突（scene_001.png）を招くので許さない
    ids = [s["id"] for s in scenes]
    if len(set(ids)) != len(ids):
        raise ValueError("シーンidが重複しています")

    scene_count = len(scenes)
    logger.info(f"台本生成完了: {scene_count}シーン（目標: {target_scenes}）")
    if scene_count < target_scenes * 0.7:
        logger.warning(f"シーン数が目標を大きく下回ります: {scene_count} / {target_scenes}")


def generate_script(
    api_key: str,
    theme: str,
    output_dir: Path,
    target_scenes: int = TARGET_SCENES,
) -> dict:
    """ドラマ台本を生成してJSONで保存"""
    genai.configure(api_key=api_key)

    prompt = SCRIPT_GENERATION_PROMPT.format(
        theme=theme,
        target_scenes=target_scenes,
    )

    logger.info(f"台本生成開始（{SCRIPT_MODEL}）: {theme}")
    script = _generate_json(
        model_name=SCRIPT_MODEL,
        prompt=prompt,
        temperature=0.8,
        max_output_tokens=SCRIPT_MAX_OUTPUT_TOKENS,
    )

    _validate_script(script, target_scenes)

    # 保存
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / "script.json"
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"台本保存: {script_path}")

    return script


def rewrite_image_prompt(api_key: str, prompt: str, attempt: int = 1) -> str:
    """センシティブ判定で弾かれた画像プロンプトを穏当に書き直す

    同じプロンプトで作り直しても必ず同じ判定になるため、表現を変えるしかない。
    拒否が続くほど、動作描写を捨てて情景描写に寄せる。

    Args:
        api_key: Gemini APIキー
        prompt: 拒否されたプロンプト
        attempt: 何回目の書き直しか（2回目以降はより穏当に寄せる）

    Returns:
        書き直したプロンプト（失敗したら元のプロンプトをそのまま返す）
    """
    escalation = ""
    if attempt > 1:
        escalation = IMAGE_PROMPT_SOFTEN_ESCALATION.format(attempt=attempt)

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(THEME_MODEL)
        response = model.generate_content(
            IMAGE_PROMPT_SOFTEN_PROMPT.format(prompt=prompt, escalation=escalation),
            generation_config=genai.GenerationConfig(temperature=0.9, max_output_tokens=2048),
        )
        rewritten = response.text.strip().strip("`").replace("\n", " ")
        if rewritten:
            logger.info(f"画像プロンプトを書き直しました（{attempt}回目）: {rewritten[:70]}...")
            return rewritten
    except Exception as e:
        logger.warning(f"画像プロンプトの書き直しに失敗: {e}")

    return prompt


def generate_thumbnail_text(api_key: str, title: str, fallback_chars: int = 15) -> str:
    """サムネイル用の短い惹句を生成する

    タイトルを機械的に切ると文の途中で切れて意味が通らなくなるため、
    AIに10-15文字の一言を作らせる。失敗しても動画は完成させたいので
    その場合はタイトルの頭を切って返す。
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(THEME_MODEL)
        response = model.generate_content(
            THUMBNAIL_TEXT_PROMPT.format(title=title),
            generation_config=genai.GenerationConfig(temperature=0.9, max_output_tokens=2048),
        )
        text = response.text.strip().strip("「」\"'").replace("\n", "")
        if text:
            logger.info(f"サムネ惹句: {text}")
            return text[:20]
        logger.warning("サムネ惹句が空だったのでタイトルを流用します")
    except Exception as e:
        logger.warning(f"サムネ惹句の生成に失敗（タイトルで代用）: {e}")

    return title[:fallback_chars]


def auto_select_theme(api_key: str) -> str:
    """テーマを自動選択（AI提案 → ランダム選択）"""
    themes = suggest_themes(api_key)
    selected = random.choice(themes)
    logger.info(f"テーマ自動選択: {selected['title']}")
    return selected["title"]
