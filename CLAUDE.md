# drama-video-generator

## 概要
AI生成画像 + VOICEVOX ナレーションによる30分ドラマ動画を完全自動生成し、YouTubeに毎日投稿するシステム。

## 参考チャンネル
- 人生はドラマ（@人生はドラマ-001）: 平均44.7万再生、30分前後の逆転劇ドラマ

## パイプライン
1. **台本生成** (`src/script_gen.py`) → Gemini API で70シーン前後のドラマ台本をJSON生成
2. **画像生成** (`src/image_gen.py`) → Nano Banana (KIEAI) でシーンごとにリアル調AI画像生成
3. **音声生成** (`src/voice_gen.py`) → VOICEVOX で女性アナウンサー声のナレーション（未起動なら自動起動）
4. **動画合成** (`src/video_edit.py`) → 字幕を焼き込んだ静止画＋音声を moviepy で結合 (1920x1080)
5. **YouTube投稿** (`src/youtube_uploader.py`) → 18:00 JST に予約投稿

各ステージは成果物を `generated/<日付>/` に保存し、**生成済みはスキップして再開できる**
（画像はクレジット消費するので作り直さない）。作り直したいときは該当ファイルを消す。

## 技術スタック
- Python 3.10+
- Gemini API (台本生成)
- KIEAI API (Nano Banana画像生成)
- VOICEVOX (音声合成, localhost:50021)
- moviepy + Pillow (動画合成)
- YouTube Data API v3 (アップロード)

## コマンド
```bash
# フルパイプライン実行（動画完成まで。投稿はしない）
python main.py --auto

# 投稿までやる（--upload を付けたときだけ投稿する。事故投稿防止）
python main.py --auto --upload

# テーマ指定
python main.py --theme "清掃員のおばあさんが実は大富豪だった"

# テーマ提案のみ
python main.py --suggest-themes

# 動作確認（少シーンで一周。本番70シーンはクレジットと時間を食う）
python main.py --theme "..." --scenes 4 --output-dir ./generated/test

# 特定ステージのみ（台本以降は --theme 不要。保存済みscript.jsonから再開する）
python main.py --theme "..." --stage script
python main.py --stage image
python main.py --stage voice
python main.py --stage video
python main.py --stage upload
```

## 環境変数
`GEMINI_API_KEY` `KIEAI_API_KEY` `VOICEVOX_URL` `DISCORD_WEBHOOK_URL` は
中央シークレット `_shared/secrets/.env` から自動継承される（ローカル`.env`が優先）。
```
YT_CLIENT_ID=          # ★未設定：投稿にはこの3つが要る
YT_CLIENT_SECRET=      #   発行: python ../_shared/secrets/mint_youtube_token.py --target 3_drama
YT_REFRESH_TOKEN=      #   YT_REFRESH_TOKENはチャンネル固有なのでローカル.envに置く
```

## 残作業（社長の手が要るもの・2026-07-16時点）
投稿以外は全ステージ実測で動作確認済み。残りは全てブラウザ操作が要るため未完了。

1. **YouTube投稿の鍵**（これが無いと投稿できない。1番のLINE動画も同じく未設定）
   - GCPでYouTube Data API v3を有効化 → OAuth同意画面を「公開(本番)」に
     （テスト状態だとrefresh_tokenが7日で失効し毎週止まる）
   - OAuthクライアントID（デスクトップアプリ）を作成しjsonをDL
   - `python ../_shared/secrets/mint_youtube_token.py --target 3_drama --client-secrets <json>`
2. **GitHub Actionsの自動実行**（毎日15:00実行→18:00予約投稿）
   - `gh auth login` … 現在トークンが失効（401）。Secrets登録もランナー登録もこれが起点
   - Secrets 6つを登録: `gh secret set GEMINI_API_KEY` 等
     （GEMINI / KIEAI / YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN / DISCORD_WEBHOOK_URL）
   - self-hostedランナーをこのPCに登録（VOICEVOXがlocalhost必須のため）。
     **サービスではなく対話セッションで起動**すること
3. 初回は `--upload` 無しで動画を確認 → 良ければ `--upload` を付ける

## 落とし穴（実測で踏んだもの・2026-07-16）
- **Geminiのモデル名は直書きしない**。`gemini-2.0-flash` も `2.5`系もこのキーでは提供終了(404)。
  `-latest` エイリアス（`config/settings.py` の `SCRIPT_MODEL`）を使う。
- **KIEAIは `api.kie.ai`**（`api.kieai.com` ではない）。API実装は `_shared/skills/kieai` が正で、
  自前で書かない。
- **字幕は画像に焼き込む**。moviepyのCompositeVideoClipに毎フレーム合成させると16倍遅くなり、
  30分動画で4時間コースになる。
- **音声はWAVを配列で読んで無音パディングごとクリップ化する**。`concatenate_videoclips` は
  各音声に `set_start()` を掛け直すため、映像より短い音声を終端超えで読んでIOErrorになる。
- **尺は「文字数 ÷ 6.96文字/秒」で決まる**（VOICEVOX speed=1.1の実測値）。30分＝約12,400文字。
  シーン数を増やすのではなく1シーンのナレーションを長くする（画像1枚=2クレジットのため）。
- **VOICEVOXはエンジン単体(vv-engine/run.exe)を使う**。GUI版はデスクトップセッションが必要。
  起動時は出力をDEVNULLに捨てること（繋いだままだと進捗バーで詰まって起動しない）。
- **ログはcp932で出る**。`Path(log).read_text(encoding='utf-8')` は文字化けする。
