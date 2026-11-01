# -*- coding: utf-8 -*-
"""학습된 시각 정책 — 카메라 이미지를 조향 클래스로 매핑하는 경량 분류기.

순수 numpy 소프트맥스 로지스틱 회귀. '녹음-재생'이 아니라 이미지→행동을 일반화하는
정책을 데이터에서 학습한다(가중치 = AI가 보는 곳). 학습/시험 정확도로 과적합을 관찰.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

from typing import Any

import numpy as np
import numpy.typing as npt

# 팀이 학습한 모델을 저장/불러올 기본 경로.
# GUI [모델 저장] 이 여기에 쓰고, scaffold.py --model 이 여기서 읽는다(같은 PC).
DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "team_model.npz"
)


def extract_features(
    frame: npt.NDArray[np.uint8], size: tuple[int, int] = (32, 24)
) -> npt.NDArray[np.float32]:
    """프레임(HxWx3 RGB uint8) → 다운스케일·그레이·정규화·평탄화 1D float32(0..1)."""
    arr = np.asarray(frame)
    if arr.ndim == 3:
        gray = arr.mean(axis=2)
    else:
        gray = arr.astype(np.float64)
    w, h = int(size[0]), int(size[1])
    height, width = gray.shape
    # 최근접 다운샘플(외부 의존 없이)
    ys = (np.linspace(0, height - 1, h)).astype(int)
    xs = (np.linspace(0, width - 1, w)).astype(int)
    small = gray[np.ix_(ys, xs)]
    return (small.reshape(-1) / 255.0).astype(np.float32)


def _softmax(z: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    result: npt.NDArray[np.float64] = e / e.sum(axis=1, keepdims=True)
    return result


class VisionPolicy:
    """이미지→조향 클래스 분류기(소프트맥스 로지스틱 회귀)."""

    def __init__(
        self, classes: list[str], feature_size: tuple[int, int] = (32, 24)
    ) -> None:
        self._classes = list(classes)
        self._idx = {c: i for i, c in enumerate(self._classes)}
        self.feature_size = (int(feature_size[0]), int(feature_size[1]))
        self._X: list[npt.NDArray[np.float32]] = []
        self._y: list[int] = []
        self._W: npt.NDArray[np.float64] | None = None
        self._b: npt.NDArray[np.float64] | None = None

    @property
    def classes(self) -> list[str]:
        return list(self._classes)

    @property
    def counts(self) -> dict[str, int]:
        d = {c: 0 for c in self._classes}
        for yi in self._y:
            d[self._classes[yi]] += 1
        return d

    @property
    def is_trained(self) -> bool:
        return self._W is not None

    def add_example(self, frame: npt.NDArray[np.uint8], label: str) -> None:
        if label not in self._idx:
            raise ValueError(f"알 수 없는 라벨: {label!r} (classes={self._classes!r})")
        self._X.append(extract_features(frame, self.feature_size))
        self._y.append(self._idx[label])

    def train(
        self,
        epochs: int = 200,
        lr: float = 0.5,
        val_ratio: float = 0.2,
        seed: int = 0,
    ) -> dict[str, Any]:
        if not self._X:
            raise RuntimeError("학습 예시가 없습니다. add_example()으로 데이터를 먼저 모으세요.")
        X = np.stack(self._X).astype(np.float64)
        y = np.array(self._y, dtype=int)
        n, d = X.shape
        k = len(self._classes)
        rng = np.random.default_rng(seed)
        perm = rng.permutation(n)
        X, y = X[perm], y[perm]
        n_val = int(round(n * val_ratio))
        Xv, yv = X[:n_val], y[:n_val]
        Xt, yt = X[n_val:], y[n_val:]
        if len(Xt) == 0:  # val_ratio 과대 방지
            Xt, yt, Xv, yv = X, y, X[:0], y[:0]
        W = np.zeros((d, k))
        b = np.zeros((1, k))
        Y = np.eye(k)[yt]
        m = len(Xt)
        for _ in range(int(epochs)):
            P = _softmax(Xt @ W + b)
            gW = Xt.T @ (P - Y) / m
            gb = (P - Y).mean(axis=0, keepdims=True)
            W -= lr * gW
            b -= lr * gb
        self._W, self._b = W, b
        train_acc = float((np.argmax(_softmax(Xt @ W + b), axis=1) == yt).mean())
        if len(Xv):
            pv = np.argmax(_softmax(Xv @ W + b), axis=1)
            val_acc = float((pv == yv).mean())
            conf = np.zeros((k, k), dtype=int)
            for t, pr in zip(yv, pv):
                conf[t, pr] += 1
        else:
            val_acc, conf = train_acc, np.zeros((k, k), dtype=int)
        return {
            "train_acc": train_acc,
            "val_acc": val_acc,
            "confusion": conf,
            "n_train": len(Xt),
            "n_val": len(Xv),
        }

    def predict(self, frame: npt.NDArray[np.uint8]) -> tuple[str, float]:
        if self._W is None or self._b is None:
            raise RuntimeError("학습되지 않았습니다. train()을 먼저 호출하세요.")
        f = extract_features(frame, self.feature_size).astype(np.float64)[None, :]
        p = _softmax(f @ self._W + self._b)[0]
        i = int(np.argmax(p))
        return self._classes[i], float(p[i])

    def predict_proba(self, frame: npt.NDArray[np.uint8]) -> dict[str, float]:
        """클래스별 확률 전체를 반환(합=1). 티처블머신식 신뢰도 막대 표시용."""
        if self._W is None or self._b is None:
            raise RuntimeError("학습되지 않았습니다. train()을 먼저 호출하세요.")
        f = extract_features(frame, self.feature_size).astype(np.float64)[None, :]
        p = _softmax(f @ self._W + self._b)[0]
        return {c: float(p[i]) for i, c in enumerate(self._classes)}

    def save(self, path: str) -> None:
        if self._W is None or self._b is None:
            raise RuntimeError("학습되지 않아 저장할 수 없습니다.")
        np.savez(
            path,
            W=self._W,
            b=self._b,
            classes=np.array(self._classes),
            fs=np.array(self.feature_size),
        )

    @classmethod
    def load(cls, path: str) -> "VisionPolicy":
        d = np.load(path, allow_pickle=False)
        fs = d["fs"]
        obj = cls([str(c) for c in d["classes"]], (int(fs[0]), int(fs[1])))
        obj._W, obj._b = d["W"], d["b"]
        return obj
