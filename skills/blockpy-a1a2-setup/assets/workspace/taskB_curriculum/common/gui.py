"""common/gui.py — 차시 공용 GUI 베이스 (Tkinter + OpenCV 카메라 + 로봇 + 비상정지).

목적
----
강사/학생이 **마우스로 직접** 차시를 실행·조작하도록 하는 공통 GUI 틀.
좌측에 라이브 카메라(오버레이 가능), 우측에 로봇 연결/상태·차시별 컨트롤·로그·
빨간 **비상정지** 버튼을 둔다. 차시별 GUI는 이 베이스에 콜백만 주입하면 된다.

설계
----
- 카메라 캡처는 **백그라운드 스레드**에서 돌고, 매 프레임 `process_frame(frame, app)`
  콜백을 호출한다(여기서 차시 로직·로봇 이동 수행 가능 — UI 스레드 안 막음).
  콜백은 화면에 그릴 BGR 프레임을 반환한다(오버레이 포함).
- UI 스레드는 `after()`로 최신 프레임만 캔버스에 표시(PIL ImageTk).
- 로봇 연결/비상정지/로그는 스레드 안전하게 처리.

의존성: tkinter(기본), opencv-python, Pillow, numpy. 없으면 친절한 오류.
하드웨어/카메라 없어도 import 는 되며, 실행 시 카메라/로봇이 없으면 mock/안내로 폴백.

사용 예 (차시 GUI)
------------------
    from common.gui import LessonGUI
    def proc(frame, app):
        # frame(BGR) 처리·오버레이, app.set_status(...), app.robot 사용 가능
        return frame
    app = LessonGUI("M2 가위바위보", camera_index=0, use_robot=True,
                    process_frame=proc,
                    controls=[("게임 시작", on_start)])
    app.run()
"""
from __future__ import annotations

import threading
import time

# --- tkinter (표준) ---
try:
    import tkinter as tk
    from tkinter import scrolledtext
    _HAS_TK = True
except Exception:
    tk = None
    _HAS_TK = False

# --- opencv / Pillow / numpy (가드) ---
try:
    import cv2
    _HAS_CV2 = True
except Exception:
    cv2 = None
    _HAS_CV2 = False

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    Image = ImageTk = None
    _HAS_PIL = False

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    np = None
    _HAS_NUMPY = False

# 로봇 제어기(있으면). GUI 자체는 로봇 없이도 동작.
try:
    from common.dobot_ctl import get_robot
except Exception:
    get_robot = None


# 색상(테마) — 차분한 다크 패널
_BG = "#1e1e2e"
_PANEL = "#2a2a3c"
_FG = "#e6e6e6"
_ACCENT = "#4f9dff"
_DANGER = "#e5484d"


class LessonGUI:
    """차시 공용 GUI 창.

    파라미터
    --------
    title : 창 제목.
    camera_index : 사용할 카메라 인덱스(차시에 맞게: 손=CAM_HAND, 책상=CAM_TABLE).
    use_robot : True면 로봇 연결 버튼/상태 표시.
    port : 로봇 포트(None이면 자동/설정).
    process_frame : callback(frame_bgr, app) -> frame_bgr. 매 프레임 호출(캡처 스레드).
                    여기서 차시 로직·오버레이·로봇 이동 수행. None이면 원본 표시.
    controls : [(라벨, callback(app)), ...] 우측에 추가할 버튼들.
    info : 상단에 표시할 안내 문구.
    """

    def __init__(self, title="차시", camera_index=0, use_robot=True, port=None,
                 process_frame=None, controls=None, info="", build_controls=None,
                 on_canvas_click=None):
        if not _HAS_TK:
            raise RuntimeError("tkinter 가 없어 GUI를 띄울 수 없습니다.")
        if not (_HAS_CV2 and _HAS_PIL):
            raise RuntimeError("GUI 카메라 표시는 opencv-python 과 Pillow 가 필요합니다. "
                               "`pip install opencv-python pillow` 후 실행하세요.")
        self.title = title
        self.camera_index = camera_index
        self.use_robot = use_robot
        self.port = port
        self._process_frame = process_frame
        self._controls = controls or []
        self.info = info
        self._build_controls = build_controls   # callback(parent_frame, app): 커스텀 위젯 추가용
        self._on_canvas_click = on_canvas_click  # callback(px, py, app): 카메라 영상 클릭 시(픽셀좌표)
        self._frame_wh = None                    # 마지막 표시 프레임 크기(w,h) — 클릭 좌표 보정용

        # 상태
        self.robot = None            # 연결된 RobotController(없으면 None)
        self.running = True          # 캡처 루프 on/off
        self._cap = None
        self._raw = None             # 카메라 최신 원본 프레임(BGR)
        self._display = None         # 표시용(처리/오버레이 결과) 프레임(BGR)
        self._display_ver = 0        # 표시 프레임 버전(바뀐 경우에만 다시 그림 → UI 부하↓)
        self._shown_ver = -1
        self._lock = threading.Lock()
        self._log_q: list[str] = []

        self._build_ui()
        self._start_camera()

    # ---------------- UI 구성 ----------------
    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title(self.title)
        self.root.configure(bg=_BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 좌측: 카메라
        left = tk.Frame(self.root, bg=_BG)
        left.grid(row=0, column=0, padx=8, pady=8, sticky="n")
        self.canvas = tk.Label(left, bg="#000000", bd=0, highlightthickness=0)
        # 첫 프레임 표시 전, Label 의 width/height 는 '텍스트 단위(문자/줄)'로 해석돼
        # 창이 거대(480줄≈7000px)해진다. 640x480 px 블랭크 이미지를 미리 넣어 픽셀 크기를
        # 고정한다(첫 프레임이 오면 그 이미지로 교체됨). 참조 유지(GC 방지).
        self._blank_img = tk.PhotoImage(width=640, height=480)
        self.canvas.configure(image=self._blank_img)
        self.canvas.pack()
        # 카메라 영상 클릭 → 픽셀좌표 콜백(캘리브레이션 등). 영상은 원본 해상도로 표시하므로
        # 위젯 좌표 ≈ 프레임 픽셀좌표(표시 크기와 다르면 _canvas_click 에서 스케일 보정).
        if self._on_canvas_click is not None:
            self.canvas.bind("<Button-1>", self._canvas_click)
        tk.Label(left, text=self.info, bg=_BG, fg=_FG, wraplength=640,
                 justify="left", font=("맑은 고딕", 10)).pack(anchor="w", pady=(6, 0))

        # 우측: 컨트롤 패널
        #   컨트롤이 많아 창 높이를 넘으면 잘리던 문제 → 세로 '스크롤' 가능하게 한다.
        #   단, 비상정지(E-STOP)와 로그는 스크롤 영역 '밖' 하단에 고정해 **항상 보이게**
        #   한다(안전·실시간 가시성). 나머지(제목/상태/로봇연결/차시 컨트롤)는 스크롤된다.
        right_outer = tk.Frame(self.root, bg=_PANEL)
        right_outer.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="ns")

        # (1) 하단 고정: 비상정지 — 스크롤과 무관하게 항상 보임(맨 아래)
        estop = tk.Button(right_outer, text="■ 비상정지 (E-STOP)", command=self._estop,
                          bg=_DANGER, fg="white", font=("맑은 고딕", 12, "bold"),
                          relief="raised", height=2)
        estop.pack(side="bottom", fill="x", padx=12, pady=(6, 10))

        # (2) 하단 고정: 로그 — 항상 보임(실시간 메시지 확인). E-STOP 바로 위.
        log_frame = tk.Frame(right_outer, bg=_PANEL)
        log_frame.pack(side="bottom", fill="x", padx=12)
        tk.Label(log_frame, text="로그", bg=_PANEL, fg=_FG,
                 font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(6, 2))
        self.logbox = scrolledtext.ScrolledText(log_frame, width=34, height=8,
                                                bg="#16161f", fg="#cfcfcf",
                                                font=("Consolas", 9))
        self.logbox.pack(fill="x")

        # (3) 상단 스크롤 영역: 나머지 컨트롤을 담는 캔버스 + 스크롤바
        sc_canvas = tk.Canvas(right_outer, bg=_PANEL, highlightthickness=0, bd=0)
        sc_bar = tk.Scrollbar(right_outer, orient="vertical", command=sc_canvas.yview)
        sc_canvas.configure(yscrollcommand=sc_bar.set)
        sc_bar.pack(side="right", fill="y")
        sc_canvas.pack(side="left", fill="both", expand=True)

        # 실제 컨트롤이 쌓이는 내부 프레임(= 이전의 right). 이후 코드는 그대로 사용.
        right = tk.Frame(sc_canvas, bg=_PANEL, padx=12, pady=12)
        sc_canvas.create_window((0, 0), window=right, anchor="nw")

        # 창 전체가 화면에 들어오도록 스크롤 영역 가시 높이 상한을 화면높이에 맞춰 정한다.
        try:
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_h = 900
        _max_panel_h = max(240, min(640, screen_h - 390))  # 로그/E-STOP/창여백 제외분

        def _sync_scroll(_evt=None):
            # 내용 크기에 맞춰 스크롤영역/캔버스 크기 갱신(짧으면 짧게, 길면 상한+스크롤)
            sc_canvas.configure(scrollregion=sc_canvas.bbox("all"))
            sc_canvas.configure(height=min(right.winfo_reqheight(), _max_panel_h),
                                width=right.winfo_reqwidth())
        right.bind("<Configure>", _sync_scroll)

        # 마우스휠: 패널에 마우스가 올라가 있을 때만 스크롤(카메라 위에선 동작 안 함)
        def _wheel(evt):
            sc_canvas.yview_scroll(int(-1 * (evt.delta / 120)), "units")
        sc_canvas.bind("<Enter>", lambda e: sc_canvas.bind_all("<MouseWheel>", _wheel))
        sc_canvas.bind("<Leave>", lambda e: sc_canvas.unbind_all("<MouseWheel>"))

        # ── 이하 컨트롤은 모두 스크롤 내부 프레임(right)에 쌓는다 ──
        tk.Label(right, text=self.title, bg=_PANEL, fg=_ACCENT,
                 font=("맑은 고딕", 14, "bold")).pack(anchor="w")

        # 상태 라벨
        self.status_var = tk.StringVar(value="준비됨")
        tk.Label(right, textvariable=self.status_var, bg=_PANEL, fg=_FG,
                 font=("맑은 고딕", 11), wraplength=260, justify="left").pack(
            anchor="w", pady=(8, 8))

        # 로봇 연결
        if self.use_robot:
            self.robot_status = tk.StringVar(value="로봇: 미연결")
            tk.Label(right, textvariable=self.robot_status, bg=_PANEL, fg=_FG,
                     font=("맑은 고딕", 10)).pack(anchor="w")
            self._mk_btn(right, "로봇 연결", self._connect_robot_async, _ACCENT)

        # 차시별 컨트롤 버튼
        for label, cb in self._controls:
            self._mk_btn(right, label, lambda c=cb: c(self), "#3a3a52")

        # 차시별 커스텀 위젯(텍스트 입력·보드 등) — 콜백이 우측 패널에 직접 추가
        if self._build_controls is not None:
            try:
                self._build_controls(right, self)
            except Exception as e:
                self.log(f"[컨트롤 구성 오류] {e}")

        self.log(f"'{self.title}' 시작. 카메라 index={self.camera_index}.")

    def _canvas_click(self, event):
        """카메라 영상 클릭 → 프레임 픽셀좌표로 변환해 콜백 호출(캘리브레이션 마킹 등).

        영상은 원본 해상도(1:1)로 캔버스 좌상단부터 표시하므로 위젯좌표가 곧 픽셀좌표다.
        표시 영상 크기(_frame_wh) 밖 클릭(여백)은 무시한다. 첫 프레임 표시 전이면 무시.
        """
        cb = self._on_canvas_click
        if cb is None:
            return
        px, py = event.x, event.y
        wh = self._frame_wh
        if wh is None:
            return                                  # 아직 첫 프레임 표시 전 — 좌표 기준 없음
        fw, fh = wh
        # 영상은 캔버스 좌상단(0,0)부터 원본 해상도(1:1)로 그려지므로 위젯좌표 == 픽셀좌표.
        # 영상 영역 밖 클릭은 무시(여백 클릭 방지).
        if px < 0 or py < 0 or px >= fw or py >= fh:
            return
        try:
            cb(int(px), int(py), self)
        except Exception as e:
            self.log(f"[클릭 처리 오류] {type(e).__name__}: {e}")

    def _mk_btn(self, parent, label, cmd, color):
        b = tk.Button(parent, text=label, command=cmd, bg=color, fg="white",
                      font=("맑은 고딕", 11), relief="flat", height=1)
        b.pack(fill="x", pady=3)
        return b

    # ---------------- 로그/상태(스레드 안전) ----------------
    def log(self, msg: str):
        self._log_q.append(time.strftime("%H:%M:%S ") + str(msg))

    def set_status(self, msg: str):
        try:
            self.status_var.set(str(msg))
        except Exception:
            pass

    def _drain_log(self):
        if self._log_q:
            for line in self._log_q:
                self.logbox.insert("end", line + "\n")
            self._log_q.clear()
            self.logbox.see("end")

    # ---------------- 카메라 ----------------
    # 끊김(뚝뚝) 방지: [캡처(빠른 읽기)] / [처리(무거운 AI·로봇)] / [표시] 를 분리하고,
    # 카메라 버퍼를 최신 1장만 유지(밀림·지연 누적 방지). 처리 스레드는 항상 '최신
    # 원본'만 처리(밀린 프레임은 드롭)하여 지연이 쌓이지 않게 한다.
    def _start_camera(self):
        self._cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if self._cap:
            try:
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 최신 프레임만(지연/밀림 방지)
            except Exception:
                pass
        if not self._cap or not self._cap.isOpened():
            self.log(f"[경고] 카메라 {self.camera_index} 를 열 수 없습니다. 다른 인덱스를 시도하세요.")
        threading.Thread(target=self._capture_loop, daemon=True).start()  # 빠른 읽기
        if self._process_frame is not None:
            threading.Thread(target=self._worker_loop, daemon=True).start()  # 무거운 처리
        self._tick()  # UI 갱신 루프 시작

    def _capture_loop(self):
        """카메라에서 최대한 빠르게 읽어 최신 원본(_raw)만 유지(버퍼 밀림 방지)."""
        while self.running:
            if not self._cap:
                time.sleep(0.1)
                continue
            ok, frame = self._cap.read()
            if not ok or frame is None:
                time.sleep(0.02)
                continue
            with self._lock:
                self._raw = frame
                if self._process_frame is None:
                    self._display = frame   # 처리기 없으면 원본을 그대로 표시
                    self._display_ver += 1
            time.sleep(0.003)

    def _worker_loop(self):
        """무거운 처리(mediapipe/로봇)는 별도 스레드에서 '최신 원본'에만 수행.
        밀린 프레임은 건너뛰어(드롭) 지연 누적·끊김을 막는다."""
        last = None
        while self.running:
            with self._lock:
                frame = self._raw
            if frame is None or frame is last:
                time.sleep(0.008)
                continue
            last = frame
            try:
                out = self._process_frame(frame.copy(), self)  # 차시 로직(로봇 이동 등)
            except Exception as e:
                self.log(f"[처리 오류] {type(e).__name__}: {e}")
                out = frame
            with self._lock:
                self._display = out
                self._display_ver += 1
            time.sleep(0.003)

    def _tick(self):
        # 최신 표시 프레임을 캔버스에 표시(UI 스레드). 처리결과 있으면 그것, 없으면 원본.
        with self._lock:
            ver = self._display_ver
            need = (ver != self._shown_ver)        # 프레임이 바뀐 경우에만 다시 그림
            src = self._display if self._display is not None else self._raw
            frame = src.copy() if (need and src is not None) else None
        if frame is not None:
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
                imgtk = ImageTk.PhotoImage(image=img)
                self.canvas.imgtk = imgtk  # 참조 유지(GC 방지)
                self.canvas.configure(image=imgtk)
                self._frame_wh = (img.width, img.height)  # 클릭 좌표 보정용 표시 크기
                self._shown_ver = ver
            except Exception:
                pass
        self._drain_log()
        if self.running:
            self.root.after(15, self._tick)

    # ---------------- 로봇 ----------------
    def _connect_robot_async(self):
        self.robot_status.set("로봇: 연결 중...")
        threading.Thread(target=self._connect_robot, daemon=True).start()

    def _connect_robot(self):
        if get_robot is None:
            self.log("[오류] 로봇 제어 모듈을 불러올 수 없습니다.")
            return
        try:
            bot = get_robot(port=self.port, mock=False)
            bot.connect()
            self.robot = bot
            mode = "mock" if getattr(bot, "mock", False) else "실기"
            self.robot_status.set(f"로봇: 연결됨({mode})")
            self.log(f"로봇 연결됨 ({mode}). 홈 복귀 중...")
            bot.home()
            self.log("홈 복귀 완료.")
        except Exception as e:
            self.robot_status.set("로봇: 연결 실패")
            self.log(f"[로봇 연결 오류] {e}")

    def _estop(self):
        self.log("■ 비상정지!")
        self.set_status("■ 비상정지됨")
        bot = self.robot
        if bot is not None:
            try:
                # 흡착/그리퍼 끄고 정지 시도
                if hasattr(bot, "_safe_stop"):
                    threading.Thread(target=bot._safe_stop, daemon=True).start()
            except Exception as e:
                self.log(f"[비상정지 오류] {e}")

    # ---------------- 종료 ----------------
    def _on_close(self):
        """창 종료 시: 캡처 중단 → 카메라 해제 → 로봇 안전정지 + 연결 해제(COM 포트 완전 해제) → 창 파괴."""
        self.running = False           # 캡처/틱 루프 중단 신호
        time.sleep(0.2)                # 캡처 스레드가 진행 중 프레임 처리 끝낼 시간
        # 1) 카메라 해제
        try:
            if self._cap:
                self._cap.release()
                self._cap = None
        except Exception:
            pass
        # 2) 로봇: 안전정지(흡착/그리퍼 OFF) → disconnect(device.close() = 시리얼/COM 포트 해제)
        bot = self.robot
        if bot is not None:
            try:
                if hasattr(bot, "_safe_stop"):
                    bot._safe_stop()
            except Exception:
                pass
            try:
                bot.disconnect()       # COM 포트 완전 해제
                self.log("로봇 연결 해제(COM 포트 반환).")
            except Exception:
                pass
            self.robot = None
        # 3) 창 파괴(프로세스 종료 시 OS 가 남은 핸들도 정리)
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# 자가 데모 — 카메라 뷰어만(로봇 없이). 카메라 index 0.
if __name__ == "__main__":
    import os
    idx = int(os.environ.get("DEMO_CAM", "0"))
    app = LessonGUI(f"GUI 베이스 데모 (cam {idx})", camera_index=idx, use_robot=False,
                    info="카메라 미리보기. 닫기로 종료.")
    app.run()
