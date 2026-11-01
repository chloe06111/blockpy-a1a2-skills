# -*- coding: utf-8 -*-
"""A1 · 음성 제어 오케스트레이션 — 수동 테스트 GUI (범용 동작, 색 무관)

음성/자연어 한 마디를 여러 동작 단계로 분해하고 로봇이 순차 실행한다. 색 판별은
이 차시에 없다(M1 전용). 언어 해석은 MiniMax(키 없으면 로컬 규칙), STT는 로컬 Whisper.

- 우측: 명령 입력창 + "분해·실행" + (whisper 설치 시) "🎤 녹음".
- 실행은 별도 스레드에서 solution 의 decompose_command/execute_plan 을 호출한다.
"""
# ── sys.path 부트스트랩 ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading

import tkinter as tk

from common import config
from common.ai_clients import LLMClient, STTClient
from common.audio import mic_available, record_wav
from common.gui import LessonGUI

from a1_voice_orchestration.solution import (
    decompose_command,   # 자연어 명령 → 다단계 동작 계획
    execute_plan,        # 계획을 로봇으로 순차 실행
    listen_command,      # 음성 파일 → 텍스트(STT)
)

# whisper(STT) 설치 여부 — 설치돼 있으면 "🎤 녹음" 버튼을 노출한다.
try:
    import whisper as _whisper          # noqa: F401
    _HAS_WHISPER = True
except Exception:
    _HAS_WHISPER = False


INFO = (
    "음성 오케스트레이션: 자연어 한 마디를 작은 동작 단계들로 분해→로봇이 순차 실행합니다.\n"
    "MINIMAX_API_KEY 가 있으면 MiniMax 로, 없으면 로컬 규칙으로 분해합니다(색 판별 없음).\n"
    "예: '홈으로 갔다가 오른쪽으로 5cm 이동하고 흡착 켜' · '위로 20mm 올린 다음 왼쪽으로 3cm'\n"
    "사용법: ① '로봇 연결' → ② 명령 입력 → ③ '분해·실행'. (whisper 설치 시 🎤 녹음 가능)"
)


def _describe(step: dict) -> str:
    """동작 dict 를 사람이 읽기 좋은 한 줄로."""
    a = step.get("action")
    if a == "move_to":
        return f"move_to (x={step.get('x')}, y={step.get('y')}, z={step.get('z')})"
    if a == "move_relative":
        return f"move_relative (dx={step.get('dx')}, dy={step.get('dy')}, dz={step.get('dz')})"
    if a in ("suck", "grip"):
        return f"{a} {'ON' if step.get('on') else 'OFF'}"
    if a == "speed":
        return f"speed (v={step.get('velocity')})"
    return str(a)


def _build_controls(parent, app):
    """우측 패널에 명령 입력창 + 실행 버튼(+선택적 녹음 버튼)을 추가한다."""
    _PANEL, _FG, _ACCENT = "#2a2a3c", "#e6e6e6", "#4f9dff"

    tk.Label(parent, text="명령 입력 (자연어)", bg=_PANEL, fg=_FG,
             font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(10, 2))
    cmd_var = tk.StringVar(value="홈으로 갔다가 오른쪽으로 5cm 이동하고 흡착 켜")
    entry = tk.Entry(parent, textvariable=cmd_var, width=32, font=("맑은 고딕", 11),
                     bg="#16161f", fg="#e6e6e6", insertbackground="#e6e6e6")
    entry.pack(fill="x", pady=(0, 4))

    tk.Label(parent, text="실행 계획(스텝)", bg=_PANEL, fg=_FG,
             font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(8, 2))
    steps_box = tk.Text(parent, width=34, height=6, bg="#16161f", fg="#cfcfcf",
                        font=("Consolas", 9), state="disabled")
    steps_box.pack()

    # 언어 해석 백엔드: MiniMax(OpenAI 호환). 키 없으면 mock → None → 로컬 규칙 폴백.
    _llm = LLMClient(provider="minimax")
    app._a1_llm = None if getattr(_llm, "mock", True) else _llm
    app._a1_stt = STTClient()   # 로컬 Whisper(없으면 mock 폴백)
    app._a1_busy = False

    def _show_steps(plan):
        def _update():
            steps_box.configure(state="normal")
            steps_box.delete("1.0", "end")
            for i, s in enumerate(plan, 1):
                steps_box.insert("end", f"{i}. {_describe(s)}\n")
            steps_box.configure(state="disabled")
        try:
            app.root.after(0, _update)
        except Exception:
            pass

    def _run_command(command):
        """스레드 본체: 분해 → 스텝 표시 → 로봇 순차 실행."""
        try:
            command = (command or "").strip()
            if not command:
                app.log("[안내] 명령이 비어 있습니다.")
                return
            app.set_status("명령 분해 중...")
            app.log(f"[명령] {command!r}")

            plan = decompose_command(command, app._a1_llm)
            app.log(f"[분해] {len(plan)}단계 계획:")
            for i, s in enumerate(plan, 1):
                app.log(f"   {i}. {_describe(s)}")
            _show_steps(plan)
            if not plan:
                app.log("[안전중단] 유효한 동작을 얻지 못했습니다.")
                app.set_status("안전중단")
                return

            bot = app.robot
            if bot is None:
                app.set_status("로봇 미연결 — 계획만 표시")
                app.log("[안내] 로봇 미연결 — 실행 생략. '로봇 연결' 후 다시 실행하세요.")
                return

            app.set_status("계획 실행 중...")
            summary = execute_plan(plan, bot)
            for line in summary.get("logs", []):
                app.log("   - " + str(line))
            app.log(f"[완료] {summary.get('steps')}단계 실행")
            app.set_status("실행 완료")
        except Exception as e:
            app.log(f"[실행 오류] {type(e).__name__}: {e}")
            app.set_status("실행 오류")
        finally:
            app._a1_busy = False

    def on_run(*_):
        if app._a1_busy:
            app.log("[안내] 이미 실행 중입니다.")
            return
        app._a1_busy = True
        threading.Thread(target=_run_command, args=(cmd_var.get(),), daemon=True).start()

    entry.bind("<Return>", on_run)
    tk.Button(parent, text="분해·실행", command=on_run, bg=_ACCENT, fg="white",
              font=("맑은 고딕", 11, "bold"), relief="flat", height=1).pack(fill="x", pady=(6, 3))

    # ── 마이크 녹음(장치 있으면) → STT → 명령 ──
    _REC_SEC = 4.0
    if mic_available():
        def _record_and_run():
            import os as _os
            import tempfile
            try:
                app.set_status(f"🎤 녹음 중 ({int(_REC_SEC)}초)...")
                app.log(f"[녹음] {int(_REC_SEC)}초간 마이크로 녹음합니다...")
                wav = _os.path.join(tempfile.gettempdir(), "a1_voice_command.wav")
                record_wav(wav, seconds=_REC_SEC)            # 실제 마이크 녹음
                app.set_status("음성 인식 중...")
                text = listen_command(wav, app._a1_stt)      # STT(whisper) 인식
                is_mock = bool(getattr(app._a1_stt, "mock", False))
                if is_mock:
                    app.log("[STT] whisper 미설치 → mock(실제 인식 아님). "
                            "'pip install openai-whisper' 후 사용하세요.")
                app.log(f"[STT] 인식 결과: {text!r}")
                app.root.after(0, lambda: cmd_var.set(text))
                if is_mock:
                    return   # mock 텍스트는 실제 명령이 아니므로 실행하지 않음
                if app._a1_busy:
                    return
                app._a1_busy = True
                threading.Thread(target=_run_command, args=(text,), daemon=True).start()
            except Exception as e:
                app.log(f"[녹음/STT 오류] {type(e).__name__}: {e}")
                app.set_status("녹음/STT 오류")

        tk.Button(parent, text=f"🎤 녹음({int(_REC_SEC)}초)",
                  command=lambda *_: threading.Thread(
                      target=_record_and_run, daemon=True).start(),
                  bg="#3a3a52", fg="white", font=("맑은 고딕", 11),
                  relief="flat", height=1).pack(fill="x", pady=3)
        if not _HAS_WHISPER:
            tk.Label(parent, text="(실제 인식엔 whisper 필요: pip install openai-whisper)",
                     bg=_PANEL, fg="#c9a94f", font=("맑은 고딕", 9)).pack(anchor="w")
    else:
        tk.Label(parent, text="(마이크 없음 — 텍스트 입력 사용)", bg=_PANEL, fg="#8a8a9a",
                 font=("맑은 고딕", 9)).pack(anchor="w", pady=(2, 0))


def main():
    app = LessonGUI(
        title="A1 · 음성 제어 오케스트레이션",
        camera_index=config.CAM_TABLE,   # 패시브 작업공간 뷰(색검출 없음)
        use_robot=True,
        build_controls=_build_controls,
        info=INFO,
    )
    app.run()


if __name__ == "__main__":
    main()
