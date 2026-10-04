"""条件（声など）ごとに再生数・視聴維持率を比べて、週報を書く

data/uploads.jsonl（何を試したか）× data/stats.jsonl（毎日の数字）を突き合わせ、
公開から約1日・約7日の再生数と、最新の平均視聴率を条件ごとに並べる。
reports/analysis_YYYYMMDD.md に書き、--notify なら Discord に要約を送る。

⚠ 1つの条件に5本未満の比較は「参考」。新しいチャンネルは再生数そのものが少なく、ブレが大きい。

使い方:
    .venv/Scripts/python.exe scripts/analyze.py            # 週報を書くだけ
    .venv/Scripts/python.exe scripts/analyze.py --notify   # Discord にも送る
"""

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / "_shared" / "secrets" / ".env")

from src.experiment import DATA_DIR, VOICE_VARIANTS, load_uploads  # noqa: E402

JST = timezone(timedelta(hours=9))
REPORTS_DIR = ROOT / "reports"
MIN_SAMPLES = 5  # これ未満の比較は「参考」扱い


def _parse(ts: str | None) -> datetime | None:
    """ISO文字列を時刻に（Z もタイムゾーン付きとして読む）"""
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _load_stats() -> dict[str, list[dict]]:
    """video_id → 記録の時系列"""
    path = DATA_DIR / "stats.jsonl"
    out: dict[str, list[dict]] = defaultdict(list)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if not r.get("missing"):
                    out[r["video_id"]].append(r)
    for snaps in out.values():
        snaps.sort(key=lambda r: r["collected_at"])
    return out


def _views_after(snaps: list[dict], published: datetime, hours: float) -> int | None:
    """公開から hours 時間以上たった最初の記録の再生数（まだその時間に届いていなければ None）"""
    for s in snaps:
        if _parse(s["collected_at"]) - published >= timedelta(hours=hours):
            return s.get("views")
    return None


def build_rows() -> list[dict]:
    """1本ごとに条件と数字を並べる"""
    stats = _load_stats()
    rows = []
    for u in load_uploads():
        snaps = stats.get(u["video_id"], [])
        published = _parse(u.get("publish_at")) or _parse(u.get("uploaded_at"))
        latest = snaps[-1] if snaps else {}
        rows.append({
            **u,
            "views_1d": _views_after(snaps, published, 24) if published else None,
            "views_7d": _views_after(snaps, published, 24 * 7) if published else None,
            "views_now": latest.get("views"),
            "avg_view_pct": latest.get("avg_view_pct"),
        })
    return rows


def _summ(vals: list[float]) -> str:
    """中央値と本数（外れ値1本に引っぱられないよう平均でなく中央値）"""
    vals = [v for v in vals if v is not None]
    if not vals:
        return "—"
    note = "" if len(vals) >= MIN_SAMPLES else "（参考）"
    return f"{statistics.median(vals):,.1f}（{len(vals)}本）{note}"


def build_report(rows: list[dict]) -> str:
    """Markdown の週報"""
    labels = {v["key"]: v["label"] for v in VOICE_VARIANTS}
    by_voice: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_voice[r.get("voice") or "不明"].append(r)

    lines = [
        f"# ドラマ動画の分析（{datetime.now(JST):%Y-%m-%d}）",
        "",
        f"投稿 {len(rows)} 本。数字は中央値。{MIN_SAMPLES}本未満の条件は（参考）。",
        "",
        "## ナレーションの声ごと",
        "",
        "| 声 | 公開1日の再生 | 公開7日の再生 | 平均視聴率(%) |",
        "|---|---|---|---|",
    ]
    for key, rs in sorted(by_voice.items()):
        lines.append(
            f"| {labels.get(key, key)} | {_summ([r['views_1d'] for r in rs])} | "
            f"{_summ([r['views_7d'] for r in rs])} | {_summ([r['avg_view_pct'] for r in rs])} |"
        )
    lines += ["", "## 1本ずつ（新しい順）", "", "| 公開 | 声 | 再生(今) | 平均視聴率 | タイトル |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r.get("publish_at") or "", reverse=True):
        pct = f"{r['avg_view_pct']:.1f}" if r.get("avg_view_pct") is not None else "—"
        lines.append(
            f"| {(r.get('publish_at') or '')[:10]} | {labels.get(r.get('voice'), r.get('voice'))} | "
            f"{r.get('views_now', '—')} | {pct} | {r.get('title', '')[:40]} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    """週報を書き、必要なら Discord に送る"""
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", action="store_true", help="Discord に要約を送る")
    args = ap.parse_args()

    rows = build_rows()
    if not rows:
        print("投稿記録が無いので何もしません")
        return 0
    report = build_report(rows)
    REPORTS_DIR.mkdir(exist_ok=True)
    out = REPORTS_DIR / f"analysis_{datetime.now(JST):%Y%m%d}.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"→ {out}")

    if args.notify:
        from src.notifier import send_discord_notification

        voice_part = report.split("## 1本ずつ")[0]
        send_discord_notification(
            os.getenv("DISCORD_WEBHOOK_URL", ""), "ドラマ動画 週次分析", voice_part[:1900], color=0x7A1F2B
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
