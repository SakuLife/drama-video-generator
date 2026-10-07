"""再生数を見ながら試すための仕組み（声の日替わり・投稿記録・説明欄のクレジット）

社長指示（2026-10-02）「再生数見て色々テストしながら試してみて」。
1本ごとに「何を変えたか」を data/uploads.jsonl に残し、scripts/collect_stats.py が
再生数・視聴維持率を data/stats.jsonl に貯め、scripts/analyze.py が条件ごとに比べる。

いま試しているのはナレーションの声（3種を日替わり）。比べたい条件を増やすときは
choose_variant() に足し、uploads.jsonl に1項目増やす（analyze.py は項目ごとに集計する）。
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
UPLOADS_LOG = DATA_DIR / "uploads.jsonl"

# ナレーションの声の候補（VOICEVOX）。credit は利用規約で必須の表記「VOICEVOX:キャラ名」
# 🔴 足す前に必ずその声の規約（エンジンの /speaker_info の policy）を読む。キャラごとに商用条件が違う。
# 2026-10-06: 青山龍星（企業が携わる利用は事前確認）と No.7（配信収入以外の商用は事前確認）を外した。
# 収益化を目指す SakuLife の運用が当たるか判断がつかないため。確認が取れたら RETIRED_VOICES から戻す。
VOICE_VARIANTS: list[dict] = [
    {"key": "metan", "speaker_id": 2, "label": "四国めたん（ノーマル）", "credit": "VOICEVOX:四国めたん"},
]
# 規約の確認待ちで外した声（分析の表示名にだけ使う。投稿には使わない）
RETIRED_VOICES: list[dict] = [
    {"key": "no7_yomikikase", "speaker_id": 31, "label": "No.7（読み聞かせ）", "credit": "VOICEVOX:No.7"},
    {"key": "ryusei_shittori", "speaker_id": 84, "label": "青山龍星（しっとり）", "credit": "VOICEVOX:青山龍星"},
]


def voice_for_day(day: date) -> dict:
    """日付で声を決める（同じ日に作り直しても同じ声になる＝途中再開で声が混ざらない）"""
    return VOICE_VARIANTS[day.toordinal() % len(VOICE_VARIANTS)]


def choose_variant(output_dir: Path) -> dict:
    """この回の条件を決めて output_dir/variant.json に保存する（既にあればそれを使う）

    途中のステージから再開したときに、最初の回と違う声で続きを作らないための保存。
    """
    path = output_dir / "variant.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    voice = voice_for_day(datetime.now(JST).date())
    variant = {"voice": voice["key"], "speaker_id": voice["speaker_id"], "credit": voice["credit"]}
    path.write_text(json.dumps(variant, ensure_ascii=False, indent=2), encoding="utf-8")
    return variant


def description_with_credits(description: str, variant: dict) -> str:
    """動画の説明欄の末尾に、フィクションの断りと素材のクレジットを付ける"""
    footer = (
        "\n\n※この物語はフィクションです。登場する人物・団体・出来事は実在のものとは関係ありません。\n"
        f"映像：AI生成画像 ／ ナレーション：{variant['credit']}"
    )
    return (description or "").rstrip() + footer


def record_upload(result: dict, script: dict, variant: dict, output_dir: Path, duration_sec: float) -> None:
    """投稿した1本の条件を data/uploads.jsonl に1行追記する（分析の母数）"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "video_id": result["video_id"],
        "url": result["url"],
        "title": script.get("title", ""),
        "theme": script.get("theme", ""),
        "scenes": len(script.get("scenes", [])),
        "duration_sec": round(duration_sec, 1),
        "voice": variant.get("voice"),
        "publish_at": result.get("publish_at"),
        "output_dir": output_dir.name,
        "uploaded_at": datetime.now(JST).isoformat(timespec="seconds"),
    }
    with UPLOADS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def slot_filled(publish_at: str) -> bool:
    """次の公開枠（publish_at）に、もう1本予約してあるか

    2026-10-08: 「今日投稿したか」（uploaded_at の日付）で判定していたのを、公開枠で判定に変えた。
    読み作りが上限で止まった分を夜中に作り直して投稿すると、uploaded_at が翌日になり、
    翌日 19:30 の本番が「今日はもう投稿済み」と誤って止まるため。
    """
    want = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
    for u in load_uploads():
        p = u.get("publish_at")
        if p and datetime.fromisoformat(p.replace("Z", "+00:00")) == want:
            return True
    return False


def load_uploads() -> list[dict]:
    """投稿記録を読む（同じ video_id が複数あれば最後の行を使う）"""
    if not UPLOADS_LOG.exists():
        return []
    rows: dict[str, dict] = {}
    for line in UPLOADS_LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["video_id"]] = r
    return list(rows.values())
