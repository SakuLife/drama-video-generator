# drama-video-generator

## 概要
AI生成画像 + VOICEVOX ナレーションによる**約13分**のドラマ動画を完全自動生成し、YouTubeに毎日投稿するシステム。
🔴 **2026-10-01 に30分→約13分へ短縮**（社長判断）。電話番号未確認のチャンネルは15分超を上げられない（28分版が「長すぎる動画」で弾かれた）。確認すれば `config/settings.py` の `TARGET_SCENES`（28→70）と `MAX_UPLOAD_SEC` を上げて30分に戻せる。1本の費用と時間も約半分になる。

## 参考チャンネル
- 人生はドラマ（@人生はドラマ-001）: 平均44.7万再生、30分前後の逆転劇ドラマ

## パイプライン
1. **台本生成** (`src/script_gen.py`) → Gemini API で28シーン（`TARGET_SCENES`）のドラマ台本をJSON生成
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

# 動作確認（少シーンで一周。本番28シーンでもクレジットと時間を食う）
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
YT_CLIENT_ID=          # 中央 .env に設定済み（2026-09-27・1番と共用）
YT_CLIENT_SECRET=      # 同上
YT_REFRESH_TOKEN=      # 設定済み（2026-09-29・「AIショートドラマ」）。チャンネル固有なのでローカル.envに置く
```

## 🔴 いまの状態（2026-09-29）＝稼働。毎日19:30に1本作り、翌18:00に「AIショートドラマ」へ予約投稿

- 投稿先＝**「AIショートドラマ」`@ai---short---dramaa`**（id=`UCHNn33QhtCIUdVBvYOzITHw`・長尺アップロード可＝`eligible`）。
  鍵は `.env` の `YT_REFRESH_TOKEN`（2026-09-29 発行）。クライアントは4番の `client_secret_1051884138240-…json` を1番と共用
- **止めたいとき＝`.env` の `YT_REFRESH_TOKEN` を空にする**（`require_env.py` が弾いて何もせず正常終了する）
- 鍵の作り直し: `.venv/Scripts/python.exe ../_shared/secrets/mint_youtube_token.py --target 3_drama --client-secrets ../4_youtube-data-factory/secrets/client_secret_1051884138240-av2d1a3e507cb6sm2l7sdit1sivu94em.apps.googleusercontent.com.json`
  - 🔴 **鍵は「許可したときに選んだチャンネル」に紐づく**。同じGoogleアカウントに漢字クイズ・LINEチャットがあるので、
    同意画面でドラマ用を選ぶ。最後に「この鍵の投稿先チャンネル」が出る＝違えば空にしてやり直す
  - ⚠ Claude Code の `!` は Git Bash で動く＝パス区切りは `/`（`\` は消えて `command not found` になる）
- 投稿は `private`＋`publishAt`（18:00 JST・過ぎていれば翌日）＋**`containsSyntheticMedia: True`**
  （実写風のAI人物＝YouTubeの「改変・合成コンテンツ」の申告対象。2026-09-29 追加）
- ⚠ 1日の上限は1プロジェクト10,000ユニット・投稿1本1,600。1番と共用で1日2本＝3,200
- 🔴 **電話番号の確認（`youtube.com/verify`）前のチャンネルは15分超を上げられない**。2026-09-29 の本番1本目（28分）は`videos.insert` が ID を返したのに Studio で「アップロード失敗: 長すぎる動画」になり、ログと Discord は「投稿完了」だった。`channels.list` の `status.longUploadsStatus` は **`eligible` を返していた＝当てにならない**。→ 投稿後に `wait_until_accepted()`（`src/youtube_uploader.py`）で `uploadStatus` を見て、弾かれたら失敗として Discord に出す（2026-09-30）
- ⚠ カスタムサムネも電話番号の確認前だと403で付かない（失敗しても投稿は止まらない）
- 1本の実測（2026-09-25・`generated/check_0925/`）: 28.5分・台本1分＋画像49分＋音声24分＋合成23分＝**約1時間40分**。
  KIEAI 画像70枚＝1本あたり約100〜210円（一覧価格からの見積り・実額は未確認）。**↑は30分版の数字**。短縮版の実測（2026-10-01・`generated/20261001_first12/`・30シーン）: **14.1分・全体48分**（台本1分＋画像16分＋音声16分＋合成13分＋投稿2分）。上限まで35秒しか無かったので28シーンに減らした。`containsSyntheticMedia` は videos.list の返事に出てこない＝**反映は未確認**（Studio で見る）
- 🔴 **投稿前に尺を検査して15分近くを超えたら投稿しない**（`verify_video` の `MAX_UPLOAD_SEC`＝14分40秒）。送っても弾かれるだけ
- 🔴 **タスクの最大実行時間は5時間**（`07_tasks.ps1` の `TimeLimitHours = 5`）。2026-09-29 の本番1本目は **2時間34分**（画像だけで1時間41分）かかり、既定の2時間で 21:30 に wscript が打ち切られていた（結果 267014）。Python は生き残って投稿まで済んだが運任せ＝2026-09-30 に延ばした

## チャンネルの見た目（2026-10-02 Studio で設定）
- 表の名前は **「ほろり劇場」**＝アイコン・バナー・説明文・ハンドル `@horori_gekijo` は設定済み。
  ⚠ **チャンネル名だけ「AIショートドラマ」のまま**（名前は14日に2回まで。最初の保存が失敗扱いで枠を使い、
  2026-10-16 ごろまで変えられない）→ その日以降に Studio で「ほろり劇場｜泣ける逆転ドラマ」へ
- 素材＝`assets/channel/`（`icon.html`/`banner.html` を Edge `--headless --screenshot` でPNG化・説明文 `description.txt`）。
  アイコン・説明文は API では変えられない（今の鍵のスコープ外）＝Studio を Chrome 拡張で操作した

## 再生数を見ながら試す（社長指示 2026-10-02「再生数見て色々テストしながら試してみて」）
- **ナレーションの声を日替わり**（`src/experiment.py` の `VOICE_VARIANTS`）。🔴 **2026-10-06 から四国めたんだけ**。
  VOICEVOX の規約はキャラごとに違う（エンジンの `/speaker_info` の `policy` で読める）＝**声を足す前に必ず読む**。
  青山龍星＝「企業が携わる形で使う場合はななはぴに事前確認」／No.7＝「配信収入以外の商用は No.7製作委員会に事前確認」
  ＝収益化を目指す SakuLife の運用が当たるか判断できず外した（`RETIRED_VOICES`。確認が取れたら戻す）。
  四国めたんはクレジット表記だけで商用可。青山龍星で出た1本（`yu2cDjrtmBY`・10/04公開）は**社長判断で公開のまま**（2026-10-06・本社経由）。
  ⚠ No.7 は読みが遅く、28シーンで15.9分になり投稿前検査で止まった（10/05・投稿なし）
  その日の条件は `generated/<日付>/variant.json` に保存＝途中再開しても声が混ざらない。説明欄の末尾に
  フィクションの断り＋`VOICEVOX:キャラ名`（利用規約で必須）を自動で付ける
- 投稿ごとに `data/uploads.jsonl`（何を試したか）、毎日 `scripts/collect_stats.py` が `data/stats.jsonl`（再生数）、
  月曜に `scripts/analyze.py --notify` が `reports/analysis_*.md`＋Discord。**1条件5本未満の比較は「参考」**
- ⚠ 視聴維持率（YouTube Analytics API）は **GCP プロジェクト `1051884138240` で API が無効**＝403。
  有効化（コンソールでボタン1つ）は社長の作業。それまでは再生数だけ記録する
- `run_daily.bat`: **1日1本の当日ガード**（`main.py --upload` は今日投稿済みなら exit 9・追加は `--force`）／
  失敗したら1回だけ再実行（生成済みの画像・音声は使い回す。2026-09-30 画像3枚失敗・10-01 MemoryError で2日落ちた）

## 🔴 読み間違いゼロの仕組み（社長指示 2026-10-07「読み方完璧」・本社の共通部品 `_shared/skills/voicevox/reading_check.py`）
- **2026-10-08 から本番に組み込み**。字幕は漢字のまま、**VOICEVOX には かなだけ渡す**（`main.py` 音声ステージ→`src/reading.py` の `prepare_readings`）。
  1. 字幕1枚ずつ claude -p にかなを書かせる（`readings.json`）
  2. 漢字のまま読ませた音と食い違う行だけ、別の claude -p が正しい読みを判定（＝台本のかな自体の誤りの手当て）
  3. かなで VOICEVOX に読ませて1音ずつ突き合わせ（`reading_check.txt` に全件）→ ズレた行は書き方を変えさせて再検査
  4. ズレ0件の読みだけ `readings_ok.json` に保存し、音声はこれで作る
- かなの決まり（版2）: 助詞は わ・え と書かせ、`kana_for_tts()` で は・へ を含む語をカタカナに（ひらがなの はは をエンジンが ワワ と読む）
- 🔴 **漢字のまま出すことはしない**（本社決定 2026-10-08）。claude -p の上限などで読みが作れない回は
  `readings_pending.json` を残して終了コード7 → タスク `drama_reading_retry`（02:00 から3時間ごと・`run_reading_retry.bat`）が続きから作って投稿。
  **16時を過ぎても揃わなければ、その回は作らず Discord に1行**
- 1日1本のガードは「次の公開枠（publish_at）が埋まっているか」で判定（`slot_filled`）。夜中の再試行で投稿すると
  uploaded_at が翌日になり、旧方式（今日投稿したか）だと翌日の本番が誤って止まるため
- 試験＝`tools/check_readings.py generated/<日付>`。旧方式（漢字のまま）は2本で計60行が誤読候補だった
  （鷹山→ヨウザン・聖央→ヒジリヒサシ・一目→イチモク・中から→チュウカラ・黄金色→オオゴンショク・白日の下→シタ 等）

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
- **尺は「文字数 ÷ 6.36文字/秒」で決まる**（speed=1.05＋文末の間0.4秒での実測・2026-10-01: 5,263字→音声13.8分。旧値6.96は speed=1.1・間なしの頃）。**15分＝約5,700文字**。1シーン約0.47分＝`MINUTES_PER_SCENE`
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
- **字幕は簡易禁則つきで折り返す**（`_wrap_text`）。単純に22字で切ると行頭に「、」「」」が来る
  （2026-09-25 の30分版で336文中31文）。行頭禁則の文字は前の行へ最大3字はみ出して入れる。
- **実行中にコードや設定を編集しない**。ステージが遅延importなので、走行中のプロセスが
  古い設定モジュールと新しいコードを掴んでImportErrorで落ちる（1本無駄にした）。


## 18番からの申し送り（2026-09-18）：BGM を KIE×Suno から Google Lyria 3.5 に替えられるか小口実測

**→ 2026-09-25 実測済み・採用（結果は上の「BGM」節）。**

- Suno に公式 API は無い（KIE は非公式ラッパー＝規約変更・遮断リスク常在）。Google が Gemini API 内で **Lyria 3.5（フルソング $0.08/曲・無料枠なし）** を出した。料金は 18番が公式 pricing（`ai.google.dev/gemini-api/docs/pricing`）で確認済み。
- やること：既存の Gemini キーで **1曲だけ**生成し、①音質 ②尺・ループ性 ③商用利用条件（規約を読む）④実際の課金額 を `llm_usage.jsonl` と CLAUDE.md に記録。合格なら `src/` の BGM 生成を Lyria に切替（KIE は画像用に残してよい）。
- API 従量だが本社ルールの例外②（Claude にできない仕事）に該当。理由をこの行に残す。
