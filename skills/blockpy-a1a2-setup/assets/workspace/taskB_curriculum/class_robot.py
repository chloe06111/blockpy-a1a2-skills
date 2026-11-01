# -*- coding: utf-8 -*-
"""[실습준비 · BlockPy 수업용 · 원본 아님] 실제 로봇팔(Magician Lite + 집게) 연결 부품.

A1 · A2 수업 파일이 `with 로봇_연결() as 팔:` 로 쓴다.
  · DobotLink 로 로봇이 보이면 → 실제 로봇을 움직인다 (dobotkit, BlockPy 와 같은 연결 방식)
  · 로봇이 없거나 연결에 실패하면 → 이유를 알려 주고 모의(가짜) 로봇으로 계속한다

원본 수업 코드(common.motion_control · a2 place_marker)가 부르는 명령
home / move_to / get_pose / grip / suck / pump_off 를 dobotkit 으로 바꿔 준다.
연결 코드는 실습준비/A1_음성명령/A1_실물시연.py 의 '실제로봇' 을 그대로 옮긴 것이다(실물 리허설 전).

안전값: 시작 자리(홈) (200, 0, 50) · 높이 0 mm 아래로 내려가지 않음 · 속도 30 %
우리 장비는 흡착컵이 아니라 집게라서 suck(켜기/끄기) 는 집게 닫기/열기로 바꿔 보낸다.
"""
import time

START = (200.0, 0.0, 50.0)   # 시작 자리이자 '홈'(mm)
Z_MIN = 0.0                  # 이보다 낮게 내려가지 않는다 (책상 보호)
SPEED = 30                   # 속도 · 가속도(%)


class 실제로봇:
    mock = False

    def __init__(self, port="auto", 원점맞추기=False):
        from dobotkit import MagicianLite
        self.arm = MagicianLite(port=port, auto_connect=False)
        if port == "auto":                          # 블루투스 직렬 포트는 로봇이 아니므로 뺀다
            후보 = [p for p in (self.arm.cmds.search() or []) if "Bluetooth" not in p.get("description", "")]
            if not 후보:
                try:
                    self.arm._client.close()
                except Exception:
                    pass
                raise ConnectionError("USB 로 연결된 로봇이 보이지 않아요")
            self.arm._port = 후보[0]["portName"]
            self.arm.cmds.port_name = 후보[0]["portName"]
        self.arm.connect()
        self.port = self.arm.cmds.port_name
        self.arm.cmds._call("ClearAllAlarmsState")  # 전원 켠 직후의 경고 지우기 (움직이지 않음)
        self.arm.set_speed(SPEED, SPEED)
        if 원점맞추기:
            print("   원점 맞추는 중... (팔이 크게 움직여요)")
            번호 = self.arm.home(wait=False)
            self._기다리기(번호, 90)
        self.home()
        self.grip(False)                            # 집게를 열어 둔 채로 시작

    def _기다리기(self, 번호, 초):
        끝 = time.time() + 초
        while self.arm.cmds.current_index() < 번호:
            if time.time() > 끝:
                raise TimeoutError(f"팔이 {초}초 안에 움직임을 끝내지 않았어요")
            time.sleep(0.2)

    def get_pose(self):
        p = self.arm.get_pose()
        return {"x": float(p["x"]), "y": float(p["y"]), "z": float(p["z"]), "r": float(p.get("r", 0.0))}

    def move_to(self, x, y, z, r=0.0, wait=True):
        요청 = {"x": x, "y": y, "z": z, "r": r}
        if z < Z_MIN:
            print(f"   (안전: 높이 {z:.0f}mm 는 {Z_MIN:.0f}mm 에서 멈춰요)")
            z = Z_MIN
        번호 = self.arm.move_to(x, y, z, r, wait=False)
        self._기다리기(번호, 30)
        끝 = time.time() + 5                         # 마지막 몇 mm 까지 도착했는지 위치로 확인
        while time.time() < 끝:
            p = self.get_pose()
            if abs(p["x"] - x) < 2 and abs(p["y"] - y) < 2 and abs(p["z"] - z) < 2:
                break
            time.sleep(0.2)
        return {"requested": 요청, "actual": {"x": x, "y": y, "z": z, "r": r}, "clamped": 요청["z"] != z}

    def home(self):
        self.move_to(*START, 0.0)

    def grip(self, on):
        self.arm.grip(bool(on))
        self.arm.cmds.set_wait_cmd(800)             # 집게가 다 움직일 시간
        time.sleep(0.9)

    grasp = grip

    def suck(self, on):
        print("   (우리 장비는 집게라 흡착 대신 집게를 " + ("닫아요)" if on else "열어요)"))
        self.grip(on)

    def pump_off(self):
        self.arm.pump_off()

    def close(self):
        self.arm.__exit__(None, None, None)         # 큐 정지 · 펌프 끔 · 연결 해제


class 로봇_연결:
    """with 로봇_연결() as 팔:  — 실제 로봇이 있으면 실제로, 없으면 모의로."""

    def __init__(self, 실제로봇_쓰기=True, 원점맞추기=False, port="auto"):
        self.실제 = 실제로봇_쓰기
        self.원점 = 원점맞추기
        self.port = port
        self._ctx = None
        self.bot = None

    def __enter__(self):
        if self.실제:
            try:
                self.bot = 실제로봇(self.port, self.원점)
                print(f"[연결] 실제 로봇 ({self.bot.port}) · 속도 {SPEED}% · 시작 자리 {START}")
                return self.bot
            except Exception as e:
                print(f"[연결] 실제 로봇에 연결하지 못했어요 → 모의(가짜) 로봇으로 해요  ({type(e).__name__}: {e})")
                print("       로봇을 쓰려면: 로봇 전원 · USB 선 · DobotLink 켜기 · BlockPy 로봇 패널 연결 끊기")
                self.bot = None
        from common.dobot_ctl import get_robot
        self._ctx = get_robot(mock=True)
        if not self.실제:
            print("[연결] 모의(가짜) 로봇 — 로봇은 움직이지 않아요")
        return self._ctx.__enter__()

    def __exit__(self, *exc):
        if self.bot is not None:
            try:
                self.bot.home()
            except Exception:
                pass
            try:
                self.bot.close()
            except Exception:
                pass
            print("[종료] 로봇을 시작 자리로 보내고 펌프를 끄고 연결을 끊었어요")
        elif self._ctx is not None:
            self._ctx.__exit__(*exc)
        return False
