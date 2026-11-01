# -*- coding: utf-8 -*-
"""common/audio.py — 마이크 녹음 유틸(A1 음성 제어용).

STT(whisper)는 **파일**을 받아 인식한다. 그런데 지금까지 A1 은 마이크에서 실제로
녹음하는 단계가 없어(고정 파일 경로만 넘김) STT 가 동작하지 않았다. 이 모듈이 그
빠진 조각 — `sounddevice` 로 마이크를 녹음해 16kHz mono WAV(whisper 친화)로 저장한다.

의존성은 선택적: `sounddevice`/`numpy` 가 없거나 입력 장치가 없으면 record_wav 는
RuntimeError 를 던지고, mic_available() 은 False 를 돌려준다(호출부가 안전 처리).
WAV 쓰기는 표준 라이브러리(wave)만 쓴다(추가 의존성 없음).
"""
from __future__ import annotations

import wave

__all__ = ["mic_available", "record_wav", "load_wav_float32", "DEFAULT_SAMPLERATE"]

DEFAULT_SAMPLERATE = 16000   # whisper 권장 입력(16kHz mono)


def mic_available() -> bool:
    """녹음 가능한 입력 장치가 있으면 True(없거나 라이브러리 미설치면 False)."""
    try:
        import sounddevice as sd
        return sd.query_devices(kind="input") is not None
    except Exception:
        return False


def write_wav_int16(path: str, samples, samplerate: int = DEFAULT_SAMPLERATE) -> str:
    """int16 mono 샘플(numpy 배열 또는 bytes)을 WAV 파일로 저장한다(표준 wave)."""
    data = samples.tobytes() if hasattr(samples, "tobytes") else bytes(samples)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)         # mono
        w.setsampwidth(2)         # int16 = 2 bytes
        w.setframerate(int(samplerate))
        w.writeframes(data)
    return path


def load_wav_float32(path: str):
    """WAV(16bit PCM) 파일을 float32 mono 배열([-1,1])과 샘플레이트로 읽는다.

    whisper 는 기본적으로 ffmpeg 로 오디오를 로드하는데(Windows 에서 ffmpeg 미설치 시
    FileNotFoundError [WinError 2]), 이렇게 우리가 직접 배열로 읽어 넘기면 ffmpeg 없이
    인식할 수 있다. 반환: (numpy.float32 배열, samplerate). numpy 필요.
    """
    import numpy as np

    with wave.open(path, "rb") as w:
        ch, width, rate, nframes = (
            w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
        raw = w.readframes(nframes)

    if width != 2:
        raise RuntimeError(f"16bit PCM WAV 만 지원합니다(sampwidth={width}).")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:                       # 스테레오 → mono 평균
        data = data.reshape(-1, ch).mean(axis=1)
    return data, rate


def record_wav(path: str, seconds: float = 4.0,
               samplerate: int = DEFAULT_SAMPLERATE) -> str:
    """마이크에서 ``seconds`` 초 녹음해 ``path`` (16kHz mono WAV)로 저장한다.

    sounddevice/numpy 미설치이거나 입력 장치가 없으면 RuntimeError.
    반환: 저장된 WAV 경로.
    """
    try:
        import numpy as np  # noqa: F401  (dtype 지정에 사용)
        import sounddevice as sd
    except Exception as exc:  # 라이브러리 없음
        raise RuntimeError(
            "녹음하려면 sounddevice(+numpy)가 필요합니다: pip install sounddevice numpy"
        ) from exc

    frames = int(max(0.1, seconds) * samplerate)
    audio = sd.rec(frames, samplerate=samplerate, channels=1, dtype="int16")
    sd.wait()                                       # 녹음 완료까지 블로킹
    return write_wav_int16(path, audio.reshape(-1), samplerate)
