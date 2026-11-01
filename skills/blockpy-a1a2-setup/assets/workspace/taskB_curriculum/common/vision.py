"""common/vision.py — 비전(카메라/색검출/객체검출/손제스처) 공통 모듈.

목적
----
국립부산과학관 두봇 라이트 교육 커리큘럼의 **비전 입력 계층**을 담당한다.
색 블록 픽앤플레이스, YOLO 객체검출, 손 제스처 기반 상호작용 차시가 모두
이 모듈의 동일한 인터페이스(CONTRACTS.md) 위에서 동작한다.

핵심 원칙 (ADR-0004)
--------------------
- **하드웨어·모델·API 키 없이도 import와 실행이 된다.** opencv / numpy /
  ultralytics(YOLO) / mediapipe 같은 무거운 의존성은 모두 try/except로 감싸,
  없으면 자동으로 mock 모드로 폴백한다.
- mock 모드에서는 numpy(있으면)로 합성 프레임(색상 블록 배치)을 만들고,
  검출기는 결정적인 캔드(canned) 결과를 돌려준다 → 교실에서 카메라가 없어도
  학생이 코드 흐름을 그대로 체험할 수 있다.

사용법
------
    from common.vision import Camera, detect_colors, YoloDetector, HandTracker

    with Camera(mock=True) as cam:          # 카메라 열기 (없으면 mock)
        frame = cam.read()                  # 한 프레임 획득(ndarray)
        blocks = detect_colors(frame)       # [{color,bbox,center,area}, ...]
        hands = HandTracker(mock=True).process(frame)
        gesture = HandTracker.classify_gesture(hands.get("landmarks"))

자가 데모
---------
    python -m common.vision      (또는 직접 실행)
  → mock 프레임을 만들어 색검출 결과와 제스처 분류 결과를 출력한다.

인터페이스 계약: deliverables/pm/CONTRACTS.md  →  common/vision.py 절
"""

from __future__ import annotations

# os: 모델 캐시 경로 계산·파일 존재 확인에 사용(표준 라이브러리 — 항상 가용).
import os

# ──────────────────────────────────────────────────────────────────────────
# 안전한 의존성 import — 없으면 mock으로 폴백 (하드웨어/모델/키 불필요)
# ──────────────────────────────────────────────────────────────────────────

# numpy: 프레임은 ndarray로 표현. 없으면 합성 프레임도 못 만들므로 가장 기초.
try:
    import numpy as np  # noqa: N813 (관례상 np)
    _HAS_NUMPY = True
except Exception:  # pragma: no cover - 환경에 numpy가 없을 때만
    np = None  # type: ignore[assignment]  # 이후 코드에서 _HAS_NUMPY로 분기
    _HAS_NUMPY = False

# opencv: HSV 변환·윤곽 검출·카메라 캡처에 사용. 없으면 mock 색검출로 폴백.
try:
    import cv2  # type: ignore
    _HAS_CV2 = True
except Exception:
    cv2 = None  # type: ignore[assignment]
    _HAS_CV2 = False

# config: 전역 mock 판정. 아직 작성 전이거나 import 실패해도 vision은 동작해야 함.
try:
    from common import config as _config  # type: ignore
except Exception:
    _config = None  # type: ignore[assignment]

# accel: GPU 가속 정책/탐지. 없거나 실패해도 vision 은 CPU 로 동작해야 함.
try:
    from common import accel as _accel  # type: ignore
except Exception:
    _accel = None  # type: ignore[assignment]


def _global_is_mock() -> bool:
    """config.is_mock()이 있으면 그 값을, 없으면 numpy 유무로 추정.

    config 모듈이 아직 없거나 import에 실패해도 vision 단독으로 동작하도록
    방어적으로 처리한다. numpy조차 없으면 무조건 mock.
    """
    if _config is not None:
        try:
            # 비전 전용 판정(vision_is_mock)을 우선 사용 — opencv 유무로만 결정하며
            # LLM 키와 무관(설계: 비전은 LLM 없이 동작). 구버전 호환으로 is_mock 폴백.
            decider = getattr(_config, "vision_is_mock", None) or getattr(_config, "is_mock", None)
            if decider is not None:
                return bool(decider())
        except Exception:
            pass
    # config가 없으면: numpy/opencv가 없으면 당연히 mock
    return not (_HAS_NUMPY and _HAS_CV2)


# ──────────────────────────────────────────────────────────────────────────
# 색상 팔레트 — HSV(OpenCV 기준: H 0~179, S 0~255, V 0~255) 임계 범위
#   빨강은 색상환 양끝(0 근처 + 179 근처)에 걸쳐 두 구간으로 나눈다.
#   각 값은 (BGR표시색, [ (low,high), ... ]) 형태.
# ──────────────────────────────────────────────────────────────────────────
DEFAULT_PALETTE: dict[str, dict] = {
    "red": {
        "bgr": (0, 0, 255),
        "ranges": [((0, 80, 60), (10, 255, 255)),
                   ((170, 80, 60), (179, 255, 255))],
    },
    "green": {
        "bgr": (0, 200, 0),
        "ranges": [((40, 60, 50), (85, 255, 255))],
    },
    "blue": {
        "bgr": (255, 0, 0),
        "ranges": [((100, 80, 50), (130, 255, 255))],
    },
    "yellow": {
        "bgr": (0, 220, 220),
        "ranges": [((20, 80, 80), (35, 255, 255))],
    },
}

# 검출로 인정할 최소 면적(픽셀). 너무 작은 잡음 블롭은 무시.
_MIN_AREA = 400


# ──────────────────────────────────────────────────────────────────────────
# Camera — 실제 웹캠 또는 mock(합성/샘플) 프레임 공급자
# ──────────────────────────────────────────────────────────────────────────
class Camera:
    """카메라 프레임 공급원.

    파라미터
    --------
    source : int | str
        OpenCV VideoCapture에 넘길 카메라 인덱스(0) 또는 동영상 경로.
    mock : bool | None
        None이면 config.is_mock()/환경으로 자동 판정. True면 강제 mock.
    sample_dir : str | None
        mock일 때 이 폴더의 이미지(jpg/png)를 순환 재생. 없으면 합성 프레임 생성.
    """

    def __init__(self, source=0, mock=None, sample_dir=None):
        # mock 여부 결정: 명시값 우선, 없으면 전역 판정
        self.mock = _global_is_mock() if mock is None else bool(mock)
        self.source = source
        self.sample_dir = sample_dir
        self._cap = None            # 실제 카메라(VideoCapture) 핸들
        self._samples: list = []    # mock 샘플 이미지 경로 목록
        self._idx = 0               # 샘플/합성 프레임 순환 인덱스

        if self.mock:
            # mock: 샘플 폴더가 있으면 이미지 목록을 모은다(없으면 합성으로 폴백)
            self._load_samples()
        else:
            # 실제 카메라 열기. 실패하면 친절히 mock으로 강등.
            if not _HAS_CV2:
                print("[Camera] OpenCV가 없어 mock 모드로 전환합니다.")
                self.mock = True
                self._load_samples()
            else:
                self._cap = cv2.VideoCapture(self.source)
                if not self._cap or not self._cap.isOpened():
                    print(f"[Camera] 카메라({self.source})를 열 수 없어 "
                          "mock 모드로 전환합니다.")
                    self.mock = True
                    self._cap = None
                    self._load_samples()

    # --- 컨텍스트 매니저: with Camera() as cam: 형태로 안전하게 열고 닫기 ---
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False  # 예외를 삼키지 않음

    def _load_samples(self):
        """sample_dir에서 이미지 경로를 수집(있을 때만). os는 지연 import."""
        if not self.sample_dir:
            return
        try:
            import os
            exts = (".jpg", ".jpeg", ".png", ".bmp")
            files = sorted(
                os.path.join(self.sample_dir, f)
                for f in os.listdir(self.sample_dir)
                if f.lower().endswith(exts)
            )
            self._samples = files
        except Exception:
            # 폴더가 없거나 접근 불가 → 합성 프레임으로 폴백
            self._samples = []

    def read(self):
        """한 프레임을 반환한다.

        - 실제 카메라: VideoCapture.read()
        - mock + 샘플폴더: 폴더 이미지 순환(읽기 실패 시 합성으로 폴백)
        - mock + 폴더없음: numpy 합성 프레임(색상 블록 배치)
        반환: np.ndarray (H, W, 3) BGR. numpy가 전혀 없으면 RuntimeError.
        """
        if not self.mock and self._cap is not None:
            ok, frame = self._cap.read()
            if not ok:
                # 스트림 끝/오류 → mock으로 안전하게 폴백
                print("[Camera] 프레임 읽기 실패 → mock 합성 프레임 사용.")
                return self._synthetic_frame()
            return frame

        # mock: 샘플 폴더 이미지가 있으면 순환 재생
        if self._samples and _HAS_CV2:
            path = self._samples[self._idx % len(self._samples)]
            self._idx += 1
            img = cv2.imread(path)
            if img is not None:
                return img
            # 읽기 실패 시 합성으로 폴백

        # 합성 프레임
        frame = self._synthetic_frame()
        self._idx += 1
        return frame

    def _synthetic_frame(self, w=640, h=480):
        """numpy로 합성 프레임 생성 — 회색 배경에 색상 블록 3개 배치.

        red/green/blue 블록을 고정 좌표에 그려, detect_colors가 항상
        결정적으로 3개를 잡도록 한다(교육용 재현성).
        numpy가 없으면 RuntimeError로 명확히 안내.
        """
        if not _HAS_NUMPY:
            raise RuntimeError(
                "numpy가 없어 합성 프레임을 만들 수 없습니다. "
                "`pip install numpy` 후 다시 시도하세요."
            )
        # 중립 회색 배경(BGR) — 색 블록과 대비되도록
        frame = np.full((h, w, 3), 60, dtype=np.uint8)

        # (color_name, (cx, cy)) — 블록 중심을 가로로 분산 배치
        layout = [
            ("red", (140, 240)),
            ("green", (320, 240)),
            ("blue", (500, 240)),
        ]
        half = 55  # 블록 한 변 절반 길이(→ 약 110x110 정사각형)
        for name, (cx, cy) in layout:
            bgr = DEFAULT_PALETTE[name]["bgr"]
            # BGR 채널을 직접 채워 채도/명도 높은 블록을 그린다
            frame[cy - half:cy + half, cx - half:cx + half] = bgr
        return frame

    def release(self):
        """카메라 자원 해제(있을 때만)."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None


# ──────────────────────────────────────────────────────────────────────────
# detect_colors — HSV 임계 기반 색 블록 검출
# ──────────────────────────────────────────────────────────────────────────
def detect_colors(frame, palette=None) -> list[dict]:
    """프레임에서 팔레트 색상 블록을 찾아 목록으로 반환한다.

    파라미터
    --------
    frame : np.ndarray (BGR)
        Camera.read()가 돌려준 프레임.
    palette : dict | None
        DEFAULT_PALETTE 형식. None이면 기본 팔레트(red/green/blue/yellow).

    반환
    ----
    list[dict] : [{color, bbox, center, area}, ...]
        bbox=(x,y,w,h), center=(cx,cy), area=면적(px). 면적 내림차순 정렬.

    동작
    ----
    opencv/numpy가 있으면 HSV 마스크 → 윤곽선으로 실제 검출.
    둘 중 하나라도 없으면 mock 캔드 결과(합성 프레임 좌표와 동일)를 반환.
    """
    palette = palette or DEFAULT_PALETTE

    # opencv/numpy 미설치 또는 frame이 ndarray가 아니면 캔드 결과로 폴백
    if not (_HAS_CV2 and _HAS_NUMPY) or not _is_ndarray(frame):
        return _mock_color_detections(palette)

    # BGR → HSV 변환 (OpenCV 색검출의 표준 전처리)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    results: list[dict] = []

    for color_name, spec in palette.items():
        # 한 색에 여러 HSV 구간(예: 빨강)이 있을 수 있어 마스크를 OR로 합친다
        mask = None
        for (lo, hi) in spec["ranges"]:
            lo_arr = np.array(lo, dtype=np.uint8)
            hi_arr = np.array(hi, dtype=np.uint8)
            part = cv2.inRange(hsv, lo_arr, hi_arr)
            mask = part if mask is None else cv2.bitwise_or(mask, part)

        if mask is None:  # 팔레트에 HSV 구간(ranges)이 하나도 없으면 이 색은 건너뜀
            continue

        # 노이즈 제거: 열림(open) 연산으로 작은 점/구멍 정리
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        # 윤곽선 검출(외곽선만). OpenCV 버전별 반환 개수 차이 방어.
        found = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                 cv2.CHAIN_APPROX_SIMPLE)
        contours = found[-2]  # (img,)contours,hierarchy → 뒤에서 2번째가 contours

        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < _MIN_AREA:
                continue  # 잡음 블롭 무시
            x, y, w, h = cv2.boundingRect(cnt)  # 외접 사각형
            results.append({
                "color": color_name,
                "bbox": (int(x), int(y), int(w), int(h)),
                "center": (int(x + w / 2), int(y + h / 2)),
                "area": area,
            })

    # 큰 블록이 먼저 오도록 면적 내림차순 정렬(픽 우선순위에 유용)
    results.sort(key=lambda d: d["area"], reverse=True)
    return results


def _mock_color_detections(palette) -> list[dict]:
    """opencv 없이도 쓰는 캔드 색검출 결과(합성 프레임 좌표와 일치)."""
    # _synthetic_frame의 red/green/blue 블록 위치(half=55)와 동일하게 맞춤
    canned = [
        ("red", 140, 240),
        ("green", 320, 240),
        ("blue", 500, 240),
    ]
    half = 55
    side = half * 2
    out = []
    for name, cx, cy in canned:
        if name not in palette:
            continue
        out.append({
            "color": name,
            "bbox": (cx - half, cy - half, side, side),
            "center": (cx, cy),
            "area": float(side * side),
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# YoloDetector — ultralytics YOLO 래퍼 (없으면 캔드 박스)
# ──────────────────────────────────────────────────────────────────────────
class YoloDetector:
    """ultralytics YOLO 객체 검출 래퍼.

    ultralytics가 없거나 mock이면 모델 로드를 건너뛰고 캔드 박스를 반환한다.
    """

    def __init__(self, model="yolo11n.pt", mock=None):
        self.mock = _global_is_mock() if mock is None else bool(mock)
        self.model_name = model
        self._model = None
        self.device = "cpu"   # 추론 디바이스: 'cuda'(가속) | 'cpu'

        if self.mock:
            return  # mock이면 무거운 모델 로드 자체를 하지 않음

        # 실제 모드: ultralytics 지연 import. 실패하면 mock으로 강등.
        try:
            from ultralytics import YOLO  # type: ignore
            self._model = YOLO(model)  # 가중치 파일 로드(다운로드 발생 가능)
            # 가속: 정책상 GPU 가능하면 CUDA 로(아니면 CPU). 실패해도 CPU 로 안전 폴백.
            self.device = _accel.torch_device() if _accel is not None else "cpu"
            if self.device != "cpu":
                try:
                    self._model.to(self.device)   # 가중치를 GPU 로 이동(예열)
                    print(f"[YoloDetector] CUDA(GPU) 사용(가속): device={self.device}")
                except Exception as e:
                    print(f"[YoloDetector] GPU 이동 실패({type(e).__name__}) → CPU.")
                    self.device = "cpu"
        except Exception as e:
            print(f"[YoloDetector] ultralytics 로드 실패({e}) → mock 전환.")
            self.mock = True

    def detect(self, frame) -> list[dict]:
        """프레임에서 객체를 검출해 [{label, conf, bbox}, ...]를 반환.

        bbox=(x, y, w, h) (좌상단 + 폭/높이). mock이면 캔드 박스.
        """
        if self.mock or self._model is None or not _is_ndarray(frame):
            return self._mock_detections()

        # 실제 추론. 결과 파싱 중 예외가 나면 안전하게 캔드로 폴백.
        try:
            res = self._model(frame, device=self.device, verbose=False)[0]  # 가속 device 지정
            out: list[dict] = []
            names = getattr(self._model, "names", {})
            for box in res.boxes:
                # xyxy(좌상단/우하단) → xywh로 변환
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                cls_id = int(box.cls[0])
                out.append({
                    "label": names.get(cls_id, str(cls_id)),
                    "conf": float(box.conf[0]),
                    "bbox": (int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                })
            return out
        except Exception as e:
            print(f"[YoloDetector] 추론 실패({e}) → mock 박스 반환.")
            return self._mock_detections()

    @staticmethod
    def _mock_detections() -> list[dict]:
        """모델 없이 쓰는 캔드 객체 검출 결과(교육 데모용 고정값)."""
        return [
            {"label": "cube", "conf": 0.92, "bbox": (110, 200, 110, 110)},
            {"label": "cube", "conf": 0.88, "bbox": (470, 200, 110, 110)},
            {"label": "hand", "conf": 0.75, "bbox": (260, 120, 130, 160)},
        ]


# ──────────────────────────────────────────────────────────────────────────
# HandTracker — MediaPipe Hands 래퍼 (없으면 캔드 랜드마크)
# ──────────────────────────────────────────────────────────────────────────
class HandTracker:
    """MediaPipe 손 추적 래퍼 + 제스처 분류.

    mediapipe가 없거나 mock이면 캔드 랜드마크를 반환한다.
    랜드마크는 21개 점의 (x, y, z) 정규화 좌표(0~1) 리스트.

    백엔드 우선순위(초기화 시 자동 선택):
      1) 레거시 ``mp.solutions.hands`` (구버전 mediapipe, ≤0.10.x 일부)
      2) Tasks API ``mp.tasks.vision.HandLandmarker`` (신버전; 0.10.35 등)
         - 모델 파일 ``models/hand_landmarker.task`` 를 자동 다운로드/캐시.
      3) 둘 다 불가 → mock 폴백(캔드 랜드마크).
    어떤 단계든 실패하면 친절한 메시지 후 안전하게 mock 으로 강등한다.
    """

    # MediaPipe Hands 21개 랜드마크 인덱스 중 분류에 쓰는 핵심 점
    WRIST = 0
    THUMB_TIP = 4
    INDEX_MCP = 5   # 검지 첫 마디(손바닥쪽)
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_TIP = 12
    RING_TIP = 16
    PINKY_TIP = 20

    # Tasks API HandLandmarker 모델(.task) 다운로드 정보
    _MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/"
                  "hand_landmarker/hand_landmarker/float16/1/"
                  "hand_landmarker.task")
    # 저장 위치: 이 파일(common/) 기준 상위 루트의 models/ 폴더
    #   (os 는 모듈 상단에서 안전하게 import 됨 — 미설치 환경이 없는 표준 라이브러리)
    _MODEL_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models", "hand_landmarker.task",
    )

    def __init__(self, mock=None):
        self.mock = _global_is_mock() if mock is None else bool(mock)
        self._hands = None        # 레거시 mp.solutions.hands.Hands 인스턴스
        self._landmarker = None   # Tasks API HandLandmarker 인스턴스
        self._mp = None
        self._backend = "mock"    # 'solutions' | 'tasks' | 'mock'
        self._delegate = "CPU"    # 'GPU' | 'CPU' — Tasks API 가속 delegate(폴백 후 실제값)

        if self.mock:
            return  # mock이면 mediapipe 초기화 생략

        # 실제 모드: mediapipe 지연 import. 실패 시 mock 강등.
        try:
            import mediapipe as mp  # type: ignore
            self._mp = mp
        except Exception as e:
            print(f"[HandTracker] mediapipe 로드 실패({e}) → mock 전환.")
            self.mock = True
            return

        # 1) 레거시 solutions API 가 있으면 그대로 사용(구버전 호환)
        if hasattr(mp, "solutions") and hasattr(getattr(mp, "solutions"), "hands"):
            try:
                self._hands = mp.solutions.hands.Hands(
                    static_image_mode=True,      # 단일 프레임 처리(추적 누적 X)
                    max_num_hands=1,             # 교육 데모: 한 손만
                    min_detection_confidence=0.5,
                )
                self._backend = "solutions"
                return
            except Exception as e:
                print(f"[HandTracker] solutions API 초기화 실패({e}) → Tasks API 시도.")
                self._hands = None

        # 2) Tasks API(HandLandmarker) 시도 — 신버전 mediapipe(0.10.35 등)
        if hasattr(mp, "tasks"):
            try:
                self._init_tasks_api(mp)
                self._backend = "tasks"
                return
            except Exception as e:
                print(f"[HandTracker] Tasks API 초기화 실패({e}) → mock 전환.")
                self._landmarker = None

        # 3) 둘 다 불가 → mock 폴백
        print("[HandTracker] 사용 가능한 mediapipe 손 검출 백엔드가 없어 "
              "mock 모드로 전환합니다.")
        self.mock = True

    # --- Tasks API 초기화(모델 다운로드 + GPU/CPU delegate 선택) -------------
    def _init_tasks_api(self, mp):
        """mp.tasks.vision.HandLandmarker 를 IMAGE 모드로 생성한다.

        가속: 정책상 GPU 를 시도(가능 시)하고, 생성/워밍업이 실패하면 CPU 로 폴백한다.
        모델(.task)이 없으면 _MODEL_URL 에서 받아 _MODEL_PATH 에 캐시한다.
        네트워크 실패/오프라인이면 RuntimeError 를 던져 상위에서 mock 폴백.
        """
        model_path = self._ensure_model()  # 없으면 다운로드(실패 시 예외)

        # Tasks API 구성요소 가져오기(신버전 mediapipe 경로)
        BaseOptions = mp.tasks.BaseOptions
        vision = mp.tasks.vision
        HandLandmarker = vision.HandLandmarker
        HandLandmarkerOptions = vision.HandLandmarkerOptions
        RunningMode = vision.RunningMode

        def _build(delegate=None):
            # delegate 가 None 이면 인자 자체를 빼서 '구버전 mediapipe 원래 동작(CPU)'과 동일하게.
            if delegate is not None:
                base = BaseOptions(model_asset_path=model_path, delegate=delegate)
            else:
                base = BaseOptions(model_asset_path=model_path)
            options = HandLandmarkerOptions(
                base_options=base,
                running_mode=RunningMode.IMAGE,   # 단일 프레임(추적 누적 X)
                num_hands=1,                      # 교육 데모: 한 손만
                min_hand_detection_confidence=0.5,
            )
            return HandLandmarker.create_from_options(options)

        # delegate enum 이 있는 버전만 GPU/CPU 를 명시한다. 없으면 인자 없이 빌드(=원래 동작).
        Delegate = getattr(BaseOptions, "Delegate", None)
        prefer_gpu = bool(_accel is not None and _accel.mediapipe_prefer_gpu())

        # 1) 정책이 GPU 시도(auto/on)이고 delegate enum 이 있으면 GPU 로 만들고 워밍업 검증
        if prefer_gpu and Delegate is not None:
            try:
                lm = _build(Delegate.GPU)
                self._warmup(mp, lm)          # GPU delegate 가 실제로 도는지 1회 검증
                self._landmarker = lm
                self._delegate = "GPU"
                print("[HandTracker] Tasks API: GPU delegate 사용(가속).")
                return
            except Exception as e:
                # 데스크톱 Windows 등 GPU delegate 미지원 → 조용히 CPU 로 폴백
                print(f"[HandTracker] GPU delegate 사용 불가({type(e).__name__}) → CPU 폴백.")

        # 2) CPU(기본/폴백). delegate enum 이 없으면 인자 없이(=구버전 원래 동작).
        self._landmarker = _build(Delegate.CPU if Delegate is not None else None)
        self._delegate = "CPU"

    def _warmup(self, mp, landmarker):
        """작은 더미 이미지로 1회 detect 해 delegate(특히 GPU)가 실제 동작하는지 검증한다.

        GPU delegate 는 create 는 성공해도 첫 추론에서 실패하는 플랫폼이 있어,
        여기서 한 번 돌려 보고 예외가 나면 호출측이 CPU 로 폴백하게 한다.
        numpy 가 없으면 검증을 건너뛴다(이후 process 에서 처리).
        """
        if not _HAS_NUMPY:
            return
        dummy = np.zeros((48, 48, 3), dtype=np.uint8)
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=dummy)
        landmarker.detect(img)   # 예외 발생 시 상위 try 가 받아 CPU 폴백

    def backend_info(self) -> str:
        """현재 손추적 백엔드/가속 요약 문자열(GUI 로그용)."""
        if self.mock:
            return "mock(캔드 랜드마크)"
        if self._backend == "tasks":
            return f"mediapipe Tasks/{self._delegate}"
        if self._backend == "solutions":
            return "mediapipe solutions/CPU"
        return self._backend

    @classmethod
    def _ensure_model(cls):
        """HandLandmarker 모델 파일을 보장한다(있으면 그대로, 없으면 다운로드).

        반환: 모델 파일의 절대 경로(str).
        네트워크 실패/오프라인이면 친절한 메시지 후 RuntimeError 를 던진다.
        """
        model_path = cls._MODEL_PATH
        # 이미 존재하고 비어있지 않으면 재다운로드 생략
        if os.path.exists(model_path) and os.path.getsize(model_path) > 0:
            return model_path

        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        print(f"[HandTracker] HandLandmarker 모델 다운로드 중 …\n"
              f"            URL : {cls._MODEL_URL}\n"
              f"            저장: {model_path}")
        try:
            import urllib.request
            # 임시 파일로 받아 완료 후 교체(부분 다운로드로 오염 방지)
            tmp_path = model_path + ".part"
            urllib.request.urlretrieve(cls._MODEL_URL, tmp_path)
            os.replace(tmp_path, model_path)
            print("[HandTracker] 모델 다운로드 완료.")
            return model_path
        except Exception as e:
            # 부분 파일 정리
            try:
                if os.path.exists(model_path + ".part"):
                    os.remove(model_path + ".part")
            except Exception:
                pass
            raise RuntimeError(
                "HandLandmarker 모델을 내려받지 못했습니다(오프라인/네트워크 문제일 수 있음). "
                f"수동으로 아래 URL 의 파일을 받아 {model_path} 에 두면 됩니다.\n"
                f"  {cls._MODEL_URL}\n  (원인: {e})"
            ) from e

    def process(self, frame) -> dict:
        """프레임에서 손을 찾아 {landmarks, handedness}를 반환(없으면 {}).

        landmarks : list[(x, y, z)] (21개, 정규화 0~1)
        handedness : 'Left' | 'Right'

        백엔드(solutions/tasks)에 따라 입력 처리만 다르고, 반환 형식은 동일하다.
        """
        if (self.mock
                or (self._hands is None and self._landmarker is None)
                or not _is_ndarray(frame)):
            return self._mock_hand()

        try:
            # MediaPipe는 RGB 입력을 기대 → BGR에서 변환
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if _HAS_CV2 else frame

            if self._backend == "tasks":
                return self._process_tasks(rgb)
            return self._process_solutions(rgb)
        except Exception as e:
            print(f"[HandTracker] 처리 실패({e}) → mock 랜드마크 반환.")
            return self._mock_hand()

    def _process_solutions(self, rgb) -> dict:
        """레거시 solutions API 로 손을 검출해 표준 dict 로 변환."""
        res = self._hands.process(rgb)
        if not res.multi_hand_landmarks:
            return {}  # 손을 못 찾음
        lm = res.multi_hand_landmarks[0].landmark
        landmarks = [(p.x, p.y, p.z) for p in lm]
        handed = "Right"
        if res.multi_handedness:
            handed = res.multi_handedness[0].classification[0].label
        return {"landmarks": landmarks, "handedness": handed}

    def _process_tasks(self, rgb) -> dict:
        """Tasks API HandLandmarker 로 손을 검출해 표준 dict 로 변환.

        반환 형식은 solutions 경로와 동일: {'landmarks': [(x,y,z)*21], 'handedness': ...}
        손이 없으면 {} 반환(기존 계약 유지).
        """
        mp = self._mp
        # numpy RGB → mp.Image(SRGB). frame 이 ndarray 가 아니면 process()에서 걸러짐.
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = self._landmarker.detect(mp_image)
        if not res.hand_landmarks:
            return {}  # 손을 못 찾음
        lm = res.hand_landmarks[0]            # 첫 손의 21개 정규화 랜드마크
        landmarks = [(p.x, p.y, p.z) for p in lm]
        handed = "Right"
        # handedness 는 [[Category, ...], ...] 구조(첫 손의 최상위 라벨)
        try:
            if res.handedness and res.handedness[0]:
                handed = res.handedness[0][0].category_name
        except Exception:
            pass
        return {"landmarks": landmarks, "handedness": handed}

    @staticmethod
    def _mock_hand() -> dict:
        """캔드 랜드마크 — '편 손(open)'으로 분류되도록 구성한 21점."""
        # 손목을 아래(y 큰 값), 손가락 끝을 위(y 작은 값)에 두어 '펴짐'을 표현.
        # 인덱스별 (x, y, z). z는 0으로 단순화.
        lm = [(0.5, 0.95, 0.0)] * 21  # 일단 손목 위치로 초기화
        # 손목
        lm[0] = (0.50, 0.95, 0.0)
        # 엄지: 손목에서 옆+위로 뻗음
        lm[1] = (0.42, 0.88, 0.0)
        lm[2] = (0.36, 0.80, 0.0)
        lm[3] = (0.32, 0.73, 0.0)
        lm[4] = (0.28, 0.66, 0.0)   # 엄지 끝
        # 검지(5 MCP → 8 TIP): 위로 곧게 펴짐
        lm[5] = (0.46, 0.62, 0.0)
        lm[6] = (0.46, 0.50, 0.0)
        lm[7] = (0.46, 0.40, 0.0)
        lm[8] = (0.46, 0.30, 0.0)   # 검지 끝(MCP보다 한참 위 = 펴짐)
        # 중지(9 → 12)
        lm[9] = (0.52, 0.62, 0.0)
        lm[10] = (0.52, 0.48, 0.0)
        lm[11] = (0.52, 0.36, 0.0)
        lm[12] = (0.52, 0.26, 0.0)  # 중지 끝
        # 약지(13 → 16)
        lm[13] = (0.58, 0.63, 0.0)
        lm[14] = (0.58, 0.50, 0.0)
        lm[15] = (0.58, 0.39, 0.0)
        lm[16] = (0.58, 0.30, 0.0)  # 약지 끝
        # 새끼(17 → 20)
        lm[17] = (0.64, 0.66, 0.0)
        lm[18] = (0.64, 0.55, 0.0)
        lm[19] = (0.64, 0.46, 0.0)
        lm[20] = (0.64, 0.38, 0.0)  # 새끼 끝
        return {"landmarks": lm, "handedness": "Right"}

    @staticmethod
    def classify_gesture(landmarks) -> str:
        """랜드마크로 손 제스처를 분류한다.

        반환: 'open' | 'fist' | 'point' | 'pinch' | 'none'

        규칙(간단·교육용, 정규화 좌표 가정. 화면 위 = y 작음):
          - 손가락이 '펴짐' = 끝(TIP)이 첫 마디(MCP)보다 위(y가 더 작음).
          - pinch  : 엄지끝과 검지끝이 매우 가깝다(우선 판정).
          - point  : 검지만 펴고 중지/약지/새끼는 접힘.
          - open   : 검지·중지·약지·새끼 모두 펴짐.
          - fist   : 네 손가락 모두 접힘.
          - none   : 그 외/입력 없음.
        """
        # 입력 방어: 21점이 아니면 분류 불가
        if not landmarks or len(landmarks) < 21:
            return "none"

        def y(i):  # i번 점의 y좌표
            return landmarks[i][1]

        def dist(a, b):  # 두 점 사이 유클리드 거리(2D)
            ax, ay = landmarks[a][0], landmarks[a][1]
            bx, by = landmarks[b][0], landmarks[b][1]
            return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

        # 각 손가락이 펴졌는지: 끝이 MCP보다 위(y 작음)면 펴짐
        index_open = y(HandTracker.INDEX_TIP) < y(HandTracker.INDEX_MCP)
        middle_open = y(HandTracker.MIDDLE_TIP) < y(HandTracker.MIDDLE_MCP)
        # 약지/새끼는 MCP 인덱스가 팔레트에 없어 중지 MCP 기준선으로 근사
        ring_open = y(HandTracker.RING_TIP) < y(HandTracker.MIDDLE_MCP)
        pinky_open = y(HandTracker.PINKY_TIP) < y(HandTracker.MIDDLE_MCP)

        # 손 크기 기준 거리(손목→중지MCP)로 pinch 임계를 정규화
        hand_span = dist(HandTracker.WRIST, HandTracker.MIDDLE_MCP) or 1e-6
        pinch_gap = dist(HandTracker.THUMB_TIP, HandTracker.INDEX_TIP)

        # 1) pinch: 엄지끝-검지끝이 손 크기 대비 충분히 가까움
        if pinch_gap < hand_span * 0.30:
            return "pinch"

        # 2) point: 검지만 펴짐
        if index_open and not (middle_open or ring_open or pinky_open):
            return "point"

        # 3) open: 네 손가락 모두 펴짐
        if index_open and middle_open and ring_open and pinky_open:
            return "open"

        # 4) fist: 네 손가락 모두 접힘
        if not (index_open or middle_open or ring_open or pinky_open):
            return "fist"

        # 5) 그 외 애매한 상태
        return "none"


# ──────────────────────────────────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────────────────────────────────
def _is_ndarray(x) -> bool:
    """x가 numpy ndarray인지 안전하게 확인(numpy 미설치 시 False)."""
    return _HAS_NUMPY and isinstance(x, np.ndarray)


# ──────────────────────────────────────────────────────────────────────────
# 자가 데모 (mock) — 하드웨어/모델 없이 색검출 + 제스처 분류 출력
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(" common/vision.py 자가 데모 (mock 모드)")
    print("=" * 60)
    print(f" numpy 사용 가능 : {_HAS_NUMPY}")
    print(f" opencv 사용 가능: {_HAS_CV2}")
    if _accel is not None:
        print(f" 하드웨어 가속   : {_accel.describe()}")
    print("-" * 60)

    # 1) mock 카메라에서 합성 프레임 한 장 획득
    with Camera(mock=True) as cam:
        frame = cam.read()
    if _is_ndarray(frame):
        print(f" 프레임 크기     : {frame.shape}  (H, W, C)")
    else:
        print(" 프레임          : (numpy 없음 → 캔드 데이터 경로 사용)")

    # 2) 색 블록 검출
    blocks = detect_colors(frame)
    print(f"\n[색 검출] {len(blocks)}개 발견:")
    for b in blocks:
        print(f"  - {b['color']:6s} center={b['center']} "
              f"bbox={b['bbox']} area={b['area']:.0f}")

    # 3) YOLO 객체 검출 (mock 캔드 박스)
    yolo = YoloDetector(mock=True)
    dets = yolo.detect(frame)
    print(f"\n[YOLO 검출] {len(dets)}개 (mock 캔드):")
    for d in dets:
        print(f"  - {d['label']:5s} conf={d['conf']:.2f} bbox={d['bbox']}")

    # 4) 손 제스처 추적 + 분류
    tracker = HandTracker(mock=True)
    hand = tracker.process(frame)
    gesture = HandTracker.classify_gesture(hand.get("landmarks"))
    print(f"\n[손 추적] handedness={hand.get('handedness')} "
          f"랜드마크={len(hand.get('landmarks', []))}점")
    print(f"[제스처 분류] → '{gesture}'")

    # 5) 분류기 검증: 여러 손 모양을 넣어 결과 확인
    print("\n[제스처 분류기 점검]")
    open_hand = HandTracker._mock_hand()["landmarks"]
    print(f"  편 손        → {HandTracker.classify_gesture(open_hand)}")

    # 주먹: 모든 끝을 MCP 아래(y 큼)로
    fist = [list(p) for p in open_hand]
    for i in (HandTracker.INDEX_TIP, HandTracker.MIDDLE_TIP,
              HandTracker.RING_TIP, HandTracker.PINKY_TIP):
        fist[i][1] = 0.80  # MCP(약 0.62)보다 아래 → 접힘
    print(f"  주먹         → {HandTracker.classify_gesture([tuple(p) for p in fist])}")

    # 검지만 펴기: 나머지 접기
    point = [list(p) for p in open_hand]
    for i in (HandTracker.MIDDLE_TIP, HandTracker.RING_TIP,
              HandTracker.PINKY_TIP):
        point[i][1] = 0.80
    print(f"  검지 포인트  → {HandTracker.classify_gesture([tuple(p) for p in point])}")

    # 핀치: 엄지끝을 검지끝에 붙이기
    pinch = [list(p) for p in open_hand]
    pinch[HandTracker.THUMB_TIP] = list(open_hand[HandTracker.INDEX_TIP])
    print(f"  핀치         → {HandTracker.classify_gesture([tuple(p) for p in pinch])}")

    print(f"  빈 입력      → {HandTracker.classify_gesture(None)}")
    print("\n데모 완료. (실제 카메라/모델 연결 시 mock=False 또는 자동판정)")
