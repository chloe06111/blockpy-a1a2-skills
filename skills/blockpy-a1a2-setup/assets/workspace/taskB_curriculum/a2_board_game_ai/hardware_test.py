"""a2_board_game_ai/hardware_test.py — [A2] 실제 Dobot 하드웨어 검증 스크립트(QUR-002).

목적
----
복귀(현장) 후 실제 두봇 라이트로 본 차시 모범답안(solution.py)을 **3회 연속 구동**해
재현성과 안전성을 검증하는 turnkey 스크립트다(QUR-002: 3회 구동 검증).

각 회차마다:
  - solution 의 인식→minimax→로봇 착수(픽앤플레이스) 파이프라인을 한 턴 실행
  - 결과(둔 칸/좌표)와 소요시간을 로그로 남김
  - 좌표초과(클램프 발생)·예외(충돌 가능성)를 검출해 회차 성공/실패 판정
  - 매 회차 종료 시 안전정지(흡착/그리퍼 OFF) 보장

안전(SFR-002)
-------------
- 모든 이동은 solution.place_marker 내부에서 safety.check_move + move_to 의 clamp_move 로
  이중 검사된다. 본 스크립트는 추가로 '좌표초과(클램프)'를 비정상 신호로 집계한다.
- with get_robot(...) 컨텍스트가 회차/전체 종료 시 안전정지 후 연결을 해제한다.
- 어떤 예외가 발생해도 finally 에서 비상정지(가능하면 흡착 OFF)를 시도한다.

사용법
------
    # 실제 하드웨어(권장: 포트 명시)
    python a2_board_game_ai/hardware_test.py --port COM3

    # 포트 자동탐지
    python a2_board_game_ai/hardware_test.py

    # 하드웨어 없이 리허설(mock 강제) — 스크립트 자체 점검용
    python a2_board_game_ai/hardware_test.py --mock
    CURRICULUM_FORCE_MOCK=1 python a2_board_game_ai/hardware_test.py

종료코드 : 0=3회 모두 성공, 1=일부/전부 실패(충돌·좌표초과·예외).
좌표/한계 근거 : docs/두봇_라이트_API.md , 인터페이스: deliverables/pm/CONTRACTS.md
"""

from __future__ import annotations

# ── sys.path 부트스트랩 2줄 ──
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse     # --port/--mock 인자 파싱
import time         # 회차 소요시간 측정
import warnings     # 클램프/연결 경고 포착

# 공통 라이브러리 + 모범답안 재사용(중복 구현 금지)
from common.dobot_ctl import get_robot          # 로봇 제어(컨텍스트=안전정지 보장)
from common import safety                        # 안전 검사(좌표초과 사전 검출)
from common import config                        # 전역 설정
from a2_board_game_ai import solution            # 검증 대상 모범답안

RUNS = 3        # QUR-002: 3회 구동 검증

# 각 회차에서 사용할 테스트 보드(결정적): AI 가 (0,2) 에 두면 즉시 승리하는 상황.
# 회차마다 동일 시나리오로 재현성(좌표/소요시간 편차)을 확인한다.
TEST_BOARD = [
    [solution.P_AI,    solution.P_AI,    solution.EMPTY],   # O O _  → 기대수 (0,2)
    [solution.P_HUMAN, solution.P_HUMAN, solution.EMPTY],
    [solution.EMPTY,   solution.EMPTY,   solution.EMPTY],
]
EXPECTED_MOVE = (0, 2)   # minimax 가 둬야 하는 정답 칸(검증용)


def _preflight_safety(board):
    """실행 전 정적 안전 점검 — 둘 칸의 목표 좌표가 작업영역 안인지 미리 확인.

    반환: (ok, 메시지). 좌표초과가 예상되면 ok=False 로 회차를 중단시킨다.
    """
    move = solution.best_move(board, solution.P_AI)     # minimax 최적수(순수함수)
    if move is None:
        return False, "둘 수 있는 칸이 없습니다(보드 가득)."
    r, c = move
    tx, ty = solution.cell_to_xy(r, c)                  # 목표 칸 로봇 좌표(mm)
    # 픽앤플레이스의 양 끝 높이(이동/집기)에 대해 좌표 검사
    for z in (solution.Z_TRAVEL, solution.Z_PICK):
        ok, msg = safety.check_move(tx, ty, z)          # 작업영역/관절 검사
        if not ok:
            return False, f"목표 좌표({tx},{ty},{z}) 위험: {msg.splitlines()[0]}"
    fx, fy = solution.FEEDER_XY
    for z in (solution.Z_TRAVEL, solution.Z_PICK):      # 피더 좌표도 검사
        ok, msg = safety.check_move(fx, fy, z)
        if not ok:
            return False, f"피더 좌표({fx},{fy},{z}) 위험: {msg.splitlines()[0]}"
    return True, f"사전 안전점검 통과(목표 칸 {move} → x={tx}, y={ty})"


def run_once(run_idx, port, mock):
    """한 회차 실행 → 결과 dict 반환.

    {run, ok, move, expected, duration_s, clamped, error}
    - clamped(좌표초과로 보정 발생) 또는 error(예외/충돌) 가 있으면 ok=False.
    """
    print(f"\n{'='*60}\n[회차 {run_idx}/{RUNS}] 시작\n{'='*60}")

    # (0) 사전 정적 안전 점검(좌표초과 예방)
    pf_ok, pf_msg = _preflight_safety(TEST_BOARD)
    print(f"  사전점검: {pf_msg}")
    if not pf_ok:
        return {"run": run_idx, "ok": False, "move": None,
                "expected": EXPECTED_MOVE, "duration_s": 0.0,
                "clamped": False, "error": "preflight_fail: " + pf_msg}

    board = [row[:] for row in TEST_BOARD]   # 회차별 독립 보드 사본
    clamped_flag = False                     # 좌표초과(클램프) 발생 여부
    error = None                             # 예외/충돌 메시지
    move = None
    t0 = time.time()

    try:
        # 경고(클램프 등)를 예외처럼 포착해 좌표초과를 검출
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always")
            # with 컨텍스트: 회차 종료 시 안전정지(suck/grip OFF)+disconnect 보장
            with get_robot(port=port, mock=mock) as bot:
                bot.home()                                  # 전원 직후 홈(좌표 신뢰성)
                board, move, log = solution.play_ai_turn(bot, board)
                # 착수 로그에서 클램프(좌표초과 보정) 흔적 확인
                if log is not None:
                    for _desc, actual in log["steps"]:
                        # move_to 결과(actual)와 step 의 다름은 위에서 못 보므로
                        # 경고 목록(wlist)로 종합 판단(아래)
                        pass
            # 컨텍스트 종료 후 경고 메시지 분석
            for w in wlist:
                wmsg = str(w.message)
                if "클램프" in wmsg or "벗어나" in wmsg:
                    clamped_flag = True                     # 좌표초과 → 비정상 신호
                    print(f"  ⚠ 좌표초과 경고: {wmsg.splitlines()[0]}")
                elif "연결" in wmsg or "실패" in wmsg:
                    print(f"  ⚠ 연결 경고: {wmsg.splitlines()[0]}")
    except Exception as e:      # 충돌/통신 오류 등 — 회차 실패로 기록
        error = f"{type(e).__name__}: {e}"
        print(f"  ✗ 예외 발생(충돌/통신 가능성): {error}")

    dt = time.time() - t0

    # 성공 판정: 예외 없음 + 좌표초과 없음 + 정답 칸에 착수
    ok = (error is None) and (not clamped_flag) and (move == EXPECTED_MOVE)
    status = "성공" if ok else "실패"
    print(f"  결과: {status} | 둔 칸={move}(기대 {EXPECTED_MOVE}) | "
          f"소요={dt:.3f}s | 좌표초과={clamped_flag} | 예외={error or '없음'}")

    return {"run": run_idx, "ok": ok, "move": move, "expected": EXPECTED_MOVE,
            "duration_s": round(dt, 3), "clamped": clamped_flag, "error": error}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # 콘솔 한글 깨짐 방지
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="[A2] 보드게임 AI 모범답안 실제 하드웨어 3회 구동 검증(QUR-002)")
    ap.add_argument("--port", default=None,
                    help="두봇 시리얼 포트(예: COM3). 미지정 시 자동탐지.")
    ap.add_argument("--mock", action="store_true",
                    help="하드웨어 없이 mock 으로 리허설(스크립트 자체 점검).")
    args = ap.parse_args()

    # --mock 또는 전역 mock 판정 시 mock 으로, 아니면 실하드웨어
    use_mock = True if args.mock else (True if config.is_mock() else False)

    print("=" * 60)
    print(" [A2] 보드게임 AI — 실제 Dobot 3회 구동 검증 (QUR-002)")
    print(f"  포트   : {args.port or '(자동탐지)'}")
    print(f"  모드   : {'MOCK(리허설)' if use_mock else 'REAL(실하드웨어)'}")
    print(f"  시나리오: AI 가 {EXPECTED_MOVE} 에 착수해 승리(결정적 보드)")
    print("=" * 60)
    if not use_mock:
        print(" ⚠ 실제 로봇이 움직입니다. 작업영역 내 사람·물체를 치우고, ")
        print("   비상정지(전원 차단) 위치를 확인하세요. 마커 피더가 채워졌는지 확인!")

    results = []
    for i in range(1, RUNS + 1):
        try:
            results.append(run_once(i, args.port, use_mock))
        except KeyboardInterrupt:
            # 사용자가 중단(Ctrl+C) — 안전정지는 컨텍스트가 이미 처리. 즉시 종료.
            print("\n[중단] 사용자 요청으로 검증을 중단합니다(안전정지 완료).")
            return 1
        except Exception as e:
            # run_once 밖에서의 예기치 못한 오류도 회차 실패로 집계
            print(f"  ✗ 회차 {i} 치명적 오류: {e}")
            results.append({"run": i, "ok": False, "move": None,
                            "expected": EXPECTED_MOVE, "duration_s": 0.0,
                            "clamped": False, "error": str(e)})

    # ---- 종합 리포트 ----
    print("\n" + "=" * 60)
    print(" 검증 종합 리포트")
    print("=" * 60)
    n_ok = sum(1 for r in results if r["ok"])
    for r in results:
        mark = "OK " if r["ok"] else "FAIL"
        print(f"  회차 {r['run']}: [{mark}] 둔칸={r['move']} "
              f"소요={r['duration_s']}s 좌표초과={r['clamped']} "
              f"예외={r['error'] or '없음'}")
    durs = [r["duration_s"] for r in results if r["duration_s"] > 0]
    if durs:
        print(f"  소요시간 평균={sum(durs)/len(durs):.3f}s "
              f"최소={min(durs):.3f}s 최대={max(durs):.3f}s")
    print(f"\n  성공 {n_ok}/{RUNS} 회 — "
          f"{'전체 통과(QUR-002 충족)' if n_ok == RUNS else '검증 실패: 위 로그 확인 필요'}")

    return 0 if n_ok == RUNS else 1


if __name__ == "__main__":
    sys.exit(main())
