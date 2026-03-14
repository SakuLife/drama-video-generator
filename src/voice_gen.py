"""ステージ3: VOICEVOXによるナレーション音声生成"""

import logging
import wave
from io import BytesIO
from pathlib import Path

import requests

from config.settings import VOICEVOX_SPEAKER_ID, VOICEVOX_SPEED, VOICEVOX_URL

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

    # 音声合成
    synth_resp = requests.post(
        f"{voicevox_url}/synthesis",
        params={"speaker": speaker_id},
        json=query,
        timeout=60,
    )
    synth_resp.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(synth_resp.content)
    return output_path


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
        if audio_path.exists():
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
    except requests.ConnectionError:
        return False


def list_speakers(voicevox_url: str = VOICEVOX_URL) -> list[dict]:
    """利用可能なスピーカー一覧を取得"""
    resp = requests.get(f"{voicevox_url}/speakers", timeout=10)
    resp.raise_for_status()
    return resp.json()
