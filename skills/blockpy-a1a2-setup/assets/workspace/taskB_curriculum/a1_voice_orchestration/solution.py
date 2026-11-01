# -*- coding: utf-8 -*-
"""a1_voice_orchestration/solution.py — [모범답안]

차시: A1 · 하이브리드(Advanced)
주제: "음성 제어 오케스트레이터 — 음성 명령 다단계 분해·실행" (범용 동작, 색 무관)

수업 목표 (5E · Logic-First · 110분 · 산업연계 PBL)
--------------------------------------------------
사람의 한 마디 음성 명령("홈으로 갔다가 오른쪽으로 5cm 이동하고 흡착 켜")을
  1) STT(Whisper, 로컬)로 글자(텍스트)로 바꾸고,
  2) 오케스트레이터가 그 복합 명령을 "작은 동작 단계들"로 분해(plan)하고,
  3) 사람이 그 계획을 검토(안전 게이트)한 뒤,
  4) 로봇이 동작을 차례로 실행하며 진행을 보고한다.

설계 (색 판별 없음)
-------------------
- 색 인식(detect_colors)은 M1(색상 분류) 전용이다. A1 은 좌표·방향·홈·엔드이펙터 같은
  **범용 동작**을 음성으로 오케스트레이션한다(색·비전 의존 없음).
- 명령 분해/실행은 공통 레이어 common.motion_control 을 재사용한다(중복 구현 금지).
- 언어 해석은 MiniMax(OpenAI 호환) LLM. MINIMAX_API_KEY 가 없으면 mock → **로컬 규칙**
  파서로 폴백(키·인터넷 없이도 동작). STT(음성→텍스트)는 로컬 Whisper 그대로.

안전 (SFR-002)
--------------
- 분해된 계획은 사람 검토(승인) 후에만 실행된다(안전 게이트 review_plan).
- 모든 이동 직전 common.motion_control 이 작업영역으로 클램프한다.

무하드웨어 실행:  CURRICULUM_FORCE_MOCK=1 python a1_voice_orchestration/solution.py
"""
# ── sys.path 부트스트랩 (taskB_curriculum 을 import 루트로 추가) ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.ai_clients import STTClient          # 음성→텍스트(로컬 Whisper, 없으면 mock)
from common.dobot_ctl import get_robot            # 로봇 제어(mock 자동)
from common.motion_control import execute_motion, plan_motion  # 공통 동작 레이어(색 무관)

__all__ = [
    "listen_command", "decompose_command", "review_plan", "execute_plan",
    "run_voice_orchestration",
]


# ===========================================================================
# 1) 음성 → 텍스트 (STT, 로컬)
# ===========================================================================
def listen_command(audio_path: str, stt: STTClient) -> str:
    """오디오 파일을 텍스트 명령으로 바꾼다(로컬 Whisper, mock 시 캔드 텍스트)."""
    return stt.transcribe(audio_path)


# ===========================================================================
# 2) 명령 분해 — 복합 음성 명령 → 다단계 동작 계획
# ===========================================================================
def decompose_command(command: str, llm=None) -> list[dict]:
    """자연어 명령을 여러 동작 단계로 분해한다.

    - 실제(non-mock) LLM(MiniMax)이 주입되면 그 LLM 으로 JSON 배열을 얻어 파싱.
    - 아니면(기본) 로컬 규칙 파서로 다단계 분해(색 무관, 키 불필요).
    반환: 동작 dict 리스트(common.motion_control 스키마).
    """
    actions, _raw = plan_motion(command, llm)
    return actions


# ===========================================================================
# 3) 안전 게이트 — 사람 검토(승인) 후에만 실행
# ===========================================================================
def review_plan(plan: list[dict], approver=None) -> bool:
    """계획을 승인할지 결정한다.

    - 계획이 비어 있으면 거부(False).
    - approver 가 None 이면 자동 승인(True) — 데모/무인 실행용.
    - approver(plan) 이 주어지면 그 반환값(bool)을 따른다(사람 검토).
    """
    if not plan:
        return False
    if approver is None:
        return True
    return bool(approver(plan))


# ===========================================================================
# 4) 실행 — 계획을 안전검사 후 순차 실행
# ===========================================================================
def execute_plan(plan: list[dict], bot) -> dict:
    """동작 계획을 순서대로 실행한다. 반환: {steps, logs}."""
    logs = execute_motion(plan, bot)
    return {"steps": len(plan), "logs": logs}


# ===========================================================================
# 5) 오케스트레이션 — 음성 1건을 끝까지 처리(음성→분해→검토→실행)
# ===========================================================================
def run_voice_orchestration(audio_path: str, approver=None, llm=None,
                            bot=None, stt=None) -> dict:
    """음성 파일 1건을 처리한다: STT → 분해 → 검토 → 실행.

    반환: dict {command, plan, approved, result, status('ok'|'aborted')}
    """
    stt = stt or STTClient()
    if bot is None:
        bot = get_robot(mock=True)
    command = listen_command(audio_path, stt)
    plan = decompose_command(command, llm)
    approved = review_plan(plan, approver)
    if not approved:
        return {"command": command, "plan": plan, "approved": False,
                "result": None, "status": "aborted"}
    result = execute_plan(plan, bot)
    return {"command": command, "plan": plan, "approved": True,
            "result": result, "status": "ok"}


# ===========================================================================
# 6) 자가 데모 (mock) — 하드웨어/키 없이 끝까지 실행
# ===========================================================================
def _demo():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=" * 70)
    print(" A1 · 음성 제어 오케스트레이터 (범용 동작, 색 무관) · 무API 데모")
    print("=" * 70)

    # mock STT: transcribe 가 이 텍스트를 돌려주도록(실제로는 음성 파일에서 인식).
    class _MockSTT:
        mock = True

        def transcribe(self, audio_path):
            return "홈으로 갔다가 오른쪽으로 5cm 이동하고 흡착 켜"

    with get_robot(mock=True) as bot:
        res = run_voice_orchestration("demo.wav", llm=None, bot=bot, stt=_MockSTT())
        print(f"\n[음성 인식] {res['command']}")
        print(f"[분해 계획] {res['plan']}")
        if res["result"]:
            for line in res["result"]["logs"]:
                print("   -", line)
        print(f"[상태] {res['status']}")
    print("\n데모 완료: 색 판별 없이 음성 → 다단계 동작 → 안전실행 파이프라인이 동작했습니다.")


if __name__ == "__main__":
    _demo()
