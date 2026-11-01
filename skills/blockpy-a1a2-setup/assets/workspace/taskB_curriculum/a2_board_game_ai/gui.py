"""a2_board_game_ai/gui.py — [A2] 틱택토(보드게임 AI) 수동 조작 GUI.

강사/학생이 **마우스로 직접** 칸을 클릭해 'X'(내 수)를 두면, 로봇(AI)이 solution 의
minimax(best_move)로 최적 수 'O'를 계산해 보드에 표시하고, 로봇이 연결돼 있으면
해당 칸으로 실제 픽앤플레이스 착수(place_marker)까지 수행한다.

설계
----
- 공통 베이스 common.gui.LessonGUI 를 그대로 사용(카메라/로봇 연결/비상정지/로그 제공).
- 보드 로직은 a2_board_game_ai.solution 의 순수함수를 **재사용**(중복 구현 금지):
    best_move / winner / is_full / available_moves / place_marker / cell_to_xy
- 로봇을 움직이는 동작(AI 착수)은 반드시 threading.Thread 로 실행(UI 안 막힘).
- 카메라(CAM_TABLE)는 좌측에 보드 영역을 보여주는 용도(선택). process_frame 은
  안내 오버레이만 그린다(로봇 이동 없음).
- 하드웨어/카메라/키 없어도 import 는 된다(창/카메라/로봇은 __main__ 에서만 연다).
"""
from __future__ import annotations

# ── sys.path 부트스트랩(코드 루트 taskB_curriculum 를 import 경로에 추가) ──
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading

from common.gui import LessonGUI
from common import config
from a2_board_game_ai import solution as sol
from a2_board_game_ai.solution import EMPTY, P_AI, P_HUMAN


class TicTacToeController:
    """틱택토 게임 상태/위젯을 묶어 관리하는 컨트롤러.

    build_controls 콜백에서 인스턴스를 만들어 우측 패널에 3x3 버튼 격자를 그린다.
    """

    def __init__(self, parent, app):
        self.app = app
        self.board = [[EMPTY] * 3 for _ in range(3)]   # 2D 배열 보드
        self.buttons = [[None] * 3 for _ in range(3)]  # 칸 버튼 위젯
        self.game_over = False
        self.ai_busy = False                            # AI 착수 진행중(중복 클릭 방지)
        self._build_widgets(parent)

    # ---------------- 위젯 구성 ----------------
    def _build_widgets(self, parent):
        import tkinter as tk

        tk.Label(parent, text="틱택토 (나=X / 로봇=O)", bg="#2a2a3c", fg="#4f9dff",
                 font=("맑은 고딕", 11, "bold")).pack(anchor="w", pady=(12, 4))

        grid = tk.Frame(parent, bg="#2a2a3c")
        grid.pack()
        for r in range(3):
            for c in range(3):
                b = tk.Button(grid, text=" ", width=4, height=2,
                              font=("맑은 고딕", 16, "bold"),
                              bg="#3a3a52", fg="white", relief="raised",
                              command=lambda rr=r, cc=c: self.on_cell_click(rr, cc))
                b.grid(row=r, column=c, padx=2, pady=2)
                self.buttons[r][c] = b

        # 결과 표시 라벨
        self.result_var = tk.StringVar(value="당신(X) 차례입니다. 칸을 클릭하세요.")
        tk.Label(parent, textvariable=self.result_var, bg="#2a2a3c", fg="#e6e6e6",
                 font=("맑은 고딕", 10), wraplength=260, justify="left").pack(
            anchor="w", pady=(8, 4))

        # 새 게임 버튼
        tk.Button(parent, text="새 게임", command=self.new_game,
                  bg="#4f9dff", fg="white", font=("맑은 고딕", 11),
                  relief="flat").pack(fill="x", pady=(4, 2))

    # ---------------- 보드 갱신 ----------------
    def _refresh_buttons(self):
        """2D 배열 → 버튼 텍스트/색 반영(UI 스레드에서 호출)."""
        for r in range(3):
            for c in range(3):
                v = self.board[r][c]
                btn = self.buttons[r][c]
                btn.config(text=(v if v != EMPTY else " "))
                if v == P_HUMAN:
                    btn.config(fg="#ffd166", state="disabled")
                elif v == P_AI:
                    btn.config(fg="#06d6a0", state="disabled")
                else:
                    btn.config(fg="white",
                               state=("disabled" if self.game_over else "normal"))

    def _check_end(self):
        """승패/무승부 판정 후 표시. 종료면 True."""
        win = sol.winner(self.board)
        if win == P_HUMAN:
            self.game_over = True
            self.result_var.set("당신(X) 승리! 🎉")
            self.app.set_status("게임 종료: 당신(X) 승리")
            self.app.log("게임 종료: 당신(X) 승리")
            return True
        if win == P_AI:
            self.game_over = True
            self.result_var.set("로봇(O) 승리!")
            self.app.set_status("게임 종료: 로봇(O) 승리")
            self.app.log("게임 종료: 로봇(O) 승리")
            return True
        if sol.is_full(self.board):
            self.game_over = True
            self.result_var.set("무승부입니다.")
            self.app.set_status("게임 종료: 무승부")
            self.app.log("게임 종료: 무승부")
            return True
        return False

    # ---------------- 사용자 클릭(내 수 X) ----------------
    def on_cell_click(self, r, c):
        if self.game_over or self.ai_busy:
            return
        if self.board[r][c] != EMPTY:
            self.app.log(f"[안내] 칸({r},{c}) 은 이미 차 있습니다.")
            return
        # 내 수 착수
        self.board[r][c] = P_HUMAN
        self.app.log(f"당신(X): 칸({r},{c}) 에 둠")
        self._refresh_buttons()
        if self._check_end():
            return
        # 로봇(AI) 차례 — 스레드에서 계산/착수(UI 안 막음)
        self.ai_busy = True
        self.result_var.set("로봇(O)이 수를 계산 중...")
        self.app.set_status("로봇(O) 계산/착수 중...")
        for row in self.buttons:                       # 계산 중 클릭 잠금
            for b in row:
                b.config(state="disabled")
        threading.Thread(target=self._ai_turn, daemon=True).start()

    # ---------------- 로봇(AI) 차례 — 스레드 ----------------
    def _ai_turn(self):
        try:
            move = sol.best_move(self.board, P_AI)     # minimax 최적 수(순수함수)
            if move is None:
                return
            r, c = move
            self.app.log(f"로봇(O): minimax 최적 수 ({r},{c})")

            bot = self.app.robot                       # '로봇 연결' 됐으면 RobotController
            if bot is not None:
                try:
                    # solution 의 픽앤플레이스(격자→로봇좌표 매핑 cell_to_xy 내장) 재사용
                    log = sol.place_marker(bot, r, c, P_AI)
                    tx, ty = log["target_xy"]
                    self.app.log(f"로봇 착수 완료: 칸({r},{c}) → (x={tx}, y={ty})")
                except Exception as e:
                    self.app.log(f"[로봇 착수 오류] {type(e).__name__}: {e}")
            else:
                self.app.log("[안내] 로봇 미연결 — 화면에만 'O' 표시(로봇 연결 시 실제 착수).")

            # 2D 배열 갱신 + UI 반영(UI 스레드로 위임)
            self.board[r][c] = P_AI
            self.app.root.after(0, self._after_ai_move)
        finally:
            self.ai_busy = False

    def _after_ai_move(self):
        """AI 착수 결과를 UI 에 반영(UI 스레드)."""
        self._refresh_buttons()
        if not self._check_end():
            self.result_var.set("당신(X) 차례입니다. 칸을 클릭하세요.")
            self.app.set_status("당신(X) 차례")

    # ---------------- 새 게임 ----------------
    def new_game(self):
        if self.ai_busy:
            self.app.log("[안내] 로봇 착수 중에는 새 게임을 시작할 수 없습니다.")
            return
        self.board = [[EMPTY] * 3 for _ in range(3)]
        self.game_over = False
        self.result_var.set("당신(X) 차례입니다. 칸을 클릭하세요.")
        self.app.set_status("새 게임 시작")
        self.app.log("새 게임 시작.")
        self._refresh_buttons()


def _make_process_frame():
    """카메라 프레임에 안내 오버레이만 그리는 콜백(로봇 이동 없음)."""
    import cv2

    def process_frame(frame, app):
        try:
            cv2.putText(frame, "A2 TicTacToe - board area",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (79, 157, 255), 2, cv2.LINE_AA)
        except Exception:
            pass
        return frame

    return process_frame


def main():
    """GUI 생성/실행(하드웨어/카메라는 여기서만 연다)."""
    INFO = ("틱택토: 우측 3x3 격자에서 칸을 클릭하면 당신의 수(X)가 놓이고, "
            "로봇(O)이 minimax 로 최적 수를 계산해 착수합니다. "
            "'로봇 연결' 시 로봇이 실제 칸으로 이동/착수합니다. "
            "'새 게임'으로 초기화. 카메라는 보드 영역 표시용.")

    app = LessonGUI(
        title="A2 보드게임 AI (틱택토)",
        camera_index=config.CAM_TABLE,
        use_robot=True,
        process_frame=_make_process_frame(),
        info=INFO,
        build_controls=lambda parent, app: setattr(
            app, "_ttt", TicTacToeController(parent, app)),
    )
    app.run()


if __name__ == "__main__":
    main()
