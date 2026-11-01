# ── BlockPy 에서 실행하기 위한 줄 (지우지 마세요) ──────────────────────────
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "taskB_curriculum"))   # BlockPy 작업 폴더의 수업 코드
os.environ.setdefault("CURRICULUM_FORCE_MOCK", "1")                  # 원본 코드의 자동 연결은 끄고
실제로봇_쓰기 = True    # True = 연결된 로봇팔을 움직여요(없으면 모의로) / False = 화면만(모의)
# ──────────────────────────────────────────────────────────────────────────
음성으로_말하기 = True   # True = 마이크로 말하기(녹음) / False = 글자(말한_문장)로 대신
녹음_시간 = 4            # 녹음 초
음성모델 = "medium"      # 더 정확함(인식 약 6초) / 더 빠르게: "small" (방향을 잘못 들을 때가 있음)

# 원본 정답 코드(a1_voice_orchestration/solution.py)의 데모와 같은 일을 한다 — 로봇은 실제 로봇, 음성은 진짜 마이크.
from a1_voice_orchestration import solution
from class_robot import 로봇_연결


class 글자_STT:                     # 원본 데모의 가짜 STT 와 같은 문장
    mock = True

    def transcribe(self, audio_path):
        return "홈으로 갔다가 오른쪽으로 5cm 이동하고 흡착 켜"


print("=" * 70)
print(" A1 · 음성 제어 오케스트레이터 (범용 동작, 색 무관) · 무API 데모")
print("=" * 70)
if 음성으로_말하기:                       # 로봇이 움직이기 전에 듣는다(로봇 소리가 섞이지 않게)
    from class_voice import 녹음하기, 음성인식기
    stt = 음성인식기(음성모델)
    소리 = 녹음하기(녹음_시간)
else:
    stt, 소리 = 글자_STT(), "demo.wav"
with 로봇_연결(실제로봇_쓰기) as bot:
    res = solution.run_voice_orchestration(소리, llm=None, bot=bot, stt=stt)
    print(f"\n[음성 인식] {res['command']}")
    print(f"[분해 계획] {res['plan']}")
    if res["result"]:
        for line in res["result"]["logs"]:
            print("   -", line)
    print(f"[상태] {res['status']}")
