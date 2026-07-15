"""ステージ3: VOICEVOXによるナレーション音声生成"""

import logging
import os
import subprocess
import time
import wave
from pathlib import Path

import requests

from config.settings import (
    AUDIO_SAMPLE_RATE,
    VOICEVOX_BOOT_TIMEOUT,
    VOICEVOX_EXE_PATH,
    VOICEVOX_SPEAKER_ID,
    VOICEVOX_SPEED,
    VOICEVOX_URL,
)

logger = logging.getLogger(__name__)


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

    # 速度調整
    query["speedScale"] = speed
    # ピッチやイントネーション微調整（アナウンサー風）
    query["pitchScale"] = 0.0
    query["intonationScale"] = 1.2
    query["volumeScale"] = 1.0
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


def generate_all_voices(
    script: dict,
    output_dir: Path,
    speaker_id: int = VOICEVOX_SPEAKER_ID,
    voicevox_url: str = VOICEVOX_URL,
) -> list[dict]:
    """台本の全シーンの音声を生成"""
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    results = []
    scenes = script["scenes"]
    total = len(scenes)

    for i, scene in enumerate(scenes):
        audio_path = audio_dir / f"scene_{scene['id']:03d}.wav"
        text = scene["narration"]

        # 既に生成済みならスキップ
        if _is_valid_wav(audio_path):
            duration = get_audio_duration(audio_path)
            logger.info(f"スキップ（生成済み）: {audio_path.name} ({duration:.1f}秒)")
            results.append({"scene_id": scene["id"], "path": audio_path, "duration": duration})
            continue

        logger.info(f"音声生成 [{i + 1}/{total}]: {text[:30]}...")

        generate_voice(
            text=text,
            output_path=audio_path,
            speaker_id=speaker_id,
            voicevox_url=voicevox_url,
        )
        duration = get_audio_duration(audio_path)
        results.append({"scene_id": scene["id"], "path": audio_path, "duration": duration})

    total_duration = sum(r["duration"] for r in results)
    logger.info(f"全音声生成完了: {len(results)}件, 合計{total_duration / 60:.1f}分")
    return results


def check_voicevox_available(voicevox_url: str = VOICEVOX_URL) -> bool:
    """VOICEVOXが起動しているか確認"""
    try:
        resp = requests.get(f"{voicevox_url}/version", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def ensure_voicevox(
    voicevox_url: str = VOICEVOX_URL,
    exe_path: str = VOICEVOX_EXE_PATH,
    timeout: int = VOICEVOX_BOOT_TIMEOUT,
) -> bool:
    """VOICEVOXが未起動なら自動起動し、APIが応答するまで待つ

    Returns:
        使える状態になったらTrue
    """
    if check_voicevox_available(voicevox_url):
        return True

    if not Path(exe_path).exists():
        logger.error(f"VOICEVOXが見つかりません: {exe_path}")
        return False

    logger.info(f"VOICEVOXを自動起動します: {exe_path}")
    # 親プロセス終了に巻き込まれないよう切り離して起動
    subprocess.Popen(
        [exe_path],
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
