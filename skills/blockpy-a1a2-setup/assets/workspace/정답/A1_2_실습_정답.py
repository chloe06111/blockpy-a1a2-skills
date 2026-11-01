# -*- coding: utf-8 -*-
"""[초안 v1 · 새로 만든 실습 파일] A1 · 음성 명령으로 연속 동작 만들기 — 학생 실습본

대표님이 주신 원본 파일이 아닙니다. 원본 a1_voice_orchestration/solution.py(정답)와 같은 구조로,
함수 다섯 개의 속을 비워 둔 실습본입니다. (원본 scaffold.py 는 옛 설계라 현재 정답과 맞지 않아 새로 만들었습니다.)

오늘 만드는 흐름
    음성 → (1) 글자로 바꾸기 → (2) 걸음 목록으로 나누기 → (3) 사람이 확인하기 → (4) 차례로 실행하기
    그리고 이 넷을 하나로 잇는 (5) 지휘 함수

쓰는 법
  1) 이 파일을 실습 폴더(taskB_curriculum) 안에 복사해요.  (common 폴더가 보이는 곳)
  2) # TODO 다섯 곳을 채워요.
  3) 맨 아래 '말한_문장' 과 '사람이_승인' 을 바꿔 가며 실행해요.  (로봇 없이 모의 실행)
"""
import os
import sys

실습폴더 = os.environ.get("TASKB_DIR") or os.path.join(os.getcwd(), "taskB_curriculum")   # BlockPy: 작업 폴더의 수업 코드
sys.path.insert(0, 실습폴더)
os.environ.setdefault("CURRICULUM_FORCE_MOCK", "1")    # 로봇 없이 모의 실행
실제로봇_쓰기 = True    # True = 연결된 로봇팔을 움직여요(없으면 모의로) / False = 화면만(모의)
음성으로_말하기 = True   # True = 마이크로 말하기(녹음) / False = 글자(말한_문장)로 대신
녹음_시간 = 4            # 녹음 초
음성모델 = "medium"      # 더 정확함(인식 약 6초) / 더 빠르게: "small" (방향을 잘못 들을 때가 있음)


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from common.dobot_ctl import get_robot                          # 로봇(모의)
    from common.motion_control import execute_motion, plan_motion   # 나누기 · 안전 실행 부품(그대로 써요)
except ModuleNotFoundError as e:
    raise SystemExit("실습 폴더(taskB_curriculum)를 찾지 못했어요: %s\n이 파일을 taskB_curriculum 폴더 안에 복사한 뒤 다시 실행해요." % e)


class 글자_STT:
    """오늘은 마이크 대신 글자를 넣어요. 진짜 STT 처럼 transcribe() 가 문장을 돌려줘요."""
    mock = True

    def __init__(self, 문장):
        self.문장 = 문장

    def transcribe(self, audio_path):
        return self.문장


# ===========================================================================
# (1) 음성 → 글자
# ===========================================================================
def listen_command(audio_path, stt):
    """음성 파일을 글자 명령으로 바꾼다."""
    # TODO(1): stt.transcribe(audio_path) 의 결과를 돌려줘요.
    return stt.transcribe(audio_path)



# ===========================================================================
# (2) 글자 → 걸음 목록(동작 계획)
# ===========================================================================
def decompose_command(command, llm=None):
    """문장을 여러 동작 걸음으로 나눈다. 돌려주는 값: 동작 dict 의 리스트."""
    # TODO(2): plan_motion(command, llm) 은 (actions, raw) 두 개를 돌려줘요. 그중 actions 만 돌려줘요.
    actions, _ = plan_motion(command, llm)
    return actions


# ===========================================================================
# (3) 사람이 확인 — 승인된 계획만 실행한다 (안전 게이트)
# ===========================================================================
def review_plan(plan, approver=None):
    """계획을 실행해도 되는지 정한다. True = 승인, False = 거부."""
    # TODO(3): 세 가지 경우를 순서대로 써요.
    #   ① 계획이 비어 있으면            → False
    #   ② approver 가 None 이면         → True   (확인할 사람이 없는 연습용)
    #   ③ 그 밖에는 approver(plan) 의 답 → bool(...) 로 돌려줘요
    if not plan:
        return False
    if approver is None:
        return True
    return bool(approver(plan))


# ===========================================================================
# (4) 실행 — 범위를 지키며 차례로
# ===========================================================================
def execute_plan(plan, bot):
    """계획을 차례로 실행한다. 돌려주는 값: {"steps": 걸음 수, "logs": 로그 목록}"""
    # TODO(4): logs = execute_motion(plan, bot) 로 실행하고, 위 모양의 dict 를 돌려줘요.
    logs = execute_motion(plan, bot)
    return {"steps": len(plan), "logs": logs}


# ===========================================================================
# (5) 지휘 — 네 단계를 하나로 잇는다
# ===========================================================================
def run_voice_orchestration(audio_path, approver=None, llm=None, bot=None, stt=None):
    """음성 한 건을 끝까지 처리한다: 듣기 → 나누기 → 확인 → 실행."""
    command = listen_command(audio_path, stt)
    plan = decompose_command(command, llm)
    approved = review_plan(plan, approver)
    # TODO(5): 승인되지 않았으면 실행하지 말고 아래 '거부' 모양을 돌려줘요.
    #          승인됐으면 execute_plan(plan, bot) 을 실행해 '승인' 모양을 돌려줘요.
    #   거부: {"command": command, "plan": plan, "approved": False, "result": None,   "status": "aborted"}
    #   승인: {"command": command, "plan": plan, "approved": True,  "result": result, "status": "ok"}
    if not approved:
        return {"command": command, "plan": plan, "approved": False, "result": None, "status": "aborted"}
    result = execute_plan(plan, bot)
    return {"command": command, "plan": plan, "approved": True, "result": result, "status": "ok"}



# ===========================================================================
# 실행해 보기 — 아래 두 줄을 바꿔 가며 실험해요
# ===========================================================================
말한_문장 = "홈으로 갔다가 오른쪽으로 5cm 이동하고 그리퍼 닫아"
사람이_승인 = True        # True = 승인해요 / False = 거부해요


def main():
    print("=" * 64)
    print(" A1 · 음성 명령으로 연속 동작 만들기 (모의 실행 · 로봇 없음)")
    print("=" * 64)

    def 확인하는_사람(plan):
        print("\n[사람 확인] 이 계획을 실행할까요?")
        for 번호, 걸음 in enumerate(plan, 1):
            print("   %d. %s" % (번호, 걸음))
        print("   →", "승인" if 사람이_승인 else "거부")
        return 사람이_승인

    if 음성으로_말하기:                    # 로봇이 움직이기 전에 마이크로 듣는다
        from class_voice import 녹음하기, 음성인식기
        stt = 음성인식기(음성모델)
        소리 = 녹음하기(녹음_시간)
    else:                                  # 글자로 대신: 아래 말한_문장
        stt, 소리 = 글자_STT(말한_문장), "demo.wav"
    from class_robot import 로봇_연결
    with 로봇_연결(실제로봇_쓰기) as 팔:          # 로봇이 연결돼 있으면 실제로 움직여요
        결과 = run_voice_orchestration(소리, approver=확인하는_사람, bot=팔, stt=stt)
    print("\n[음성 인식]", 결과["command"])
    print("[분해 계획] %d 걸음" % len(결과["plan"]))
    if 결과["result"]:
        for 줄 in 결과["result"]["logs"]:
            print("   -", 줄)
    print("[상태]", 결과["status"])
    if not 결과["command"]:
        print("\n아직 TODO(1) 을 채우지 않았어요. 위에서부터 하나씩 채워요.")


if __name__ == "__main__":
    main()
