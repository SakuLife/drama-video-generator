"""既存の台本で「読み間違いゼロの仕組み」を試す（動画は作らない・投稿もしない）

1. 字幕1枚ぶんずつ、正しい読み（かな）を claude -p に作らせる（generated/<日付>/readings.json）
2. 漢字のまま VOICEVOX に読ませた音とかなを突き合わせ、食い違いを数える
   ＝「今のやり方（漢字を渡す）で VOICEVOX が読み間違えていた候補」
3. 食い違った行だけ別の claude -p に判定させ、かなを直す
4. かなを VOICEVOX に渡して reading_check で突き合わせ（本番と同じ判定）

使い方:
    .venv/Scripts/python.exe tools/check_readings.py generated/20261005 [generated/20261003 ...]
"""

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.reading import adjudicate, compare_engine, fix_mismatches, make_readings, segment_lines, verify  # noqa: E402

SPEAKER = 2  # 四国めたん（本番の声）


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for d in sys.argv[1:]:
        out_dir = ROOT / d
        script = json.loads((out_dir / "script.json").read_text(encoding="utf-8"))
        lines = segment_lines(script, out_dir)
        readings = make_readings(lines, out_dir)
        diffs = compare_engine(lines, readings, SPEAKER)
        fixed = adjudicate(diffs)
        changed = {k: v for k, v in fixed.items() if v != readings[k]}
        readings.update(changed)
        (out_dir / "readings.json").write_text(json.dumps(readings, ensure_ascii=False, indent=1), encoding="utf-8")
        rep = verify(readings, SPEAKER, out_dir)
        first_mismatches = len(rep.mismatches)
        readings = fix_mismatches(readings, rep, speaker=SPEAKER)
        (out_dir / "readings.json").write_text(json.dumps(readings, ensure_ascii=False, indent=1), encoding="utf-8")
        rep = verify(readings, SPEAKER, out_dir)
        report = {
            "dir": d, "lines": len(lines), "engine_vs_kana_diffs": len(diffs),
            "adjudicated_changed": len(changed), "mismatches_before_fix": first_mismatches, "final_mismatches": len(rep.mismatches),
        }
        (out_dir / "reading_diffs.json").write_text(
            json.dumps({"summary": report, "diffs": diffs, "changed": changed}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        print(rep.summary(limit=30))
    return 0


if __name__ == "__main__":
    sys.exit(main())
