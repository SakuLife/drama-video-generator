# drama-video-generator

## 概要
AI生成画像 + VOICEVOX ナレーションによる30分ドラマ動画を完全自動生成し、YouTubeに毎日投稿するシステム。

## 参考チャンネル
- 人生はドラマ（@人生はドラマ-001）: 平均44.7万再生、30分前後の逆転劇ドラマ

## パイプライン
1. **台本生成** (`src/1_script_gen.py`) → Gemini API で70シーン前後のドラマ台本をJSON生成
2. **画像生成** (`src/2_image_gen.py`) → Nano Banana (KIEAI) でシーンごとにリアル調AI画像生成
3. **音声生成** (`src/3_voice_gen.py`) → VOICEVOX で女性アナウンサー声のナレーション
4. **動画合成** (`src/4_video_edit.py`) → moviepy で画像+音声+字幕を合成 (1920x1080)
5. **YouTube投稿** (`src/youtube_uploader.py`) → 18:00 JST に予約投稿

## 技術スタック
- Python 3.10+
- Gemini API (台本生成)
- KIEAI API (Nano Banana画像生成)
- VOICEVOX (音声合成, localhost:50021)
- moviepy + Pillow (動画合成)
- YouTube Data API v3 (アップロード)

## コマンド
```bash
# フルパイプライン実行
python main.py --auto

# テーマ指定
python main.py --theme "清掃員のおばあさんが実は大富豪だった" --auto

# テーマ提案のみ
python main.py --suggest-themes

# 特定ステージのみ
python main.py --theme "..." --stage script
python main.py --theme "..." --stage image
python main.py --theme "..." --stage voice
python main.py --theme "..." --stage video
python main.py --theme "..." --stage upload
```

## 環境変数
```
GEMINI_API_KEY=
KIEAI_API_KEY=
VOICEVOX_URL=http://localhost:50021
YT_CLIENT_ID=
YT_CLIENT_SECRET=
YT_REFRESH_TOKEN=
DISCORD_WEBHOOK_URL=  # オプション
```
