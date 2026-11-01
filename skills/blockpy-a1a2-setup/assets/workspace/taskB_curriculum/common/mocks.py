"""common.mocks — 공유 테스트 데이터 / 팩토리 (하드웨어·API 키 불필요)

목적
----
vision.py(카메라/색검출/제스처)·ai_clients.py(LLM/VLM/STT)의 Mock 구현과
pytest 테스트가 **공통으로 재사용**하는 결정적(deterministic) 가짜 데이터와
팩토리 함수를 한곳에 모은다. 하드웨어나 API 키가 없어도 import·실행되어야 하므로
numpy 같은 무거운/외부 의존 import는 try/except로 감싸 자동 폴백한다(ADR-0004).

제공 항목
--------
- make_color_frame(colors) -> ndarray   : 색 블록이 박힌 BGR 프레임 생성(테스트 입력)
- SAMPLE_HAND_LANDMARKS : dict           : 제스처별 21점 손 랜드마크 샘플
- SAMPLE_AUDIO_TEXT     : dict           : STT가 돌려줄 캔드(canned) 음성 인식 텍스트
- CANNED_LLM_RESPONSES  : dict           : 키워드별 LLM 캔드 응답(소크라테스식 발문)
- CANNED_VLM_RESPONSES  : dict           : 색/장면별 VLM 캔드 묘사
- DEFAULT_PALETTE       : dict           : 색이름 -> BGR 기준값(색검출 mock과 공유)
- canned_llm(messages, system) -> str    : 메시지에서 키워드 매칭해 LLM 응답 선택
- canned_vlm(prompt) -> str              : 프롬프트에서 키워드 매칭해 VLM 응답 선택
- canned_stt(audio_path) -> str          : 경로/파일명에서 캔드 STT 텍스트 선택

사용법
-----
    from common import mocks
    frame = mocks.make_color_frame(["red", "blue"])      # 빨강·파랑 블록 프레임
    lm = mocks.SAMPLE_HAND_LANDMARKS["fist"]             # 주먹 제스처 랜드마크
    reply = mocks.canned_llm([{"role": "user", "content": "무한루프 도와줘"}])

자가 데모(무하드웨어):
    python -m common.mocks      # 생성 데이터 요약을 출력
"""

from __future__ import annotations

# ── numpy import 보호: 없으면 경량 폴백으로 자동 전환 ────────────────────────
# (교육용 환경에서 numpy 미설치 시에도 import·mock 실행이 되어야 한다.)
try:
    import numpy as np  # 정상 경로: 진짜 ndarray 사용

    _HAS_NUMPY = True
except Exception:  # pragma: no cover - 환경에 numpy가 없을 때만 진입
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False


# 프레임 기본 크기(가로 x 세로). 작은 크기로 테스트를 가볍게 유지한다.
FRAME_W = 320
FRAME_H = 240


# ── 색 팔레트: 색이름 -> BGR(파랑,초록,빨강) 기준값 ──────────────────────────
# OpenCV 관례를 따라 채널 순서는 BGR. detect_colors mock과 테스트가 공유한다.
DEFAULT_PALETTE: dict[str, tuple[int, int, int]] = {
    "red": (40, 40, 220),     # 빨강(R 강조)
    "green": (40, 200, 40),   # 초록(G 강조)
    "blue": (220, 60, 40),    # 파랑(B 강조)
    "yellow": (40, 220, 220), # 노랑(G+R)
    "black": (20, 20, 20),    # 검정(배경/물체)
    "white": (240, 240, 240), # 흰색
}


def make_color_frame(colors=None, width: int = FRAME_W, height: int = FRAME_H):
    """색 블록이 가로로 나란히 박힌 BGR 프레임을 생성한다(테스트 입력용).

    Args:
        colors: 색이름 리스트(DEFAULT_PALETTE 키). 예: ["red", "blue"].
                None이면 단색 회색 배경만 반환. 모르는 색이름은 회색으로 처리.
        width, height: 프레임 크기(px).

    Returns:
        np.ndarray (height, width, 3) uint8 — numpy가 있으면 진짜 배열,
        없으면 동일 형상을 흉내 내는 경량 _FakeFrame(테스트에서 shape만 확인 가능).

    블록 배치: 프레임을 색 개수만큼 세로 띠로 등분하고, 각 띠 중앙에
    사각형을 채워 detect_colors가 색/위치를 찾을 수 있게 한다.
    """
    colors = list(colors or [])

    # 회색(128) 배경으로 시작 — 색 블록이 도드라지도록.
    if _HAS_NUMPY:
        frame = np.full((height, width, 3), 128, dtype=np.uint8)
    else:  # numpy 폴백: 형상만 흉내 내는 경량 객체
        frame = _FakeFrame((height, width, 3), fill=128)

    if not colors:
        return frame  # 색 지정이 없으면 배경만 반환

    n = len(colors)
    band = max(1, width // n)  # 색 하나가 차지할 가로 띠 폭

    for i, name in enumerate(colors):
        # 모르는 색은 회색(중립)으로 — 테스트가 깨지지 않게 방어.
        bgr = DEFAULT_PALETTE.get(name, (128, 128, 128))

        # 이 색 띠의 좌우 경계.
        x0 = i * band
        x1 = width if i == n - 1 else (i + 1) * band

        # 띠 안쪽에 여백을 두고 사각형을 채운다(가장자리 노이즈 방지).
        pad_x = max(2, band // 6)
        pad_y = max(2, height // 6)
        bx0, bx1 = x0 + pad_x, x1 - pad_x
        by0, by1 = pad_y, height - pad_y

        if _HAS_NUMPY:
            # BGR 순서로 각 채널을 채운다.
            frame[by0:by1, bx0:bx1] = bgr
        else:
            frame.fill_rect(bx0, by0, bx1, by1, bgr)

    return frame


class _FakeFrame:
    """numpy 미설치 시 ndarray를 대신하는 최소 폴백.

    테스트가 frame.shape / len() 정도만 보는 경우를 지원한다.
    실제 픽셀 연산은 지원하지 않으며, 색검출 mock은 캔드 결과를 반환한다.
    """

    def __init__(self, shape: tuple[int, int, int], fill: int = 0):
        self.shape = shape           # (H, W, C)
        self.dtype = "uint8(fake)"   # 표시용
        self._fill = fill
        # 실제 데이터는 보관하지 않는다(메모리 절약). 형상 정보만 유지.

    def fill_rect(self, x0, y0, x1, y1, bgr):
        """진짜 그리기는 생략 — 폴백에서는 no-op(형상 검사만 통과시키면 충분)."""
        return None

    def __len__(self):
        return self.shape[0]

    def __repr__(self):
        return f"_FakeFrame(shape={self.shape})"


# ── 손 랜드마크 샘플 (MediaPipe Hands: 21점, 정규화 좌표 0~1) ────────────────
# 각 점은 {"x","y","z"}. classify_gesture가 이 데이터로 'open/fist/point/pinch'
# 를 구분할 수 있도록 손가락 펴짐/접힘을 단순화해 구성했다.
# 인덱스 의미(요약): 0=손목, 4=엄지끝, 8=검지끝, 12=중지끝, 16=약지끝, 20=새끼끝.
def _pt(x: float, y: float, z: float = 0.0) -> dict[str, float]:
    """랜드마크 한 점(정규화 좌표) 생성 헬퍼."""
    return {"x": round(x, 3), "y": round(y, 3), "z": round(z, 3)}


def _make_landmarks(finger_tips_y) -> list[dict[str, float]]:
    """21점 랜드마크를 단순 생성. finger_tips_y로 손가락 펴짐 정도를 조절.

    finger_tips_y: (thumb, index, middle, ring, pinky) 각 끝점의 y값.
                   y가 작을수록(위쪽) '펴짐', 클수록(아래쪽) '접힘'으로 해석.
    손목(0)은 y=0.9 부근에 고정하고 나머지는 보기 좋게 배치한다.
    """
    th, idx, mid, rng, pky = finger_tips_y
    lm = [_pt(0.5, 0.9)]  # 0: 손목

    # 엄지(1~4): x를 좌측으로 벌려 배치
    lm += [_pt(0.40, 0.80), _pt(0.34, 0.74), _pt(0.30, 0.70), _pt(0.27, th)]
    # 검지(5~8)
    lm += [_pt(0.45, 0.65), _pt(0.45, 0.55), _pt(0.45, 0.48), _pt(0.45, idx)]
    # 중지(9~12)
    lm += [_pt(0.52, 0.64), _pt(0.52, 0.54), _pt(0.52, 0.47), _pt(0.52, mid)]
    # 약지(13~16)
    lm += [_pt(0.59, 0.65), _pt(0.59, 0.56), _pt(0.59, 0.50), _pt(0.59, rng)]
    # 새끼(17~20)
    lm += [_pt(0.66, 0.68), _pt(0.66, 0.60), _pt(0.66, 0.55), _pt(0.66, pky)]
    return lm


# 제스처별 대표 랜드마크. y가 작을수록 '펴짐'(위로 뻗음).
SAMPLE_HAND_LANDMARKS: dict[str, list[dict[str, float]]] = {
    # 손바닥 펼침: 모든 손가락 끝이 위쪽(작은 y).
    "open": _make_landmarks((0.30, 0.20, 0.18, 0.22, 0.28)),
    # 주먹: 모든 손가락 끝이 손바닥 쪽(큰 y, 접힘).
    "fist": _make_landmarks((0.66, 0.62, 0.60, 0.62, 0.64)),
    # 가리키기: 검지만 펴고 나머지는 접힘.
    "point": _make_landmarks((0.66, 0.18, 0.60, 0.62, 0.64)),
    # 핀치(엄지+검지 끝이 가까움): 두 끝점을 의도적으로 근접 배치.
    "pinch": _make_landmarks((0.45, 0.46, 0.60, 0.62, 0.64)),
}
# 핀치는 '거리'가 핵심이므로 엄지끝(4)·검지끝(8)의 x도 가깝게 보정한다.
SAMPLE_HAND_LANDMARKS["pinch"][4]["x"] = 0.44
SAMPLE_HAND_LANDMARKS["pinch"][8]["x"] = 0.46


# ── STT 캔드 텍스트: 오디오 파일 키워드 -> 인식 결과(한국어) ─────────────────
SAMPLE_AUDIO_TEXT: dict[str, str] = {
    "default": "빨간 블록을 집어서 오른쪽으로 옮겨 줘",
    "pick": "빨간 블록을 집어 줘",
    "place": "파란 상자 위에 놓아 줘",
    "stop": "지금 멈춰",
    "home": "원점으로 돌아가",
    "hello": "안녕하세요, 두봇을 시작할게요",
}


# ── LLM 캔드 응답: 키워드 -> 소크라테스식 발문(정답 직접제시 금지) ───────────
# RAGTutor.socratic_hint 등이 mock 모드에서 재사용. 발문형/유도형으로 작성.
CANNED_LLM_RESPONSES: dict[str, str] = {
    "default": (
        "지금 코드에서 어떤 부분이 의도와 다르게 동작하는 것 같나요? "
        "한 줄씩 입력과 출력을 예상해 보면 어디서 어긋나는지 보일 거예요."
    ),
    "무한루프": (
        "반복문이 멈추는 조건이 무엇인지 먼저 확인해 볼까요? "
        "루프 안에서 그 조건을 실제로 변화시키고 있는지 살펴보세요."
    ),
    "들여쓰기": (
        "이 줄이 어느 블록에 속해야 하는지 생각해 볼까요? "
        "위 줄과 같은 깊이로 맞춰야 할지, 한 단계 안으로 들어가야 할지 비교해 보세요."
    ),
    "좌표": (
        "이동하려는 좌표가 로봇의 안전 작업영역 안에 있는지 먼저 확인해 볼까요? "
        "Z값을 너무 낮게 주면 어떤 위험이 생길지 함께 생각해 봅시다."
    ),
    "흡착": (
        "물체를 집기 전에 석션을 켰는지, 그리고 충분히 내려갔는지 순서를 점검해 볼까요? "
        "집은 다음에는 언제 다시 올라가야 할까요?"
    ),
    "에러": (
        "에러 메시지의 마지막 줄을 소리 내어 읽어 볼까요? "
        "어떤 이름이나 줄 번호가 보이나요? 그 위치부터 거슬러 올라가 봅시다."
    ),
}


# ── VLM 캔드 묘사: 키워드 -> 장면 설명(한국어) ──────────────────────────────
CANNED_VLM_RESPONSES: dict[str, str] = {
    "default": "테이블 위에 여러 색의 블록이 놓여 있습니다.",
    "red": "화면 중앙에 빨간색 블록이 하나 보입니다.",
    "blue": "왼쪽에 파란색 상자가 놓여 있습니다.",
    "color": "빨강, 초록, 파랑 블록이 나란히 놓여 있습니다.",
    "robot": "두봇 로봇팔이 작업대 위 물체 근처에 위치해 있습니다.",
    "hand": "사람의 손이 화면 안에서 무언가를 가리키고 있습니다.",
}


def _match(text: str, table: dict[str, str]) -> str:
    """text 안에 table의 키워드가 포함되면 해당 값을, 없으면 'default'를 반환.

    교육용 mock의 핵심: 같은 입력 -> 같은 출력(결정적)이라 테스트가 안정적이다.
    """
    low = (text or "").lower()
    for key, value in table.items():
        if key == "default":
            continue
        # 한글 키는 그대로, 영문 키는 소문자 비교로 포함 여부 확인.
        if key.lower() in low or key in (text or ""):
            return value
    return table["default"]


def canned_llm(messages, system: str = "") -> str:
    """LLM 캔드 응답을 선택한다(mock LLMClient.complete가 재사용).

    messages: [{"role","content"}, ...] — 마지막 user 발화에서 키워드를 찾는다.
    system: 시스템 프롬프트(현재는 매칭에 사용하지 않음, 시그니처 호환용).
    """
    # 마지막 사용자 발화를 추출(없으면 빈 문자열).
    last = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            last = str(m.get("content", ""))
            break
    return _match(last, CANNED_LLM_RESPONSES)


def canned_vlm(prompt: str) -> str:
    """VLM 캔드 묘사를 선택한다(mock VLMClient.describe가 재사용)."""
    return _match(prompt, CANNED_VLM_RESPONSES)


def canned_stt(audio_path: str) -> str:
    """STT 캔드 텍스트를 선택한다(mock STTClient.transcribe가 재사용).

    파일 경로/이름에 포함된 키워드로 결과를 고른다(예: 'pick.wav' -> 집기 명령).
    """
    name = (audio_path or "").lower()
    for key, value in SAMPLE_AUDIO_TEXT.items():
        if key == "default":
            continue
        if key in name:
            return value
    return SAMPLE_AUDIO_TEXT["default"]


# ── 색검출 캔드 결과: numpy 폴백 시 detect_colors mock이 쓸 기본 반환 ────────
def canned_detections(colors=None) -> list[dict]:
    """make_color_frame과 짝을 이루는 detect_colors 캔드 결과를 생성한다.

    실제 픽셀 분석 없이도(numpy 폴백 등) 테스트가 색/위치를 검증할 수 있게,
    프레임에 넣은 색 순서대로 bbox/center/area를 계산해 돌려준다.
    반환 형식은 CONTRACTS의 detect_colors와 동일: [{color,bbox,center,area}].
    """
    colors = list(colors or [])
    out: list[dict] = []
    n = max(1, len(colors))
    band = FRAME_W // n
    for i, name in enumerate(colors):
        # make_color_frame과 동일한 여백 규칙으로 bbox를 역산.
        x0 = i * band
        pad_x = max(2, band // 6)
        pad_y = max(2, FRAME_H // 6)
        bx0, bx1 = x0 + pad_x, x0 + band - pad_x
        by0, by1 = pad_y, FRAME_H - pad_y
        out.append({
            "color": name,
            "bbox": (bx0, by0, bx1, by1),                       # (x0,y0,x1,y1)
            "center": ((bx0 + bx1) // 2, (by0 + by1) // 2),     # 중심점
            "area": max(0, (bx1 - bx0) * (by1 - by0)),          # 픽셀 면적
        })
    return out


# ── 자가 데모: 무하드웨어로 생성 데이터 요약 출력 ───────────────────────────
if __name__ == "__main__":
    print("=== common.mocks 자가 데모 (mock, 무하드웨어) ===")
    print(f"numpy 사용 가능: {_HAS_NUMPY}")

    # 1) 색 프레임 생성
    demo_colors = ["red", "green", "blue"]
    frame = make_color_frame(demo_colors)
    print(f"\n[make_color_frame] colors={demo_colors}")
    print(f"  shape={frame.shape}, type={type(frame).__name__}")

    # 2) 색검출 캔드 결과
    dets = canned_detections(demo_colors)
    print(f"\n[canned_detections] {len(dets)}개 검출:")
    for d in dets:
        print(f"  - {d['color']}: center={d['center']}, area={d['area']}")

    # 3) 손 랜드마크 샘플
    print(f"\n[SAMPLE_HAND_LANDMARKS] 제스처 {list(SAMPLE_HAND_LANDMARKS)}")
    for g, lm in SAMPLE_HAND_LANDMARKS.items():
        print(f"  - {g}: 점 {len(lm)}개, 검지끝(8) y={lm[8]['y']}")

    # 4) STT 캔드 텍스트
    print("\n[canned_stt]")
    for sample in ["pick.wav", "stop_cmd.wav", "unknown.wav"]:
        print(f"  - {sample} -> {canned_stt(sample)!r}")

    # 5) LLM/VLM 캔드 응답
    print("\n[canned_llm]")
    msg = [{"role": "user", "content": "무한루프에 빠진 것 같아요"}]
    print(f"  - '무한루프' 질문 -> {canned_llm(msg)[:30]}...")
    print("\n[canned_vlm]")
    print(f"  - 'red object?' -> {canned_vlm('what red object is here?')!r}")

    print("\n=== 데모 완료: 모든 데이터가 결정적으로 생성됨 ===")
