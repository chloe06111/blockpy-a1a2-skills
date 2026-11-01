# -*- coding: utf-8 -*-
"""common/classifier.py — 저장된 AI 이미지 분류 모델을 '쉽게' 쓰는 고수준 API.

블록 코딩(중등)과 파이썬 코딩(고등)에서 **똑같이** 쓰는 얇은 래퍼다. BlockPy는
블록 ⇄ Python 이 1:1 이므로, 블록 학생이 끌어 쓰는 "모델로 분류하기" 블록이 곧
아래 함수 호출이고, 파이썬 학생은 같은 함수를 코드로 쓴다.

전제: 🎓 모델 만들기(웹캠 수집→학습→저장)로 `team_model.npz` 를 먼저 저장해 둔다.
      (common.vision_drive.VisionPolicy = 순수 numpy 소프트맥스 이미지 분류기)

예)
    from common.vision import Camera
    from common.classifier import recognize
    cam = Camera(mock=True)
    name, sure = recognize(cam)        # 카메라를 보고 "이게 뭐지?" → (이름, 확신도 0~1)
    if sure >= 0.8:
        print("이건", name)            # 예: 캔 / 플라스틱 / 종이
"""
from __future__ import annotations

from typing import Any, Tuple

from common.vision_drive import VisionPolicy, DEFAULT_MODEL_PATH


def load_model(path: str | None = None) -> VisionPolicy:
    """저장된 AI 모델(team_model.npz)을 불러온다. 경로를 안 주면 기본 저장 위치."""
    return VisionPolicy.load(path or DEFAULT_MODEL_PATH)


def classify(model: VisionPolicy, frame: Any) -> Tuple[str, float]:
    """불러온 모델로 사진 한 장(frame)을 분류한다. (이름, 확신도 0~1) 반환."""
    return model.predict(frame)


def recognize(camera: Any, path: str | None = None) -> Tuple[str, float]:
    """카메라에서 한 장을 찍어 저장된 모델로 분류한다 — 블록에서 한 줄로.

    (이름, 확신도 0~1) 반환. 매번 모델을 불러오므로 반복 호출이 많으면
    load_model() + classify() 로 나눠 쓰는 게 빠르다.
    """
    model = VisionPolicy.load(path or DEFAULT_MODEL_PATH)
    frame = camera.read()
    return model.predict(frame)


__all__ = ["load_model", "classify", "recognize"]
