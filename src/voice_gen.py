"""ステージ3: VOICEVOXによるナレーション音声生成"""

import logging
import os
import re
import subprocess
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

import requests

from config.settings import (
    AUDIO_SAMPLE_RATE,
    SUBTITLE_MAX_CHARS_PER_SEGMENT,
    VOICEVOX_BOOT_TIMEOUT,
    VOICEVOX_ENGINE_PATH,
    VOICEVOX_EXE_PATH,
    VOICEVOX_INTONATION,
    VOICEVOX_POST_PHONEME,
    VOICEVOX_PRE_PHONEME,
    VOICEVOX_SPEAKER_ID,
    VOICEVOX_SPEED,
    VOICEVOX_URL,
)

logger = logging.getLogger(__name__)

_SENTENCE_END = "。！？!?"
_QUOTE_OPEN = "「『（("
_QUOTE_CLOSE = "」』）)"


def _split_sentences(text: str) -> list[str]:
    """文末で切る。ただし鉤括弧の中では切らない

    セリフ「おい爺さん！汚い服で入るな！」を「！」で切ると
    閉じ括弧のない字幕が出てしまうため、括弧の内側は1文として扱う。
    """
    sentences: list[str] = []
    current = ""
    depth = 0

    for char in text:
        current += char
        if char in _QUOTE_OPEN:
            depth += 1
        elif char in _QUOTE_CLOSE:
            depth = max(0, depth - 1)
            # 「〜。」のように閉じ括弧で文が終わる形
            if depth == 0 and len(current) > 1 and current[-2] in _SENTENCE_END:
                sentences.append(current)
                current = ""
        elif char in _SENTENCE_END and depth == 0:
            sentences.append(current)
            current = ""

    if current.strip():
        sentences.append(current)

    return sentences


def split_narration(text: str, max_chars: int = SUBTITLE_MAX_CHARS_PER_SEGMENT) -> list[str]:
    """ナレーションを字幕1枚ぶんずつに切り分ける

    1枚の絵を長く見せながら字幕だけを送るため、ナレーションを文単位に切る。
    1文が長すぎると字幕が画面を覆うので、その場合は読点でさらに分割する。
    """
    segments: list[str] = []

    for sentence in _split_sentences(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            segments.append(sentence)
            continue

        # 長い文は読点で分割し、上限まで詰め直す
        chunk = ""
        for part in re.split(r"(?<=、)", sentence):
            if chunk and len(chunk) + len(part) > max_chars:
                segments.append(chunk)
                chunk = part
            else:
                chunk += part
        if chunk:
            segments.append(chunk)

    # 読点すら無い長文は機械的に切る（字幕が画面を覆うのを防ぐのが目的）
    result: list[str] = []
    for seg in segments:
        while len(seg) > max_chars:
            result.append(seg[:max_chars])
            seg = seg[max_chars:]
        if seg:
            result.append(seg)

    return result


def generate_voice(
    text: str,
    output_path: Path,
    speaker_id: int = VOICEVOX_SPEAKER_ID,
    speed: float = VOICEVOX_SPEED,
    voicevox_url: str = VOICEVOX_URL,
) -> Path:
    """テキストからVOICEVOXで音声を生成"""
    # 音声合成クエリ作成
    query_resp = requests.post(
        f"{voicevox_url}/audio_query",
        params={"text": text, "speaker": speaker_id},
        timeout=30,
    )
    query_resp.raise_for_status()
    query = query_resp.json()

    # 速度・抑揚（棒読み対策）
    query["speedScale"] = speed
    query["pitchScale"] = 0.0
    query["intonationScale"] = VOICEVOX_INTONATION
    query["volumeScale"] = 1.0
    # 文の前後に「間」を入れる（各文が別合成なので、文末の余白が次の字幕までのためになる）
    query["prePhonemeLength"] = VOICEVOX_PRE_PHONEME
    query["postPhonemeLength"] = VOICEVOX_POST_PHONEME
    # 動画側と同じサンプリングレートで出す（合成時の再変換を避ける）
    query["outputSamplingRate"] = AUDIO_SAMPLE_RATE
    query["outputStereo"] = False

    # 音声合成
    synth_resp = requests.post(
        f"{voicevox_url}/synthesis",
        params={"speaker": speaker_id},
        json=query,
        timeout=60,
    )
    synth_resp.raise_for_status()

    # 一時ファイル経由で書く（途中で落ちても壊れたWAVを正式名で残さない）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".wav.part")
    tmp_path.write_bytes(synth_resp.content)
    os.replace(tmp_path, output_path)
    return output_path


def _is_valid_wav(path: Path) -> bool:
    """再開時に「生成済み」と見なしてよいWAVか（壊れていれば作り直す）

    途中で切れたWAVはヘッダーが残るため、ヘッダーのフレーム数だけ見ても気付けない。
    実データがヘッダーの申告どおり入っているかまで照合する。
    """
    if not path.exists():
        return False
    try:
        with wave.open(str(path), "rb") as wf:
            declared = wf.getnframes()
            if declared <= 0:
                raise ValueError("フレーム数が0")
            block_align = wf.getnchannels() * wf.getsampwidth()
            actual = len(wf.readframes(declared))
            if actual < declared * block_align:
                raise ValueError(f"データが途中で切れている（{actual} < {declared * block_align}）")
        return True
    except Exception as e:
        logger.warning(f"壊れた音声を検出。作り直します: {path.name}（{e}）")
        return False


def get_audio_duration(audio_path: Path) -> float:
    """WAVファイルの長さ（秒）を取得"""
    with wave.open(str(audio_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate


def _segment_path(audio_dir: Path, scene_id: int, index: int) -> Path:
    """字幕1枚ぶんの音声ファイルのパス"""
    return audio_dir / f"scene_{scene_id:03d}_{index:02d}.wav"


def build_scene_segments(scene: dict, audio_dir: Path) -> list[dict]:
    """シーンを字幕単位のセグメントに分解する（パスは決定的に決まる）"""
    return [
        {"index": i, "text": text, "path": _segment_path(audio_dir, scene["id"], i)}
        for i, text in enumerate(split_narration(scene["narration"]), 1)
    ]


def generate_all_voices(
    script: dict,
    output_dir: Path,
    speaker_id: int = VOICEVOX_SPEAKER_ID,
    voicevox_url: str = VOICEVOX_URL,
) -> list[dict]:
    """台本の全シーンの音声を字幕単位で生成する

    1枚の絵を長く見せながら字幕を送るため、ナレーションを文単位に切って
    それぞれの音声を作る。こうすると字幕の切り替え時刻が音声の実尺で決まり、
    ズレようがない。

    Returns:
        [{"scene_id": 1, "segments": [{"index","text","path","duration"}...], "duration": 合計}, ...]
    """
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    results = []
    scenes = script["scenes"]
    total = len(scenes)

    for i, scene in enumerate(scenes):
        segments = build_scene_segments(scene, audio_dir)
        if not segments:
            raise ValueError(f"シーン{scene['id']}のナレーションが空です")

        for seg in segments:
            if not _is_valid_wav(seg["path"]):
                generate_voice(
                    text=seg["text"],
                    output_path=seg["path"],
                    speaker_id=speaker_id,
                    voicevox_url=voicevox_url,
                )
            seg["duration"] = get_audio_duration(seg["path"])

        scene_duration = sum(s["duration"] for s in segments)
        logger.info(
            f"音声生成 [{i + 1}/{total}] scene_{scene['id']:03d}: "
            f"字幕{len(segments)}枚 / {scene_duration:.1f}秒"
        )
        results.append(
            {"scene_id": scene["id"], "segments": segments, "duration": scene_duration}
        )

    total_duration = sum(r["duration"] for r in results)
    seg_count = sum(len(r["segments"]) for r in results)
    logger.info(
        f"全音声生成完了: {len(results)}シーン / 字幕{seg_count}枚 / 合計{total_duration / 60:.1f}分"
    )
    return results


def load_audio_results(script: dict, output_dir: Path) -> list[dict]:
    """生成済みの音声から結果を復元する（--stage video 単独実行用）"""
    audio_dir = output_dir / "audio"
    results = []

    for scene in script["scenes"]:
        segments = build_scene_segments(scene, audio_dir)
        missing = [s["path"].name for s in segments if not _is_valid_wav(s["path"])]
        if missing:
            raise RuntimeError(
                f"シーン{scene['id']}の音声が足りません: {missing[:3]}"
                "（先に --stage voice を実行してください）"
            )
        for seg in segments:
            seg["duration"] = get_audio_duration(seg["path"])
        results.append(
            {
                "scene_id": scene["id"],
                "segments": segments,
                "duration": sum(s["duration"] for s in segments),
            }
        )

    return results


def check_voicevox_available(voicevox_url: str = VOICEVOX_URL) -> bool:
    """VOICEVOXが起動しているか確認"""
    try:
        resp = requests.get(f"{voicevox_url}/version", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def _build_launch_command(voicevox_url: str) -> list[str] | None:
    """起動コマンドを組み立てる（エンジン単体を優先、無ければGUI版）"""
    if Path(VOICEVOX_ENGINE_PATH).exists():
        port = urlparse(voicevox_url).port or 50021
        return [VOICEVOX_ENGINE_PATH, "--port", str(port)]
    if Path(VOICEVOX_EXE_PATH).exists():
        # GUI版はポート指定できないので既定(50021)前提
        return [VOICEVOX_EXE_PATH]
    return None


def ensure_voicevox(
    voicevox_url: str = VOICEVOX_URL,
    timeout: int = VOICEVOX_BOOT_TIMEOUT,
) -> bool:
    """VOICEVOXが未起動なら自動起動し、APIが応答するまで待つ

    エンジン単体(run.exe)を優先する。GUI版はデスクトップセッションが必要で、
    サービスとして動く実行環境（CI・タスクスケジューラのバックグラウンド実行）から
    起動できないため。

    Returns:
        使える状態になったらTrue
    """
    if check_voicevox_available(voicevox_url):
        return True

    command = _build_launch_command(voicevox_url)
    if command is None:
        logger.error(
            f"VOICEVOXが見つかりません（エンジン: {VOICEVOX_ENGINE_PATH} / GUI: {VOICEVOX_EXE_PATH}）"
        )
        return False

    logger.info(f"VOICEVOXを自動起動します: {command[0]}")
    # 親プロセス終了に巻き込まれないよう切り離して起動。
    # 出力は必ず捨てる：エンジンは進捗バーを大量に吐くため、コンソールを持たない
    # 切り離しプロセスで出力先を繋いだままにすると書き込みが詰まって起動しない。
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )

    start = time.time()
    while time.time() - start < timeout:
        if check_voicevox_available(voicevox_url):
            logger.info(f"VOICEVOX起動完了（{time.time() - start:.0f}秒）")
            return True
        time.sleep(3)

    logger.error(f"VOICEVOXの起動がタイムアウトしました（{timeout}秒）")
    return False


def list_speakers(voicevox_url: str = VOICEVOX_URL) -> list[dict]:
    """利用可能なスピーカー一覧を取得"""
    resp = requests.get(f"{voicevox_url}/speakers", timeout=10)
    resp.raise_for_status()
    return resp.json()
