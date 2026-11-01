# -*- coding: utf-8 -*-
"""common/grounding.py — 시각 그라운딩(자연어 지칭 → 픽셀 좌표) 클라이언트.

목적
----
H1 VLA 확장("카메라에 보이는 것 집어줘")의 **눈** 역할. 카메라 프레임과
자연어 타깃("빨간 블록")을 받아, 그 물체 중심의 **픽셀 좌표**를 돌려준다.
백엔드는 로컬 Qwen3-VL 2B(llama.cpp llama-server, OpenAI 호환 API)이며,
좌표 규약은 0–1000 정규화 ``{"point_2d": [x, y]}`` (2026-07-14 실측 벤치 확정).

핵심 안전장치 (교육용·무하드웨어 원칙, ai_clients.py 패턴)
----------------------------------------------------------
- 서버/모델/키가 없어도 import 와 실행이 절대 죽지 않는다.
  CURRICULUM_FORCE_MOCK=1 또는 provider="mock"(또는 mock=True) 이면
  결정적 MockGrounding 백엔드로 폴백한다.
- 실모드에서도 서버없음/타임아웃/파싱실패는 예외 없이 ``None`` 을 반환한다
  ("모르면 멈춘다" — 상위 resolve 단계가 안전하게 중단).
- HTTP 는 urllib 만 사용하고, 테스트용 ``_http_post``/``_http_get`` 주입
  슬롯을 둔다(ai_clients 의 MiniMax 경로와 동일한 스텁 방식).

좌표 파싱 함정(실측 회귀)
-------------------------
응답에서 정규식으로 숫자만 뽑으면 키 이름 ``point_2d`` 의 '2' 가 잡힌다.
→ ``parse_point_xy`` 는 **대괄호 안 숫자쌍을 최우선**으로 파싱한다.

사용법
------
    from common.grounding import GroundingClient, ensure_server

    proc = ensure_server()               # 로컬 llama-server 보장(이미 떠 있으면 None)
    g = GroundingClient()                # 서버 없으면 자동 mock
    xy = g.point(frame, "빨간 블록")     # (px, py) 픽셀 | None

이 파일을 직접 실행하면(python -m common.grounding) mock 자가 데모가 돈다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import subprocess
import time
import urllib.request
import zlib
from typing import Any, cast
from urllib.parse import urlsplit

# ──────────────────────────────────────────────────────────────────────────
# 1) 의존성 import — 없으면 None 으로 두고, 이후 mock 으로 폴백한다.
# ──────────────────────────────────────────────────────────────────────────
try:
    import numpy as np  # 프레임(ndarray) 처리용 — 없어도 import 는 성공해야 함
except Exception:  # pragma: no cover - 미설치 환경 폴백
    np = None  # type: ignore[assignment]

try:
    from common import config as _config  # 전역 mock 판정·경로 상수
except Exception:  # pragma: no cover - config 미존재/단독 실행 시
    _config = None  # type: ignore[assignment]


# ──────────────────────────────────────────────────────────────────────────
# 2) 상수 — 기본 엔드포인트/모델 경로는 config 위임(없으면 아래 기본값)
# ──────────────────────────────────────────────────────────────────────────
QWEN_CHAT_URL_DEFAULT = "http://127.0.0.1:8123/v1"  # config.GROUNDING_URL 위임

# 이 파일(common/) 기준 커리큘럼 루트(taskB_curriculum) — models/ 기본 경로 계산용.
_TASKB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 그라운딩 시스템 프롬프트 — JSON 한 개만, 0-1000 정규화 좌표 명시(실측 벤치 검증).
_GROUNDING_SYSTEM = (
    "You are a visual grounding assistant. Locate the requested object in the image "
    'and reply with ONLY a JSON object: {"point_2d": [x, y]} — the center point of '
    "the object, in 0-1000 normalized coordinates. No other text."
)

__all__ = [
    "QWEN_CHAT_URL_DEFAULT", "GroundingClient", "MockGrounding",
    "parse_point_xy", "ensure_server",
]


def _cfg(name: str, default: str) -> str:
    """config 의 문자열 상수를 읽는다(없으면 default)."""
    val = getattr(_config, name, None) if _config is not None else None
    return str(val) if val else default


def _force_mock() -> bool:
    """그라운딩의 mock 자동판정 — **CURRICULUM_FORCE_MOCK 만** 본다.

    주의: config.is_mock() 을 쓰면 안 된다. 그건 ANTHROPIC_API_KEY 부재로도 True 가
    되는데, 그라운딩은 Anthropic 이 아니라 로컬 Qwen 서버(llama-server)를 쓴다. 교실
    PC 는 대개 Anthropic 키가 없으므로(두뇌는 MiniMax), config.is_mock() 을 따르면
    실제 Qwen 눈이 항상 mock 으로 죽어 vision 명령이 실기에서 영구 거부된다.
    서버 미가동 시의 폴백은 point() 가 None 을 돌려주는 것으로 이미 처리된다.
    """
    val = os.environ.get("CURRICULUM_FORCE_MOCK", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _frame_hw(frame: Any) -> tuple[int, int]:
    """프레임의 (H, W). shape 가 없으면 교육용 기본 해상도(480, 640)."""
    try:
        return int(frame.shape[0]), int(frame.shape[1])
    except Exception:
        return (480, 640)


# ──────────────────────────────────────────────────────────────────────────
# 3) 좌표 파싱 — 대괄호 숫자쌍 우선 (순수함수, pytest 대상)
# ──────────────────────────────────────────────────────────────────────────
def parse_point_xy(text: str) -> tuple[float, float] | None:
    """VLM 응답 텍스트에서 좌표쌍 (x, y) 를 추출한다. 실패 시 None.

    1순위: 대괄호 안의 숫자쌍 ``[x, y]`` — 키 이름 ``point_2d`` 의 '2' 가
           숫자로 잘못 잡히는 함정(실측)을 회피한다.
    2순위: 키 이름(point_2d/bbox_2d 등)을 지운 뒤 남은 숫자 2개.
    여분 텍스트/코드펜스가 섞여 있어도 동작한다.
    """
    if not text:
        return None
    m = re.search(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1)), float(m.group(2))
    cleaned = re.sub(r"point_2d|bbox_2d|point2d|_2d", "", text)
    nums = re.findall(r"-?\d+(?:\.\d+)?", cleaned)
    if len(nums) < 2:
        return None
    return float(nums[0]), float(nums[1])


# ──────────────────────────────────────────────────────────────────────────
# 4) 프레임 → PNG base64 인코딩 (PIL 있으면 사용, 없으면 순수 zlib 폴백)
# ──────────────────────────────────────────────────────────────────────────
def _png_bytes_pure(frame: Any) -> bytes:
    """순수 표준 라이브러리(zlib/struct) PNG 인코더 — RGB 8bit, 필터 0.

    PIL/opencv 가 없는 교실 PC에서도 실서버 경로가 동작하도록 하는 폴백.
    """
    arr = frame
    if np is not None:
        arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = int(arr.shape[0]), int(arr.shape[1])
    # 각 스캔라인 앞에 필터 타입 0(없음) 바이트를 붙인다.
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8bit / color type 2 = RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _encode_png_b64(frame: Any) -> str:
    """HxWx3 uint8 RGB ndarray → PNG base64 문자열."""
    try:
        import io  # 지연 import (PIL 경로에서만 필요)

        from PIL import Image
        buf = io.BytesIO()
        Image.fromarray(frame).save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        # PIL 미설치/실패 → 순수 zlib PNG 인코더로 폴백
        return base64.b64encode(_png_bytes_pure(frame)).decode("ascii")


# ──────────────────────────────────────────────────────────────────────────
# 5) MockGrounding — 결정적 좌표 생성기 (무서버 데모/테스트용 백엔드)
# ──────────────────────────────────────────────────────────────────────────
class MockGrounding:
    """GroundingClient(provider="mock") 의 내부 백엔드.

    - set_point 로 등록한 target 은 그 정규화(0..1) 좌표를 돌려준다.
    - 미등록 target 은 문자열 sha256 해시 기반의 **결정적** 좌표(0.1~0.9)를
      돌려준다(같은 target → 항상 같은 좌표, 프로세스 무관).
    """

    def __init__(self) -> None:
        self._points: dict[str, tuple[float, float]] = {}

    def set_point(self, target: str, norm_xy: tuple[float, float]) -> None:
        """target 의 정규화(0..1) 좌표를 등록한다(테스트/GUI 데모용)."""
        self._points[str(target)] = (float(norm_xy[0]), float(norm_xy[1]))

    def point_norm(self, target: str) -> tuple[float, float]:
        """등록값 우선, 미등록이면 해시 기반 결정적 정규화 좌표."""
        key = str(target)
        if key in self._points:
            return self._points[key]
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        nx = 0.1 + 0.8 * (digest[0] / 255.0)   # 프레임 가장자리(0/1)는 피한다
        ny = 0.1 + 0.8 * (digest[1] / 255.0)
        return (nx, ny)

    def point(self, frame: Any, target: str) -> tuple[float, float] | None:
        """프레임 크기에 맞춘 픽셀 좌표. frame 이 None 이면 None."""
        if frame is None:
            return None
        h, w = _frame_hw(frame)
        nx, ny = self.point_norm(target)
        return (nx * w, ny * h)


# ──────────────────────────────────────────────────────────────────────────
# 6) GroundingClient — 자연어 target → 프레임 픽셀 좌표
# ──────────────────────────────────────────────────────────────────────────
class GroundingClient:
    """시각 그라운딩 클라이언트 (qwen-local 실서버 | mock 폴백).

    파라미터
    --------
    provider : "qwen-local"(기본) | "mock"(강제 mock 백엔드).
               기본값("qwen-local") 그대로 두면 config.GROUNDING_PROVIDER 에
               위임한다 — GROUNDING_PROVIDER=mock 환경변수/설정이 실제로
               반영된다(명시 인자가 있으면 그 값이 우선).
    endpoint : OpenAI 호환 베이스 URL(예: http://127.0.0.1:8123/v1).
               None 이면 config.GROUNDING_URL → QWEN_CHAT_URL_DEFAULT.
    mock     : True/False 명시 시 최우선. None 이면 config.is_mock() 자동판정.
    timeout  : HTTP 타임아웃(초). 새 장면 추론이 ~6s(실측)라 기본 120s.
    _http_post/_http_get : 테스트용 주입 슬롯(ai_clients 패턴).
    """

    def __init__(self, provider: str = "qwen-local", endpoint: str | None = None,
                 mock: bool | None = None, timeout: float = 120.0,
                 *, _http_post: Any = None, _http_get: Any = None) -> None:
        # 기본값이면 config.GROUNDING_PROVIDER 위임(죽은 설정 방지 — 문서화된
        # 스위치 GROUNDING_PROVIDER=mock 이 조용히 무시되지 않게 한다).
        if provider == "qwen-local":
            provider = _cfg("GROUNDING_PROVIDER", "qwen-local")
        self.provider = provider
        self.timeout = float(timeout)
        self.endpoint = (endpoint or _cfg("GROUNDING_URL", QWEN_CHAT_URL_DEFAULT)).rstrip("/")
        self.calls: list[dict[str, Any]] = []  # 호출 기록(검수·테스트용)
        self._http_post = _http_post         # 테스트용 주입 가능한 전송기(POST)
        self._http_get = _http_get           # 테스트용 주입 가능한 전송기(GET/health)
        self.mock_backend = MockGrounding()  # mock 시 좌표 공급원(set_point 대상)
        # mock 판정 — provider="mock" 최우선 → 호출자 명시값 → config.is_mock().
        if provider == "mock":
            self._mock = True
        elif mock is not None:
            self._mock = bool(mock)
        else:
            self._mock = _force_mock()

    # -- 상태 ---------------------------------------------------------------- #
    @property
    def is_mock(self) -> bool:
        """mock 백엔드로 동작 중인지."""
        return self._mock

    def _health_url(self) -> str:
        """endpoint 의 호스트 기준 /health URL (…/v1 을 떼고 붙인다)."""
        parts = urlsplit(self.endpoint)
        return f"{parts.scheme}://{parts.netloc}/health"

    def is_ready(self) -> bool:
        """그라운딩 백엔드 준비 여부. mock 은 항상 True, 예외는 False."""
        if self._mock:
            return True
        return _health_ok(self._health_url(), timeout=min(self.timeout, 3.0),
                          _http_get=self._http_get)

    # -- mock 편의(등록 위임) -------------------------------------------------- #
    def set_point(self, target: str, norm_xy: tuple[float, float]) -> None:
        """mock 백엔드에 target 의 정규화(0..1) 좌표를 등록한다(데모/테스트)."""
        self.mock_backend.set_point(target, norm_xy)

    # -- 핵심: 포인팅 ----------------------------------------------------------- #
    def point(self, frame: Any, target: str) -> tuple[float, float] | None:
        """frame(HxWx3 uint8 RGB)에서 target 중심의 **픽셀 좌표**를 찾는다.

        서버없음/타임아웃/파싱실패 어떤 경우에도 예외를 던지지 않고 None 을
        반환한다("모르면 멈춘다" — 상위 resolve 단계가 안전하게 중단).
        """
        self.calls.append({"method": "point", "target": target, "mock": self._mock})
        if frame is None:
            return None
        if self._mock:
            return self.mock_backend.point(frame, target)

        h, w = _frame_hw(frame)
        try:
            b64 = _encode_png_b64(frame)
            payload = json.dumps({
                "model": "qwen3vl",
                "temperature": 0,
                "max_tokens": 80,
                "messages": [
                    {"role": "system", "content": _GROUNDING_SYSTEM},
                    {"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": "data:image/png;base64," + b64}},
                        {"type": "text", "text": f"Point to: {target}"},
                    ]},
                ],
            }).encode("utf-8")
            raw = self._post(self.endpoint + "/chat/completions", payload)
            data = json.loads(raw)
            content = str(data["choices"][0]["message"]["content"])
        except Exception:
            return None  # 서버없음/타임아웃/응답형식 오류 → 조용히 None

        xy = parse_point_xy(content)
        if xy is None:
            return None  # 파싱 실패 → None
        # 0-1000 정규화 → 픽셀. 모델이 범위를 벗어나도 프레임 안으로 클램프.
        px = min(max(xy[0] / 1000.0 * w, 0.0), float(w - 1))
        py = min(max(xy[1] / 1000.0 * h, 0.0), float(h - 1))
        return (px, py)

    def _post(self, url: str, payload: bytes) -> str:
        """로컬 서버로 POST. 테스트 시 _http_post(url, payload) 주입으로 대체."""
        if self._http_post is not None:  # 테스트/대체 전송기
            return str(self._http_post(url, payload))
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - 로컬 서버
            return str(resp.read().decode("utf-8"))


# ──────────────────────────────────────────────────────────────────────────
# 7) 서버 헬스체크 + ensure_server (llama-server 기동 보장)
# ──────────────────────────────────────────────────────────────────────────
def _health_ok(url: str, timeout: float = 2.0, _http_get: Any = None) -> bool:
    """GET url 이 200 이면 True. 어떤 예외도 False (서버 부재 = 정상 상황)."""
    try:
        if _http_get is not None:  # 테스트/대체 전송기
            return bool(_http_get(url))
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - 로컬 서버
            return int(resp.status) == 200
    except Exception:
        return False


def ensure_server(model: str | None = None, mmproj: str | None = None,
                  port: int = 8123, exe: str | None = None,
                  wait_s: float = 60.0,
                  *, _popen: Any = None, _health_check: Any = None,
                  _sleep: Any = None) -> subprocess.Popen[bytes] | None:
    """로컬 llama-server(Qwen3-VL) 가동을 보장한다.

    - 이미 ``/health`` 가 200 이면 **None** 을 반환(기존 서버 재사용).
    - 아니면 llama-server 를 기동(``-c 8192, --threads cpu-2, --no-webui``,
      실측 벤치와 동일 옵션)하고 health 가 뜰 때까지 최대 wait_s 초
      **유한 루프**로 폴링한 뒤 Popen 핸들을 반환한다.
    - 실행파일/모델 파일이 없으면 RuntimeError(친절한 안내 포함).
    - 폴링 시간 내에 준비되지 않으면 자식 프로세스를 정리하고 RuntimeError.
    - 테스트 주입: _popen(argv)→proc, _health_check(url)→bool, _sleep(sec).
      (실서버 없이 기동 경로를 검증하기 위한 스텁 슬롯)
    """
    health = _health_check if _health_check is not None else _health_ok
    sleep = _sleep if _sleep is not None else time.sleep
    health_url = f"http://127.0.0.1:{int(port)}/health"

    if health(health_url):
        return None  # 이미 떠 있음 → 재사용

    # 기본 경로: config 상수(models/ 아래, 이미 배치됨) → 하드코딩 폴백.
    model = model or _cfg("QWEN_MODEL_PATH", os.path.join(
        _TASKB_ROOT, "models", "Qwen3VL-2B-Instruct-Q4_K_M.gguf"))
    mmproj = mmproj or _cfg("QWEN_MMPROJ_PATH", os.path.join(
        _TASKB_ROOT, "models", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"))
    exe = exe or _cfg("LLAMA_SERVER_EXE", os.path.join(
        _TASKB_ROOT, "models", "llamacpp", "llama-server.exe"))

    missing = [p for p in (exe, model, mmproj) if not os.path.exists(p)]
    if missing:
        raise RuntimeError(
            "llama-server 를 기동할 수 없습니다 — 아래 파일이 없습니다:\n  "
            + "\n  ".join(missing)
            + "\nmodels/README.md 의 재다운로드 안내를 참고하세요."
        )

    # --threads = cpu-2 (스펙 §2b·실측 벤치와 동일 옵션): 추론 중에도 GUI/카메라
    # 스레드가 굶지 않도록 코어 2개를 남긴다(하한 1 — 저코어 교실 PC 안전).
    argv = [exe, "-m", model, "--mmproj", mmproj, "--port", str(int(port)),
            "-c", "8192", "--threads", str(max(1, (os.cpu_count() or 4) - 2)),
            "--no-webui"]
    if _popen is not None:  # 테스트/대체 실행기
        proc = cast("subprocess.Popen[bytes]", _popen(argv))
    else:
        proc = subprocess.Popen(  # noqa: S603 - 신뢰된 로컬 실행파일
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # health 폴링 — wait_s 초 한도의 유한 루프(0.5s 간격).
    tries = max(1, int(float(wait_s) / 0.5))
    for _ in range(tries):
        if health(health_url):
            return proc
        sleep(0.5)

    # 기동 실패 → 자식 정리 후 명확한 오류
    try:
        proc.kill()
    except Exception:  # pragma: no cover - 이미 종료된 경우 등
        pass
    raise RuntimeError(
        f"llama-server 가 {float(wait_s):.0f}s 안에 준비되지 않았습니다 (port={port}). "
        "모델 로드가 느린 PC 라면 wait_s 를 늘려 보세요."
    )


# ──────────────────────────────────────────────────────────────────────────
# 8) 자가 데모 — mock 으로 전 과정 확인 (서버/카메라/키 불필요)
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    try:  # Windows 콘솔(cp949)에서도 한국어 출력이 깨지지 않도록(관례)
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        pass

    print("=== common/grounding.py mock 자가 데모 ===\n")

    # 1) 좌표 파싱(대괄호 우선 — 'point_2d' 의 '2' 함정 회귀 확인)
    demo_raw = '{"point_2d": [244, 675]}'
    print(f"[파싱] {demo_raw!r} → {parse_point_xy(demo_raw)}  (('2' 함정 없이) 244, 675)")
    fenced = '```json\n{"point_2d": [100, 200]}\n``` 좌표입니다.'
    print(f"[파싱] 코드펜스 응답 → {parse_point_xy(fenced)}")

    # 2) mock 그라운딩 — 결정적 좌표 + set_point 등록
    g = GroundingClient(provider="mock")
    print(f"\n[클라이언트] is_mock={g.is_mock} is_ready={g.is_ready()}")
    if np is not None:
        demo_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        print(f"[point] '빨간 블록'(해시 기반) → {g.point(demo_frame, '빨간 블록')}")
        g.set_point("빨간 블록", (0.25, 0.62))
        print(f"[point] '빨간 블록'(등록 후)   → {g.point(demo_frame, '빨간 블록')}")
        print(f"[기록] calls={len(g.calls)}건, 마지막={g.calls[-1]}")
    else:  # pragma: no cover - numpy 없는 환경 안내
        print("[point] numpy 가 없어 프레임 데모는 건너뜁니다(파싱/판정은 정상).")

    print("\n=== 데모 완료 (서버·카메라·키 없이 mock 폴백 정상) ===")
