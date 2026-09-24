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

## 残作業（社長の手が要るもの・2026-09-25時点）
投稿以外は全ステージ実測で動作確認済み。**残りは YouTube の鍵だけ**（ブラウザ操作が要る）。

1. **YouTube投稿の鍵**（これが無いと投稿できない。1番のLINE動画も同じく未設定）
   - ⚠ 2026-09-25 時点で `YT_CLIENT_ID` / `YT_CLIENT_SECRET`（中央 .env）も空＝クライアントIDから作る
   - **GCPプロジェクトは「新AutoSystem」**（GEMINI_API_KEYを発行した方）。
     親CLAUDE.mdの `1051884138240` はDrive/Sheets用なので取り違えないこと
   - YouTube Data API v3を有効化 → OAuth同意画面を「公開(本番)」に
     （テスト状態だとrefresh_tokenが7日で失効し毎週止まる）
   - OAuthクライアントID（デスクトップアプリ）を作成しjsonをDL
   - `.venv\Scripts\python.exe ../_shared/secrets/mint_youtube_token.py --target 3_drama --client-secrets <json>`
2. 鍵を入れる前に `--upload` 無しで30分版を1本作って中身を確認 → 良ければ鍵を入れる
   （入れた翌日から `drama_daily` が毎日19:30に作って翌日18:00に予約投稿する）

**自動実行はタスクスケジューラ `drama_daily`（`run_daily.bat`）に決定**（2026-09-23）。
旧案の GitHub Actions（`.github/workflows/daily-drama.yml`・self-hostedランナー）は使わない。
`run_daily.bat` は `.venv` の Python を使う＝**venv の依存がズレると毎日黙って落ちる**（下の moviepy 参照）。

## BGM（2026-09-25 Lyria 3.5 で実測・採用）
- `assets/bgm/` の最初の mp3/wav をループして `BGM_VOLUME`(0.08) で敷く。それまで空フォルダ＝**BGM無しで作っていた**。
- 1曲目 `drama_piano_lyria35.mp3`（ピアノ＋弦・70BPM・2分54秒・192kbps/44.1kHz stereo・34秒で生成）を
  `python tools/make_bgm_lyria.py` で作成。**mp3は .gitignore 対象**＝別PCでは同じコマンドで作り直す（毎回曲は変わる）。
- 実測: 1.2分の試作（7/16の素材を流用・課金ゼロ）で、文末の「間」も無音にならず BGM で埋まる（-45dB以下0.3秒超の無音=0箇所）。
  末尾が約3秒フェードアウトするので、ループ継ぎ目で一瞬静かになる（音で気になれば曲を差し替える）。
- 料金: 一覧価格 $0.08/曲（18番が公式 pricing で確認）。**実際の請求額は GCP の請求画面でしか見えず未確認**。
  usage は `llm_usage.jsonl` に記録（input 80 / output 1,492 tokens）。
- 商用: Gemini API 利用規約（`ai.google.dev/gemini-api/terms`）は「生成物の所有権を Google は主張しない」。
  音楽特有の制限は規約に無い。全曲に SynthID 透かし入り＝YouTube 投稿時は「AI生成コンテンツを含む」を申告する前提。
- Suno（KIE経由・非公式）は使っていない（`src/` に Suno の実装は元々無かった）。

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
- **KIEAIはタスクが固まることがある**（70枚に1枚程度）。共有クライアントの既定 max_wait=600秒を
  そのまま使うと1枚に10分ぶら下がるので、`IMAGE_MAX_WAIT`(150秒)を渡している。
  失敗しても残りは作り切り、再実行で失敗分だけ焼き直す設計。
- **venv の moviepy は 1.0.3 に固定**（`requirements.txt`）。2026-09-23 に作った `.venv` に 2.2.1 が入り、
  `moviepy.editor` が無くて**動画合成が必ず落ちる状態**だった（鍵を入れた日から毎日失敗していた）。2026-09-25 に直した。
  システムの `py -3.11` は 1.0.3 なので手動実行では気づけない＝**確認は必ず `.venv\Scripts\python.exe` で**。
- **実行中にコードや設定を編集しない**。ステージが遅延importなので、走行中のプロセスが
  古い設定モジュールと新しいコードを掴んでImportErrorで落ちる（1本無駄にした）。


## 18番からの申し送り（2026-09-18）：BGM を KIE×Suno から Google Lyria 3.5 に替えられるか小口実測

**→ 2026-09-25 実測済み・採用（結果は上の「BGM」節）。**

- Suno に公式 API は無い（KIE は非公式ラッパー＝規約変更・遮断リスク常在）。Google が Gemini API 内で **Lyria 3.5（フルソング $0.08/曲・無料枠なし）** を出した。料金は 18番が公式 pricing（`ai.google.dev/gemini-api/docs/pricing`）で確認済み。
- やること：既存の Gemini キーで **1曲だけ**生成し、①音質 ②尺・ループ性 ③商用利用条件（規約を読む）④実際の課金額 を `llm_usage.jsonl` と CLAUDE.md に記録。合格なら `src/` の BGM 生成を Lyria に切替（KIE は画像用に残してよい）。
- API 従量だが本社ルールの例外②（Claude にできない仕事）に該当。理由をこの行に残す。
