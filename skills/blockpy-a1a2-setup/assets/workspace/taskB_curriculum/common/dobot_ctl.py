"""common/dobot_ctl.py — 두봇 라이트(Dobot Magician Lite) 제어 래퍼 (ADR-0002)

목적
----
교육용 커리큘럼에서 학생/강사가 한 줄로 로봇팔을 안전하게 제어하도록 돕는
얇은 래퍼다. 내부적으로 순수 파이썬 라이브러리 ``pydobot``(시리얼 직접 통신,
DLL 불필요)을 사용한다. 자세한 근거는 ``docs/두봇_라이트_API.md`` 7절(pydobot 경로) 참고.

핵심 안전 원칙 (SFR-002)
------------------------
- 모든 이동은 ``common.safety.clamp_move`` 로 작업영역(WORKSPACE) 안으로 클램프한다.
  안전범위를 벗어난 좌표가 들어오면 거부하지 않고 가까운 안전점으로 보정 후 경고를 띄운다.
- ``with`` 블록 종료 시 흡착/그리퍼를 끄는 '안전정지' 후 연결을 해제한다.

하드웨어/키 없이 동작 (ADR-0004)
--------------------------------
- ``pydobot`` import 실패(미설치) 또는 ``config.is_mock()`` 이 True 이면
  실제 하드웨어 대신 :class:`MockDobot` 으로 자동 폴백한다.
- 따라서 이 파일은 로봇·시리얼 포트 없이도 import 되고 자가 데모가 실행된다.

사용법
------
>>> from common.dobot_ctl import get_robot
>>> with get_robot() as bot:          # mock 자동판정(키/하드웨어 없으면 mock)
...     bot.home()                    # 원점 복귀
...     bot.move_to(220, 0, 50)       # 직선 이동(절대좌표, mm)
...     bot.suck(True)                # 흡착 ON
...     print(bot.get_pose())         # {'x':..,'y':..,'z':..,'r':..,'j1':..,..}

명시적으로 mock/실하드웨어를 강제하려면 ``get_robot(mock=True)`` / ``get_robot(mock=False)``.

자가 데모
---------
``python common/dobot_ctl.py`` 실행 시 mock 으로
home → move_to → suck → get_pose 시퀀스를 수행하고 명령 로그를 출력한다.
"""

from __future__ import annotations

# 표준 라이브러리: 경고 출력 / 재시도·정착 지연용
import time
import warnings

# ----------------------------------------------------------------------------
# 1) 의존 모듈 import — 하드웨어/키 없이도 import 되도록 모두 try/except 로 감싼다.
# ----------------------------------------------------------------------------

# (a) pydobot: 실제 로봇 제어용 순수 파이썬 라이브러리. 미설치면 None 으로 두고 mock 폴백.
try:
    import pydobot  # type: ignore
    _PYDOBOT_AVAILABLE = True            # pydobot 사용 가능 플래그
except Exception:                        # ImportError 외에 시리얼 의존성 문제 등도 포괄
    pydobot = None                       # 미설치 시 None
    _PYDOBOT_AVAILABLE = False

# ----------------------------------------------------------------------------
# 1-1) pydobot.Dobot._read_message 'patient-read' 몽키패치 (검증된 1차 방어선)
# ----------------------------------------------------------------------------
# 근본원인: pydobot 기본 ``Dobot._read_message`` 는 시리얼 응답을 0.1초만 단발로
# 기다린 뒤 None 을 반환한다. 빠른 연속 이동에서 응답이 그 안에 다 안 오면 None 이
# 돌아오고, 이를 사용하는 pydobot 내부가
# ``AttributeError: 'NoneType' object has no attribute 'params'`` 로 크래시한다
# (실측: 게임 중 약 1/3 이동 실패, 아래 _retry/_reconnect 재시도로도 가끔 복구 실패).
#
# 해결: 응답을 충분히(최대 2초) 기다리며 들어오는 바이트를 누적하고, 데이터가
# 들어온 뒤 더 이상 오지 않으면 메시지 완성으로 간주해 한 번에 파싱하는
# 'patient-read' 버전으로 모듈 임포트 시점에 한 번 교체한다.
# (실측: patient_read 적용 후 16/16 이동 성공·0 실패·재시도경고 0 으로 완전 해결)
#
# - 이 패치는 _retry/_reconnect/_settle(아래 RobotController) 의 이중 안전망보다
#   앞단에서 동작하는 **1차 방어선**이다. 기존 로직은 그대로 유지한다.
# - 실 pydobot.Dobot 에만 적용되며 MockDobot/ mock 경로에는 전혀 영향이 없다.
# - import(또는 Message 임포트) 실패 시 조용히 건너뛴다(무해). pydobot 미설치면 패치 안 함.
if _PYDOBOT_AVAILABLE:
    try:
        from pydobot.message import Message as _PydobotMessage  # type: ignore

        def _patient_read_message(self):
            """pydobot.Dobot._read_message 의 인내심 있는 대체 구현.

            원본은 0.1초만 기다리고 None 을 반환하지만, 이 버전은 최대 2초까지
            바이트를 누적하며 기다리고, 데이터가 들어온 뒤 잠시 더 안 오면 메시지가
            완성된 것으로 보고 한 번에 파싱한다(원본 시그니처 self 유지)."""
            buf = bytearray()
            deadline = time.time() + 2.0
            idle = 0
            while time.time() < deadline:
                b = self.ser.read_all()
                if b:
                    buf.extend(b)
                    idle = 0
                elif buf:
                    idle += 1
                    if idle >= 2:   # 데이터가 들어온 뒤 더 안 오면 메시지 완성으로 간주
                        break
                time.sleep(0.04)
            if buf:
                try:
                    return _PydobotMessage(bytes(buf))
                except Exception:
                    return None
            return None

        # 실제 교체(monkeypatch). 교체 실패해도 무해하도록 전체를 try/except 로 감쌌다.
        pydobot.dobot.Dobot._read_message = _patient_read_message
    except Exception:
        # pydobot 구조 변경/임포트 실패 등 — 패치를 건너뛰어도 기존 안전망으로 동작.
        pass

# (b) 시리얼 포트 자동탐지(선택). 없어도 동작해야 하므로 try/except.
try:
    from serial.tools import list_ports  # type: ignore
except Exception:
    list_ports = None                    # 포트 탐지 불가 시 None

# (c) config: 작업영역/mock 판정. 아직 없을 수 있으므로 폴백 기본값을 둔다.
try:
    from common import config            # type: ignore
except Exception:
    config = None  # type: ignore[assignment]  # config 미존재 시 아래 _is_mock 가 보수적으로 mock 선택

# (d) safety: 안전필터(클램프/검사). 없으면 항등(클램프 안 함) 폴백을 제공한다.
try:
    from common import safety            # type: ignore
except Exception:
    safety = None  # type: ignore[assignment]

# config 가 없을 때 사용할 보수적 기본 작업영역(강사매뉴얼/CONTRACTS 와 동일 값).
_DEFAULT_WORKSPACE = {
    "x": (180, 320),    # 전후(mm)
    "y": (-150, 150),   # 좌우(mm)
    "z": (-60, 150),    # 상하(mm)
    "r": (-150, 150),   # 엔드이펙터 회전(deg)
}


def _is_mock(mock: bool | None) -> bool:
    """이 컨트롤러가 mock 으로 동작해야 하는지 최종 판정한다.

    우선순위:
      1) 인자 ``mock`` 이 명시되면(True/False) 그대로 따른다.
      2) pydobot 이 없으면 무조건 mock(실하드웨어 불가).
      3) config.robot_is_mock() 결과를 따른다 — **로봇은 pydobot 유무로만 판정하며
         LLM 키 유무와 무관하다**(ADR/설계: LLM 없이도 로봇은 실제 동작해야 함).
      4) config 도 없으면 안전하게 mock 으로 본다.
    """
    if mock is not None:                  # 1) 명시적 지정이 최우선
        return bool(mock)
    if not _PYDOBOT_AVAILABLE:            # 2) 라이브러리가 없으면 실하드웨어 불가
        return True
    if config is not None:
        # 로봇 전용 판정(robot_is_mock)을 우선 사용. 구버전 호환으로 is_mock 폴백.
        decider = getattr(config, "robot_is_mock", None) or getattr(config, "is_mock", None)
        if decider is not None:
            try:
                return bool(decider())     # 3) 로봇 mock 자동판정(키와 무관)
            except Exception:
                return True                # 판정 중 오류 시 안전하게 mock
    return True                            # 4) config 부재 → mock


def _get_workspace() -> dict:
    """현재 작업영역(안전 한계)을 반환한다. config 가 있으면 그 값을, 없으면 기본값."""
    if config is not None and hasattr(config, "WORKSPACE"):
        return config.WORKSPACE
    return _DEFAULT_WORKSPACE


def _clamp(x, y, z, r):
    """좌표를 작업영역 안으로 클램프한다.

    common.safety.clamp_move 가 있으면 그것을 사용하고(SFR-002 단일 출처),
    없으면 내장 폴백으로 WORKSPACE 범위에 맞춰 직접 클램프한다.
    반환: (x, y, z, r, clamped) — clamped 는 보정이 일어났는지 여부(bool).
    """
    # 1순위: 안전 모듈의 공식 클램프 사용
    if safety is not None and hasattr(safety, "clamp_move"):
        cx, cy, cz, cr = safety.clamp_move(x, y, z, r)
        # 입력과 결과가 다르면 보정이 일어난 것
        clamped = (cx, cy, cz, cr) != (x, y, z, r)
        return cx, cy, cz, cr, clamped

    # 폴백: WORKSPACE 범위로 직접 클램프
    ws = _get_workspace()

    def _cl(v, lo_hi):
        lo, hi = lo_hi
        return min(max(v, lo), hi)        # [lo, hi] 구간으로 제한

    cx = _cl(x, ws["x"])
    cy = _cl(y, ws["y"])
    cz = _cl(z, ws["z"])
    cr = _cl(r, ws["r"])
    clamped = (cx, cy, cz, cr) != (x, y, z, r)
    return cx, cy, cz, cr, clamped


# ----------------------------------------------------------------------------
# 2) MockDobot — 하드웨어 없는 가짜 로봇. RobotController 가 감싸는 내부 드라이버이며,
#    pydobot.Dobot 과 동일한 호출 인터페이스(pose/move_to/suck/grip/...)를 흉내 낸다.
#    모든 명령을 self.log 리스트에 기록한다(테스트/검수/교육 시연용).
# ----------------------------------------------------------------------------
class MockDobot:
    """가짜 두봇 — 실제 하드웨어 없이 명령을 기록만 한다.

    pydobot.Dobot 과 같은 메서드(pose/move_to/suck/grip/speed/wait/close)를 제공하므로
    RobotController 입장에서 실드라이버와 똑같이 다룰 수 있다.
    모든 호출은 ``self.log`` 에 ``(명령이름, 인자...)`` 형태로 적재된다.
    """

    def __init__(self, port=None, verbose=False):
        # 내부 상태: 현재 포즈(좌표/관절). 홈 기준의 합리적 초기값.
        self.x, self.y, self.z, self.r = 200.0, 0.0, 0.0, 0.0
        self.j1 = self.j2 = self.j3 = self.j4 = 0.0
        self.port = port                  # 받은 포트(가짜이므로 사용 안 함)
        self.verbose = verbose            # 로그를 화면에도 출력할지
        self.log: list[tuple] = []        # 명령 기록 리스트
        self._suction = False             # 흡착 상태
        self._grip = False                # 그리퍼 상태
        self._record("__init__", port)    # 생성도 기록

    def _record(self, name, *args):
        """명령 한 건을 로그에 적재(필요 시 화면 출력)."""
        entry = (name, *args)
        self.log.append(entry)
        if self.verbose:
            print(f"[MockDobot] {entry}")

    # --- pydobot.Dobot 호환 메서드들 ---------------------------------------
    def home(self):
        """원점 복귀(가짜). 포즈를 홈 기준값으로 되돌린다."""
        self.x, self.y, self.z, self.r = 200.0, 0.0, 0.0, 0.0
        self.j1 = self.j2 = self.j3 = self.j4 = 0.0
        self._record("home")

    def move_to(self, x, y, z, r=0.0, wait=False):
        """직선 이동(가짜). 내부 포즈를 목표값으로 갱신하고 기록."""
        self.x, self.y, self.z, self.r = float(x), float(y), float(z), float(r)
        self._record("move_to", x, y, z, r, wait)

    def suck(self, enable):
        """흡착 ON/OFF(가짜)."""
        self._suction = bool(enable)
        self._record("suck", bool(enable))

    def grip(self, enable):
        """그리퍼 잡기/놓기(가짜)."""
        self._grip = bool(enable)
        self._record("grip", bool(enable))

    def pump_off(self):
        """엔드이펙터 공압 펌프 완전 정지(가짜) — isCtrlEnabled=0 상당.

        실 pydobot 의 grip/suck(False) 는 펌프를 켠 채 그리퍼만 여는 것과 달리,
        이건 펌프 자체를 끈 상태를 표현한다. 흡착/그리퍼 상태도 해제로 본다."""
        self._suction = False
        self._grip = False
        self._pump = False
        self._record("pump_off")

    def speed(self, velocity=100.0, acceleration=100.0):
        """속도/가속 설정(가짜)."""
        self._record("speed", velocity, acceleration)

    def wait(self, ms):
        """대기(가짜) — 실제로 멈추지 않고 기록만 한다."""
        self._record("wait", ms)

    def pose(self):
        """현재 포즈를 pydobot 과 같은 8-튜플로 반환."""
        self._record("pose")
        return (self.x, self.y, self.z, self.r,
                self.j1, self.j2, self.j3, self.j4)

    def close(self):
        """연결 해제(가짜)."""
        self._record("close")


# ----------------------------------------------------------------------------
# 3) RobotController — CONTRACTS 의 공개 인터페이스. 실드라이버/Mock 을 동일하게 감싼다.
# ----------------------------------------------------------------------------
class RobotController:
    """두봇 라이트 제어기 (pydobot 래퍼, ADR-0002).

    mock 여부에 따라 내부 드라이버로 :class:`MockDobot` 또는 ``pydobot.Dobot`` 을 쓴다.
    공개 메서드: connect/home/move_to/suck/grip/get_pose/disconnect 와 컨텍스트 매니저.

    실하드웨어 안정화 (통신 글리치 대응 + 재연결 복구)
    --------------------------------------------------
    실제 두봇(pydobot)으로 빠른 연속 이동 명령을 보내면, 간헐적으로 응답이 None 으로
    와서 pydobot 내부에서 ``AttributeError: 'NoneType' object has no attribute 'params'``
    류의 통신 오류로 크래시한다(실측). 같은 명령을 즉시 재시도해도 시리얼 버퍼/연결이
    어긋난(desync) 상태라 복구되지 않는 경우가 있다. 이를 막기 위해
    **실하드웨어(self.mock=False)에서만**:
      - 모든 device.* 호출을 :meth:`_retry` 재시도 래퍼로 감싼다
        (실패 시 ``_RETRY_DELAY`` 만큼 sleep 후 ``_MAX_RETRIES`` 회까지 재시도).
      - 재시도 직전마다 :meth:`_flush_input` 로 시리얼 입력 버퍼의 잔류 바이트를
        비워 응답 어긋남(desync)을 줄인다.
      - in-place 재시도(N회)로도 실패하면 :meth:`_reconnect` 로 **연결을 재설정**한 뒤
        실패했던 동작을 한 번 더 시도한다(reconnect-on-failure). pydobot.Dobot 의
        재연결은 큐 클리어+포즈읽기만 하므로 팔이 움직이지 않아 안전하다.
      - 큐 이동(move_to/home) 직후 ``_SETTLE_DELAY`` 만큼의 작은 정착 지연을 둬
        연속 명령을 안정화한다(교육용 반응성 유지를 위해 과도한 지연은 금지).
    mock(MockDobot) 경로에는 지연/재시도/재연결을 적용하지 않는다(즉시 동작·결정성 유지).
    """

    # --- 실하드웨어 안정화 상수(필요 시 인자/속성으로 조정 가능) -------------
    _MAX_RETRIES = 3        # device.* 호출 실패 시 최대 (in-place) 재시도 횟수
    _RETRY_DELAY = 0.4      # 재시도 전 대기(초)
    _SETTLE_DELAY = 0.3     # 큐 이동 후 정착 지연(초) — 연속 명령 안정화

    def __init__(self, port=None, mock=None,
                 settle_delay=None, max_retries=None, retry_delay=None):
        # 사용할 포트(None 이면 connect 시 자동탐지 시도). config.DOBOT_PORT 가 있으면 보조로 사용.
        self.port = port
        if self.port is None and config is not None:
            self.port = getattr(config, "DOBOT_PORT", None)
        # 최종 mock 판정(인자 → pydobot 유무 → config 순)
        self.mock = _is_mock(mock)
        self.device = None                # 내부 드라이버(연결 후 채워짐)
        self.connected = False            # 연결 상태 플래그
        # 안정화 파라미터: 인자로 받으면 인스턴스 속성으로 덮어쓰고, 아니면 클래스 상수 사용.
        if settle_delay is not None:
            self._settle_delay = float(settle_delay)
        else:
            self._settle_delay = self._SETTLE_DELAY
        if max_retries is not None:
            self._max_retries = int(max_retries)
        else:
            self._max_retries = self._MAX_RETRIES
        if retry_delay is not None:
            self._retry_delay = float(retry_delay)
        else:
            self._retry_delay = self._RETRY_DELAY

    # --- 연결 / 해제 -------------------------------------------------------
    def connect(self) -> bool:
        """로봇에 연결한다. mock 이면 MockDobot 생성, 아니면 pydobot.Dobot 연결.

        반환: 연결 성공 여부(bool). 실하드웨어 연결 실패 시 자동으로 mock 으로 폴백한다.
        """
        if self.connected:                # 중복 연결 방지
            return True

        if self.mock:                     # mock 모드: 가짜 로봇
            self.device = MockDobot(port=self.port)
            self.connected = True
            return True

        # 실하드웨어 모드: 포트 자동탐지(미지정 시)
        port = self._resolve_port()
        try:
            # pydobot 연결 (verbose=False: 교육용으로 콘솔 소음 최소화)
            self.device = self._open_device(port)
            self.port = port                      # 재연결 복구에서 재사용하도록 확정 포트 보관
            self.connected = True
            return True
        except Exception as e:            # 연결 실패 → 친절한 경고 후 mock 폴백
            warnings.warn(
                f"로봇 연결에 실패했습니다({e}). 모의(mock) 모드로 전환합니다. "
                f"하드웨어/포트를 확인하세요."
            )
            self.mock = True
            self.device = MockDobot(port=port)
            self.connected = True
            return True

    def _resolve_port(self):
        """사용할 시리얼 포트를 결정한다.

        우선순위: self.port(명시/config.DOBOT_PORT) > 자동탐지.
        자동탐지는 **블루투스 포트를 제외하고 USB 시리얼(두봇)을 우선** 선택한다.
        (블루투스 COM 은 열면 'Access denied' 가 나므로 첫 포트를 무작정 쓰면 안 됨.)
        """
        port = self.port
        if port is None and list_ports is not None:
            ports = list(list_ports.comports())   # 연결된 시리얼 포트 목록
            if ports:
                def _score(p):
                    desc = " ".join(str(x or "") for x in
                                    (p.description, p.device,
                                     getattr(p, "manufacturer", ""),
                                     getattr(p, "hwid", ""))).lower()
                    if "bluetooth" in desc or "블루투스" in desc:
                        return -1                 # 블루투스 제외
                    s = 0
                    if "usb" in desc:
                        s += 2                    # USB 시리얼 우선(두봇)
                    if any(k in desc for k in ("serial", "ch340", "cp210", "ftdi", "silicon")):
                        s += 1
                    return s
                cand = [p for p in ports if _score(p) >= 0]   # 블루투스 빼고
                if cand:
                    cand.sort(key=_score, reverse=True)
                    port = cand[0].device
                else:
                    port = ports[0].device        # 전부 블루투스뿐이면 폴백
        return port

    def _open_device(self, port):
        """pydobot.Dobot 인스턴스를 생성해 반환한다(연결 핵심 로직 단일 출처).

        pydobot.Dobot.__init__ 은 큐 시작/클리어 + 파라미터 설정 + 포즈 읽기만 하고
        실제 모션(이동)은 수행하지 않으므로, 이 호출만으로 팔이 움직이지 않는다.
        => 재연결 복구(:meth:`_reconnect`)에서 재사용해도 안전하다.
        """
        return pydobot.Dobot(port=port, verbose=False)

    def disconnect(self) -> None:
        """연결을 해제한다. 이미 끊겼으면 아무것도 하지 않는다."""
        if self.device is not None:
            try:
                self.device.close()       # pydobot/Mock 공통 close()
            except Exception as e:
                warnings.warn(f"연결 해제 중 경고: {e}")
        self.device = None
        self.connected = False

    def _ensure(self):
        """명령 전 연결을 보장한다(미연결이면 자동 connect)."""
        if not self.connected:
            self.connect()

    # --- 실하드웨어 안정화: 입력버퍼 플러시 / 재연결 복구 / 재시도 래퍼 -----
    def _flush_input(self):
        """시리얼 입력 버퍼의 잔류 바이트를 비운다(응답 어긋남=desync 예방).

        실하드웨어에서 연속 명령 중 응답이 어긋나면(이전 응답의 잔류 바이트가 다음
        명령의 응답으로 잘못 해석됨) None 응답/AttributeError 의 원인이 된다.
        pydobot.Dobot 은 내부에 ``ser``(pyserial.Serial)를 직접 들고 있으므로
        ``device.ser.reset_input_buffer()`` 로 잔류 바이트를 비운다.
        ser 가 없거나(또는 Mock) 호출이 실패해도 조용히 무시한다(베스트-에포트).
        """
        if self.mock:                     # mock: 시리얼 없음 → 아무것도 안 함
            return
        try:
            ser = getattr(self.device, "ser", None)
            if ser is not None and hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
        except Exception:
            pass                          # 플러시는 베스트-에포트 — 실패해도 무시

    def _reconnect(self):
        """연결을 안전하게 재설정한다(reconnect-on-failure 의 핵심).

        현재 device 를 close 한 뒤 같은 포트(self.port)로 pydobot.Dobot 을 다시 연다.
        pydobot.Dobot.__init__ 은 큐 클리어 + 포즈읽기만 하고 모션은 없으므로 팔이
        움직이지 않아 재연결이 안전하다(실하드웨어 전용 — mock 에서는 호출되지 않음).
        실패하면 예외를 그대로 전파한다(상위 _retry 가 잡아 최종 메시지로 변환).
        """
        # 1) 기존 연결을 안전하게 정리(close 실패는 무시 — 어차피 새로 열 것).
        old = self.device
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.device = None
        self.connected = False
        # 2) 같은 포트로 재연결(자동탐지가 필요하면 _resolve_port 가 처리).
        port = self._resolve_port()
        self.device = self._open_device(port)
        self.port = port
        self.connected = True

    def _retry(self, action_name, func, *args, **kwargs):
        """device.* 호출을 통신 글리치에 강건하게 감싸는 재시도 + 재연결 래퍼.

        실하드웨어(self.mock=False)에서만 동작하며 다음 순서로 복구를 시도한다:
          1) 호출이 통신 오류로 실패하면 입력버퍼를 플러시하고 ``self._retry_delay``
             만큼 sleep 후 ``self._max_retries`` 회까지 in-place 재시도한다.
          2) in-place 재시도로도 실패하면 :meth:`_reconnect` 로 연결을 재설정한 뒤
             실패했던 동작(func)을 한 번 더 호출한다(reconnect-on-failure).
          3) 재연결 후 호출도 실패하면 어느 동작/포트에서 실패했는지 담은 친절한
             한국어 RuntimeError 로 raise 한다(원인 체이닝).
        대표 증상: 응답이 None 으로 와서 pydobot 내부가
        ``AttributeError: 'NoneType' object has no attribute 'params'`` 로 크래시.
        같은 명령을 즉시 재시도해도 시리얼 버퍼/연결이 어긋나면 복구가 안 되므로
        (1)의 플러시와 (2)의 재연결이 필요하다.

        mock 경로에서는 지연/재시도/재연결 없이 즉시 1회만 호출한다(반응성·결정성 유지).

        action_name : 실패 메시지에 표시할 동작 이름(예: "이동(move_to)").
        func        : 실제로 호출할 device 메서드(또는 임의의 호출 가능 객체).

        주의: func 는 보통 ``self.device.<메서드>`` 형태의 바운드 메서드로 전달된다.
        재연결 시 device 객체가 새로 만들어지므로, 재연결 후 호출은 새 device 의
        같은 이름 메서드를 다시 바인딩해 호출한다(메서드 이름으로 재바인딩).
        """
        # mock 경로: 안정화 불필요 → 그대로 1회 호출(예외도 그대로 전파).
        if self.mock:
            return func(*args, **kwargs)

        last_exc = None
        # 총 시도 횟수 = 최초 1회 + 재시도. (_max_retries 가 '최대 재시도 횟수')
        attempts = max(1, self._max_retries)
        for attempt in range(1, attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:  # AttributeError(None 응답)·serial 예외 등 통신오류 포괄
                last_exc = e
                if attempt < attempts:
                    # 마지막 시도가 아니면: 입력버퍼 플러시 + 잠시 쉬고 재시도.
                    self._flush_input()   # 잔류 바이트 비우기(desync 회복)
                    warnings.warn(
                        f"로봇 통신 오류로 '{action_name}' 재시도 "
                        f"{attempt}/{attempts - 1} (원인: {e})"
                    )
                    time.sleep(self._retry_delay)

        # --- in-place 재시도 전부 실패 → 재연결 복구(reconnect-on-failure) ---
        warnings.warn(
            f"로봇 '{action_name}' 이 {attempts}회 재시도로도 실패하여 "
            f"연결을 재설정합니다(포트: {self.port})."
        )
        try:
            self._reconnect()                              # 연결 재설정(팔 안 움직임)
            self._flush_input()                            # 재연결 직후 입력버퍼 정리
            time.sleep(self._retry_delay)                  # 재연결 안정화 대기
            rebound = self._rebind(func)                   # 새 device 에 메서드 재바인딩
            return rebound(*args, **kwargs)                # 실패했던 동작 재실행
        except Exception as e:
            last_exc = e

        # 재연결 후에도 실패 → 친절한 한국어 메시지로 raise(원인 체이닝).
        raise RuntimeError(
            f"로봇 '{action_name}' 동작이 통신 오류로 {attempts}회 재시도와 "
            f"재연결 복구 후에도 실패했습니다(포트: {self.port}). "
            f"케이블/포트 연결과 펌웨어 상태를 확인하세요. "
            f"(마지막 오류: {last_exc})"
        ) from last_exc

    def _rebind(self, func):
        """재연결 후, func 가 (재연결 전) device 의 바운드 메서드였다면 새 device 의
        같은 이름 메서드로 다시 바인딩해 돌려준다.

        device 메서드가 아니면(임의 호출 가능 객체) func 를 그대로 반환한다.
        """
        # 바운드 메서드의 소유 객체(__self__)가 (구) device 였으면 새 device 로 교체.
        owner = getattr(func, "__self__", None)
        name = getattr(func, "__name__", None)
        if owner is not None and name and self.device is not None:
            rebound = getattr(self.device, name, None)
            if callable(rebound):
                return rebound
        return func

    def _settle(self):
        """큐 이동(move_to/home) 직후의 작은 정착 지연.

        실하드웨어(self.mock=False)에서만 ``self._settle_delay`` 초 만큼 쉬어
        빠른 연속 명령에서 응답이 None 으로 오는 통신 글리치를 줄인다.
        mock 경로에서는 아무 일도 하지 않는다(즉시).
        """
        if self.mock:
            return
        if self._settle_delay and self._settle_delay > 0:
            time.sleep(self._settle_delay)

    # --- 동작 명령 ---------------------------------------------------------
    def home(self) -> None:
        """원점 복귀. 전원 직후 좌표 신뢰성 확보를 위해 권장(API 문서 8절)."""
        self._ensure()
        # MockDobot 은 home() 을 갖지만, 실 pydobot.Dobot 에는 home() 이 없다.
        if hasattr(self.device, "home"):
            self._retry("원점 복귀(home)", self.device.home)   # MockDobot 경로
        else:
            # pydobot 경로: 별도 홈 명령이 없으므로 작업영역 중앙 안전점으로 이동해 대체한다.
            ws = _get_workspace()
            hx = (ws["x"][0] + ws["x"][1]) / 2.0   # x 중앙
            hy = 0.0                                # y 중앙(좌우 0)
            hz = ws["z"][1]                         # z 최상단(가장 안전)
            self._retry("원점 복귀(home)",
                        self.device.move_to, hx, hy, hz, 0.0, wait=True)
        # 큐 이동 후 정착 지연(실하드웨어에서만) — 연속 명령 안정화.
        self._settle()

    def move_to(self, x, y, z, r=0.0, wait=True) -> dict:
        """직선 이동(절대좌표, mm/deg). 안전범위 밖이면 클램프하고 경고한다.

        반환: 실행 결과 dict
          {'requested': {x,y,z,r}, 'actual': {x,y,z,r}, 'clamped': bool}
        """
        self._ensure()
        # 1) 안전 클램프: 작업영역 밖이면 가까운 안전점으로 보정
        cx, cy, cz, cr, clamped = _clamp(x, y, z, r)
        if clamped:
            # 거부 대신 보정 + 경고(교육용: 왜 못 가는지 학생에게 알려줌)
            warnings.warn(
                f"요청 좌표({x}, {y}, {z}, r={r})가 안전 작업영역을 벗어나 "
                f"({cx}, {cy}, {cz}, r={cr})로 클램프했습니다."
            )
        # 2) 실제 이동(보정된 안전 좌표로) — 통신 글리치 대비 재시도 래퍼로 감쌈.
        self._retry("이동(move_to)",
                    self.device.move_to, cx, cy, cz, cr, wait=wait)
        # 큐 이동 후 정착 지연(실하드웨어에서만) — 연속 명령 안정화.
        self._settle()
        # 3) 결과 보고
        return {
            "requested": {"x": x, "y": y, "z": z, "r": r},
            "actual": {"x": cx, "y": cy, "z": cz, "r": cr},
            "clamped": clamped,
        }

    def suck(self, on: bool) -> None:
        """흡착컵 ON/OFF."""
        self._ensure()
        self._retry("흡착(suck)", self.device.suck, bool(on))

    def grip(self, on: bool) -> None:
        """그리퍼 잡기(True)/놓기(False)."""
        self._ensure()
        self._retry("그리퍼(grip)", self.device.grip, bool(on))

    def grasp(self, on: bool) -> None:
        """엔드이펙터 추상화: 부착한 도구에 맞게 '집기/놓기'를 수행한다.

        config.EFFECTOR 가 "gripper"(기본/실측)면 그리퍼(grip)를, "suction"이면
        흡착컵(suck)을 사용한다. 차시 코드는 이 메서드만 호출하면 되며, 실제 교구가
        그리퍼든 흡착이든 같은 픽앤플레이스 로직이 그대로 동작한다.

        on : True = 잡기(집기), False = 놓기.
        """
        self._ensure()
        # config 가 있으면 EFFECTOR 설정을 따르고, 없으면 보수적으로 그리퍼로 본다(실측 기본).
        effector = getattr(config, "EFFECTOR", "gripper") if config is not None else "gripper"
        if str(effector).lower() == "suction":
            self.suck(bool(on))           # 흡착컵: ON=집기, OFF=놓기
        else:
            self.grip(bool(on))           # 그리퍼(기본): True=잡기, False=놓기

    def get_pose(self) -> dict:
        """현재 포즈를 dict 로 반환: {x,y,z,r,j1,j2,j3,j4}."""
        self._ensure()
        x, y, z, r, j1, j2, j3, j4 = self._retry("포즈 조회(get_pose)", self.device.pose)
        return {"x": x, "y": y, "z": z, "r": r,
                "j1": j1, "j2": j2, "j3": j3, "j4": j4}

    def pump_off(self) -> None:
        """엔드이펙터 공압 펌프를 완전히 끈다(isCtrlEnabled=0).

        suck(False)/grip(False) 는 진공/그립만 해제할 뿐 펌프는 계속 돈다. '펌프 꺼'
        같은 명령은 이 메서드로 펌프 회로 자체를 끈다(공개 API). 내부 구현 위임.
        """
        self._effector_pump_off()

    # --- 엔드이펙터 펌프 완전 정지 -----------------------------------------
    def _effector_pump_off(self) -> None:
        """엔드이펙터 공압 펌프를 **완전히 끈다**(isCtrlEnabled=0).

        실측 문제: pydobot 의 grip(False)/suck(False) 는 명령 첫 바이트를 항상
        isCtrlEnabled=1 로 보내, '그리퍼만 열' 뿐 **공압 펌프는 계속 돈다**(소음·발열·잔압).
        종료(창 닫기/with 종료) 시엔 펌프 자체를 꺼야 하므로, SetEndEffectorGripper /
        SuctionCup 명령을 **isCtrlEnabled=0(첫 바이트 0x00)** 으로 직접 만들어 보낸다.

        - 실 pydobot(device._send_command 보유): 원시 Message 두 개(그리퍼/흡착) 전송.
        - MockDobot(pump_off 보유): 기록만.
        종료 경로이므로 실패해도 예외를 던지지 않고 경고만 남긴다.
        """
        dev = self.device
        if dev is None:
            return
        # 실 pydobot 경로: isCtrlEnabled=0 원시 명령
        if hasattr(dev, "_send_command"):
            try:
                from pydobot.message import Message
                from pydobot.enums.CommunicationProtocolIDs import CommunicationProtocolIDs as _CID  # type: ignore[import-untyped]
                from pydobot.enums.ControlValues import ControlValues as _CV  # type: ignore[import-untyped]
            except Exception as e:                      # pydobot 내부 경로가 다르면 조용히 포기
                warnings.warn(f"펌프 OFF 준비 실패(원시 명령 불가): {e}")
                return
            for _name, _id in (("그리퍼", _CID.SET_GET_END_EFFECTOR_GRIPPER),
                               ("흡착", _CID.SET_GET_END_EFFECTOR_SUCTION_CUP)):
                try:
                    msg = Message()
                    msg.id = _id
                    msg.ctrl = _CV.THREE
                    msg.params = bytearray([0x00, 0x00])  # [isCtrlEnabled=0, state=0] → 펌프 OFF
                    dev._send_command(msg)                # 종료 경로: 재시도/재연결 없이 1회 전송
                except Exception as e:
                    warnings.warn(f"펌프 OFF({_name}) 중 경고: {e}")
            return
        # MockDobot 등: 기록만(테스트 가시성)
        if hasattr(dev, "pump_off"):
            try:
                dev.pump_off()
            except Exception:
                pass

    # --- 안전정지 ----------------------------------------------------------
    def _safe_stop(self) -> None:
        """안전정지: 흡착/그리퍼를 꺼 물체 낙하·끼임을 막고, **공압 펌프까지 완전히 끈다**.

        순서: (1) 흡착/그리퍼 '놓기'로 잡고 있던 물체를 먼저 안전하게 해제 →
              (2) 펌프 자체를 끈다(isCtrlEnabled=0). 놓기만 하면 펌프가 계속 돌기 때문.
        각 단계를 독립적으로 try 로 감싸(한쪽 실패가 다른쪽을 막지 않게), 종료 경로이므로
        끝까지 실패해도 예외를 던지지 않고 경고만 남긴다."""
        if self.device is None:
            return
        # (1) 흡착 해제와 그리퍼 개방을 각각 독립적으로 시도(잡은 물체 먼저 놓기).
        try:
            self._retry("안전정지-흡착 해제(suck off)", self.device.suck, False)
        except Exception as e:
            warnings.warn(f"안전정지(흡착 해제) 중 경고: {e}")
        try:
            self._retry("안전정지-그리퍼 개방(grip off)", self.device.grip, False)
        except Exception as e:
            warnings.warn(f"안전정지(그리퍼 개방) 중 경고: {e}")
        # 그리퍼가 실제로 열릴 시간을 잠깐 준 뒤(실하드웨어만) 펌프를 끈다.
        if hasattr(self.device, "_send_command"):
            try:
                time.sleep(0.4)
            except Exception:
                pass
        # (2) 공압 펌프 자체를 완전히 끈다(isCtrlEnabled=0). ← 핵심: 놓기만으론 펌프가 계속 돈다.
        self._effector_pump_off()

    # --- 컨텍스트 매니저 ---------------------------------------------------
    def __enter__(self) -> "RobotController":
        """with 진입 시 자동 연결."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:  # type: ignore[exit-return]
        """with 종료 시 안전정지 후 연결 해제. 예외는 억제하지 않는다(False)."""
        self._safe_stop()                 # 1) 엔드이펙터 끄기
        self.disconnect()                 # 2) 연결 해제
        return False                      # 예외를 그대로 전파


# ----------------------------------------------------------------------------
# 4) 팩토리 함수 — 권장 진입점.
# ----------------------------------------------------------------------------
def get_robot(port=None, mock=None) -> RobotController:
    """RobotController 를 생성해 반환한다(연결은 connect()/with 에서).

    인자
      port: 시리얼 포트(None 이면 자동탐지/config 값)
      mock: True/False 강제, None 이면 자동판정(키·하드웨어 없으면 mock)
    """
    return RobotController(port=port, mock=mock)


# ----------------------------------------------------------------------------
# 5) 자가 데모 (mock) — 하드웨어 없이 실행 가능. home → move_to → suck → pose.
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== dobot_ctl 자가 데모 (mock) ===")
    print(f"pydobot 사용 가능: {_PYDOBOT_AVAILABLE} / config 로드: {config is not None} "
          f"/ safety 로드: {safety is not None}")

    # mock=True 로 강제해 하드웨어 없이 안전하게 시연
    with get_robot(mock=True) as bot:
        bot.home()                                  # 1) 원점 복귀
        r1 = bot.move_to(220, 0, 50)                # 2) 정상 좌표 이동
        print("move_to(정상):", r1)
        r2 = bot.move_to(500, 0, 50)                # 3) 범위 밖 → 클램프 + 경고
        print("move_to(범위밖→클램프):", r2)
        bot.suck(True)                              # 4) 흡착 ON
        print("get_pose:", bot.get_pose())          # 5) 현재 포즈 조회

    # with 종료 후: 내부 mock 로그를 다시 만들 수 없으므로(이미 disconnect됨),
    # 시퀀스 로그를 보고 싶으면 명시적으로 device 를 유지한 채 확인한다.
    print("\n=== 명령 로그 확인용 재시연 ===")
    bot2 = get_robot(mock=True)
    bot2.connect()
    bot2.home()
    bot2.move_to(220, 0, 50)
    bot2.suck(True)
    bot2.get_pose()
    print("MockDobot.log:")
    for i, entry in enumerate(bot2.device.log, 1):  # 기록된 모든 명령 출력
        print(f"  {i:02d}. {entry}")
    bot2._safe_stop()
    bot2.disconnect()
    print("\n데모 완료: 하드웨어 없이 mock 으로 home→move_to→suck→pose 시퀀스 실행됨.")
