"""ステージ4: moviepyによる動画合成"""

import logging
from pathlib import Path

import numpy as np
from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

from config.settings import (
    AUDIO_BITRATE,
    AUDIO_CODEC,
    BGM_VOLUME,
    SUBTITLE_BG_COLOR,
    SUBTITLE_FONT_COLOR,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_MARGIN_BOTTOM,
    SUBTITLE_MAX_CHARS_PER_LINE,
    VIDEO_CODEC,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)

logger = logging.getLogger(__name__)


def _wrap_text(text: str, max_chars: int = SUBTITLE_MAX_CHARS_PER_LINE) -> str:
    """テキストを指定文字数で改行"""
    lines = []
    while len(text) > max_chars:
        lines.append(text[:max_chars])
        text = text[max_chars:]
    if text:
        lines.append(text)
    return "\n".join(lines)


def _create_subtitle_frame(
    text: str,
    width: int = VIDEO_WIDTH,
    font_path: str | None = None,
    font_size: int = SUBTITLE_FONT_SIZE,
) -> np.ndarray:
    """字幕画像をPillowで生成（透過背景付き）"""
    wrapped = _wrap_text(text)
    line_count = wrapped.count("\n") + 1

    # フォント設定
    if font_path and Path(font_path).exists():
        font = ImageFont.truetype(font_path, font_size)
    else:
        # Windowsデフォルト日本語フォント
        for fp in [
            "C:/Windows/Fonts/meiryo.ttc",
            "C:/Windows/Fonts/msgothic.ttc",
            "C:/Windows/Fonts/YuGothM.ttc",
        ]:
            if Path(fp).exists():
                font = ImageFont.truetype(fp, font_size)
                break
        else:
            font = ImageFont.load_default()

    # テキストサイズ計算
    dummy_img = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # 背景バー作成
    padding_x = 40
    padding_y = 20
    bar_w = width
    bar_h = text_h + padding_y * 2

    img = Image.new("RGBA", (bar_w, bar_h), SUBTITLE_BG_COLOR)
    draw = ImageDraw.Draw(img)

    # テキスト中央配置
    x = (bar_w - text_w) // 2
    y = padding_y
    draw.multiline_text((x, y), wrapped, font=font, fill="white", align="center")

    return np.array(img)


def create_scene_clip(
    image_path: Path,
    audio_path: Path,
    narration_text: str,
    duration: float,
    font_path: str | None = None,
) -> CompositeVideoClip:
    """1シーン分のクリップを生成"""
    # 余白（前後0.3秒）
    padding = 0.3
    total_duration = duration + padding * 2

    # 背景画像
    img = Image.open(image_path).convert("RGB")
    img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
    bg_clip = ImageClip(np.array(img)).set_duration(total_duration)

    # 音声
    audio_clip = AudioFileClip(str(audio_path))

    # 字幕
    subtitle_frame = _create_subtitle_frame(narration_text, font_path=font_path)
    sub_h = subtitle_frame.shape[0]
    subtitle_clip = (
        ImageClip(subtitle_frame)
        .set_duration(duration)
        .set_start(padding)
        .set_position(("center", VIDEO_HEIGHT - sub_h - SUBTITLE_MARGIN_BOTTOM))
    )

    # 合成
    composite = CompositeVideoClip(
        [bg_clip, subtitle_clip],
        size=(VIDEO_WIDTH, VIDEO_HEIGHT),
    )
    composite = composite.set_audio(audio_clip.set_start(padding))
    composite = composite.set_duration(total_duration)

    return composite


def compose_video(
    script: dict,
    audio_results: list[dict],
    output_dir: Path,
    bgm_path: Path | None = None,
    font_path: str | None = None,
) -> Path:
    """全シーンを結合して最終動画を生成"""
    images_dir = output_dir / "images"
    scenes = script["scenes"]
    output_path = output_dir / "video.mp4"

    logger.info(f"動画合成開始: {len(scenes)}シーン")

    # シーンクリップ作成
    clips = []
    audio_map = {r["scene_id"]: r for r in audio_results}

    for scene in scenes:
        scene_id = scene["id"]
        image_path = images_dir / f"scene_{scene_id:03d}.png"
        audio_info = audio_map.get(scene_id)

        if not image_path.exists():
            logger.warning(f"画像なし、スキップ: scene_{scene_id:03d}")
            continue
        if not audio_info:
            logger.warning(f"音声なし、スキップ: scene_{scene_id:03d}")
            continue

        clip = create_scene_clip(
            image_path=image_path,
            audio_path=audio_info["path"],
            narration_text=scene["narration"],
            duration=audio_info["duration"],
            font_path=font_path,
        )
        clips.append(clip)

    if not clips:
        raise ValueError("有効なシーンクリップがありません")

    # 全シーン結合
    logger.info(f"シーン結合中: {len(clips)}クリップ")
    final = concatenate_videoclips(clips, method="compose")

    # BGM追加
    if bgm_path and bgm_path.exists():
        logger.info("BGM追加中...")
        bgm = AudioFileClip(str(bgm_path))
        # BGMをループして動画の長さに合わせる
        if bgm.duration < final.duration:
            loops = int(final.duration / bgm.duration) + 1
            bgm = concatenate_audioclips([bgm] * loops)
        bgm = bgm.subclip(0, final.duration).volumex(BGM_VOLUME)

        # ナレーション + BGM をミックス
        from moviepy.audio.AudioClip import CompositeAudioClip
        mixed_audio = CompositeAudioClip([final.audio, bgm])
        final = final.set_audio(mixed_audio)

    # 書き出し
    logger.info(f"エンコード開始: {output_path}")
    final.write_videofile(
        str(output_path),
        fps=VIDEO_FPS,
        codec=VIDEO_CODEC,
        audio_codec=AUDIO_CODEC,
        audio_bitrate=AUDIO_BITRATE,
        threads=4,
        logger=None,
    )

    # リソース解放
    final.close()
    for clip in clips:
        clip.close()

    duration_min = final.duration / 60
    logger.info(f"動画合成完了: {output_path} ({duration_min:.1f}分)")
    return output_path
