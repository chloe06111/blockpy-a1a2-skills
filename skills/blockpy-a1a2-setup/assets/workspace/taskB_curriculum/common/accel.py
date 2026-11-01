"""common/accel.py — 하드웨어 가속(GPU) 가용성 탐지 + 정책.

목적
----
비전 처리(mediapipe 손추적, YOLO 객체검출)가 CPU만으로 버거울 때 GPU 가속을
'가능하면' 쓰도록 돕는다. **가속이 불가하거나 초기화에 실패하면 항상 CPU로 안전
폴백**한다(동작 보장 — 교실/노트북 어디서든 깨지지 않게).

정책 (config.USE_GPU = 환경변수 DOBOT_USE_GPU)
  "auto"(기본): GPU 가능하면 GPU, 아니면 CPU.
  "on"/"1"    : GPU 우선(실제 생성/워밍업 실패 시 호출측이 CPU 폴백).
  "off"/"0"   : 강제 CPU.

설계 원칙
  - 무거운 의존성(torch 등)은 **지연 import** 하고, 없으면 조용히 CPU로 본다.
  - 이 모듈을 import 하는 것만으로는 어떤 GPU 라이브러리도 강제로 로드하지 않는다.
  - 모든 탐지 함수는 예외를 삼키고 보수적(=CPU)으로 답한다 → 절대 죽지 않는다.

쓰는 곳
  - common/vision.py : HandTracker(Tasks API delegate=GPU/CPU), YoloDetector(device).
"""

from __future__ import annotations

import os

# config 는 정책값(USE_GPU)의 단일 출처. import 실패해도 환경변수로 폴백.
try:
    from common import config as _config  # type: ignore
except Exception:  # pragma: no cover - config 가 없는 비정상 환경
    _config = None  # type: ignore[assignment]


def gpu_mode() -> str:
    """정규화된 GPU 정책: 'auto' | 'on' | 'off'.

    config.USE_GPU 를 우선 보고, 없으면 환경변수 DOBOT_USE_GPU, 그것도 없으면 'auto'.
    """
    # 런타임 env 변경을 즉시 반영(config.is_mock() 과 동일한 '매 호출 재판정' 철학):
    # 환경변수를 먼저 보고, 없으면 config.USE_GPU(=import 시 env 기본), 그래도 없으면 'auto'.
    raw = os.environ.get("DOBOT_USE_GPU")
    if not raw and _config is not None:
        raw = getattr(_config, "USE_GPU", None)
    if not raw:
        raw = "auto"
    raw = str(raw).strip().lower()
    if raw in ("off", "0", "false", "no", "none", "cpu"):
        return "off"
    if raw in ("on", "1", "true", "yes", "gpu", "force"):
        return "on"
    return "auto"


def want_gpu() -> bool:
    """GPU 사용을 '시도'할지(정책이 auto 또는 on 이면 True; off 면 False)."""
    return gpu_mode() in ("auto", "on")


def _cuda_present() -> bool:
    """정책과 무관하게 torch+CUDA 가 실제로 있는지(진단용). torch 없으면 False."""
    try:
        import torch  # 지연 import (ultralytics 설치 시 동반)
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def torch_cuda_available() -> bool:
    """정책을 반영해 torch CUDA 를 '쓸지'. (정책 off 면 하드웨어가 있어도 False)"""
    return want_gpu() and _cuda_present()


def torch_device() -> str:
    """YOLO/torch 추론에 쓸 디바이스 문자열: 'cuda' | 'cpu'."""
    return "cuda" if torch_cuda_available() else "cpu"


def opencv_cuda_count() -> int:
    """OpenCV 가 CUDA 빌드인 경우 가용 CUDA 디바이스 수(아니면/오류면 0).

    참고: pip 의 표준 opencv-python 휠은 CUDA 미포함이라 보통 0 이다.
    """
    try:
        import cv2  # type: ignore
        if hasattr(cv2, "cuda"):
            return int(cv2.cuda.getCudaEnabledDeviceCount())
    except Exception:
        pass
    return 0


def mediapipe_prefer_gpu() -> bool:
    """mediapipe Tasks delegate 로 GPU 를 '시도'할지.

    정책이 auto/on 이면 시도한다. mediapipe GPU delegate 는 플랫폼 의존(데스크톱
    Windows 는 미지원인 경우가 많음)이라, 여기서는 시도만 결정하고 실제 생성/워밍업
    실패는 호출측(HandTracker)이 받아 CPU 로 폴백한다.
    """
    return want_gpu()


def describe() -> str:
    """현재 가속 상태를 사람이 읽는 한 줄 요약(정책 + 실제 하드웨어 유무)."""
    parts = [f"정책={gpu_mode()}"]
    cuda = _cuda_present()
    if cuda:
        name = "?"
        try:
            import torch
            name = torch.cuda.get_device_name(0)
        except Exception:
            pass
        parts.append(f"torch.CUDA=사용가능({name})")
    else:
        parts.append("torch.CUDA=없음")
    occ = opencv_cuda_count()
    parts.append(f"OpenCV.CUDA={occ}")
    eff = "GPU시도" if want_gpu() else "CPU강제"
    parts.append(f"→비전={eff}")
    return " · ".join(parts)


if __name__ == "__main__":
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass
    print("=" * 56)
    print(" common/accel.py — 하드웨어 가속 탐지")
    print("=" * 56)
    print(f"  gpu_mode()            : {gpu_mode()}")
    print(f"  want_gpu()            : {want_gpu()}")
    print(f"  torch CUDA(실하드웨어) : {_cuda_present()}")
    print(f"  torch_device()        : {torch_device()}")
    print(f"  opencv_cuda_count()   : {opencv_cuda_count()}")
    print(f"  mediapipe_prefer_gpu(): {mediapipe_prefer_gpu()}")
    print("-" * 56)
    print(f"  요약: {describe()}")
