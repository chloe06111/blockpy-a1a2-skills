# -*- coding: utf-8 -*-
"""common/calibration.py — 카메라 픽셀 → 로봇 좌표(mm) 4점 호모그래피 캘리브레이션.

목적
----
H1 VLA 확장(vision_pick/vision_place)의 좌표 변환 계층. Qwen3-VL 이 돌려준
"화면 픽셀 좌표"를 로봇팔이 이해하는 "작업평면 mm 좌표"로 바꾼다.
GUI 캘리브레이션 마법사가 (픽셀, 로봇) 대응쌍 4개 이상을 등록하면
DLT(Direct Linear Transform) 호모그래피를 **순수 numpy** SVD 로 푼다(cv2 금지).

수학 배경(교육용 요약)
----------------------
평면→평면 사영변환(호모그래피) H(3×3)는 [px, py, 1]·Hᵀ → [x', y', w] 에서
(x'/w, y'/w) 가 로봇 좌표가 된다. 대응쌍 하나당 방정식 2줄이 나오므로
미지수 8개(스케일 제외)를 풀려면 최소 4쌍이 필요하다. 쌍이 더 많으면
최소제곱 해(SVD 최소 특이벡터)가 되어 잡음에 강해진다.

핵심 원칙 (ADR-0004, 무하드웨어)
--------------------------------
- numpy 가 없어도 **import 는 절대 죽지 않는다**(solve 만 numpy 필요).
  pixel_to_robot/save/load 는 순수 파이썬으로 동작한다.
- config.py 에 CALIB_PATH 가 아직 없어도 방어적으로 기본 경로를 쓴다.

사용법
------
    from common.calibration import Calibration, DEFAULT_CALIB_PATH

    calib = Calibration()
    calib.add_pair((100, 100), (200, -50))   # (픽셀 xy) ↔ (로봇 mm xy)
    ... 4쌍 이상 등록 ...
    report = calib.solve()                    # {"mean_err_mm":.., "max_err_mm":..}
    rx, ry = calib.pixel_to_robot(320, 240)   # 픽셀 → 로봇 mm
    calib.save(DEFAULT_CALIB_PATH)
    calib2 = Calibration.load(DEFAULT_CALIB_PATH)   # H 포함 시 즉시 is_solved

자가 데모: python -m common.calibration  (합성 쌍으로 solve→변환→저장/복원 시연)
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Any

# sys.path 부트스트랩 — 단독 실행(python common/calibration.py)에서도
# `from common import ...` 가 되도록 코드 루트(taskB_curriculum)를 추가.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # pragma: no cover - reconfigure 미지원 환경
    pass

# ──────────────────────────────────────────────────────────────────────────
# 안전한 의존성 import — 없으면 폴백 (import 자체는 절대 실패하지 않음)
# ──────────────────────────────────────────────────────────────────────────
try:
    import numpy as np  # DLT 행렬 SVD 에만 사용
    _HAS_NUMPY = True
except Exception:  # pragma: no cover - numpy 미설치 환경 폴백
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

# config: CALIB_PATH 위임. 아직 CALIB_PATH 가 없거나 config 자체가 없어도 동작.
try:
    from common import config as _config
except Exception:  # pragma: no cover - config 미존재 시 기본 경로 사용
    _config = None  # type: ignore[assignment]

# 기본 캘리브레이션 저장 경로: config.CALIB_PATH 가 있으면 그 값,
# 없으면 <taskB_curriculum>/calibration.json (이 파일 기준 상위 폴더).
_TASKB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CALIB_PATH: str = str(getattr(
    _config, "CALIB_PATH", os.path.join(_TASKB_ROOT, "calibration.json"),
))

__all__ = ["Calibration", "DEFAULT_CALIB_PATH"]


def _project(h: list[list[float]], px: float, py: float) -> tuple[float, float]:
    """호모그래피 H 로 픽셀 (px, py) 를 사영한다: [px,py,1]·Hᵀ → (x/w, y/w).

    solve() 의 잔차 계산과 pixel_to_robot 이 공유하는 순수 함수.
    예외: w≈0 (픽셀이 소실선 위) → RuntimeError — 물리적으로 잘못된
          캘리브레이션 신호이므로 좌표를 지어내지 않고 멈춘다.
    """
    px, py = float(px), float(py)
    w = h[2][0] * px + h[2][1] * py + h[2][2]
    if abs(w) < 1e-12:
        raise RuntimeError(
            "호모그래피 특이점(w≈0)입니다 — 캘리브레이션을 다시 하세요.")
    x = (h[0][0] * px + h[0][1] * py + h[0][2]) / w
    y = (h[1][0] * px + h[1][1] * py + h[1][2]) / w
    return (float(x), float(y))


class Calibration:
    """4점(이상) 대응쌍으로 픽셀→로봇 호모그래피를 푸는 캘리브레이터.

    속성
    ----
    pairs : list[tuple[tuple[float, float], tuple[float, float]]]
        [((px, py), (rx, ry)), ...] — 등록된 (픽셀, 로봇 mm) 대응쌍.
    """

    def __init__(self) -> None:
        # 대응쌍: [((px, py), (rx, ry)), ...]
        self.pairs: list[tuple[tuple[float, float], tuple[float, float]]] = []
        # 풀린 호모그래피(행 우선 3×3). None 이면 미해결 상태.
        # 순수 파이썬 리스트로 보관 → numpy 없이도 변환/저장/복원 가능.
        self._H: list[list[float]] | None = None

    # ------------------------------------------------------------------ #
    # 대응쌍 관리
    # ------------------------------------------------------------------ #
    def add_pair(self, pixel_xy: tuple[float, float],
                 robot_xy: tuple[float, float]) -> None:
        """(픽셀 xy, 로봇 mm xy) 대응쌍 하나를 등록한다.

        새 쌍이 들어오면 기존 해(H)는 더 이상 유효하지 않으므로 무효화한다
        (다시 solve() 해야 is_solved 가 True 가 된다).
        """
        px, py = float(pixel_xy[0]), float(pixel_xy[1])
        rx, ry = float(robot_xy[0]), float(robot_xy[1])
        self.pairs.append(((px, py), (rx, ry)))
        self._H = None  # 데이터가 바뀌었으니 기존 해 무효화

    def clear(self) -> None:
        """등록된 대응쌍과 풀린 해를 모두 지운다(마법사 재시작용)."""
        self.pairs.clear()
        self._H = None

    @property
    def n_pairs(self) -> int:
        """등록된 대응쌍 개수."""
        return len(self.pairs)

    @property
    def is_solved(self) -> bool:
        """호모그래피가 풀려 pixel_to_robot 을 쓸 수 있는 상태인지."""
        return self._H is not None

    # ------------------------------------------------------------------ #
    # DLT 호모그래피 풀기 (순수 numpy SVD — cv2 불필요)
    # ------------------------------------------------------------------ #
    def solve(self) -> dict[str, float]:
        """등록쌍으로 DLT 호모그래피를 풀고 재투영 잔차 리포트를 돌려준다.

        각 쌍 ((u,v),(x,y)) 은 아래 두 방정식(2N×9 행렬의 두 행)을 만든다:
            [u, v, 1, 0, 0, 0, -x·u, -x·v, -x] · h = 0
            [0, 0, 0, u, v, 1, -y·u, -y·v, -y] · h = 0
        h(9) 는 SVD 의 최소 특이값 우측 특이벡터(= 최소제곱 해)로 구한다.

        반환: {"mean_err_mm": 평균 재투영 오차, "max_err_mm": 최대 재투영 오차}
        예외: n_pairs < 4 → ValueError("... 4점 필요 ..."),
              numpy 미설치 → RuntimeError(친절 안내),
              대응쌍 배치 퇴화(일직선/중복 등) → RuntimeError.
        실패 시 self._H 는 반드시 None 으로 남는다(is_solved=False) —
        잘못 풀린 H 로 로봇이 움직이는 일이 없게 한다("모르면 멈춘다").
        """
        if self.n_pairs < 4:
            raise ValueError(
                f"호모그래피를 풀려면 최소 4점 필요 (현재 {self.n_pairs}점)")
        if not _HAS_NUMPY:
            raise RuntimeError(
                "numpy 가 없어 캘리브레이션을 풀 수 없습니다. "
                "`pip install numpy` 후 다시 시도하세요.")

        # 2N×9 DLT 행렬 구성
        rows: list[list[float]] = []
        for (u, v), (x, y) in self.pairs:
            rows.append([u, v, 1.0, 0.0, 0.0, 0.0, -x * u, -x * v, -x])
            rows.append([0.0, 0.0, 0.0, u, v, 1.0, -y * u, -y * v, -y])
        a = np.asarray(rows, dtype=np.float64)

        # SVD: 최소 특이값의 우측 특이벡터가 ‖A·h‖ 최소화 해
        _, sv, vt = np.linalg.svd(a)
        # 퇴화 감지: 유일해가 존재하려면 rank(A)=8 이어야 한다. 4점이 일직선에
        # 가깝거나 겹치면 널공간이 2차원 이상이 되어 8번째 특이값이 0 으로
        # 무너진다(실측: 정상 배치 sv[7]/sv[0]≈1e-6, 일직선 ≤1e-17).
        # (h=vt[-1] 은 SVD 단위벡터라 norm(h)==1 — norm 검사로는 못 잡는다.)
        if float(sv[7]) <= 1e-9 * float(sv[0]):
            raise RuntimeError(
                "대응쌍 배치가 퇴화했습니다(4점이 한 직선에 가깝거나 겹침) — "
                "점 배치를 넓게 바꿔 다시 캘리브레이션하세요.")
        hm = vt[-1].reshape(3, 3)
        # 보기 좋게 H[2][2]=1 로 정규화(0 에 가까우면 스케일만 유지)
        if abs(float(hm[2, 2])) > 1e-12:
            hm = hm / hm[2, 2]
        cand = [[float(hm[i, j]) for j in range(3)] for i in range(3)]

        # 등록쌍 재투영 잔차(등록 데이터가 얼마나 잘 맞았는지 → GUI 표시용).
        # 후보 H(cand) 로 계산이 **전부 성공한 뒤에만** self._H 로 채택한다 —
        # 등록쌍이 소실선 위에 있으면(_project 의 w≈0) 해를 남기지 않고 중단.
        errs: list[float] = []
        try:
            for (u, v), (x, y) in self.pairs:
                rx, ry = _project(cand, u, v)
                errs.append(math.hypot(rx - x, ry - y))
        except RuntimeError:
            self._H = None  # 실패한 해가 is_solved/save 로 새지 않게 확정 무효화
            raise
        self._H = cand
        return {
            "mean_err_mm": float(sum(errs) / len(errs)),
            "max_err_mm": float(max(errs)),
        }

    # ------------------------------------------------------------------ #
    # 좌표 변환 (순수 파이썬 — numpy 불필요)
    # ------------------------------------------------------------------ #
    def pixel_to_robot(self, px: float, py: float) -> tuple[float, float]:
        """픽셀 좌표 (px, py) → 로봇 작업평면 좌표 (x, y) mm.

        [px, py, 1] 에 H 를 곱해 (x/w, y/w) 로 사영한다.
        예외: 미해결(is_solved=False) → RuntimeError.
        """
        if self._H is None:
            raise RuntimeError(
                "캘리브레이션이 풀리지 않았습니다 — solve() 또는 load() 를 먼저 하세요.")
        return _project(self._H, px, py)

    # ------------------------------------------------------------------ #
    # 저장/복원 (JSON — 순수 파이썬)
    # ------------------------------------------------------------------ #
    def save(self, path: str) -> None:
        """대응쌍과 (풀렸다면) H 를 JSON 으로 저장한다.

        형식: {"pairs": [[[px,py],[rx,ry]], ...], "H": [[..]*3] | null}
        """
        data: dict[str, Any] = {
            "pairs": [[[px, py], [rx, ry]] for (px, py), (rx, ry) in self.pairs],
            "H": self._H,  # 미해결이면 null 로 저장(상태 그대로 왕복)
        }
        parent = os.path.dirname(os.path.abspath(path))
        if parent:  # 하위 폴더가 없으면 만들어 준다(교실 PC 첫 실행 대비)
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "Calibration":
        """save() 가 만든 JSON 을 읽어 Calibration 을 복원한다.

        H 가 포함돼 있으면 즉시 is_solved=True (재-solve 불필요).
        파일이 없으면 FileNotFoundError 가 그대로 전파된다(호출측 판단).
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        calib = cls()
        for item in data.get("pairs") or []:
            (px, py), (rx, ry) = item[0], item[1]
            calib.add_pair((float(px), float(py)), (float(rx), float(ry)))
        h = data.get("H")
        if h is not None:
            # add_pair 가 해를 무효화하므로 반드시 쌍 등록 '후' 에 H 를 복원한다.
            calib._H = [[float(h[i][j]) for j in range(3)] for i in range(3)]
        return calib


# ──────────────────────────────────────────────────────────────────────────
# 자가 데모 — 합성 대응쌍으로 solve → 변환 → 저장/복원 (무하드웨어)
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(" common/calibration.py 자가 데모 (합성 4점 호모그래피)")
    print("=" * 60)
    print(f" numpy 사용 가능    : {_HAS_NUMPY}")
    print(f" DEFAULT_CALIB_PATH : {DEFAULT_CALIB_PATH}")

    # 알려진 어핀 변환(픽셀→mm): x = 0.5u + 100, y = -0.4v + 180 로 합성쌍 생성
    demo = Calibration()
    for (u_px, v_px) in [(0.0, 0.0), (640.0, 0.0), (0.0, 480.0), (640.0, 480.0)]:
        demo.add_pair((u_px, v_px), (0.5 * u_px + 100.0, -0.4 * v_px + 180.0))
    print(f"\n 등록쌍 {demo.n_pairs}개, is_solved={demo.is_solved}")

    if _HAS_NUMPY:
        rep = demo.solve()
        print(f" solve() 잔차: mean={rep['mean_err_mm']:.2e}mm "
              f"max={rep['max_err_mm']:.2e}mm")
        cx, cy = demo.pixel_to_robot(320.0, 240.0)
        print(f" 화면 중앙(320,240) → 로봇 ({cx:.1f}, {cy:.1f}) mm  "
              f"[기대 (260.0, 84.0)]")

        # 저장/복원 왕복 데모(임시 파일 → 즉시 삭제)
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "calib_demo.json")
            demo.save(p)
            back = Calibration.load(p)
            bx, by = back.pixel_to_robot(320.0, 240.0)
            print(f" save/load 왕복 후 동일 변환: ({bx:.1f}, {by:.1f}) mm, "
                  f"is_solved={back.is_solved}")
    else:  # pragma: no cover - numpy 없는 환경 안내
        print(" numpy 가 없어 solve 데모는 건너뜁니다(pip install numpy).")

    print("\n데모 완료. (GUI 마법사는 로봇 프리셋 4좌표 + 화면 클릭으로 쌍을 만든다)")
