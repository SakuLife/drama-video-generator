"""サムネイル自動生成"""

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# サムネイル設定
THUMB_WIDTH = 1280
THUMB_HEIGHT = 720


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """太字の日本語フォントを取得"""
    for fp in [
        "C:/Windows/Fonts/meiryob.ttc",  # メイリオ太字
        "C:/Windows/Fonts/YuGothB.ttc",  # 游ゴシック太字
        "C:/Windows/Fonts/msgothic.ttc",
    ]:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def generate_thumbnail(
    scene_image_path: Path,
    text: str,
    output_path: Path,
) -> Path:
    """シーン画像 + テキストでサムネイルを生成"""
    # ベース画像（最初のシーン画像を使用）
    base = Image.open(scene_image_path).convert("RGB")
    base = base.resize((THUMB_WIDTH, THUMB_HEIGHT), Image.LANCZOS)

    # 暗めのオーバーレイ（テキストを読みやすく）
    overlay = Image.new("RGBA", (THUMB_WIDTH, THUMB_HEIGHT), (0, 0, 0, 100))
    base = Image.alpha_composite(base.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(base)

    # テキスト描画（縁取り付き）
    font = _get_font(72)

    # テキスト折り返し（8文字で改行）
    lines = []
    while len(text) > 8:
        lines.append(text[:8])
        text = text[8:]
    if text:
        lines.append(text)
    display_text = "\n".join(lines)

    # テキスト位置（中央）
    bbox = draw.multiline_textbbox((0, 0), display_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (THUMB_WIDTH - text_w) // 2
    y = (THUMB_HEIGHT - text_h) // 2

    # 縁取り（黒）
    outline_width = 4
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx * dx + dy * dy <= outline_width * outline_width:
                draw.multiline_text(
                    (x + dx, y + dy), display_text, font=font, fill="black", align="center"
                )

    # 本文（白 or 黄色）
    draw.multiline_text((x, y), display_text, font=font, fill=(255, 255, 0), align="center")

    # 保存
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(str(output_path), quality=95)
    logger.info(f"サムネイル生成: {output_path}")
    return output_path
