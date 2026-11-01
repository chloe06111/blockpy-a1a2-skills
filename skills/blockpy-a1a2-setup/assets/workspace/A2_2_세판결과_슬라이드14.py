# [실습준비 · 시연용 사본] 강의자료\A2_보드게임AI\실습파일\A2_실습_보드실험_초안v1.py 에서 '정답으로_보기 = True' 만 바꾼 것. 원본은 그대로.
# -*- coding: utf-8 -*-
"""[초안 v1 · 새로 만든 실습 파일] A2 · 보드를 넣고 로봇의 다음 수 보기

대표님이 주신 원본 파일이 아닙니다. 내가 채운 scaffold.py(또는 정답 solution.py)의 함수를 불러
보드 여러 개를 한 번에 시험하는 얇은 실험용 파일입니다. 로봇 없이 돌아갑니다(모의 실행).

쓰는 법
  1) 이 파일을 실습 폴더(taskB_curriculum) 안에 복사해요.  (a2_board_game_ai 폴더와 common 폴더가 보이는 곳)
  2) 아래 '시험할_보드' 에 보드를 적어요.  X = 사람, O = 로봇, _ = 빈 칸
  3) 실행해요.  →  보드마다 이긴 쪽 · 로봇의 다음 수 · 그 칸의 로봇 자리(mm)가 나와요.
"""
import os
import sys

실습폴더 = os.environ.get("TASKB_DIR") or os.path.join(os.getcwd(), "taskB_curriculum")   # BlockPy: 작업 폴더의 수업 코드
sys.path.insert(0, 실습폴더)
os.environ.setdefault("CURRICULUM_FORCE_MOCK", "1")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

정답으로_보기 = True      # False = 내가 채운 scaffold.py 로 / True = 정답 solution.py 로 (선생님용)

try:
    if 정답으로_보기:
        from a2_board_game_ai import solution as 게임
    else:
        from a2_board_game_ai import scaffold as 게임
except ModuleNotFoundError as e:
    raise SystemExit("실습 폴더(taskB_curriculum)를 찾지 못했어요: %s\n이 파일을 taskB_curriculum 폴더 안에 복사한 뒤 다시 실행해요." % e)

# ── 여기에 보드를 적어요 (위에서 아래로 세 줄) ───────────────────────────
시험할_보드 = [
    ["XO_",
     "X__",
     "__O"],
    ["X__",
     "___",
     "___"],
    ["X__",
     "_O_",
     "__X"],
]
# ────────────────────────────────────────────────────────────────────────


def 배열로(줄들):
    """'XO_' 같은 글자 세 줄을 2D 배열로 바꾼다. _ 는 빈 칸."""
    바꿈 = {"X": 게임.P_HUMAN, "O": 게임.P_AI, "_": 게임.EMPTY}
    return [[바꿈[글자] for 글자 in 줄] for 줄 in 줄들]


def main():
    print("=" * 60)
    print(" A2 보드 실험 (모의 실행 · 로봇 없음) —", "정답 코드" if 정답으로_보기 else "내 scaffold")
    print("=" * 60)
    for 번호, 줄들 in enumerate(시험할_보드, 1):
        보드 = 배열로(줄들)
        print("\n[보드 %d]" % 번호)
        print(게임.render_board(보드))
        print("  · 이긴 쪽      :", 게임.winner(보드))
        수 = 게임.best_move(보드, 게임.P_AI)
        print("  · 로봇의 다음 수:", 수)
        if 수 is None:
            print("    (None 이면: 둘 칸이 없거나, 아직 scaffold 의 TODO 를 채우지 않았어요)")
        else:
            print("  · 그 칸의 자리  :", 게임.cell_to_xy(수[0], 수[1]), "mm")
    print("\n끝. 내 예상과 비교해요.")


if __name__ == "__main__":
    main()
