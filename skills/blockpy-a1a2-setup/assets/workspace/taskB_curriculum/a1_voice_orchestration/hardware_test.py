"""a1_voice_orchestration/hardware_test.py — [실하드웨어 검증 · turnkey]

차시 A1(LLM 오케스트레이터) 모범답안(solution.py)을 **실제 Dobot 라이트로 3회 구동**해
재현성/안정성을 검증하는 복귀-후-실행용 스크립트다. (QUR-002: 3회 반복 구동)

무엇을 하나
----------
- solution.run_voice_orchestration 파이프라인(음성→분해→검토→실행)을 3회 실행한다.
- 각 회차의 결과(옮긴 블록 수)·소요시간을 로그로 남긴다.
- 매 회차 종료 시 흡착/그리퍼를 끄는 안전정지를 보장한다(with + 명시 호출).
- 실행 중 모든 이동을 가로채(check_move) 충돌/좌표초과 위험을 검출·집계한다.

사용법
------
  실제 로봇:   python a1_voice_orchestration/hardware_test.py --port COM3
  mock 점검:   python a1_voice_orchestration/hardware_test.py --mock
  회차 변경:   python a1_voice_orchestration/hardware_test.py --port COM3 --runs 3

안전 (SFR-002)
--------------
- --port 로 실제 포트를 줘도, 이동 직전 safety.check_move 로 작업영역을 검사한다.
- 좌표초과/Z과다하강이 1건이라도 검출되면 해당 회차를 '위험'으로 표시한다.
- 어떤 예외가 나도 finally 에서 안전정지(흡착 OFF)+연결 해제를 시도한다.
"""

# ── sys.path 부트스트랩 2줄 (taskB_curriculum 을 import 루트로 추가) ──────────
import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.dobot_ctl import get_robot                  # 로봇 제어(실/mock)
# (색·카메라 없음: A1 은 동작 오케스트레이션 전용)
from common import safety                                # 안전 검사
from common import config                                # 카메라 인덱스(CAM_TABLE) 등 전역 설정
import solution                                          # 검증 대상 모범답안(같은 폴더)

import argparse   # --port / --runs / --mock 인자 파싱
import time       # 회차별 소요시간 측정
import traceback  # 예외 발생 시 상세 로그


# ===========================================================================
# 1) 안전 감시 래퍼 — RobotController.move_to 를 감싸 충돌/좌표초과를 집계
# ===========================================================================
class SafetyMonitor:
    """로봇의 move_to 호출을 가로채 위험(좌표초과·Z과다하강)을 검출·집계한다.

    RobotController 인스턴스의 move_to 를 런타임에 교체(monkey-patch)해서,
    실제 이동 전에 safety.check_move 로 한 번 더 검사하고 위반을 센다.
    """

    def __init__(self, bot):
        self.bot = bot
        self._orig_move = bot.move_to            # 원래 move_to 보관
        self.violations: list[str] = []          # 검출된 위험 메시지 목록
        self.move_count = 0                      # 총 이동 횟수

    def install(self):
        """감시 래퍼를 설치한다."""
        def guarded(x, y, z, r=0.0, wait=True):
            self.move_count += 1                 # 이동 횟수 집계
            ok, msg = safety.check_move(x, y, z, r)  # 작업영역 검사
            if not ok:
                # 좌표초과/Z과다하강 등 위험 — 메시지 첫 줄을 기록
                self.violations.append(f"({x},{y},{z},r={r}) {msg.splitlines()[0]}")
            return self._orig_move(x, y, z, r, wait=wait)  # 실제 이동(클램프됨)
        self.bot.move_to = guarded               # 메서드 교체
        return self

    def remove(self):
        """원래 move_to 로 복원한다."""
        self.bot.move_to = self._orig_move


# ===========================================================================
# 2) 한 회차 실행 — 연결→감시설치→파이프라인→안전정지(보장)
# ===========================================================================
def run_once(run_idx: int, port, mock: bool) -> dict:
    """모범답안 파이프라인을 1회 실행하고 결과 dict 를 반환한다.

    반환: {run, ok, moved, steps, elapsed, moves, violations, error}
    """
    print(f"\n{'='*64}\n[회차 {run_idx}] 시작 (port={port or '자동'} / mock={mock})\n{'='*64}")
    result = {"run": run_idx, "ok": False, "moved": 0, "steps": 0,
              "elapsed": 0.0, "moves": 0, "violations": [], "error": None}
    bot = get_robot(port=port, mock=mock)        # 컨트롤러 생성(연결은 with에서)
    monitor = None
    t0 = time.perf_counter()
    try:
        with bot:                                # 진입 시 연결, 종료 시 안전정지+해제
            monitor = SafetyMonitor(bot).install()  # 이동 감시 설치
            # 가짜 음성 경로(mock STT는 캔드 응답). 실모드에서도 파이프라인 흐름은 동일.
            fake_audio = "voice_command.wav"
            # 모범답안 실행: 음성→분해→검토→실행 (색·카메라 없음)
            summary = solution.run_voice_orchestration(fake_audio, approver=None, bot=bot)
            result["steps"] = len(summary.get("plan", []))
        # with 정상 종료 = 안전정지(흡착 OFF)+disconnect 완료
        result["ok"] = True
    except Exception as e:                        # 어떤 오류도 회차를 막지 않게 흡수
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"[회차 {run_idx}] 예외 발생: {result['error']}")
        traceback.print_exc()
    finally:
        # 이중 안전: with 가 처리하지만, 혹시 모를 경우를 대비해 안전정지 재시도
        try:
            bot._safe_stop()
        except Exception:
            pass
        if monitor is not None:
            result["moves"] = monitor.move_count
            result["violations"] = monitor.violations
    result["elapsed"] = round(time.perf_counter() - t0, 3)

    # 회차 요약 출력
    status = "성공" if result["ok"] else "실패"
    risk = f"위험 {len(result['violations'])}건" if result["violations"] else "위험 0건"
    print(f"\n[회차 {run_idx}] {status} | 동작 {result['steps']}단계 | "
          f"이동 {result['moves']}회 | {risk} | {result['elapsed']}초")
    for v in result["violations"]:
        print(f"    ⚠ 좌표초과/충돌위험: {v}")
    return result


# ===========================================================================
# 3) 메인 — 인자 파싱, N회 반복, 최종 집계
# ===========================================================================
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="A1 LLM 오케스트레이터 모범답안 실하드웨어 3회 구동 검증 (QUR-002)")
    parser.add_argument("--port", default=None,
                        help="Dobot 시리얼 포트 (예: COM3). 미지정 시 자동탐지.")
    parser.add_argument("--runs", type=int, default=3,
                        help="구동 횟수 (기본 3, QUR-002).")
    parser.add_argument("--mock", action="store_true",
                        help="강제 mock 모드(하드웨어 없이 스크립트 자체 점검).")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # 한글 콘솔 깨짐 방지
    except Exception:
        pass

    # --mock 미지정 + --port 미지정이면 mock=None(자동판정: 하드웨어 없으면 mock)
    mock = True if args.mock else None

    print("#" * 64)
    print(f"# A1 모범답안 실하드웨어 검증 — {args.runs}회 구동 (QUR-002)")
    print(f"# port={args.port or '자동탐지'} / mock={'강제' if args.mock else '자동판정'}")
    print("#" * 64)

    results = []
    for i in range(1, args.runs + 1):
        results.append(run_once(i, args.port, mock))  # 회차별 실행

    # ── 최종 집계 ──────────────────────────────────────────────────────────
    print(f"\n{'#'*64}\n# 최종 집계\n{'#'*64}")
    ok_count = sum(1 for r in results if r["ok"])
    total_violations = sum(len(r["violations"]) for r in results)
    print(f"{'회차':<6}{'상태':<8}{'동작':<6}{'이동':<6}{'위험':<6}{'소요(초)':<10}")
    for r in results:
        st = "성공" if r["ok"] else "실패"
        print(f"{r['run']:<6}{st:<8}{r['steps']:<6}{r['moves']:<6}"
              f"{len(r['violations']):<6}{r['elapsed']:<10}")
    print("-" * 48)
    print(f"성공 {ok_count}/{args.runs} 회 | 총 좌표초과/충돌위험 {total_violations} 건")

    # 종료코드: 모든 회차 성공 + 위험 0건이면 0(통과), 아니면 1(점검 필요)
    passed = (ok_count == args.runs) and (total_violations == 0)
    print("결과:", "통과 ✅" if passed else "점검 필요 ⚠")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
