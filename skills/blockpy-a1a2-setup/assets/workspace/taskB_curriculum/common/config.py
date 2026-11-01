"""common/config.py — 중앙 설정 모듈 (커리큘럼 전역 공통 설정)

목적
----
교육용 두봇(Dobot Magician Lite) 커리큘럼의 모든 단계가 공유하는 설정값을
한곳에 모아 둡니다. AI 클라이언트, 로봇 제어, 카메라 등 다른 모듈은 이 파일의
값을 읽어 동작 모드를 결정합니다.

핵심 원칙 (ADR-0004)
--------------------
하드웨어(로봇/카메라)나 API 키가 **없어도** import와 mock 실행이 가능해야 합니다.
따라서:
  * pydobot / pyserial 같은 하드웨어 의존 라이브러리는 try/except로 감싸 import 하고,
    없으면 자동으로 mock 모드로 폴백합니다.
  * ANTHROPIC_API_KEY 환경변수가 없으면 AI 호출도 mock 으로 동작합니다.
  * CURRICULUM_FORCE_MOCK=1 로 언제든 강제 mock 을 켤 수 있습니다.

사용법
------
    from common import config            # 또는 import common.config as config

    if config.is_mock():
        print("mock 모드로 동작합니다 (하드웨어/키 없음)")

    port = config.DOBOT_PORT             # None 이면 자동탐지
    model = config.LLM_MODEL

직접 실행하면 현재 설정을 출력합니다(자가 데모):
    python -m common.config
    python common/config.py

순수 표준 라이브러리(os)만 사용합니다 — 추가 설치 불필요.
"""

import os  # 환경변수 읽기에 사용(표준 라이브러리만)


# ---------------------------------------------------------------------------
# 1) 환경변수 헬퍼
# ---------------------------------------------------------------------------
def _env_true(name: str) -> bool:
    """환경변수가 '참'을 의미하는 값인지 판정한다.

    '1', 'true', 'yes', 'on'(대소문자 무관)을 참으로 본다.
    값이 없으면 False.
    """
    # 환경변수를 읽어 공백 제거 후 소문자로 정규화
    raw = os.environ.get(name, "").strip().lower()
    # 흔히 쓰는 참 표현들과 비교
    return raw in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# 2) 환경변수에서 직접 읽는 설정값
# ---------------------------------------------------------------------------

# 로봇 시리얼 포트. 지정하지 않으면 None → 연결 시 자동탐지(pydobot/list_ports).
#   예) Windows: "COM3" / Linux: "/dev/ttyUSB0"
DOBOT_PORT: "str | None" = os.environ.get("DOBOT_PORT") or None

# Anthropic API 키. 없으면 None → AI 클라이언트는 mock 응답으로 동작.
ANTHROPIC_API_KEY: "str | None" = os.environ.get("ANTHROPIC_API_KEY") or None


# ---------------------------------------------------------------------------
# 2-b) 엔드이펙터 / 집기(그래스프) 설정 — 실측 캘리브레이션 (실제 하드웨어 검증값)
# ---------------------------------------------------------------------------
# EFFECTOR: 부착한 엔드이펙터 종류. "gripper"(그리퍼: 잡기/놓기) | "suction"(흡착컵).
#   사용자의 실제 두봇 매지션 라이트는 '그리퍼'를 사용한다(실측 검증).
#   환경변수 DOBOT_EFFECTOR 로 덮어쓸 수 있다(예: "suction").
EFFECTOR = os.environ.get("DOBOT_EFFECTOR", "gripper")  # "gripper" | "suction"

# GRASP_Z: 블록을 집는(그래스프) 하강 높이(mm). 실측 캘리브레이션값.
#   초록 매트 위 블록 몸통을 그리퍼가 감싸는 높이로, 실제 하드웨어 테스트로 검증되었다.
#   교구/책상 높이가 다르면 이 값(또는 DOBOT_GRASP_Z 환경변수)을 조정한다.
GRASP_Z = float(os.environ.get("DOBOT_GRASP_Z", "-25"))  # 집기 높이(mm), 실측값(교구/책상에 맞춰 조정)

# BACKGROUND_COLORS: 매트/배경으로 '항상 무시'할 색 목록(실측 버그 대응).
#   사용자의 매트가 초록색이라, 카메라에 매트가 작게 보여도 '초록 블록'으로 오검출되는
#   문제가 있었다. 이 목록에 속한 색은 비전 단계에서 무조건 배경으로 제외한다(매트색).
#   기본 ["green"]. 환경변수 DOBOT_BG_COLORS(콤마구분, 예: "green,gray")로 변경한다.
BACKGROUND_COLORS = [c.strip() for c in os.environ.get("DOBOT_BG_COLORS", "green").split(",") if c.strip()]


# ---------------------------------------------------------------------------
# 2-c) 카메라 인덱스 — 환경 강건화 (실측 버그 대응)
# ---------------------------------------------------------------------------
# OpenCV(VideoCapture)의 카메라 인덱스는 **환경 의존**이며, 어떤 카메라가 먼저
# enable 되는지(드라이버 로드 순서/USB 허브/노트북 내장캠 on-off)에 따라 0↔1 이
# 런타임마다 바뀔 수 있다. 실측: 노트북 웹캠을 켜자 index 0↔1 이 스왑되어,
# 차시 코드가 `Camera(source=0)`/`VideoCapture(0)` 로 하드코딩돼 있으면 엉뚱한
# 카메라를 열어 동작이 틀어졌다.
#   → 차시는 인덱스 숫자 대신 아래 두 '의미 있는 이름'을 쓴다. 환경이 바뀌어
#     인덱스가 스왑되면 코드 수정 없이 환경변수만 조정하면 된다.
#
#   CAM_HAND  : 사용자를 향한 카메라(손/제스처용). M2 가위바위보, H2 텔레오퍼레이션.
#   CAM_TABLE : 위에서 책상/매트를 내려다보는 카메라(블록/색상용). M1 색상분류,
#               H1 VLM 장면설명, A1 음성 색블록 정리.
#
# 현재 사용자 환경 기준 기본값: index 0 = 노트북 웹캠(사용자 향함, 손 제스처용),
#                              index 1 = 책상/두봇 카메라(위에서 매트, 블록용).
# 인덱스가 스왑되면 환경변수로 조정한다(예: 손=1, 책상=0 으로 바뀐 경우):
#   set DOBOT_CAM_HAND=1   /   set DOBOT_CAM_TABLE=0   (Windows)
#   export DOBOT_CAM_HAND=1 ; export DOBOT_CAM_TABLE=0 (Linux/macOS)
CAM_HAND = int(os.environ.get("DOBOT_CAM_HAND", "0"))    # 사용자 향함(제스처 M2/H2)
CAM_TABLE = int(os.environ.get("DOBOT_CAM_TABLE", "1"))  # 위에서 매트(블록 M1/H1/A1)


# ---------------------------------------------------------------------------
# 2-d) 하드웨어 가속(GPU) 사용 정책 — 비전 처리가 CPU로 버거울 때
# ---------------------------------------------------------------------------
# CPU만으로 mediapipe 손추적/YOLO 객체검출이 느릴 수 있어, '가능하면' GPU를 쓴다.
# 가속이 불가하거나 초기화에 실패하면 항상 CPU로 안전 폴백한다(동작 보장).
#   "auto"(기본): GPU 가능하면 GPU, 아니면 CPU.
#   "on"/"1"    : GPU 우선(초기화/워밍업 실패 시 CPU 폴백).
#   "off"/"0"   : 강제 CPU.
# 적용 대상(common/accel.py 가 탐지·결정): mediapipe HandLandmarker GPU delegate,
#   YOLO(ultralytics)의 torch CUDA device. (OpenCV는 CUDA 빌드일 때만 해당)
USE_GPU = (os.environ.get("DOBOT_USE_GPU", "auto") or "auto").strip().lower()


# ---------------------------------------------------------------------------
# 3) AI 모델 기본값 (CONTRACTS 계약 고정값)
# ---------------------------------------------------------------------------

# 텍스트 LLM(소크라테스식 힌트 등)에 쓰는 기본 모델
LLM_MODEL = "claude-sonnet-4-6"

# 이미지 이해(VLM: 카메라 프레임 설명 등)에 쓰는 기본 모델
VLM_MODEL = "claude-sonnet-4-6"

# MiniMax(OpenAI 호환) — H1 자연어 제어 / A1 음성 오케스트레이션의 명령 해석용.
# 키는 환경변수 MINIMAX_API_KEY 로 주입한다(코드에 넣지 말 것).
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.5")
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")

# STT(로컬 whisper) 모델 크기: tiny/base/small/medium/large-v3.
# 한국어 정확도를 위해 기본을 "medium" 으로 둔다. faster-whisper 가 설치돼 있으면
# int8 로 CPU 에서도 medium 이 충분히 빠르다(권장: pip install faster-whisper).
# 교실 PC가 느리면 WHISPER_MODEL=small, 더 정확히는 large-v3 로 조정.
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")


# ---------------------------------------------------------------------------
# 3-b) H1 VLA 확장 — 시각 그라운딩(눈: 로컬 Qwen3-VL) · 픽셀→로봇 캘리브레이션
# ---------------------------------------------------------------------------
# "카메라에 보이는 것 집어줘"(vision_pick/vision_place)용 설정.
#   두뇌 = MiniMax(위 3절), 눈 = Qwen3-VL 2B(llama.cpp 로컬 서버, OpenAI 호환).
#   서버·모델·키가 없어도 GroundingClient 가 자동으로 mock 폴백한다(ADR-0004).
#   모든 값은 같은 이름의 환경변수로 덮어쓸 수 있다.

# 이 파일(common/) 기준 커리큘럼 루트(taskB_curriculum)의 절대경로.
_TASKB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 그라운딩 공급자: "qwen-local"(로컬 llama.cpp 서버) | "mock"(무서버 데모/테스트).
GROUNDING_PROVIDER = os.environ.get("GROUNDING_PROVIDER", "qwen-local")

# 로컬 Qwen3-VL 서버(OpenAI 호환)의 베이스 URL. ensure_server 기본 포트 8123 과 일치.
GROUNDING_URL = os.environ.get("GROUNDING_URL", "http://127.0.0.1:8123/v1")

# Qwen3-VL 2B GGUF 모델 / 멀티모달 프로젝터 / llama-server 실행파일 경로(이미 배치됨).
QWEN_MODEL_PATH = os.environ.get(
    "QWEN_MODEL_PATH",
    os.path.join(_TASKB_ROOT, "models", "Qwen3VL-2B-Instruct-Q4_K_M.gguf"))
QWEN_MMPROJ_PATH = os.environ.get(
    "QWEN_MMPROJ_PATH",
    os.path.join(_TASKB_ROOT, "models", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"))
LLAMA_SERVER_EXE = os.environ.get(
    "LLAMA_SERVER_EXE",
    os.path.join(_TASKB_ROOT, "models", "llamacpp", "llama-server.exe"))

# 픽셀→로봇 4점 호모그래피 캘리브레이션 저장 파일(JSON). common/calibration.py 가 사용.
CALIB_PATH = os.environ.get("CALIB_PATH", os.path.join(_TASKB_ROOT, "calibration.json"))

# vision_pick/vision_place 의 접근(호버) 높이·집기 하강 높이(mm).
VISION_Z_HOVER = float(os.environ.get("VISION_Z_HOVER", "40.0"))  # 실측 필요(테이블·블록 높이)
VISION_Z_PICK = float(os.environ.get("VISION_Z_PICK", "-40.0"))   # 실측 필요(테이블·블록 높이)

# 캘리브레이션 마법사(H1 GUI)의 프리셋 4좌표 — 로봇 작업평면 (x, y) mm.
#   마법사가 로봇을 이 4지점으로 순차 이동시키고, 강사가 각 지점의 엔드이펙터를
#   카메라 화면에서 클릭해 (픽셀, 로봇) 대응쌍 4개를 만든다(4점 호모그래피).
#   조건: WORKSPACE 안 + 카메라 화면 안 + 넓게 퍼진 사각형(퇴화 배치 금지).
CALIB_PRESETS = [           # 실측 필요(교실 카메라 화각 안에 4점이 다 보이는지 확인)
    (200.0, -80.0),
    (200.0, 80.0),
    (300.0, 80.0),
    (300.0, -80.0),
]


# ---------------------------------------------------------------------------
# 4) 작업영역(WORKSPACE) — Magician Lite 보수적 안전 한계
# ---------------------------------------------------------------------------
# 단위: x,y,z 는 mm, r 은 deg.
# safety.check_move / clamp_move 가 이 범위로 좌표를 검사·클램프한다.
# 강사매뉴얼과 일치하는 '보수적' 기본값으로, 실제 기구 한계보다 안쪽으로 잡아 둔다.
WORKSPACE = {
    "x": (180, 320),    # 전후 방향 도달 범위(mm). 너무 가까우면 자기 베이스와 충돌 위험
    "y": (-150, 150),   # 좌우 방향(mm)
    "z": (-60, 150),    # 높이(mm). 음수는 책상 면 아래로 내려가는 흡착/그립 동작용
    "r": (-150, 150),   # 엔드이펙터 회전(deg)
}


# ---------------------------------------------------------------------------
# 5) 하드웨어 의존 라이브러리 가용성 점검 (없으면 mock 유도)
# ---------------------------------------------------------------------------
# pydobot / pyserial 이 설치되어 있지 않으면 실제 로봇 제어가 불가능하므로
# 자동으로 mock 모드로 폴백한다. import 자체는 절대 실패하지 않도록 try/except 로 감싼다.
try:
    import serial  # type: ignore[import-untyped]  # noqa: F401  (pyserial — pydobot 의 시리얼 통신 의존성)
    import pydobot  # type: ignore[import-untyped]  # noqa: F401  (순수 Python Dobot 드라이버)

    _HARDWARE_LIBS_AVAILABLE = True   # 두 라이브러리 모두 import 성공
except Exception:
    # 라이브러리 미설치/로드 실패 → 하드웨어 제어 불가로 간주
    _HARDWARE_LIBS_AVAILABLE = False

# opencv(cv2) 가용성 — 비전(카메라/색검출/제스처)의 실제 동작 가능 여부.
# LLM 키와 무관하다. (실제 웹캠이 없으면 vision 모듈이 합성 프레임으로 자동 폴백)
try:
    import cv2  # noqa: F401
    _CV2_AVAILABLE = True
except Exception:
    _CV2_AVAILABLE = False


# ---------------------------------------------------------------------------
# 6) USE_MOCK 자동판정
# ---------------------------------------------------------------------------
def _decide_use_mock() -> bool:
    """mock 모드 사용 여부를 자동 판정한다.

    다음 중 하나라도 해당하면 mock(True):
      1) CURRICULUM_FORCE_MOCK 환경변수가 참 → 강제 mock
      2) ANTHROPIC_API_KEY 가 없음 → AI 호출 불가
      3) pydobot/serial import 실패 → 로봇 제어 불가
    """
    # 1) 강제 mock 스위치가 켜져 있으면 즉시 True
    if _env_true("CURRICULUM_FORCE_MOCK"):
        return True
    # 2) AI 키가 없으면 AI 기능을 실제로 호출할 수 없으므로 mock
    if not ANTHROPIC_API_KEY:
        return True
    # 3) 하드웨어 라이브러리가 없으면 실제 로봇 제어 불가 → mock
    if not _HARDWARE_LIBS_AVAILABLE:
        return True
    # 위 조건이 모두 아니면 실제(real) 모드로 동작 가능
    return False


# 모듈 로드 시점에 한 번 자동 판정한 값(다른 모듈이 직접 참조하는 기본 플래그)
USE_MOCK: bool = _decide_use_mock()


def is_mock() -> bool:
    """현재 mock 모드인지 반환한다.

    CONTRACTS 계약 함수. 다른 모듈(dobot_ctl, ai_clients 등)은 mock 인자를
    명시하지 않았을 때 이 함수를 호출해 동작 모드를 결정한다.

    참고: 환경변수가 런타임에 바뀔 수 있으므로 매 호출 시 다시 판정해
    최신 상태를 반영한다(전역 USE_MOCK 도 함께 갱신).
    """
    global USE_MOCK
    # 호출 시점 기준으로 재판정하여 환경변수 변경을 반영
    USE_MOCK = _decide_use_mock()
    return USE_MOCK


# ---------------------------------------------------------------------------
# 6-b) 서브시스템별 mock 판정 (핵심: LLM 키 유무가 로봇/비전을 좌우하지 않게 분리)
#   - 로봇 : pydobot/serial 유무로만 결정 (LLM 키와 무관)
#   - 비전 : opencv(cv2) 유무로만 결정 (LLM 키와 무관; 실카메라 없으면 합성 폴백)
#   - AI   : ANTHROPIC_API_KEY 유무로만 결정 (Smart Tutor·H1·A1 에서만 사용)
#   CURRICULUM_FORCE_MOCK=1 이면 셋 다 강제 mock(오프라인 테스트용).
# 설계 원칙: LLM 은 '학생 개발 보조(Smart Tutor)'와 불가피한 H1 자연어·A1 음성에만
#           쓰며, 그 외 수업/로봇/비전은 LLM 없이 동작해야 한다.
# ---------------------------------------------------------------------------
def robot_is_mock() -> bool:
    """로봇을 mock 으로 돌릴지. FORCE_MOCK 또는 pydobot/serial 미설치일 때만 True.
    (LLM 키가 없어도 로봇은 실제로 구동되어야 한다.)"""
    if _env_true("CURRICULUM_FORCE_MOCK"):
        return True
    return not _HARDWARE_LIBS_AVAILABLE


def vision_is_mock() -> bool:
    """비전을 mock 으로 돌릴지. FORCE_MOCK 또는 opencv(cv2) 미설치일 때만 True.
    (실제 웹캠이 없으면 vision 모듈이 합성 프레임으로 자동 폴백한다.)"""
    if _env_true("CURRICULUM_FORCE_MOCK"):
        return True
    return not _CV2_AVAILABLE


def ai_is_mock() -> bool:
    """LLM/VLM/STT 를 mock 으로 돌릴지. FORCE_MOCK 또는 ANTHROPIC_API_KEY 없음."""
    if _env_true("CURRICULUM_FORCE_MOCK"):
        return True
    return not ANTHROPIC_API_KEY


# ---------------------------------------------------------------------------
# 7) 자가 데모 — 현재 설정 출력 (mock, 무하드웨어 실행 가능)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 키/하드웨어 없이도 안전하게 실행되는 설정 출력 데모
    print("=" * 56)
    print(" 두봇 커리큘럼 공통 설정 (common/config.py)")
    print("=" * 56)
    # 민감정보(API 키)는 값 자체가 아니라 '설정 여부'만 표시
    key_state = "설정됨" if ANTHROPIC_API_KEY else "없음"
    print(f"  USE_MOCK            : {USE_MOCK}  (is_mock()={is_mock()})")
    print(f"  CURRICULUM_FORCE_MOCK: {_env_true('CURRICULUM_FORCE_MOCK')}")
    print(f"  ANTHROPIC_API_KEY   : {key_state}")
    print(f"  하드웨어 라이브러리  : {'사용가능' if _HARDWARE_LIBS_AVAILABLE else '없음(mock 폴백)'}")
    print(f"  DOBOT_PORT          : {DOBOT_PORT if DOBOT_PORT else '(자동탐지)'}")
    print(f"  LLM_MODEL           : {LLM_MODEL}")
    print(f"  VLM_MODEL           : {VLM_MODEL}")
    print(f"  EFFECTOR            : {EFFECTOR}  (그리퍼/흡착)")
    print(f"  GRASP_Z (mm)        : {GRASP_Z}  (집기 하강 높이, 실측)")
    print(f"  BACKGROUND_COLORS   : {BACKGROUND_COLORS}  (매트/배경으로 항상 무시할 색)")
    print(f"  CAM_HAND  (index)   : {CAM_HAND}  (사용자 향함·손/제스처: M2/H2)")
    print(f"  CAM_TABLE (index)   : {CAM_TABLE}  (위에서 매트·블록/색상: M1/H1/A1)")
    print("     ※ 카메라 인덱스는 환경 의존(enable 시점에 0↔1 스왑 가능).")
    print("        스왑 시 DOBOT_CAM_HAND / DOBOT_CAM_TABLE 환경변수로 조정.")
    print("  WORKSPACE (mm/deg)  :")
    # 작업영역을 축별로 보기 좋게 출력
    for axis, (lo, hi) in WORKSPACE.items():
        print(f"     {axis} : {lo} ~ {hi}")
    print("=" * 56)
    # mock 판정 이유 안내(학생용 친절 메시지)
    if USE_MOCK:
        print(" → 현재 mock 모드입니다. 하드웨어/키 없이 학습용으로 동작합니다.")
    else:
        print(" → 실제(real) 모드: 로봇/AI 를 실제로 호출합니다. 작업 공간을 확보하세요.")
