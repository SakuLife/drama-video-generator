"""ステージ4: moviepyによる動画合成"""

import logging
import os
import wave
from pathlib import Path

import numpy as np
from moviepy.audio.AudioClip import AudioArrayClip
from moviepy.editor import (
    AudioFileClip,
    ImageClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

from config.settings import (
    AUDIO_BITRATE,
    AUDIO_CODEC,
    AUDIO_SAMPLE_RATE,
    BGM_VOLUME,
    SUBTITLE_BG_COLOR,
    SUBTITLE_FONT_COLOR,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_MARGIN_BOTTOM,
    SUBTITLE_MAX_CHARS_PER_LINE,
    VIDEO_CODEC,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_PRESET,
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
    padding_y = 20
    bar_w = width
    bar_h = text_h + padding_y * 2

    img = Image.new("RGBA", (bar_w, bar_h), SUBTITLE_BG_COLOR)
    draw = ImageDraw.Draw(img)

    # テキスト中央配置
    x = (bar_w - text_w) // 2
    y = padding_y
    draw.multiline_text((x, y), wrapped, font=font, fill=SUBTITLE_FONT_COLOR, align="center")

    return np.array(img)


def _load_audio_as_clip(audio_path: Path, lead: float, total_duration: float) -> AudioArrayClip:
    """WAVを読み込み、前後を無音で埋めた総尺ぶんの音声クリップにする

    moviepyのconcatenate_videoclipsは各クリップの音声にset_start()を掛け直すため、
    クリップ側で付けた開始オフセットは失われ、映像より短い音声を終端超えで読んで
    IOErrorになる。音声を最初から総尺ぶんの配列にしておけばこの問題は起きない。

    Args:
        audio_path: 読み込むWAV
        lead: 先頭に入れる無音の秒数
        total_duration: 生成するクリップの総尺（秒）
    """
    with wave.open(str(audio_path), "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())

    if sample_width != 2:
        raise ValueError(f"想定外のWAV量子化ビット数: {sample_width * 8}bit（16bitのみ対応）")

    # int16 → -1.0〜1.0 のfloatへ
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    samples = samples.reshape(-1, channels)
    if channels == 1:
        samples = np.repeat(samples, 2, axis=1)  # ステレオ化
    elif channels > 2:
        samples = samples[:, :2]

    total_frames = int(round(total_duration * rate))
    lead_frames = int(round(lead * rate))

    buffer = np.zeros((total_frames, 2), dtype=np.float32)
    end = min(lead_frames + samples.shape[0], total_frames)
    buffer[lead_frames:end] = samples[: end - lead_frames]

    return AudioArrayClip(buffer, fps=rate)


def _load_background(image_path: Path) -> Image.Image:
    """シーン画像を動画サイズに合わせて読み込む（シーンにつき1回だけ）"""
    return Image.open(image_path).convert("RGB").resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)


def _render_frame(
    background: Image.Image,
    subtitle_text: str,
    font_path: str | None = None,
) -> np.ndarray:
    """背景に字幕を焼き込んだ1枚の完成フレームを作る

    絵は字幕が変わる間も動かないので、フレームは字幕1枚につき1枚作れば足りる。
    moviepyのCompositeVideoClipに任せると同じ絵を毎フレーム合成し直して
    エンコードが十数倍遅くなるため、ここで焼き込んでしまう。
    """
    frame = background.copy()

    subtitle = Image.fromarray(_create_subtitle_frame(subtitle_text, font_path=font_path), "RGBA")
    y = VIDEO_HEIGHT - subtitle.height - SUBTITLE_MARGIN_BOTTOM
    frame.paste(subtitle, (0, y), subtitle)  # RGBAをマスクにして半透明合成

    return np.array(frame)


def create_scene_clips(
    image_path: Path,
    segments: list[dict],
    font_path: str | None = None,
    padding: float = 0.3,
) -> list[ImageClip]:
    """1シーン分のクリップ列を生成する

    同じ絵の上で字幕だけが切り替わるので、字幕1枚 = 静止画クリップ1つ。
    尺はその字幕の音声の実尺そのものなので、字幕と声がズレない。
    シーンの前後にだけ無音の余白を入れる（字幕ごとに空けると間延びするため）。
    """
    background = _load_background(image_path)
    clips = []
    last = len(segments) - 1

    for i, seg in enumerate(segments):
        lead = padding if i == 0 else 0.0
        trail = padding if i == last else 0.0
        total_duration = seg["duration"] + lead + trail

        frame = _render_frame(background, seg["text"], font_path=font_path)
        audio_clip = _load_audio_as_clip(
            seg["path"], lead=lead, total_duration=total_duration
        )
        clips.append(ImageClip(frame).set_duration(total_duration).set_audio(audio_clip))

    return clips


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

    # シーンクリップ作成（字幕1枚につき静止画1つ）
    clips = []
    audio_map = {r["scene_id"]: r for r in audio_results}
    skipped = []

    for scene in scenes:
        scene_id = scene["id"]
        image_path = images_dir / f"scene_{scene_id:03d}.png"
        audio_info = audio_map.get(scene_id)

        if not image_path.exists():
            skipped.append(f"scene_{scene_id:03d}(画像なし)")
            continue
        if not audio_info or not audio_info.get("segments"):
            skipped.append(f"scene_{scene_id:03d}(音声なし)")
            continue

        clips.extend(
            create_scene_clips(
                image_path=image_path,
                segments=audio_info["segments"],
                font_path=font_path,
            )
        )

    if skipped:
        # 黙って飛ばすと歯抜けの動画が完成品として出てしまう
        logger.warning(f"素材が欠けたシーンを飛ばしました（{len(skipped)}件）: {skipped[:5]}")

    if not clips:
        raise ValueError("有効なシーンクリップがありません")

    # 全シーン結合（全クリップが同サイズなのでchainで十分。composeより速い）
    logger.info(f"シーン結合中: {len(clips)}クリップ")
    final = concatenate_videoclips(clips, method="chain")

    # BGM追加
    if bgm_path and bgm_path.exists():
        logger.info("BGM追加中...")
        bgm = AudioFileClip(str(bgm_path))
        # BGMをループして動画の長さに合わせる
        if bgm.duration < final.duration:
            loops = int(final.duration / bgm.duration) + 1
            bgm = concatenate_audioclips([bgm] * loops)
        # 終端ぴったりだとreaderが末尾を読み越してIOErrorになるため僅かに短く切る
        bgm = bgm.subclip(0, max(0, final.duration - 0.1)).volumex(BGM_VOLUME)

        # ナレーション + BGM をミックス
        from moviepy.audio.AudioClip import CompositeAudioClip
        mixed_audio = CompositeAudioClip([final.audio, bgm])
        final = final.set_audio(mixed_audio)

    # 書き出し
    duration_min = final.duration / 60
    logger.info(f"エンコード開始: {output_path}（{duration_min:.1f}分）")
    final.write_videofile(
        str(output_path),
        fps=VIDEO_FPS,
        codec=VIDEO_CODEC,
        preset=VIDEO_PRESET,
        audio_codec=AUDIO_CODEC,
        audio_bitrate=AUDIO_BITRATE,
        audio_fps=AUDIO_SAMPLE_RATE,
        threads=os.cpu_count() or 4,
        logger=None,
    )

    # リソース解放
    final.close()
    for clip in clips:
        clip.close()

    logger.info(f"動画合成完了: {output_path} ({duration_min:.1f}分)")
    return output_path
