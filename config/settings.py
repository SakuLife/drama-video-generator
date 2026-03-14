"""プロジェクト全体の設定"""

from pathlib import Path

# === パス ===
PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BGM_DIR = ASSETS_DIR / "bgm"
GENERATED_DIR = PROJECT_ROOT / "generated"
LOGS_DIR = PROJECT_ROOT / "logs"

# === 動画設定 ===
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"

# === 字幕設定 ===
SUBTITLE_FONT_SIZE = 48
SUBTITLE_FONT_COLOR = "white"
SUBTITLE_BG_COLOR = (0, 0, 0, 180)  # 半透明黒
SUBTITLE_MARGIN_BOTTOM = 60
SUBTITLE_MAX_CHARS_PER_LINE = 22  # 1行あたりの最大文字数

# === 台本設定 ===
TARGET_SCENES = 70  # 目標シーン数（30分 ≈ 70シーン × 25秒）
SCENE_DURATION_SEC = 25  # シーンあたりの平均秒数

# === 画像生成設定 ===
IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080
IMAGE_STYLE = "photorealistic Japanese drama scene"

# === 音声設定 ===
VOICEVOX_URL = "http://localhost:50021"
VOICEVOX_SPEAKER_ID = 2  # 四国めたん（ノーマル）- 女性アナウンサー風
VOICEVOX_SPEED = 1.1  # やや早め（ドラマナレーション風）

# === BGM設定 ===
BGM_VOLUME = 0.08  # BGM音量（ナレーション比）

# === YouTube設定 ===
YT_CATEGORY_ID = "24"  # Entertainment
YT_DEFAULT_TAGS = [
    "ドラマ", "スカッと", "感動", "逆転劇",
    "人生", "ストーリー", "泣ける話", "いい話",
]
YT_PUBLISH_HOUR_JST = 18  # 18:00 JST に公開
YT_MADE_FOR_KIDS = False

# === ドラマジャンル ===
DRAMA_GENRES = [
    "ビジネス逆転劇",
    "貧乏人が実は大富豪",
    "見下された人の逆襲",
    "善意が返ってくる話",
    "隠れた才能が開花",
    "家族の絆・再会",
    "いじめっ子への逆転",
    "海外での日本人活躍",
]
