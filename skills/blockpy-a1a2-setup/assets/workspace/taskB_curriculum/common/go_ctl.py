# -*- coding: utf-8 -*-
"""Dobot Magician GO(주행 카) 제어 래퍼 — H3 차시용 공통 레이어.

팔(Magician Lite)용 common.dobot_ctl 과 같은 역할을 GO에 대해 수행한다:
    - get_go(port=..., mock=...) 팩토리 하나로 실로봇/모의로봇을 동일 인터페이스로 제공
    - with 문 종료 시 무조건 트레이싱 OFF + 비상정지 (크래시에도 로봇이 서 있도록)
    - 초음파 응답 정규화(키 검증·40cm 클램프) — 안전 판정이 센서 이상값에 속지 않도록

실로봇 경로는 DobotLink(ws://localhost:9090) JSON-RPC 를 사용한다.
2026-07-02 실기 검증 완료 사항이 코드에 반영되어 있다:
    - SetTraceAuto 는 isTrace 를 int(1/0) 로, type=0 과 함께 보내야 동작
      (bool 로 보내면 펌웨어가 조용히 무시 — 켜지지도 꺼지지도 않음)
    - 공식 순찰 파라미터: 속도 20, PID (0.5, 0, 0.5)
    - connect 핸드셰이크는 거짓 성공 가능 → battery() 읽기로 링크 검증 필수
    - 초음파는 40cm 이상을 전부 40으로 보고(상한 클램프)

모의로봇(MockGO)은 하드웨어·DobotLink 없이 수업 코드를 끝까지 실행할 수 있게
라인 치우침(offset)과 오도미터를 물리 흉내 수준으로 시뮬레이션한다.
CURRICULUM_FORCE_MOCK=1 환경변수 또는 websockets 미설치 시 자동으로 mock 이 된다.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, Optional, Tuple

_ws_connect: Any = None  # websockets.sync.client.connect (미설치 시 None)
try:
    from websockets.sync.client import connect as _ws_connect  # type: ignore  # noqa: F811

    _HAS_WS = True
except Exception:  # pragma: no cover - websockets 미설치 환경
    _HAS_WS = False

# ---------------------------------------------------------------------------
# 하드웨어 실측으로 확정된 기본값 (2026-07-02)
# ---------------------------------------------------------------------------
DEFAULT_PORT = "COM5"          # GO 무선 동글의 관례 포트 (이 PC 실측)
WS_HOST = "localhost"
WS_PORT = 9090
WS_TIMEOUT_S = 6.0

PATROL_SPEED = 20              # DobotLab '라인 순찰 시작' 버튼과 동일
PATROL_PID = (0.5, 0.0, 0.5)   # 공식 데모 값 — 50 같은 큰 값은 요동으로 라인 이탈
ULTRA_MAX_CM = 40              # 초음파 상한 클램프(실측): 40 이상은 전부 40으로 보고
OBSTACLE_CM = 15               # 이 값(cm) 미만이면 장애물로 판단하는 권장 임계값


def go_is_mock() -> bool:
    """모의로봇 사용 여부 자동 판정.

    CURRICULUM_FORCE_MOCK=1 이면 무조건 mock, websockets 가 없어도 mock.
    """
    if os.environ.get("CURRICULUM_FORCE_MOCK", "").strip() == "1":
        return True
    return not _HAS_WS


class GoError(RuntimeError):
    """GO/DobotLink 통신 오류 (메시지는 학생이 읽는 한국어)."""


# ---------------------------------------------------------------------------
# DobotLink JSON-RPC 클라이언트 (실로봇 경로)
# ---------------------------------------------------------------------------
class _DobotLinkClient:
    """ws://localhost:9090 의 DobotLink 에 붙는 최소 JSON-RPC 클라이언트."""

    def __init__(self, host: str = WS_HOST, port: int = WS_PORT,
                 timeout: float = WS_TIMEOUT_S) -> None:
        self._url = f"ws://{host}:{port}"
        self._timeout = timeout
        self._ws: Any = None  # 연결된 websockets 소켓(미연결 시 None)
        self._next_id = 0

    def connect(self) -> "_DobotLinkClient":
        if not _HAS_WS:
            raise GoError("websockets 패키지가 없습니다. `pip install websockets` 후 다시 실행하세요.")
        try:
            self._ws = _ws_connect(self._url, open_timeout=self._timeout)
        except Exception as e:
            raise GoError(
                f"DobotLink({self._url})에 연결할 수 없습니다. "
                f"DobotLink.exe 가 실행 중인지 확인하세요. ({e})"
            ) from e
        return self

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            finally:
                self._ws = None

    def call(self, method: str, **params: Any) -> Any:
        """요청을 보내고 응답을 기다린다. 오류/타임아웃이면 GoError."""
        import json

        if self._ws is None:
            raise GoError("DobotLink 에 연결되어 있지 않습니다. connect() 먼저 호출하세요.")
        self._next_id += 1
        req_id = self._next_id
        self._ws.send(json.dumps({
            "jsonrpc": "2.0", "id": req_id,
            "method": f"dobotlink.{method}", "params": params,
        }))
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                raw = self._ws.recv(timeout=max(0.05, deadline - time.monotonic()))
            except Exception as e:
                raise GoError(
                    f"'{method}' 응답 대기 중 타임아웃({self._timeout:.0f}초). "
                    f"GO 전원이 켜져 있고 무선 동글이 연결되어 있는지 확인하세요. ({e})"
                ) from e
            msg = json.loads(raw)
            if msg.get("id") != req_id:
                continue  # 다른 알림/응답은 건너뛴다
            if "error" in msg:
                raise GoError(f"'{method}' 호출 실패: {msg['error']}")
            return msg.get("result")
        raise GoError(f"'{method}' 응답 대기 중 타임아웃({self._timeout:.0f}초).")

    def notify(self, method: str, **params: Any) -> None:
        """응답을 기다리지 않는 일방향 전송 (비상정지 전용 — 절대 블록되지 않음)."""
        import json

        if self._ws is None:
            return
        try:
            self._ws.send(json.dumps({
                "jsonrpc": "2.0",
                "method": f"dobotlink.{method}", "params": params,
            }))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 공통 유틸: 초음파 정규화
# ---------------------------------------------------------------------------
_ULTRA_KEYS = ("front", "back", "left", "right")


def normalize_ultra(raw: Any) -> Optional[Dict[str, float]]:
    """초음파 원시 응답을 검증·정규화한다.

    - dict 가 아니거나 front/back/left/right 키가 빠지면 None (→ 호출부는 정지 판단)
    - 0 이하·비수치 값도 None (미장착 센서 센티널 방어)
    - 40cm 초과는 40 으로 클램프 (하드웨어가 원래 40 상한)
    """
    if not isinstance(raw, dict):
        return None
    out: Dict[str, float] = {}
    for k in _ULTRA_KEYS:
        v = raw.get(k)
        if not isinstance(v, (int, float)) or v <= 0:
            return None
        out[k] = min(float(v), float(ULTRA_MAX_CM))
    return out


# ---------------------------------------------------------------------------
# 실로봇 컨트롤러
# ---------------------------------------------------------------------------
class GoController:
    """Magician GO 실로봇 제어. get_go() 를 통해 얻고 with 문으로 사용한다.

    with 블록이 어떻게 끝나든(정상/예외/Ctrl-C) __exit__ 가
    트레이싱 OFF + 비상정지 + 연결 종료를 보장한다.
    """

    is_mock = False

    def __init__(self, port: str = DEFAULT_PORT) -> None:
        self.port = port
        self._client = _DobotLinkClient()

    # -- 연결 ---------------------------------------------------------------
    def connect(self) -> "GoController":
        self._client.connect()
        try:
            self._call("ConnectDobot")
        except GoError as e:
            self._client.close()
            raise GoError(f"GO 연결 실패 (포트 {self.port}): {e}") from e
        # 핸드셰이크는 거짓 성공이 가능하므로 battery() 로 링크를 실제 검증한다.
        try:
            self.battery()
        except GoError as e:
            self._client.close()
            raise GoError(
                f"포트 {self.port} 는 열렸지만 GO 가 응답하지 않습니다. "
                f"로봇 전원 스위치를 확인하세요. ({e})"
            ) from e
        return self

    def __enter__(self) -> "GoController":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # 무슨 일이 있어도 로봇은 멈춘 상태로 끝난다.
        try:
            self.auto_trace(False)
        except Exception:
            pass
        try:
            self.emergency_stop()
        except Exception:
            pass
        self._client.close()

    def close(self) -> None:
        self.__exit__(None, None, None)

    def _call(self, func: str, **params: Any) -> Any:
        params["portName"] = self.port
        return self._client.call(f"MagicianGO.{func}", **params)

    # -- 센서 ---------------------------------------------------------------
    def battery(self) -> Dict[str, Any]:
        return self._call("GetBatteryVoltage")

    def ultrasonic(self) -> Optional[Dict[str, float]]:
        """정규화된 4방향 초음파(cm). 센서 이상 시 None."""
        return normalize_ultra(self._call("GetUltrasoundData"))

    def trace_angle(self) -> Dict[str, int]:
        """하부(CAR) 카메라의 라인 인식 결과 {'angle': .., 'count': ..}."""
        raw = self._call("GetCarCameraAngle")
        if not isinstance(raw, dict):
            return {"angle": 0, "count": 0}
        return {"angle": int(raw.get("angle", 0)), "count": int(raw.get("count", 0))}

    def odometer(self) -> Dict[str, float]:
        raw = self._call("GetSpeedometer")
        return {k: float(raw.get(k, 0.0)) for k in ("x", "y", "yaw")}

    def set_odometer(self, x: float = 0, y: float = 0, yaw: float = 0) -> Any:
        return self._call("SetSpeedometer", x=x, y=y, yaw=yaw)

    # -- 펌웨어 라인 순찰 -----------------------------------------------------
    def trace_speed(self, speed: float) -> Any:
        return self._call("SetTraceSpeed", speed=speed)

    def trace_pid(self, p: float, i: float, d: float) -> Any:
        return self._call("SetTracePid", p=p, i=i, d=d)

    def auto_trace(self, on: bool) -> Any:
        # isTrace 는 반드시 int(1/0) + type=0 — bool 이면 펌웨어가 조용히 무시한다
        # (2026-07-02 실기 검증. DobotLab '라인 순찰' 버튼과 동일한 와이어 포맷)
        self._call("SetTraceLoop", enable=bool(on))
        return self._call("SetTraceAuto", isTrace=int(bool(on)), type=0)

    # -- 주행 ---------------------------------------------------------------
    def move(self, x: float = 0, y: float = 0, r: float = 0) -> Any:
        """연속 속도 주행 (x+: 전진, y+: 좌횡이동, r+: 반시계 회전).

        주의: 멈추라고 할 때까지 계속 달린다. 반드시 유한 루프 안에서 쓰고
        정지는 stop()/with 블록 종료에 맡긴다. |속도| 는 30 으로 클램프.
        """
        clamp = lambda v: max(-30.0, min(30.0, float(v)))  # noqa: E731
        return self._call("SetMoveSpeed", x=clamp(x), y=clamp(y), r=clamp(r))

    def stop(self) -> Any:
        return self.move(0, 0, 0)

    def emergency_stop(self) -> None:
        """응답을 기다리지 않는 정지 — 링크가 죽어도 절대 블록되지 않는다."""
        self._client.notify("MagicianGO.SetMoveSpeed",
                            portName=self.port, x=0, y=0, r=0)


# ---------------------------------------------------------------------------
# 모의 로봇 (하드웨어/DobotLink 없이 수업 코드 전체 실행)
# ---------------------------------------------------------------------------
class MockGO:
    """MagicianGO 의 물리 흉내 모형.

    - 라인 치우침(offset, 도 단위)이 매 스텝 조금씩 흘러가고(드리프트),
      학생의 조향(move 의 r)이 그것을 되돌린다 → P제어가 실제로 '동작'한다.
    - auto_trace(True) 면 펌웨어 PID 를 흉내: P 가 크면 크게 요동친다.
    - 오도미터는 move 명령을 시간 적분해 전진량을 흉내낸다.
    """

    is_mock = True
    CENTER = 245  # 실기 실측 중앙값과 동일하게 맞춘 모의 영점

    def __init__(self, port: str = DEFAULT_PORT) -> None:
        self.port = port
        self._offset = 6.0        # 시작부터 살짝 치우쳐 있게 (학생 조향이 필요하도록)
        self._tick = 0
        self._tracing = False
        self._pid = PATROL_PID
        self._trace_speed = 0.0
        self._odo = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        self._last_move: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.move_log: list = []  # 테스트가 조향 이력을 검사할 수 있도록 기록

    # -- 연결 (즉시 성공) -----------------------------------------------------
    def connect(self) -> "MockGO":
        return self

    def __enter__(self) -> "MockGO":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._tracing = False
        self._last_move = (0.0, 0.0, 0.0)

    def close(self) -> None:
        self.__exit__(None, None, None)

    # -- 센서 ---------------------------------------------------------------
    def battery(self) -> Dict[str, Any]:
        return {"powerVoltage": 11.7, "powerPercentage": 1.0, "powerSourceStatus": 0}

    def ultrasonic(self) -> Optional[Dict[str, float]]:
        return {"front": 40.0, "back": 40.0, "left": 40.0, "right": 40.0}

    def trace_angle(self) -> Dict[str, int]:
        self._step()
        if abs(self._offset) > 60:      # 너무 치우치면 카메라가 라인을 놓친다
            return {"angle": 0, "count": 0}
        return {"angle": int(round(self.CENTER + self._offset)), "count": 1}

    def odometer(self) -> Dict[str, float]:
        return dict(self._odo)

    def set_odometer(self, x: float = 0, y: float = 0, yaw: float = 0) -> None:
        self._odo = {"x": float(x), "y": float(y), "yaw": float(yaw)}

    # -- 펌웨어 순찰 ----------------------------------------------------------
    def trace_speed(self, speed: float) -> None:
        self._trace_speed = float(speed)

    def trace_pid(self, p: float, i: float, d: float) -> None:
        self._pid = (float(p), float(i), float(d))

    def auto_trace(self, on: bool) -> None:
        self._tracing = bool(on)

    # -- 주행 ---------------------------------------------------------------
    def move(self, x: float = 0, y: float = 0, r: float = 0) -> None:
        self._last_move = (float(x), float(y), float(r))
        self.move_log.append(self._last_move)

    def stop(self) -> None:
        self.move(0, 0, 0)

    def emergency_stop(self) -> None:
        self._last_move = (0.0, 0.0, 0.0)

    # -- 내부 물리 흉내 --------------------------------------------------------
    def _step(self) -> None:
        self._tick += 1
        if self._tracing:
            # 펌웨어 PID 흉내: P 가 적정(≈0.5)이면 ±3도, 과대하면 크게 요동
            p = self._pid[0]
            amp = 3.0 if p <= 2.0 else min(70.0, p * 1.4)
            self._offset = amp * math.sin(self._tick * 0.9)
            if self._trace_speed > 0:
                self._odo["x"] += self._trace_speed * 0.24  # 실측 비율(속도20→약 4.8mm/틱)
            return
        # 수동 주행: 드리프트가 라인을 벗어나게 하고, 조향(r)이 되돌린다.
        # 부호 규약: angle > CENTER(offset>0) 일 때 음수 조향(r<0)이 offset 을
        # 줄여야 P제어가 수렴한다 → offset 변화량에 +r_cmd 계수.
        x_cmd, _y, r_cmd = self._last_move
        drift = 1.6 * math.sin(self._tick * 0.35) + 0.9
        self._offset += drift + 1.15 * r_cmd
        if x_cmd:
            self._odo["x"] += x_cmd * 0.24
            self._odo["yaw"] += r_cmd * 0.4


# ---------------------------------------------------------------------------
# 팩토리
# ---------------------------------------------------------------------------
def get_go(port: Optional[str] = None, mock: Optional[bool] = None):
    """GO 컨트롤러 팩토리. `with get_go(port="COM5") as go:` 로 사용한다.

    mock=None 이면 자동판정(go_is_mock): CURRICULUM_FORCE_MOCK=1 또는
    websockets 미설치 시 MockGO, 아니면 실로봇(GoController)에 연결한다.
    """
    use_mock = go_is_mock() if mock is None else bool(mock)
    p = port or DEFAULT_PORT
    if use_mock:
        return MockGO(p).connect()
    return GoController(p).connect()
