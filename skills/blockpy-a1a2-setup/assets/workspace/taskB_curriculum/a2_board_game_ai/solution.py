"""a2_board_game_ai/solution.py — [A2 · 하이브리드(Advanced)] 보드게임 AI 모범답안.

차시 개요
---------
- 주제 : "보드게임 AI — 2D 배열 알고리즘 + 로봇 착수"(틱택토)
- 흐름 : 비전으로 격자 보드를 **2D 배열**로 인식 → minimax 완전탐색으로 최적 수 계산
         → 로봇이 해당 칸에 마커를 픽앤플레이스(물리적 착수).
- 학습 목표(2D 배열/탐색 알고리즘) : 중첩 리스트로 보드를 표현하고, 재귀(minimax)로
         완전탐색하며, 격자 좌표(행,열)를 로봇 작업영역(mm)으로 변환한다.
- 교육 철학 : 110분 · 5E · 'Logic-First, Syntax-Later'(먼저 게임 트리/탐색을 손으로 따라가고
         그 뒤에 코드로 옮긴다) · 산업연계(PBL: 자동화 라인의 비전→판단→집행 파이프라인 축소판).

설계 특이사항(요구사항 반영)
---------------------------
- minimax 는 **순수함수**로 분리한다(전역상태/로봇/카메라 의존 없음 → 단위테스트 용이).
- 보드 인식은 하드웨어 없이 **mock 2D 배열**로 데모한다(비전 계층은 common.vision 사용).
- 위험 동작(이동) 직전 common.safety 로 좌표를 검사/클램프한다(SFR-002).

사용법
------
    # 하드웨어/키 없이 mock 으로 끝까지 실행
    CURRICULUM_FORCE_MOCK=1 python a2_board_game_ai/solution.py

인터페이스 계약 : deliverables/pm/CONTRACTS.md
좌표/한계 근거 : docs/두봇_라이트_API.md
"""

from __future__ import annotations

# ── sys.path 부트스트랩 2줄(코드 루트 taskB_curriculum 를 import 경로에 추가) ──
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 공통 라이브러리(계약 API). 하드웨어/키 없이 mock 으로 동작한다.
from common.dobot_ctl import get_robot          # 로봇 제어(MockDobot 자동 폴백)
from common.vision import detect_colors         # 색검출(보드 인식 보조)
from common import safety                        # 안전필터(check_move/clamp_move)
from common import config                        # 전역 설정(WORKSPACE/mock 판정)

import time     # 회차 소요시간 측정 등에 사용

# 보드 칸 상태 표기 — 가독성을 위해 상수로 분리(2D 배열 원소 값)
EMPTY = " "     # 빈 칸
P_AI = "O"      # 로봇(AI)이 두는 말
P_HUMAN = "X"   # 사람이 두는 말


# ===========================================================================
# 1) minimax — 순수함수 게임 AI (로봇/카메라 의존 없음 → 단위테스트 가능)
# ===========================================================================
def winner(board):
    """현재 2D 보드의 승자를 반환한다. 'O'/'X'/None(미결정).

    board : 3x3 중첩 리스트(각 원소 EMPTY/P_AI/P_HUMAN). 순수 입력만 본다.
    """
    lines = []                                   # 승리 판정을 볼 8개 라인 모음
    for i in range(3):
        lines.append([board[i][0], board[i][1], board[i][2]])   # 가로 3줄
        lines.append([board[0][i], board[1][i], board[2][i]])   # 세로 3줄
    lines.append([board[0][0], board[1][1], board[2][2]])       # 좌상→우하 대각
    lines.append([board[0][2], board[1][1], board[2][0]])       # 우상→좌하 대각
    for line in lines:                           # 각 라인이 한 말로 가득 찼는지 검사
        if line[0] != EMPTY and line[0] == line[1] == line[2]:
            return line[0]                       # 세 칸이 같고 비어있지 않으면 그 말이 승자
    return None                                  # 어떤 라인도 완성되지 않음 → 미결정


def is_full(board):
    """보드에 빈 칸이 하나도 없으면 True(무승부 후보)."""
    return all(cell != EMPTY for row in board for cell in row)   # 모든 칸이 채워졌는지


def available_moves(board):
    """둘 수 있는 빈 칸 좌표 목록 [(행,열), ...] 을 반환한다."""
    return [(r, c) for r in range(3) for c in range(3) if board[r][c] == EMPTY]


def _minimax(board, player, depth):
    """minimax 완전탐색 핵심(재귀). (점수, 최적수) 를 반환하는 순수함수.

    점수 규약(AI=P_AI 기준) : AI 승 = +10-깊이, 사람 승 = -10+깊이, 무승부 = 0.
    깊이를 점수에 반영해 '빠른 승리/늦은 패배'를 선호하게 한다(교육용 직관).
    player : 이번 차례에 둘 말(P_AI 또는 P_HUMAN).
    """
    win = winner(board)                          # 단말(terminal) 판정 먼저
    if win == P_AI:
        return 10 - depth, None                  # AI 승: 빨리 이길수록 높은 점수
    if win == P_HUMAN:
        return depth - 10, None                  # 사람 승: 늦게 질수록 덜 나쁜 점수
    if is_full(board):
        return 0, None                           # 무승부

    moves = available_moves(board)               # 이번 차례에 가능한 모든 수
    best_move = moves[0]                          # 기본값(빈 칸 보장됨)

    if player == P_AI:                           # AI 차례 → 점수를 '최대화'
        best_score = -999                        # 최댓값 탐색 초기값(충분히 작게)
        for (r, c) in moves:
            board[r][c] = P_AI                   # 가정: 이 칸에 AI 말 두기
            score, _ = _minimax(board, P_HUMAN, depth + 1)   # 상대 차례로 재귀
            board[r][c] = EMPTY                  # 되돌리기(백트래킹: 순수성 유지)
            if score > best_score:               # 더 좋은 수를 찾으면 갱신
                best_score, best_move = score, (r, c)
        return best_score, best_move
    else:                                         # 사람 차례 → 점수를 '최소화'
        best_score = 999                         # 최솟값 탐색 초기값(충분히 크게)
        for (r, c) in moves:
            board[r][c] = P_HUMAN                # 가정: 이 칸에 사람 말 두기
            score, _ = _minimax(board, P_AI, depth + 1)      # AI 차례로 재귀
            board[r][c] = EMPTY                  # 되돌리기
            if score < best_score:               # 사람은 AI 점수를 최소로 만들려 함
                best_score, best_move = score, (r, c)
        return best_score, best_move


def best_move(board, player=P_AI):
    """주어진 2D 보드에서 player 의 최적 수 (행,열) 을 반환하는 순수함수.

    입력 보드를 변형하지 않도록 깊은 복사 후 탐색한다(테스트 안정성).
    빈 칸이 없으면 None.
    """
    if not available_moves(board):               # 둘 곳이 없으면 즉시 종료
        return None
    work = [row[:] for row in board]             # 얕은 복사로 행 단위 독립 사본 생성
    _, move = _minimax(work, player, 0)          # 깊이 0 에서 탐색 시작
    return move


# ===========================================================================
# 2) 비전(보드 인식) — mock 2D 배열 데모 (common.vision 사용)
# ===========================================================================
def recognize_board(frame=None, mock_board=None):
    """격자 보드를 2D 배열로 인식한다(mock 데모).

    실제 수업에서는 카메라 frame 에서 격자 셀별 색/마커를 검출해 채우지만,
    본 차시는 '보드 인식은 mock 2D 배열로 데모'(특이사항)한다.
    - mock_board 가 주어지면 그대로 검증 후 반환.
    - frame 이 주어지면 detect_colors 로 마커 후보 수만 로그(인식 흐름 시연)하고,
      안전한 기본(빈 보드)을 반환한다.
    반환 : 3x3 중첩 리스트.
    """
    if mock_board is not None:                   # mock 보드 우선(데모/테스트 경로)
        _validate_board(mock_board)              # 형태 검증(3x3, 허용 문자)
        return [row[:] for row in mock_board]    # 방어적 복사본 반환

    if frame is not None:                        # 프레임이 있으면 비전 흐름만 시연
        blocks = detect_colors(frame)            # [{color,bbox,center,area}, ...]
        print(f"[비전] 프레임에서 색 마커 후보 {len(blocks)}개 검출(시연용)")
    return [[EMPTY] * 3 for _ in range(3)]       # 기본: 빈 보드


def _validate_board(board):
    """보드가 3x3 이고 허용된 문자만 갖는지 검증(친절한 한국어 예외)."""
    if len(board) != 3 or any(len(row) != 3 for row in board):
        raise ValueError("보드는 반드시 3x3 형태여야 합니다(중첩 리스트).")
    allowed = {EMPTY, P_AI, P_HUMAN}
    for row in board:
        for cell in row:
            if cell not in allowed:
                raise ValueError(
                    f"보드 칸에 허용되지 않은 값 '{cell}' 이 있습니다. "
                    f"'{EMPTY}'/'{P_AI}'/'{P_HUMAN}' 만 사용하세요."
                )


def render_board(board):
    """2D 보드를 사람이 보기 좋은 문자열로 변환(콘솔 출력/디버깅용)."""
    rows = [" " + " | ".join(row) + " " for row in board]   # 각 행을 ' X | O |   ' 형태로
    sep = "\n-----------\n"                                  # 행 구분선
    return sep.join(rows)


# ===========================================================================
# 3) 격자(행,열) → 로봇 작업영역(mm) 좌표 변환
# ===========================================================================
def cell_to_xy(row, col, workspace=None):
    """보드 칸 (행,열) 을 로봇 X,Y(mm) 좌표로 변환한다.

    3x3 격자를 작업영역 안쪽 여백을 둔 사각형에 균등 배치한다.
    - 행(row) 증가 → 로봇에서 멀어지는 방향(X 증가)으로 매핑(0행이 가장 가까움).
    - 열(col) 증가 → 오른쪽(Y 증가)으로 매핑.
    반환 : (x, y) 모두 작업영역 내부 mm.
    """
    ws = workspace or config.WORKSPACE           # 작업영역(단일 출처)
    x_lo, x_hi = ws["x"]                         # 전후 도달 범위
    y_lo, y_hi = ws["y"]                         # 좌우 범위
    margin_x = (x_hi - x_lo) * 0.15              # 가장자리 충돌 방지 여백(15%)
    margin_y = (y_hi - y_lo) * 0.15
    # 3칸을 0.5/1.5/2.5 비율 중심에 배치(셀 중앙) → (idx+0.5)/3
    fx = (row + 0.5) / 3.0                       # 행 방향 정규화 위치(0~1)
    fy = (col + 0.5) / 3.0                       # 열 방향 정규화 위치(0~1)
    x = (x_lo + margin_x) + fx * ((x_hi - x_lo) - 2 * margin_x)   # X(mm)
    y = (y_lo + margin_y) + fy * ((y_hi - y_lo) - 2 * margin_y)   # Y(mm)
    return round(x, 1), round(y, 1)


# ===========================================================================
# 4) 로봇 착수 — 마커를 집어 목표 칸에 픽앤플레이스(안전검사 포함)
# ===========================================================================
# 높이 상수(mm). 근거: docs/두봇_라이트_API.md 픽앤플레이스 예제(Z=50 이동, Z 하강 후 흡착).
Z_TRAVEL = 50.0      # 이동(공중) 높이 — 보드 위를 안전하게 가로지름
# 집기 하강 높이(mm). 교구 두께/마커 높이 기준, WORKSPACE z 하한(-60) 안쪽 — 차시 교구에 맞춰 조정
Z_PICK = -30.0       # 마커를 집는 높이(책상면 근처). WORKSPACE z 하한(-60) 안쪽

# 마커 공급 위치(피더). 작업영역 안쪽 한 지점에 마커 더미가 있다고 가정.
FEEDER_XY = (200.0, -120.0)


def place_marker(bot, row, col, marker=P_AI):
    """로봇이 마커 1개를 집어 보드의 (행,열) 칸에 착수한다.

    안전(SFR-002) : 모든 이동 좌표를 safety.check_move 로 사전 검사하고,
    실제 이동은 bot.move_to 내부의 clamp_move 가 한 번 더 보정한다(이중 안전).
    동작 순서(픽앤플레이스) : 피더 위 → 하강 → 흡착 ON → 상승 → 목표칸 위 →
                              하강 → 흡착 OFF(놓기) → 상승.
    반환 : 동작 로그(dict) — 검수/테스트용.
    """
    tx, ty = cell_to_xy(row, col)                # 목표 칸의 로봇 좌표(mm)
    fx, fy = FEEDER_XY                           # 마커 공급 좌표(mm)
    steps = []                                   # 수행 좌표 시퀀스(검수용)

    # 이동 시퀀스 정의: (설명, x, y, z, 흡착여부 or None)
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

    for desc, x, y, z, suck in plan:             # 계획된 동작을 순서대로 실행
        ok, msg = safety.check_move(x, y, z)     # 위험 동작 전 안전 검사(필수)
        if not ok:                               # 안전범위 밖이면 경고만 남기고(이동은 클램프됨)
            print(f"  [안전] {desc}: {msg.splitlines()[0]}")
        if suck is None:                         # 흡착 명령이 아닌 순수 이동
            res = bot.move_to(x, y, z)           # 내부에서 clamp_move 재보정
            steps.append((desc, res["actual"]))  # 실제(보정) 좌표 기록
        else:                                    # 흡착 ON/OFF
            bot.suck(suck)
            steps.append((desc, {"suck": suck}))

    return {"target_cell": (row, col), "target_xy": (tx, ty),
            "marker": marker, "steps": steps}


# ===========================================================================
# 5) 한 턴 진행 — 인식 → minimax → 착수 (전체 파이프라인 1턴)
# ===========================================================================
def play_ai_turn(bot, board):
    """현재 보드에서 AI(로봇)가 한 턴을 둔다(인식은 이미 board 로 주어졌다고 가정).

    1) best_move 로 최적 수 계산(순수함수) → 2) place_marker 로 물리 착수 →
    3) 보드 2D 배열 갱신. 반환 : (갱신된 보드, 둔 좌표, 착수 로그).
    """
    move = best_move(board, P_AI)                # minimax 로 최적 칸 계산
    if move is None:                             # 둘 곳이 없으면(보드 가득) 종료
        print("[AI] 둘 수 있는 칸이 없습니다(무승부).")
        return board, None, None
    r, c = move
    print(f"[AI] minimax 최적 수: ({r},{c}) → 로봇 착수 시작")
    log = place_marker(bot, r, c, P_AI)          # 로봇이 해당 칸에 마커 착수
    board[r][c] = P_AI                           # 2D 배열에 결과 반영
    return board, move, log


# ===========================================================================
# 6) 자가 데모 (mock) — 하드웨어/키 없이 끝까지 실행
# ===========================================================================
def _demo():
    """mock 으로 전체 흐름 시연: 보드 인식 → minimax → 로봇 착수 → 승부 진행."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 한글 깨짐 방지
    except Exception:
        pass

    print("=" * 60)
    print(" [A2] 보드게임 AI — 2D 배열 + minimax + 로봇 착수 (mock 데모)")
    print(f" mock 모드 : {config.is_mock()}")
    print("=" * 60)

    # (A) 단위테스트 성격의 minimax 순수함수 검증 — 한 수면 이기는 자리
    print("\n[1] minimax 순수함수 점검")
    near_win = [
        [P_AI,  P_AI,  EMPTY],   # O O _  → (0,2) 두면 AI 승
        [P_HUMAN, P_HUMAN, EMPTY],
        [EMPTY, EMPTY, EMPTY],
    ]
    mv = best_move(near_win, P_AI)
    print(f"  보드:\n{render_board(near_win)}")
    print(f"  → AI 최적 수: {mv}  (기대: (0, 2) 승리수)")
    assert mv == (0, 2), "minimax 가 승리수를 찾지 못함"

    # 블로킹 점검 — 사람이 한 수면 이기는 상황은 AI 가 막아야 함
    block = [
        [P_HUMAN, P_HUMAN, EMPTY],   # X X _  → AI 는 (0,2) 를 막아야 함
        [EMPTY, P_AI, EMPTY],
        [EMPTY, EMPTY, EMPTY],
    ]
    mvb = best_move(block, P_AI)
    print(f"  블로킹 보드 AI 수: {mvb}  (기대: (0, 2) 방어수)")
    assert mvb == (0, 2), "minimax 가 상대 승리수를 막지 못함"

    # (B) 격자→좌표 변환 점검(모두 작업영역 안인지)
    print("\n[2] 격자(행,열) → 로봇 좌표(mm) 변환")
    for (r, c) in [(0, 0), (1, 1), (2, 2)]:
        x, y = cell_to_xy(r, c)
        ok, _ = safety.check_move(x, y, Z_TRAVEL)
        print(f"  칸({r},{c}) → (x={x}, y={y})  안전={ok}")
        assert ok, "변환 좌표가 작업영역을 벗어남"

    # (C) 전체 1턴 파이프라인 — mock 보드 인식 → AI 착수
    print("\n[3] 전체 파이프라인: mock 보드 인식 → minimax → 로봇 착수")
    board = recognize_board(mock_board=[
        [P_HUMAN, EMPTY, EMPTY],
        [EMPTY,  P_AI,  EMPTY],
        [EMPTY,  EMPTY, P_HUMAN],
    ])
    print(f"  인식된 보드:\n{render_board(board)}")
    with get_robot(mock=True) as bot:            # with 종료 시 안전정지+disconnect 보장
        bot.home()                               # 전원 직후 홈(좌표 신뢰성)
        t0 = time.time()
        board, move, log = play_ai_turn(bot, board)
        dt = time.time() - t0
        print(f"  착수 완료: {move}  / 소요 {dt*1000:.1f} ms / 동작 {len(log['steps'])}단계")
        print(f"  갱신된 보드:\n{render_board(board)}")

    # (D) 끝까지 한 판 진행(AI vs 단순 상대) — mock 로 완주 보장
    print("\n[4] 한 판 자동 진행(AI=O 선공, 상대=X 는 첫 빈칸)")
    full = [[EMPTY] * 3 for _ in range(3)]
    with get_robot(mock=True) as bot:
        bot.home()
        turn = P_AI                              # 선공은 AI
        while winner(full) is None and not is_full(full):
            if turn == P_AI:
                full, mv, _ = play_ai_turn(bot, full)   # AI: minimax + 로봇 착수
            else:
                # 상대(X): 교육용 단순 정책 — 첫 번째 빈 칸에 둔다
                r, c = available_moves(full)[0]
                full[r][c] = P_HUMAN
                print(f"[상대] ({r},{c}) 에 둠")
            turn = P_HUMAN if turn == P_AI else P_AI    # 차례 교대
        result = winner(full) or "무승부"
        print(f"  최종 보드:\n{render_board(full)}")
        print(f"  결과: {result}")

    print("\n데모 완료: 하드웨어/키 없이 mock 으로 인식→탐색→착수 전 과정 실행됨.")


if __name__ == "__main__":
    _demo()
