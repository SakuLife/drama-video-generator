"""プロジェクト全体の設定"""

import os
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
# 中身は静止画のスライドショーで動きが無く、圧縮しやすい。
# 遅いpresetにしても画質はほぼ変わらず時間だけ延びるのでveryfast。
VIDEO_PRESET = "veryfast"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"

# === 字幕設定 ===
SUBTITLE_FONT_SIZE = 48
SUBTITLE_FONT_COLOR = "white"
SUBTITLE_BG_COLOR = (0, 0, 0, 180)  # 半透明黒
SUBTITLE_MARGIN_BOTTOM = 60
SUBTITLE_MAX_CHARS_PER_LINE = 22  # 1行あたりの最大文字数
# 字幕1枚あたりの上限。ナレーションは文単位で切るが、1文が長すぎると
# 行数が増えて画面を覆うため、これを超える文は読点でさらに分割する（22文字×3行想定）
SUBTITLE_MAX_CHARS_PER_SEGMENT = 66

# === 台本設定 ===
TARGET_SCENES = 70  # 目標シーン数（30分 ≈ 70シーン × 25秒）
SCENE_DURATION_SEC = 25  # シーンあたりの平均秒数

# 台本＝商品の中核なので品質重視のpro。テーマ出しは軽いのでflash。
# ※バージョン直書き（gemini-2.0-flash / 2.5系）は提供終了で404になった実績があるため、
#   自動で新版に追従する -latest エイリアスを使う（2026-07-15に疎通確認済み）。
SCRIPT_MODEL = "gemini-pro-latest"
THEME_MODEL = "gemini-flash-latest"
# JSONは途中で切れると壊れて復旧不能。上限は余裕を持たせる（70シーンで実測3万程度）
SCRIPT_MAX_OUTPUT_TOKENS = 65536
THEME_MAX_OUTPUT_TOKENS = 8192  # 未指定だと既定値で切れてJSONDecodeErrorになる

# === 画像生成設定（KIEAI / Nano Banana）===
# nano-banana     : 2クレジット/枚・~1MP。背景素材はこれで十分（70シーンで約140クレジット）
# nano-banana-pro : 8-16クレジット/枚・最大4K。高品質だが70シーンだとコストが跳ね上がる
IMAGE_MODEL = "nano-banana"
IMAGE_ASPECT_RATIO = "16:9"
IMAGE_RESOLUTION = "2K"  # pro指定時のみ有効（1K/2K/4K）
# 実測21秒/枚。共有クライアントの既定600秒は長すぎて、KIEAI側でタスクが固まると
# 1枚に10分×リトライ分ぶら下がる（実際に30分待たされて全体が落ちた）。
# 早めに見切って作り直した方が速い。
IMAGE_MAX_WAIT = 150  # 1タスクの待ち上限（秒）
IMAGE_POLL_INTERVAL = 5  # 完了確認の間隔（秒）
# 連続でこれだけ失敗したら打ち切る（クレジット切れ等、続けても無駄なとき）
IMAGE_MAX_CONSECUTIVE_FAILURES = 3
# 画風の指定は config/prompts.py 側で台本の image_prompt に埋め込ませている

# === 音声設定 ===
VOICEVOX_URL = "http://localhost:50021"
# 未起動なら自動起動する。別PCでは環境変数で上書きする。
# エンジン単体(run.exe)を優先＝GUI不要・画面セッション不要なので無人実行やCIで確実に動く。
# 見つからないときだけGUI版にフォールバックする。
VOICEVOX_ENGINE_PATH = os.getenv("VOICEVOX_ENGINE_PATH", r"D:\App\VOICEVOX\vv-engine\run.exe")
VOICEVOX_EXE_PATH = os.getenv("VOICEVOX_EXE_PATH", r"D:\App\VOICEVOX\VOICEVOX.exe")
VOICEVOX_BOOT_TIMEOUT = 120  # 起動待ちの上限（秒）
VOICEVOX_SPEAKER_ID = 2  # 四国めたん（ノーマル）- 女性アナウンサー風
VOICEVOX_SPEED = 1.1  # やや早め（ドラマナレーション風）
# VOICEVOXの既定は24kHz。動画の音声トラック(44.1kHz)と合わせておくと再変換が挟まらない
AUDIO_SAMPLE_RATE = 44100

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
