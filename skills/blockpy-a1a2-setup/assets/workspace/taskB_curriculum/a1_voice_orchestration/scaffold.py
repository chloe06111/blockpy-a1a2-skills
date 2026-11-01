"""a1_voice_orchestration/scaffold.py — [학생 실습용 골격]

차시: A1 · 하이브리드(Advanced)
주제: "LLM 오케스트레이터 — 음성 명령 다단계 분해·실행"

★ 이 파일은 '미완성'입니다. # TODO 부분을 채우면 solution.py 와 똑같이 동작합니다.
  골격(입출력·안전가드·함수 틀)은 이미 제공되어 있어요.
  Logic-First: 먼저 '무엇을 어떤 순서로 할지'(논리)를 종이에 적은 뒤 코드로 옮기세요.

흐름:  음성(STT) → 글자  →  LLM이 단계로 분해(plan)  →  사람 검토(안전 게이트)
       →  로봇이 단계를 차례로 실행(감지→분류→픽앤플레이스→복귀)

실행(채우기 전에도 import/구조는 동작):
    CURRICULUM_FORCE_MOCK=1 python a1_voice_orchestration/scaffold.py
"""

# ── sys.path 부트스트랩 2줄 (taskB_curriculum 을 import 루트로 추가) ──────────
import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.ai_clients import STTClient, LLMClient      # 음성→텍스트, 텍스트→계획
from common.dobot_ctl import get_robot                  # 로봇 제어(mock 자동)
from common.vision import Camera, detect_colors         # 카메라 프레임 + 색 블록 검출
from common import safety                                # 안전 검사(check_move)
from common import config                                # 카메라 인덱스(CAM_TABLE) 등 전역 설정

import json   # LLM 계획(JSON) 파싱에 사용
import time   # 단계별 소요시간 측정


# ===========================================================================
# 0) 작업 좌표 사전 (이미 제공) — 색깔별 정리함 위치 (mm)
# ===========================================================================
DROP_ZONES = {
    "red":    {"x": 200, "y": -120, "z": 40},
    "green":  {"x": 240, "y":    0, "z": 40},
    "blue":   {"x": 200, "y":  120, "z": 40},
    "yellow": {"x": 280, "y":    0, "z": 40},
}
PICK_Z = 5         # 집을 때 내려가는 높이(mm)
SAFE_Z = 80        # 이동 중 안전 높이(mm)

FRAME_W, FRAME_H = 640, 480
WS_X = safety.WORKSPACE["x"]
WS_Y = safety.WORKSPACE["y"]


def pixel_to_robot(center_px):
    """카메라 중심 좌표(cx, cy) → 로봇 (x, y) 근사 변환. (이미 제공)"""
    cx, cy = center_px
    y = WS_Y[0] + (cx / FRAME_W) * (WS_Y[1] - WS_Y[0])
    x = WS_X[0] + (cy / FRAME_H) * (WS_X[1] - WS_X[0])
    return round(x, 1), round(y, 1)


# ===========================================================================
# 1) STT 단계 — 음성 파일을 텍스트로
# ===========================================================================
def listen_command(audio_path: str, stt: STTClient) -> str:
    """음성 파일을 텍스트 명령으로 변환한다.

    힌트: STTClient 에는 transcribe(audio_path) 메서드가 있습니다.
    """
    # TODO: stt.transcribe(...) 를 호출해 인식된 텍스트를 반환하세요.
    text = ""  # ← 여기를 채우세요
    return text


# ===========================================================================
# 2) LLM 오케스트레이터 — 복합 명령을 단계로 분해
# ===========================================================================
ORCHESTRATOR_SYSTEM = (
    "너는 교육용 로봇팔의 작업 오케스트레이터다. "
    "사용자의 자연어 명령을 로봇이 실행 가능한 '단계 목록'으로 분해한다. "
    "반드시 JSON 배열만 출력한다. 각 단계는 "
    '{"action": "detect|sort|pick_place|home", "target": "색상 또는 all", '
    '"desc": "사람이 읽을 한 줄 설명"} 형식이다.'
)


def _fallback_plan(command: str) -> list[dict]:
    """LLM이 JSON을 못 줄 때 쓰는 결정적 기본 계획. (이미 제공)

    표준 파이프라인: 감지 → 분류 → 픽앤플레이스 → 복귀
    """
    return [
        {"action": "detect",     "target": "all", "desc": "카메라로 블록들을 감지한다"},
        {"action": "sort",       "target": "all", "desc": "감지한 블록을 색깔별로 분류한다"},
        {"action": "pick_place", "target": "all", "desc": "색깔 칸으로 차례로 옮긴다"},
        {"action": "home",       "target": "all", "desc": "작업을 마치고 원점으로 복귀한다"},
    ]


def decompose_command(command: str, llm: LLMClient) -> list[dict]:
    """자연어 명령을 LLM으로 '다단계 계획(plan)'으로 분해한다.

    힌트(순서대로):
      1) llm.complete(messages=[{"role":"user","content": ...}], system=ORCHESTRATOR_SYSTEM)
         로 응답 문자열을 받는다.
      2) 응답에서 '[' ... ']' 사이를 잘라 json.loads 로 파싱한다.
      3) 파싱 결과가 list[dict] 이고 비어있지 않으면 그대로 반환한다.
      4) 파싱이 실패하거나 mock 응답이면 _fallback_plan(command) 를 반환한다.
         (try/except (ValueError, json.JSONDecodeError) 로 감싸세요.)
    """
    # TODO 1: llm.complete(...) 로 raw 응답 받기
    raw = ""  # ← 여기를 채우세요

    # TODO 2~3: raw 에서 JSON 배열을 추출·파싱해 유효하면 반환
    #   start = raw.index("[");  end = raw.rindex("]") + 1
    #   plan = json.loads(raw[start:end])
    #   if isinstance(plan, list) and plan and all(isinstance(s, dict) for s in plan): return plan

    # TODO 4: 위에서 반환하지 못했다면 결정적 기본 계획 사용
    return _fallback_plan(command)


# ===========================================================================
# 3) 안전 게이트 — 사람이 계획 검토 후 승인 (이미 제공)
# ===========================================================================
def review_plan(plan: list[dict], approver=None) -> bool:
    """LLM이 만든 계획을 사람이 검토·승인한다(안전 게이트, SFR-002).

    approver: None이면 자동 승인(mock). 실제 수업에선 input() 기반 함수 사용.
    """
    print("\n[안전 게이트] LLM이 제안한 실행 계획을 검토하세요:")
    for i, step in enumerate(plan, 1):
        print(f"   {i}. ({step.get('action')}) {step.get('desc', '')}")
    if approver is None:
        print("   → 자동 승인(mock/무인 모드).")
        return True
    return bool(approver(plan))


# ===========================================================================
# 4) 실행 단계들
# ===========================================================================
def step_detect(cam: Camera) -> list[dict]:
    """카메라 한 프레임에서 색 블록들을 감지한다.

    힌트: frame = cam.read();  blocks = detect_colors(frame)
    """
    # TODO: 프레임을 읽고 detect_colors 로 블록 목록을 얻어 반환하세요.
    blocks = []  # ← 여기를 채우세요
    print(f"   · 감지된 블록: {[b['color'] for b in blocks]}")
    return blocks


def step_sort(blocks: list[dict]) -> dict:
    """감지된 블록을 색깔별로 분류한다. 반환: {color: [블록,...]}

    힌트: grouped.setdefault(b['color'], []).append(b)
    """
    grouped: dict[str, list] = {}
    # TODO: blocks 를 돌며 같은 색끼리 grouped 에 모으세요.

    print("   · 분류 결과: " + ", ".join(f"{c}×{len(v)}" for c, v in grouped.items()))
    return grouped


def _safe_move(bot, x, y, z, label=""):
    """이동 직전 안전 검사 후 이동한다(위험 동작 전 safety 검사). (이미 제공)"""
    ok, msg = safety.check_move(x, y, z)         # 작업영역 검사(SFR-002)
    if not ok:
        print(f"     ⚠ 안전경고({label}): {msg.splitlines()[0]}")
    return bot.move_to(x, y, z)                  # 컨트롤러가 클램프 후 이동


def step_pick_place(bot, grouped: dict) -> int:
    """색깔별 블록을 각 색 칸으로 픽앤플레이스한다. 반환: 옮긴 개수.

    한 사이클(반드시 _safe_move 사용 + 흡착 ON/OFF):
      1) 블록 위 SAFE_Z 로 접근   2) PICK_Z 로 하강   3) bot.suck(True)
      4) SAFE_Z 로 상승          5) 칸 위 SAFE_Z 로 이동
      6) 칸 zone['z'] 로 하강     7) bot.suck(False)   8) SAFE_Z 로 상승
    """
    moved = 0
    for color, items in grouped.items():
        zone = DROP_ZONES.get(color)
        if zone is None:
            print(f"     · '{color}' 칸이 없어 건너뜁니다.")
            continue
        for b in items:
            px, py = pixel_to_robot(b["center"])  # 픽셀 → 로봇 좌표 (이미 제공)
            print(f"     · {color} 블록 집기 @ ({px}, {py})")
            # TODO: 위 1~8 사이클을 _safe_move(...) 와 bot.suck(...) 로 구현하세요.
            #       흡착을 켰으면 반드시 끄는 것(안전)을 잊지 마세요!

            moved += 1
    return moved


def step_home(bot) -> None:
    """작업을 마치고 원점으로 복귀한다.

    힌트: 안전을 위해 흡착을 먼저 끄고(bot.suck(False)) bot.home() 을 호출하세요.
    """
    # TODO: 흡착 해제 후 원점 복귀
    pass


# ===========================================================================
# 5) 오케스트레이터 본체 (이미 제공) — 단계별 순차 실행 + 진행 보고
# ===========================================================================
def execute_plan(plan: list[dict], bot, cam: Camera) -> dict:
    """승인된 계획을 단계별로 순차 실행한다(파이프라인).

    단계 간 데이터: detect → blocks → sort → grouped → pick_place
    """
    blocks: list[dict] = []
    grouped: dict = {}
    moved = 0
    t0 = time.perf_counter()

    for i, step in enumerate(plan, 1):
        action = step.get("action")
        print(f"\n[{i}/{len(plan)}] 실행: ({action}) {step.get('desc', '')}")
        if action == "detect":
            blocks = step_detect(cam)
        elif action == "sort":
            grouped = step_sort(blocks)
        elif action == "pick_place":
            if not grouped and blocks:
                grouped = step_sort(blocks)
            moved += step_pick_place(bot, grouped)
        elif action == "home":
            step_home(bot)
        else:
            print(f"   · 알 수 없는 단계 '{action}' — 건너뜁니다.")

    elapsed = time.perf_counter() - t0
    return {"steps": len(plan), "moved": moved, "elapsed": round(elapsed, 3)}


def run_voice_orchestration(audio_path: str, approver=None,
                            stt=None, llm=None, bot=None, cam=None) -> dict:
    """전체 파이프라인: 듣기 → 분해 → 검토 → 실행. (이미 제공)"""
    stt = stt or STTClient()
    llm = llm or LLMClient()
    # A1 은 책상 위 색블록을 보고 정리하므로 '책상 카메라'(config.CAM_TABLE)를 쓴다.
    cam = cam or Camera(source=config.CAM_TABLE)

    command = listen_command(audio_path, stt)
    print(f"[1] 음성 인식 결과: {command!r}")

    plan = decompose_command(command, llm)
    print(f"[2] LLM이 {len(plan)}단계로 분해했습니다.")

    if not review_plan(plan, approver):
        print("[3] 사용자가 계획을 거부했습니다. 아무 동작도 실행하지 않습니다.")
        return {"approved": False, "steps": len(plan), "moved": 0}

    if bot is not None:
        summary = execute_plan(plan, bot, cam)
    else:
        with get_robot() as owned_bot:           # 종료 시 안전정지+disconnect 보장
            summary = execute_plan(plan, owned_bot, cam)

    summary["approved"] = True
    return summary


# ===========================================================================
# 6) 자가 데모 (mock)
# ===========================================================================
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=" * 64)
    print(" A1 · LLM 오케스트레이터 (학생 실습용 골격) — mock 데모")
    print("=" * 64)
    print(" ※ # TODO 를 채우기 전에는 일부 단계가 비어 있어 블록을 옮기지 않습니다.")

    fake_audio = "voice_정리해주세요.wav"
    result = run_voice_orchestration(fake_audio)

    print("\n" + "-" * 64)
    print(f"[완료] 실행 요약: 단계 {result['steps']}개, "
          f"옮긴 블록 {result['moved']}개")
    print(" TODO 를 모두 채우면 solution.py 와 같은 결과(블록 3개 이동)가 나옵니다.")
