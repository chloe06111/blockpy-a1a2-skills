# -*- coding: utf-8 -*-
"""[실습준비 · BlockPy 수업용 · 원본 아님] A1 진짜 음성 입력 — 마이크로 녹음해서 글자로 바꾼다.

  · 녹음: 원본 common.audio.record_wav (sounddevice · 16kHz mono WAV)
  · 인식: faster-whisper (한국어). 원본 STTClient 와 같은 엔진에 세 가지를 더했다(2026-11-01 실측 후):
      ① 소리 키우기 — 노트북 마이크 녹음이 너무 작아(최대치의 3%) 잘못 들었다
      ② 수업 문장 힌트 — "홈으로 갔다가 …" 같은 문장을 미리 알려 준다
      ③ 말소리만 골라 듣기(VAD) — 조용한 부분 때문에 오래 걸리던 것을 줄인다
  · 인식 결과 객체는 transcribe(path) 를 가져서 수업 코드의 stt 자리에 그대로 들어간다.
필요: BlockPy 파이썬에 faster-whisper. 처음 한 번은 모델을 인터넷에서 받는다.
"""
import os
import time

힌트 = ("로봇팔 명령입니다. 홈으로 갔다가 오른쪽으로 5센티 이동하고 그리퍼 닫아. "
        "위로 3센티 이동하고 왼쪽으로 4센티 이동한 다음 홈으로 복귀. 앞으로 2센티 가서 그리퍼 열어.")
_모델들 = {}


def _소리_읽기(경로):
    from common.audio import load_wav_float32
    data, rate = load_wav_float32(경로)
    return data, rate


def 녹음하기(초=4.0, 파일="음성입력.wav"):
    """초 동안 마이크로 녹음해 작업 폴더에 WAV 로 저장하고 경로를 돌려준다."""
    from common.audio import record_wav
    경로 = os.path.join(os.getcwd(), 파일)
    print("\n🎤 3초 뒤에 녹음을 시작해요. 마이크(노트북) 가까이에서 또박또박 말할 준비를 하세요.")
    for n in (3, 2, 1):
        print(f"   {n}...")
        time.sleep(1)
    print(f"🔴 지금 말하세요! ({초:.0f}초)")
    record_wav(경로, seconds=초)
    try:
        data, _ = _소리_읽기(경로)
        크기 = float(abs(data).max()) if len(data) else 0.0
        if 크기 < 0.05:
            print(f"⚠️  녹음 소리가 아주 작아요(최대 {크기:.0%}). 마이크 가까이에서 크게 말하거나,"
                  " Windows 설정 → 소리 → 입력 → 마이크 볼륨을 올리세요.")
    except Exception:
        pass
    print("⏹  녹음 끝 — 글자로 바꾸는 중이에요...")
    return 경로


class 음성인식:
    """faster-whisper 로 한국어 인식. 수업 코드의 stt 자리에 넣는다(transcribe 가 있음)."""
    mock = False

    def __init__(self, 모델="small"):
        from faster_whisper import WhisperModel
        print(f"(음성 인식 모델 '{모델}' 준비 중 — 처음 한 번은 오래 걸려요)")
        self.model = WhisperModel(모델, device="cpu", compute_type="int8")

    def transcribe(self, 경로):
        data, rate = _소리_읽기(경로)
        크기 = float(abs(data).max()) if len(data) else 0.0
        if 크기 > 1e-4:
            data = data * (0.9 / 크기)            # ① 소리 키우기
        t = time.time()
        조각들, _ = self.model.transcribe(
            data, language="ko", initial_prompt=힌트,          # ② 수업 문장 힌트
            vad_filter=True, condition_on_previous_text=False, beam_size=5)   # ③ 말소리만
        글자 = "".join(s.text for s in 조각들).strip().rstrip(".")
        print(f"   (인식 {time.time() - t:.1f}초)")
        return 글자


def 음성인식기(모델="medium"):
    """한 번 만든 모델은 다시 쓴다."""
    if 모델 not in _모델들:
        _모델들[모델] = 음성인식(모델)
    return _모델들[모델]
