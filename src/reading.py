"""読み上げ文の「読み」をかなで用意し、VOICEVOX の読みと突き合わせる（読み間違いゼロの仕組み）

社長指示（2026-10-07）「動画系は読み方完璧になる仕組み作っといて」。全社の決まりは
`_shared/skills/voicevox/README.md` の reading_check:
  ① 音声エンジンに漢字を渡さない（字幕は漢字のまま・読み上げはかなだけ）。助詞は わ・え と書かせ、
     残りの は・へ は kana_for_tts() でカタカナにする（版2・2026-10-08）
  ② VOICEVOX の読み（audio_query のモーラ）と1音ずつ突き合わせ、ズレたら作らない
  ③ 数字はカタカナ

流れ:
  1. make_readings(): 字幕1枚ぶんずつ、正しい読み（かな）を claude -p に書かせて readings.json に保存
  2. compare_engine(): 漢字の文をそのまま VOICEVOX に読ませた音と、かなを突き合わせる。
     食い違った所＝「VOICEVOX が読み間違えそう」か「AIのかなが間違っている」のどちらか
     → その行だけ別の claude -p に正しい読みを判定させる（台本のかな自体の誤りの手当て）
  3. verify(): かなを VOICEVOX に渡して突き合わせ（reading_check）。ズレが残れば ReadingMismatch

claude -p はサブスク枠で動かす（API課金なし）。🔴 ANTHROPIC_API_KEY を環境から外して、
D:\\AutoSystem の外の空フォルダで起動する（本社 地雷集 llm.md の2件）。
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

HQ_ROOT = Path(__file__).resolve().parents[2]  # D:\AutoSystem\PythonSystem
if str(HQ_ROOT) not in sys.path:
    sys.path.insert(0, str(HQ_ROOT))

from _shared.skills.voicevox.reading_check import (  # noqa: E402
    ReadingMismatch,
    Report,
    _particle_mask,
    _same,
    check_lines,
    engine_reading,
    kana_for_tts,
    expected_reading,
)

READINGS_FILE = "readings.json"
CHECK_FILE = "reading_check.txt"
BATCH = 40  # 1回の claude -p に渡す行数（長すぎると返りのJSONが崩れやすい）

KANA_RULES = """\
- 使ってよい文字は ひらがな・カタカナ・長音「ー」・句読点（、。）・！？・鉤括弧「」『』だけ。漢字・英字・数字・空白は使わない
- 数字は読みどおりカタカナで（18→ジュウハチ、3000万→サンゼンマン、1人→ヒトリ）
- 人名・地名・会社名などの固有名詞と、英単語はカタカナで
- 助詞の「は」「へ」は発音どおり「わ」「え」と書く（例: わたしわ、 ／ がっこうえ いく ／ こんにちわ）。
  ことばの中の「は」「へ」（はは・はな・へや）はそのまま書く。助詞の「を」は「を」のまま
- 元の文の言い回しを変えない。読みを書くだけ。句読点の位置は元の文に合わせる"""


def _clean(kana: str) -> str:
    """AI の返したかなを、読み上げに渡す形に仕上げる

    - kana_for_tts: 助詞以外の は・へ を含む語をカタカナに（ひらがなの はは をエンジンが ワワ と読む）
    - 空白を消す: VOICEVOX は空白ごとに間を空ける。2026-10-08 の試験で 13.6分→15.7分 に延び、
      未確認チャンネルの上限15分を超えた（空白の多い行は1行で+5秒）
    """
    return kana_for_tts(kana).replace(" ", "").replace("　", "")


def _val(v) -> str:
    """返事の値を文字列に。入力の形をまねて {"読みがな": ...} の入れ子で返すことがある（2026-10-08 実測）"""
    if isinstance(v, dict):
        for key in ("読みがな", "kana", "reading"):
            if isinstance(v.get(key), str):
                return v[key]
        return next((x for x in v.values() if isinstance(x, str)), "")
    return str(v)


def _claude_env() -> dict[str, str]:
    """claude -p をサブスクで動かすための環境（API キーを外す）"""
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)
    return env


def _run_claude(prompt: str, label: str, timeout: int = 600) -> str:
    """claude -p を1回叩いて標準出力を返す（失敗は例外）"""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("claude が見つかりません（読みの作成に必要）")
    workdir = Path(tempfile.gettempdir()) / "drama_reading_claude"
    workdir.mkdir(exist_ok=True)
    proc = subprocess.run(
        [exe, "-p"], input=prompt.encode("utf-8"), capture_output=True,
        timeout=timeout, cwd=workdir, env=_claude_env(),
    )
    if proc.returncode != 0:
        why = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()[:300]
        raise RuntimeError(f"claude -p 失敗（{label}・exit={proc.returncode}）: {why}")
    return proc.stdout.decode("utf-8", "replace")


def _parse_json_obj(text: str) -> dict:
    """返事から最初の { ... } を取り出して読む"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"JSON が見つからない: {text[:200]}")
    return json.loads(m.group(0))


def _ask_kana(lines: dict[str, str]) -> dict[str, str]:
    """{キー: 漢字かな混じりの文} → {キー: かなの読み}"""
    prompt = (
        "次の日本語ナレーションの各行を、音声合成に読ませるための「読みがな」に書き換えてください。\n"
        "出力は JSON オブジェクト1つだけ（キーは入力と同じ・値は読みがな）。説明文は書かない。\n\n"
        f"ルール:\n{KANA_RULES}\n\n入力:\n{json.dumps(lines, ensure_ascii=False, indent=1)}"
    )
    out = _parse_json_obj(_run_claude(prompt, "読みがな作成"))
    missing = [k for k in lines if k not in out]
    if missing:
        raise ValueError(f"読みが返ってこなかった行: {missing[:5]}")
    # 助詞を わ・え で書かせた上で、残りの は・へ をカタカナにする（ひらがなの はは をエンジンが ワワ と読むため）
    return {k: _clean(_val(out[k])) for k in lines}


def make_readings(segments: dict[str, str], output_dir: Path) -> dict[str, str]:
    """全行の読みを作って readings.json に保存する（あれば使う＝作り直さない）"""
    path = output_dir / READINGS_FILE
    readings: dict[str, str] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo = {k: v for k, v in segments.items() if k not in readings}
    keys = list(todo)
    for i in range(0, len(keys), BATCH):
        chunk = {k: todo[k] for k in keys[i : i + BATCH]}
        readings.update(_ask_kana(chunk))
        path.write_text(json.dumps(readings, ensure_ascii=False, indent=1), encoding="utf-8")  # 逐次保存
        logger.info(f"読みがな作成: {min(i + BATCH, len(keys))}/{len(keys)}行")
    # 以前の版で作った読み（空白あり）も同じ形に揃える
    return {k: _clean(readings[k]) for k in segments}


def compare_engine(segments: dict[str, str], readings: dict[str, str], speaker: int) -> list[dict]:
    """漢字の文をそのままエンジンに読ませた音と、かなの読みが食い違う行を返す

    食い違い＝VOICEVOX が漢字を読み間違えるか、AI のかなが間違っているかのどちらか。
    ここで見つかった行だけを判定役の claude -p に回す。
    """
    diffs = []
    for k, text in segments.items():
        try:
            got = engine_reading(text, speaker=speaker)
        except Exception as e:  # エンジンが一時的に返さない行は判定に回さず記録だけ残す
            logger.warning(f"エンジンの読みを取れず（{k}）: {e}")
            continue
        ok, _ = _same(expected_reading(readings[k]), got, _particle_mask(readings[k]))
        if not ok:
            diffs.append({"key": k, "text": text, "kana": readings[k], "engine": got})
    return diffs


def adjudicate(diffs: list[dict]) -> dict[str, str]:
    """食い違った行だけ、別の claude -p に正しい読みを決めさせる（台本のかな自体の誤りの手当て）"""
    if not diffs:
        return {}
    items = {d["key"]: {"文": d["text"], "読みA": d["kana"], "読みB（音声合成の推測）": d["engine"]} for d in diffs}
    prompt = (
        "日本語の文と、2通りの読みがあります。文脈から正しい読みを決め、読みがなで書いてください。\n"
        "どちらも違うなら正しい読みを書く。出力は JSON オブジェクト1つだけ（キーは入力と同じ・値は読みがな）。\n\n"
        f"読みがなのルール:\n{KANA_RULES}\n\n入力:\n{json.dumps(items, ensure_ascii=False, indent=1)}"
    )
    out = _parse_json_obj(_run_claude(prompt, "読みの判定"))
    return {k: _clean(_val(v)) for k, v in out.items() if k in items}


def verify(readings: dict[str, str], speaker: int, output_dir: Path) -> Report:
    """かなを VOICEVOX に渡して突き合わせ、結果を全件 reading_check.txt に残す"""
    rep = check_lines(readings, speaker=speaker)
    (output_dir / CHECK_FILE).write_text(
        rep.summary(limit=999) + "\n\n" + "\n".join(f"{'OK' if r.ok else 'NG'} [{r.key}] {r.got}" for r in rep.results),
        encoding="utf-8",
    )
    return rep


def fix_mismatches(readings: dict[str, str], rep: Report, rounds: int = 2, speaker: int = 2) -> dict[str, str]:
    """突き合わせでズレた行だけ、エンジンの読みを見せて claude -p に書き直させる（最大 rounds 回）

    例（2026-10-08 実測）: カタカナの「イチビョウ」をエンジンが「イチビヨウ」と読む／
    空白の直後のカタカナ「ヘたりこみ」を助詞とみなして「エタリコミ」と読む。言い回しは変えずに書き方で避けさせる。
    """
    for _ in range(rounds):
        bad = {r.key: {"読みがな": r.text, "音声合成の実際の読み": r.got, "ズレ": r.why} for r in rep.mismatches}
        if not bad:
            break
        prompt = (
            "音声合成に読ませる読みがなが、意図と違う音で読まれました。同じ意味・同じ音になるよう、"
            "書き方だけ変えてください（ひらがな⇔カタカナの入れ替え、空白の位置の変更など）。\n"
            "出力は JSON オブジェクト1つだけ（キーは入力と同じ・値は直した読みがな）。\n\n"
            f"読みがなのルール:\n{KANA_RULES}\n\n入力:\n{json.dumps(bad, ensure_ascii=False, indent=1)}"
        )
        out = _parse_json_obj(_run_claude(prompt, "読みの書き直し"))
        readings.update({k: _clean(_val(v)) for k, v in out.items() if k in bad})
        rep = check_lines({k: readings[k] for k in bad}, speaker=speaker)
    return readings


OK_FILE = "readings_ok.json"       # 突き合わせ0件で通った読み（本番の音声はこれで作る）
PENDING_FILE = "readings_pending.json"  # 上限などで読みが作れず、夜中の再試行待ち


class ReadingsPending(RuntimeError):
    """読みが今は作れない（claude -p の上限・ズレが残った）。夜中に再試行する"""


def segment_lines(script: dict, output_dir: Path) -> dict[str, str]:
    """字幕1枚ぶんの文を {scene_001_01: 文} で返す（音声ファイル名と同じキー）"""
    from src.voice_gen import build_scene_segments

    lines = {}
    for scene in script["scenes"]:
        for seg in build_scene_segments(scene, output_dir / "audio"):
            lines[seg["path"].stem] = seg["text"]
    return lines


def prepare_readings(script: dict, output_dir: Path, speaker: int) -> dict[str, str]:
    """本番用: 全行の読みを作り、VOICEVOX の読みとズレ0件を確かめて返す

    社長指示（2026-10-07）「読み方完璧」＋本社の決め（2026-10-08）:
      - 漢字のまま出すことはしない。作れなければ ReadingsPending を投げ、印を残す
      - 印があれば夜中（drama_reading_retry）に読み作りだけ再試行し、18時の公開までに通らなければその日は作らない
    """
    ok_path = output_dir / OK_FILE
    lines = segment_lines(script, output_dir)
    if ok_path.exists():
        readings = json.loads(ok_path.read_text(encoding="utf-8"))
        if set(readings) == set(lines):
            return readings
    try:
        readings = make_readings(lines, output_dir)
        diffs = compare_engine(lines, readings, speaker)
        readings.update(adjudicate(diffs))
        rep = verify(readings, speaker, output_dir)
        if rep.mismatches:
            readings = fix_mismatches(readings, rep, speaker=speaker)
            rep = verify(readings, speaker, output_dir)
    except Exception as e:  # 上限・JSON崩れ・エンジン不調。理由を印に残して後で再試行
        _mark_pending(output_dir, f"読みが作れない: {e}")
        raise ReadingsPending(str(e)) from e
    if rep.mismatches:
        _mark_pending(output_dir, rep.summary(limit=5))
        raise ReadingsPending(rep.summary(limit=5))
    ok_path.write_text(json.dumps(readings, ensure_ascii=False, indent=1), encoding="utf-8")
    (output_dir / PENDING_FILE).unlink(missing_ok=True)
    logger.info(f"読みの突き合わせ: {len(readings)}行 ズレ0件（誤読候補 {len(diffs)}行を判定済み）")
    return readings


def _mark_pending(output_dir: Path, why: str) -> None:
    from datetime import datetime

    path = output_dir / PENDING_FILE
    first = json.loads(path.read_text(encoding="utf-8"))["since"] if path.exists() else datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps({"since": first, "why": why[:500]}, ensure_ascii=False, indent=1), encoding="utf-8")


__all__ = ["ReadingMismatch", "ReadingsPending", "prepare_readings", "segment_lines", "make_readings", "compare_engine", "adjudicate", "fix_mismatches", "verify"]
