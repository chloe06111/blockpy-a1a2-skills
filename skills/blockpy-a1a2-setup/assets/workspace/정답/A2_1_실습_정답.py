"""a2_board_game_ai/scaffold.py — [A2 · 하이브리드(Advanced)] 학생 실습용 골격.

여러분이 만들 것
----------------
비전으로 인식한 격자 보드(2D 배열)를 보고, minimax 탐색으로 '최적의 수'를 찾아,
로봇이 그 칸에 마커를 착수(픽앤플레이스)하는 틱택토 AI 입니다.

채울 곳(# TODO)을 모두 완성하면 solution.py 와 똑같이 동작합니다.

학습 순서 (Logic-First, Syntax-Later)
-------------------------------------
1) 먼저 종이에 3x3 보드를 그리고, "이 자리에 두면 어떻게 될까?"를 손으로 따라가 보세요.
   minimax 는 '모든 경우의 수를 끝까지 둬 보고 가장 좋은 수를 고르는' 완전탐색입니다.
2) 그 다음 아래 TODO 를 코드로 옮깁니다. (점수: AI 승 +, 사람 승 -, 무승부 0)

규칙
----
- minimax 관련 함수는 로봇/카메라를 쓰지 않는 **순수함수**로 작성합니다(단위테스트 대상).
- 위험 동작(이동) 전에는 반드시 안전 검사를 합니다(이미 골격에 넣어 두었습니다).
- 하드웨어/키 없이 mock 으로 끝까지 실행되어야 합니다.

실행
----
    CURRICULUM_FORCE_MOCK=1 python a2_board_game_ai/scaffold.py
"""

from __future__ import annotations

# ── BlockPy 에서 실행하기 위한 줄 (지우지 마세요) ──────────────────────────
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "taskB_curriculum"))   # BlockPy 작업 폴더의 수업 코드
os.environ.setdefault("CURRICULUM_FORCE_MOCK", "1")                  # 원본 코드의 자동 연결은 끄고
실제로봇_쓰기 = True    # True = 연결된 로봇팔을 움직여요(없으면 모의로) / False = 화면만(모의)
# ──────────────────────────────────────────────────────────────────────────

# ── sys.path 부트스트랩 2줄(코드 루트를 import 경로에 추가) ──
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 공통 라이브러리(그대로 사용하세요) — mock 자동 폴백
from common.dobot_ctl import get_robot          # 로봇 제어
from common.vision import detect_colors         # 색검출(보드 인식 보조)
from common import safety                        # 안전필터
from common import config                        # 전역 설정(WORKSPACE)

import time

# 보드 칸 상태(그대로 사용)
EMPTY = " "
P_AI = "O"      # 로봇(AI)
P_HUMAN = "X"   # 사람


# ===========================================================================
# 1) minimax — 순수함수 게임 AI  ★여기가 이번 차시의 핵심★
# ===========================================================================
def winner(board):
    """3x3 보드의 승자('O'/'X')를 반환, 없으면 None.

    힌트: 검사할 라인은 가로 3 + 세로 3 + 대각선 2 = 총 8개.
          한 라인의 세 칸이 모두 EMPTY 가 아니고 서로 같으면 그 말이 승자입니다.
    """
    lines = []
    # TODO(1-a): 가로 3줄과 세로 3줄을 lines 에 추가하세요.
    #   for i in range(3):
    #       lines.append([board[i][0], board[i][1], board[i][2]])   # 가로
    #       lines.append([board[0][i], board[1][i], board[2][i]])   # 세로
    for i in range(3):
        lines.append([board[i][0], board[i][1], board[i][2]])   # 가로
        lines.append([board[0][i], board[1][i], board[2][i]])   # 세로
    # TODO(1-b): 대각선 2줄도 lines 에 추가하세요.
    lines.append([board[0][0], board[1][1], board[2][2]])       # 대각선 ↘
    lines.append([board[0][2], board[1][1], board[2][0]])       # 대각선 ↙
    # TODO(1-c): 각 line 에 대해, 세 칸이 같고 EMPTY 가 아니면 line[0] 을 반환하세요.
    for line in lines:
        if line[0] != EMPTY and line[0] == line[1] == line[2]:
            return line[0]
    return None     # 위 검사를 모두 통과하면 아직 승자 없음


def is_full(board):
    """빈 칸이 하나도 없으면 True."""
    # TODO(2): 모든 칸이 EMPTY 가 아닌지 검사해 True/False 반환.
    #   힌트: all(... for row in board for cell in row)
    return all(cell != EMPTY for row in board for cell in row)


def available_moves(board):
    """둘 수 있는 빈 칸 좌표 목록 [(행,열), ...]."""
    # TODO(3): board[r][c] == EMPTY 인 (r,c) 들을 리스트로 반환.
    return [(r, c) for r in range(3) for c in range(3) if board[r][c] == EMPTY]


def _minimax(board, player, depth):
    """minimax 완전탐색(재귀). (점수, 최적수) 반환.

    점수 규약(AI=P_AI 기준): AI 승 = 10-depth, 사람 승 = depth-10, 무승부 = 0.
    힌트(알고리즘):
      1) 단말 판정: winner()/is_full() 로 끝났으면 점수와 None 을 반환.
      2) player 가 P_AI 면 점수를 '최대화', P_HUMAN 이면 '최소화'.
      3) 각 빈 칸에 말을 둬 보고(가정) → 재귀로 상대 차례 점수 계산 → 되돌리기(백트래킹).
    """
    # TODO(4-a): 단말 판정 — winner()==P_AI → (10-depth, None),
    #            winner()==P_HUMAN → (depth-10, None), is_full() → (0, None).
    win = winner(board)
    if win == P_AI:
        return 10 - depth, None
    if win == P_HUMAN:
        return depth - 10, None
    if is_full(board):
        return 0, None

    moves = available_moves(board)
    best_move_rc = moves[0] if moves else None

    if player == P_AI:
        best_score = -999
        # TODO(4-b): 각 (r,c) 에 P_AI 를 두고 _minimax(board, P_HUMAN, depth+1) 호출,
        #            board[r][c]=EMPTY 로 되돌린 뒤 score 가 더 크면 best 갱신.
        for (r, c) in moves:
            board[r][c] = P_AI
            score, _ = _minimax(board, P_HUMAN, depth + 1)
            board[r][c] = EMPTY
            if score > best_score:
                best_score, best_move_rc = score, (r, c)
        return best_score, best_move_rc
    else:
        best_score = 999
        # TODO(4-c): 각 (r,c) 에 P_HUMAN 을 두고 _minimax(board, P_AI, depth+1) 호출,
        #            되돌린 뒤 score 가 더 작으면 best 갱신.
        for (r, c) in moves:
            board[r][c] = P_HUMAN
            score, _ = _minimax(board, P_AI, depth + 1)
            board[r][c] = EMPTY
            if score < best_score:
                best_score, best_move_rc = score, (r, c)
        return best_score, best_move_rc


def best_move(board, player=P_AI):
    """주어진 보드에서 player 의 최적 수 (행,열) 반환(순수함수)."""
    if not available_moves(board):
        return None
    work = [row[:] for row in board]    # 원본 보호용 복사(그대로 두세요)
    # TODO(5): _minimax(work, player, 0) 을 호출해 최적수만 반환.
    _, move = _minimax(work, player, 0)
    return move


# ===========================================================================
# 2) 비전(보드 인식) — mock 2D 배열 데모 (그대로 사용)
# ===========================================================================
def recognize_board(frame=None, mock_board=None):
    """격자 보드를 2D 배열로 인식(이번 차시는 mock 보드로 데모)."""
    if mock_board is not None:
        _validate_board(mock_board)
        return [row[:] for row in mock_board]
    if frame is not None:
        blocks = detect_colors(frame)
        print(f"[비전] 색 마커 후보 {len(blocks)}개 검출(시연용)")
    return [[EMPTY] * 3 for _ in range(3)]


def _validate_board(board):
    """보드 형태 검증(그대로 사용)."""
    if len(board) != 3 or any(len(row) != 3 for row in board):
        raise ValueError("보드는 반드시 3x3 형태여야 합니다.")
    allowed = {EMPTY, P_AI, P_HUMAN}
    for row in board:
        for cell in row:
            if cell not in allowed:
                raise ValueError(f"허용되지 않은 칸 값 '{cell}'.")


def render_board(board):
    """보드를 문자열로(그대로 사용)."""
    rows = [" " + " | ".join(row) + " " for row in board]
    return "\n-----------\n".join(rows)


# ===========================================================================
# 3) 격자(행,열) → 로봇 좌표(mm) 변환
# ===========================================================================
# 높이 상수(그대로 사용). 근거: docs/두봇_라이트_API.md 픽앤플레이스 예제.
Z_TRAVEL = 50.0      # 이동(공중) 높이
Z_PICK = -30.0       # 집는 높이(WORKSPACE z 하한 -60 안쪽)
FEEDER_XY = (200.0, -120.0)   # 마커 공급 위치


def cell_to_xy(row, col, workspace=None):
    """보드 칸 (행,열) 을 로봇 X,Y(mm) 로 변환.

    힌트: 작업영역(config.WORKSPACE)의 x,y 범위 안쪽에 15% 여백을 두고,
          (idx+0.5)/3 비율로 셀 중앙에 배치합니다(행→X, 열→Y).
    """
    ws = workspace or config.WORKSPACE
    x_lo, x_hi = ws["x"]
    y_lo, y_hi = ws["y"]
    # TODO(6): 위 힌트대로 x, y 를 계산해 (round(x,1), round(y,1)) 반환.
    #   margin_x = (x_hi-x_lo)*0.15 ; fx = (row+0.5)/3.0 ; ... 동일하게 y 도.
    margin_x = (x_hi - x_lo) * 0.15
    margin_y = (y_hi - y_lo) * 0.15
    fx = (row + 0.5) / 3.0
    fy = (col + 0.5) / 3.0
    x = (x_lo + margin_x) + fx * ((x_hi - x_lo) - 2 * margin_x)
    y = (y_lo + margin_y) + fy * ((y_hi - y_lo) - 2 * margin_y)
    return round(x, 1), round(y, 1)


# ===========================================================================
# 4) 로봇 착수 — 픽앤플레이스 (안전가드는 제공됨)
# ===========================================================================
def place_marker(bot, row, col, marker=P_AI):
    """마커 1개를 집어 (행,열) 칸에 착수(픽앤플레이스)."""
    tx, ty = cell_to_xy(row, col)
    fx, fy = FEEDER_XY
    steps = []

    # 픽앤플레이스 계획: (설명, x, y, z, 흡착 or None)
    plan = [
        ("피더 위로 이동", fx, fy, Z_TRAVEL, None),
        ("피더로 하강",     fx, fy, Z_PICK,   None),
        ("흡착 ON(집기)",   fx, fy, Z_PICK,   True),
        ("마커 들어올림",   fx, fy, Z_TRAVEL, None),
        ("목표칸 위로 이동", tx, ty, Z_TRAVEL, None),
        ("목표칸으로 하강", tx, ty, Z_PICK,   None),
        ("흡착 OFF(놓기)",  tx, ty, Z_PICK,   False),
        ("로봇 상승",       tx, ty, Z_TRAVEL, None),
    ]

    for desc, x, y, z, suck in plan:
        # 안전가드(제공): 위험 동작 전 좌표 검사 — 이 줄은 지우지 마세요.
        ok, msg = safety.check_move(x, y, z)
        if not ok:
            print(f"  [안전] {desc}: {msg.splitlines()[0]}")
        if suck is None:
            res = bot.move_to(x, y, z)     # 내부에서 한 번 더 클램프(이중 안전)
            steps.append((desc, res["actual"]))
        else:
            bot.suck(suck)
            steps.append((desc, {"suck": suck}))

    return {"target_cell": (row, col), "target_xy": (tx, ty),
            "marker": marker, "steps": steps}


def play_ai_turn(bot, board):
    """AI 한 턴: 최적수 계산 → 로봇 착수 → 보드 갱신."""
    move = best_move(board, P_AI)
    if move is None:
        print("[AI] 둘 칸이 없습니다.")
        return board, None, None
    r, c = move
    print(f"[AI] minimax 최적 수: ({r},{c}) → 착수")
    log = place_marker(bot, r, c, P_AI)
    board[r][c] = P_AI
    return board, move, log


# ===========================================================================
# 5) 자가 데모 (mock) — 완성하면 solution.py 와 동일하게 동작
# ===========================================================================
def _demo():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=" * 60)
    print(" [A2 실습] 보드게임 AI — TODO 를 채워 완성하세요 (mock)")
    print(f" mock 모드 : {config.is_mock()}")
    print("=" * 60)

    board = recognize_board(mock_board=[
        [P_HUMAN, EMPTY, EMPTY],
        [EMPTY,  P_AI,  EMPTY],
        [EMPTY,  EMPTY, P_HUMAN],
    ])
    print(f"인식된 보드:\n{render_board(board)}")

    from class_robot import 로봇_연결
    with 로봇_연결(실제로봇_쓰기) as bot:    # 로봇이 연결돼 있으면 실제로 말을 놓아요
        bot.home()
        t0 = time.time()
        board, move, log = play_ai_turn(bot, board)
        dt = time.time() - t0
        if move is None:
            print("아직 best_move 가 None 입니다 — TODO(1~5)를 완성하세요.")
        else:
            print(f"착수: {move} / {dt*1000:.1f} ms / {len(log['steps'])}단계")
            print(f"갱신된 보드:\n{render_board(board)}")

    # [연습용으로 더한 출력] 활동지 ④ — 칸의 로봇 자리와 말 놓기 8걸음
    print("\n[칸 → 로봇 자리 (x, y) mm]")
    for cell in [(0, 0), (1, 1), (0, 2), (2, 0)]:
        print(f"  {cell} → {cell_to_xy(*cell)}")
    print("\n[말 놓기 8걸음] (0, 2) 칸에 놓을 때")
    with get_robot(mock=True) as bot:
        for i, (desc, where) in enumerate(place_marker(bot, 0, 2)["steps"], 1):
            print(f"  {i}. {desc}  {where}")

    print("\n실습 안내: 모든 TODO 를 채우면 AI 가 (0,2) 같은 승리/방어수를 두고")
    print("로봇이 그 칸에 마커를 착수합니다. solution.py 와 결과를 비교해 보세요.")


if __name__ == "__main__":
    _demo()
