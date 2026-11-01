"""common/local_scene.py — 로컬(무모델·무API) 장면 묘사 모듈.

목적
----
국립부산과학관 두봇 라이트 교육 커리큘럼의 H1(자연어 제어, VLM+LLM) 차시에서
"테이블 위에 무엇이 보이나?"를 **클라우드 VLM 없이** 한국어 문장으로 설명한다.
색 검출 결과(common.vision.detect_colors() 출력)만으로 결정적(deterministic)인
한국어 묘사 문장을 합성하므로, 카메라/모델/API 키가 없어도 교실에서 그대로
동작한다.

핵심 원칙 (ADR-0004)
--------------------
- **무거운 의존성·API 키 없이 import와 실행이 된다.** numpy/cv2 는 선택사항이며,
  없어도(또는 frame 이 None 이어도) 기본 해상도(640x480)로 안전하게 동작한다.
- **절대 예외를 던지지 않는다.** blocks 항목에 키가 빠져 있거나 형식이 어긋나도
  방어적으로 건너뛰고, 최악의 경우에도 사람이 읽을 수 있는 문장을 돌려준다.

설계 메모(향후 확장)
--------------------
여기서는 결정적 템플릿(좌표 → 한국어 위치어)으로 묘사를 만든다. 더 풍부한
묘사가 필요하면 이 자리에 로컬 VLM(예: transformers 기반 image captioning)을
끼워 넣을 수 있으나, **기본값은 GPU·추가 의존성이 필요 없는 이 템플릿 방식**이다
(교실 안전·재현성 우선).

사용법
------
    from common.vision import Camera, detect_colors
    from common.local_scene import describe_scene

    with Camera(mock=True) as cam:
        frame = cam.read()
    blocks = detect_colors(frame)            # [{color,bbox,center,area}, ...]
    print(describe_scene(blocks, frame))      # "테이블 위에 빨강 1개(왼쪽) ..."

자가 데모
---------
    python -m common.local_scene   (또는 직접 실행)
  → 몇 가지 블록 배치와 빈 장면에 대한 한국어 묘사를 출력한다.

인터페이스 계약: deliverables/pm/CONTRACTS.md  →  common/local_scene.py 절
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────
# 안전한 의존성 — numpy/cv2 는 선택. 없어도 frame=None 과 동일하게 동작한다.
# (frame.shape 로 해상도를 읽기 위해서만 numpy 가 쓰이며, 없으면 기본값 사용)
# ──────────────────────────────────────────────────────────────────────────
try:
    import numpy as np  # noqa: N813 (관례상 np)
    _HAS_NUMPY = True
except Exception:  # pragma: no cover - 환경에 numpy 가 없을 때만
    np = None
    _HAS_NUMPY = False


# 색 검출에서 나오는 표준(canonical) 색을 한국어로 표기하기 위한 매핑.
# vision.detect_colors() 가 돌려주는 color 값(red/green/blue/yellow)과 일치.
# 알 수 없는 색이 들어와도 영문 그대로 표기하므로 예외 없이 동작한다.
_COLOR_KO: dict[str, str] = {
    "red": "빨강",
    "green": "초록",
    "blue": "파랑",
    "yellow": "노랑",
}

# 프레임 크기를 못 구할 때 쓰는 기본 해상도(두봇 비전 합성 프레임 기본값과 동일).
_DEFAULT_W = 640
_DEFAULT_H = 480


# ──────────────────────────────────────────────────────────────────────────
# describe_scene — 색 검출 목록 → 한국어 장면 묘사 문장
# ──────────────────────────────────────────────────────────────────────────
def describe_scene(blocks, frame=None) -> str:
    """색 검출 결과를 한국어 한 문장으로 묘사한다(무모델·무API).

    파라미터
    --------
    blocks : list[dict]
        common.vision.detect_colors() 출력 형식
        [{color, bbox, center, area}, ...]. 각 항목에서 color 와 center 만 사용하며,
        키가 없거나 형식이 어긋나면 그 항목을 조용히 건너뛴다.
    frame : None | np.ndarray
        프레임. ndarray 면 frame.shape 로 (높이, 너비)를 읽어 위치 구간을
        나눈다. None 이거나 shape 를 못 읽으면 기본 640x480 을 사용.

    반환
    ----
    str : 한국어 묘사 문장.
        - 검출 없음 → "테이블 위에 인식된 블록이 없습니다."
        - 예시 → "테이블 위에 빨강 1개(왼쪽), 파랑 1개(오른쪽)가 있습니다. 총 2개."

    동작 규칙
    ---------
    - center x 를 프레임 너비의 1/3 단위로 나눠 왼쪽/가운데/오른쪽 으로 표기.
    - center y 를 프레임 높이의 1/3 단위로 나눠 멀리(위)/가운데/가까이(아래) 표기.
      (작은 y = 화면 위쪽 = 카메라에서 멀리)
    - 같은 색이 여러 개면 개수를 합치고, 대표 위치(가장 처음 항목 기준)를 함께 적는다.
    - **어떤 입력에도 예외를 던지지 않는다.**
    """
    # --- 1) 프레임 해상도 결정(없으면 기본값). 어떤 경우에도 예외 없이. -------
    w, h = _frame_size(frame)

    # --- 2) blocks 정규화: 반복 가능한지부터 방어 ----------------------------
    try:
        items = list(blocks) if blocks is not None else []
    except Exception:
        items = []

    if not items:
        return "테이블 위에 인식된 블록이 없습니다."

    # --- 3) 색별로 개수와 위치를 모은다 -------------------------------------
    # 표기 순서를 보존하기 위해 처음 등장 순서대로 색을 정리한다.
    order: list[str] = []                 # 색 등장 순서(표준화된 키)
    counts: dict[str, int] = {}           # 색 -> 개수
    first_pos: dict[str, str] = {}        # 색 -> 첫 등장 위치 문구(예: "왼쪽")

    for b in items:
        # 항목이 dict 가 아니면 건너뜀(방어).
        if not isinstance(b, dict):
            continue

        color_raw = b.get("color")
        if color_raw is None:
            continue
        color_key = str(color_raw)

        # 중심 좌표(center)에서 위치 문구 계산. center 가 없거나 형식이
        # 어긋나면 위치는 비워 둔다(개수만 셈).
        pos = _position_phrase(b.get("center"), w, h)

        if color_key not in counts:
            order.append(color_key)
            counts[color_key] = 0
            first_pos[color_key] = pos
        counts[color_key] += 1
        # 첫 항목에서 위치를 못 구했고 이후 항목에서 구했다면 보완.
        if not first_pos[color_key] and pos:
            first_pos[color_key] = pos

    # 유효한 색이 하나도 없었던 경우(예: 전부 color 키 누락) → 빈 장면 취급.
    if not order:
        return "테이블 위에 인식된 블록이 없습니다."

    # --- 4) 색별 구절을 조립한다 -------------------------------------------
    phrases: list[str] = []
    total = 0
    for color_key in order:
        ko = _COLOR_KO.get(color_key, color_key)  # 모르는 색은 영문 그대로
        n = counts[color_key]
        total += n
        pos = first_pos.get(color_key) or ""
        if pos:
            phrases.append(f"{ko} {n}개({pos})")
        else:
            phrases.append(f"{ko} {n}개")

    # "빨강 1개(왼쪽), 파랑 1개(오른쪽)가 있습니다. 총 2개."
    body = ", ".join(phrases)
    return f"테이블 위에 {body}가 있습니다. 총 {total}개."


# ──────────────────────────────────────────────────────────────────────────
# 내부 유틸 — 모두 예외를 던지지 않도록 방어
# ──────────────────────────────────────────────────────────────────────────
def _frame_size(frame):
    """frame 에서 (너비, 높이)를 구한다. 못 구하면 기본 640x480.

    frame 이 numpy ndarray 면 shape=(H, W, C) 에서 H, W 를 읽는다.
    None 이거나 shape 가 비정상이면 기본값으로 안전 폴백(예외 없음).
    """
    if frame is None:
        return _DEFAULT_W, _DEFAULT_H
    try:
        shape = getattr(frame, "shape", None)
        if shape is not None and len(shape) >= 2:
            h = int(shape[0])
            w = int(shape[1])
            # 0 이하면 기본값으로(0 나눗셈/음수 구간 방지)
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    return _DEFAULT_W, _DEFAULT_H


def _position_phrase(center, w, h) -> str:
    """중심 좌표 center=(cx, cy) → "왼쪽/가운데/오른쪽" + "멀리/가까이" 문구.

    - x 를 너비의 1/3 로 나눠 가로 위치(왼쪽/가운데/오른쪽).
    - y 를 높이의 1/3 로 나눠 깊이(멀리=위쪽, 가까이=아래쪽). 가운데 깊이는 생략.
    center 형식이 어긋나면 빈 문자열을 돌려준다(개수만 표기되도록).
    예) "왼쪽", "오른쪽 가까이", "가운데 멀리"
    """
    try:
        cx = float(center[0])
        cy = float(center[1])
    except Exception:
        return ""

    # 가로: [0, w/3) 왼쪽 · [w/3, 2w/3) 가운데 · [2w/3, w] 오른쪽
    third_w = w / 3.0
    if cx < third_w:
        horiz = "왼쪽"
    elif cx < 2.0 * third_w:
        horiz = "가운데"
    else:
        horiz = "오른쪽"

    # 세로(깊이): 작은 y = 위쪽 = 멀리, 큰 y = 아래쪽 = 가까이. 중간은 생략.
    third_h = h / 3.0
    if cy < third_h:
        depth = "멀리"
    elif cy >= 2.0 * third_h:
        depth = "가까이"
    else:
        depth = ""

    return f"{horiz} {depth}" if depth else horiz


# ──────────────────────────────────────────────────────────────────────────
# 자가 데모 — 하드웨어/모델/키 없이 한국어 장면 묘사 출력
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(" common/local_scene.py 자가 데모 (무모델·무API)")
    print("=" * 60)
    print(f" numpy 사용 가능 : {_HAS_NUMPY}")
    print("-" * 60)

    # 1) 기본 예시 — 빨강(왼쪽), 파랑(오른쪽)
    demo1 = [
        {"color": "red", "center": (120, 120), "bbox": (0, 0, 10, 10), "area": 100},
        {"color": "blue", "center": (520, 360), "bbox": (0, 0, 10, 10), "area": 100},
    ]
    print(" [예시1] 빨강(왼쪽 위)·파랑(오른쪽 아래)")
    print("   →", describe_scene(demo1))

    # 2) vision 합성 프레임의 캔드 검출과 동일한 배치(빨/초/파 가로 분산)
    demo2 = [
        {"color": "red", "center": (140, 240), "bbox": (85, 185, 110, 110), "area": 12100},
        {"color": "green", "center": (320, 240), "bbox": (265, 185, 110, 110), "area": 12100},
        {"color": "blue", "center": (500, 240), "bbox": (445, 185, 110, 110), "area": 12100},
    ]
    print(" [예시2] 빨/초/파 3개 가로 분산")
    print("   →", describe_scene(demo2))

    # 3) 같은 색 여러 개(개수 합산 확인)
    demo3 = [
        {"color": "yellow", "center": (100, 100), "bbox": (0, 0, 10, 10), "area": 100},
        {"color": "yellow", "center": (300, 250), "bbox": (0, 0, 10, 10), "area": 100},
        {"color": "red", "center": (600, 400), "bbox": (0, 0, 10, 10), "area": 100},
    ]
    print(" [예시3] 노랑 2개 + 빨강 1개")
    print("   →", describe_scene(demo3))

    # 4) 빈 장면
    print(" [예시4] 빈 장면")
    print("   →", describe_scene([]))

    # 5) 방어 점검 — 키 누락/형식 오류/None 입력에도 예외 없이 동작
    print(" [예시5] 방어 점검(키 누락·형식 오류·None)")
    print("   →", describe_scene([{"area": 100}, "garbage", {"color": "red"}]))
    print("   →", describe_scene(None))

    print("\n데모 완료.")
