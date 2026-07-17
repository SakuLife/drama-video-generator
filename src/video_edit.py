"""ステージ4: moviepyによる動画合成"""

import logging
import os
import wave
from pathlib import Path

import numpy as np
from moviepy.audio.AudioClip import AudioArrayClip
from moviepy.editor import (
    AudioFileClip,
    VideoClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

# moviepy 1.0.3 のresizeは Image.ANTIALIAS を使うが、Pillow 10+ で削除された。
# ズーム(Ken Burns)でmoviepyのresizeを通るため、後方互換のエイリアスを補う。
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from config.settings import (
    AUDIO_BITRATE,
    AUDIO_CODEC,
    AUDIO_SAMPLE_RATE,
    BGM_VOLUME,
    KEN_BURNS_ZOOM,
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


def _load_scene_audio(segments: list[dict], front_pad: float, back_pad: float) -> AudioArrayClip:
    """シーンの全字幕の音声を、前後の無音paddingごと1本のクリップにまとめる

    字幕ごとにファイルを読んで無音を挟みながら連結する。moviepyの音声連結は
    終端読み越しでIOErrorになるので、numpy配列を直接組み立てる（_load_audio_as_clip
    と同じ理由）。
    """
    rate = AUDIO_SAMPLE_RATE
    parts: list[np.ndarray] = [np.zeros((int(round(front_pad * rate)), 2), dtype=np.float32)]

    for seg in segments:
        with wave.open(str(seg["path"]), "rb") as wf:
            if wf.getframerate() != rate:
                raise ValueError(f"音声レートが想定外: {wf.getframerate()} != {rate}")
            channels = wf.getnchannels()
            raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        samples = samples.reshape(-1, channels)
        if channels == 1:
            samples = np.repeat(samples, 2, axis=1)
        elif channels > 2:
            samples = samples[:, :2]
        parts.append(samples)

    parts.append(np.zeros((int(round(back_pad * rate)), 2), dtype=np.float32))
    return AudioArrayClip(np.concatenate(parts, axis=0), fps=rate)


def _load_background(image_path: Path) -> np.ndarray:
    """シーン画像を動画サイズに合わせて読み込む（シーンにつき1回だけ）"""
    img = Image.open(image_path).convert("RGB").resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
    return np.array(img)


# パン方向のプリセット（シーンごとに切替。開始→終了の位置を、余白に対する割合で表す）
_PAN_PRESETS = [
    ((0.0, 0.0), (1.0, 1.0)),  # 左上 → 右下
    ((1.0, 0.0), (0.0, 1.0)),  # 右上 → 左下
    ((0.0, 1.0), (1.0, 0.0)),  # 左下 → 右上
    ((1.0, 1.0), (0.0, 0.0)),  # 右下 → 左上
]


def _prepare_subtitle(text: str, font_path: str | None) -> dict:
    """字幕を1枚ぶん、合成に使う形（RGB・アルファ・貼付y座標）に前処理する"""
    frame = _create_subtitle_frame(text, font_path=font_path)  # (h, W, 4) uint8
    return {
        "rgb": frame[..., :3].astype(np.float32),
        "alpha": (frame[..., 3:4].astype(np.float32)) / 255.0,
        "y": VIDEO_HEIGHT - frame.shape[0] - SUBTITLE_MARGIN_BOTTOM,
        "h": frame.shape[0],
    }


def create_scene_clip(
    image_path: Path,
    segments: list[dict],
    scene_index: int,
    font_path: str | None = None,
    padding: float = 0.3,
):
    """1シーン分のクリップを生成する（背景をゆっくりパン＋字幕オーバーレイ）

    リサイズは重い（moviepyのズームは全画面を毎フレーム再サンプルするので30分で数時間）。
    そこで少し大きい画像を1回だけ作り、そこから切り取る窓をゆっくり動かす＝パンにする。
    毎フレームの処理は配列スライス＋字幕領域のα合成だけなので軽い。
    字幕は画面下部の固定位置で、背景が動いても字幕は動かない。
    """
    scene_duration = padding * 2 + sum(s["duration"] for s in segments)

    # 各字幕の表示時間帯を確定（先頭の無音paddingぶんずらして開始）
    subs = []
    cursor = padding
    for seg in segments:
        info = _prepare_subtitle(seg["text"], font_path)
        info["start"] = cursor
        info["end"] = cursor + seg["duration"]
        subs.append(info)
        cursor += seg["duration"]

    audio_clip = _load_scene_audio(segments, front_pad=padding, back_pad=padding)

    if KEN_BURNS_ZOOM <= 0:
        # 動き無し：字幕を焼き込んだ静止画を並べる（最速）
        return _static_scene_clip(image_path, subs, scene_duration, audio_clip)

    # 背景を少し大きく作り（この1回だけリサイズ）、切り取り窓を動かす
    amount = KEN_BURNS_ZOOM
    big_w, big_h = int(VIDEO_WIDTH * (1 + amount)), int(VIDEO_HEIGHT * (1 + amount))
    big = np.asarray(
        Image.open(image_path).convert("RGB").resize((big_w, big_h), Image.LANCZOS),
        dtype=np.uint8,
    )
    margin_x, margin_y = big_w - VIDEO_WIDTH, big_h - VIDEO_HEIGHT
    (sx, sy), (ex, ey) = _PAN_PRESETS[scene_index % len(_PAN_PRESETS)]

    def make_frame(t: float) -> np.ndarray:
        p = min(1.0, t / scene_duration) if scene_duration > 0 else 1.0
        ox = int(round((sx + (ex - sx) * p) * margin_x))
        oy = int(round((sy + (ey - sy) * p) * margin_y))
        frame = big[oy : oy + VIDEO_HEIGHT, ox : ox + VIDEO_WIDTH].astype(np.float32)

        for s in subs:
            if s["start"] <= t < s["end"]:
                y, h = s["y"], s["h"]
                region = frame[y : y + h]
                frame[y : y + h] = region * (1 - s["alpha"]) + s["rgb"] * s["alpha"]
                break

        return frame.astype(np.uint8)

    return VideoClip(make_frame, duration=scene_duration).set_audio(audio_clip)


def _static_scene_clip(image_path: Path, subs: list[dict], scene_duration: float, audio_clip):
    """動き無しのシーンクリップ（字幕を焼き込んだ静止画をつなぐ）"""
    background = _load_background(image_path)

    def make_frame(t: float) -> np.ndarray:
        frame = background.astype(np.float32)
        for s in subs:
            if s["start"] <= t < s["end"]:
                y, h = s["y"], s["h"]
                frame = frame.copy()
                frame[y : y + h] = frame[y : y + h] * (1 - s["alpha"]) + s["rgb"] * s["alpha"]
                break
        return frame.astype(np.uint8)

    return VideoClip(make_frame, duration=scene_duration).set_audio(audio_clip)


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

    # シーンクリップ作成（1シーン＝背景ズーム＋字幕オーバーレイの合成1つ）
    clips = []
    audio_map = {r["scene_id"]: r for r in audio_results}
    skipped = []

    for i, scene in enumerate(scenes):
        scene_id = scene["id"]
        image_path = images_dir / f"scene_{scene_id:03d}.png"
        audio_info = audio_map.get(scene_id)

        if not image_path.exists():
            skipped.append(f"scene_{scene_id:03d}(画像なし)")
            continue
        if not audio_info or not audio_info.get("segments"):
            skipped.append(f"scene_{scene_id:03d}(音声なし)")
            continue

        clips.append(
            create_scene_clip(
                image_path=image_path,
                segments=audio_info["segments"],
                scene_index=i,
                font_path=font_path,
            )
        )

    if skipped:
        # 黙って飛ばすと歯抜けの動画が完成品として出てしまう
        logger.warning(f"素材が欠けたシーンを飛ばしました（{len(skipped)}件）: {skipped[:5]}")

    if not clips:
        raise ValueError("有効なシーンクリップがありません")

    # 全シーン結合（各シーンとも同サイズのフレームを返すのでchainで十分・速い）
    logger.info(f"シーン結合中: {len(clips)}シーン")
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
