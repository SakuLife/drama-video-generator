"""投稿した動画の再生数・視聴維持率を1日1回 data/stats.jsonl に記録する

- 再生数・高評価・コメント … YouTube Data API（videos.list・50本で1ユニット）
- 平均視聴時間・平均視聴率 … YouTube Analytics API（集計に2〜3日の遅れがある＝新しい動画は空欄）
過去の推移はAPIで遡れないので、毎日の記録を data/*.jsonl に残す（git で追う）。

使い方:
    .venv/Scripts/python.exe scripts/collect_stats.py
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / "_shared" / "secrets" / ".env")

from googleapiclient.discovery import build  # noqa: E402

from src.experiment import DATA_DIR, load_uploads  # noqa: E402
from src.youtube_uploader import get_credentials  # noqa: E402

JST = timezone(timedelta(hours=9))
STATS_LOG = DATA_DIR / "stats.jsonl"


def main() -> int:
    """全投稿の今日時点の数字を1行ずつ追記する"""
    sys.stdout.reconfigure(encoding="utf-8")
    uploads = load_uploads()
    if not uploads:
        print("投稿記録（data/uploads.jsonl）が空なので何もしません")
        return 0

    creds = get_credentials(
        os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"], os.environ["YT_REFRESH_TOKEN"]
    )
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ids = [u["video_id"] for u in uploads]

    stats: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        res = yt.videos().list(part="statistics,status", id=",".join(ids[i : i + 50])).execute()
        for it in res.get("items", []):
            st = it.get("statistics", {})
            stats[it["id"]] = {
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
                "privacy": it.get("status", {}).get("privacyStatus"),
            }

    # 視聴維持（Analytics）。失敗しても再生数の記録は残す
    retention: dict[str, dict] = {}
    try:
        ya = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
        start = min(u["uploaded_at"][:10] for u in uploads)
        rep = ya.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=date.today().isoformat(),
            metrics="views,averageViewDuration,averageViewPercentage",
            dimensions="video",
            filters="video==" + ",".join(ids[:200]),
        ).execute()
        for row in rep.get("rows", []) or []:
            retention[row[0]] = {"avg_view_sec": row[2], "avg_view_pct": row[3]}
    except Exception as e:  # 集計前・権限不足など。原因は必ず出す
        print(f"⚠ 視聴維持率を取れませんでした（再生数だけ記録します）: {e}")

    now = datetime.now(JST).isoformat(timespec="seconds")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with STATS_LOG.open("a", encoding="utf-8") as f:
        for u in uploads:
            vid = u["video_id"]
            if vid not in stats:
                row = {"video_id": vid, "collected_at": now, "missing": True}
            else:
                row = {"video_id": vid, "collected_at": now, **stats[vid], **retention.get(vid, {})}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"記録しました: {len(uploads)}本（視聴維持率あり {len(retention)}本） → {STATS_LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
