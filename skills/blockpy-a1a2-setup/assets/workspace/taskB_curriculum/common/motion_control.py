# -*- coding: utf-8 -*-
"""common/motion_control.py — 자연어 → 로봇 동작 계획/실행 (색 무관, 범용).

H1(자연어 제어)·A1(음성 제어)이 공유하는 "언어 → 구조화 동작 → 안전 실행" 레이어다.
색 판별(detect_colors)에 의존하지 않으며, 명령을 아래 **고정 스키마의 동작 리스트**로
바꾼 뒤 RobotController 로 순차 실행한다. (색 인식은 M1 전용이므로 여기엔 없음.)

동작 스키마(각 항목은 dict):
    {"action": "home"}
    {"action": "move_to", "x": .., "y": .., "z": .., "r": ..}       # 절대 이동(mm/deg)
    {"action": "move_relative", "dx": .., "dy": .., "dz": .., "dr": ..}  # 상대 이동
    {"action": "suck", "on": bool}     # 흡착 on/off
    {"action": "grip", "on": bool}     # 그리퍼 close/open
    {"action": "speed", "velocity": .., "acceleration": ..}  # (지원 시) 속도%
    {"action": "vision_pick", "target": "<명사구>"}    # 카메라에 보이는 물체 집기(치환 필요)
    {"action": "vision_place", "target": "<명사구>"}   # 보이는 위치 옆/위에 내려놓기(치환 필요)
    {"action": "unknown", "reason": ".."}

vision_pick/vision_place 는 그대로 실행할 수 없는 **지연 액션**이다 —
resolve_vision_actions() 가 카메라 프레임(눈: GroundingClient)과 4점 캘리브레이션
(common.calibration)으로 좌표 액션 시퀀스(move_to→move_to→suck→move_to)로 치환한다.
치환 단계가 하나라도 확신이 없으면("모르면 멈춘다") 전체를 중단한다.

해석 경로:
  - 실제(non-mock) LLM(예: MiniMax) 주입 시 → LLM 이 JSON 배열 출력 → 견고 파싱(+1회 재질문).
  - 아니면(기본) → 로컬 규칙 파서(키/인터넷 불필요, 다단계 명령 분해).
방향 규약: 오른쪽 +Y / 왼쪽 -Y / 앞 +X / 뒤 -X / 위 +Z / 아래 -Z.
"""
from __future__ import annotations

import json
import re
from typing import Any

from common import safety

# config: VISION_Z_HOVER/VISION_Z_PICK/EFFECTOR 상수 위임. 없어도 기본값으로 동작(방어적).
try:
    from common import config as _config
except Exception:  # pragma: no cover - config 미존재/단독 실행 시
    _config = None  # type: ignore[assignment]


def _check_move(x: float, y: float, z: float) -> tuple[bool, str]:
    """safety.check_move 위임(없으면 항상 안전으로 폴백 — import는 안 죽는다)."""
    try:
        from common.safety import check_move
        ok, msg = check_move(x, y, z)
        return bool(ok), str(msg)
    except Exception:  # pragma: no cover - safety 미존재 시 방어
        return True, "안전(safety 미탑재)"

# 로봇 좌표계 방향 → 상대이동 축·부호(mm 단위 계수).
_DIRECTION_AXIS = {
    "right": ("dy", +1.0), "left": ("dy", -1.0),
    "forward": ("dx", +1.0), "back": ("dx", -1.0),
    "up": ("dz", +1.0), "down": ("dz", -1.0),
}
_DIRECTION_WORDS = {
    "right": ("오른", "우측", "right"), "left": ("왼", "좌측", "left"),
    "forward": ("앞", "전진", "forward"), "back": ("뒤", "후진", "back"),
    "up": ("위로", "위", "올려", "up"), "down": ("아래", "내려", "down"),
}
_HOME_WORDS = ("홈", "원점", "처음 위치", "처음위치", "home")
_STOP_WORDS = ("정지", "멈춰", "멈춤", "스톱", "stop")
_GRIP_WORDS = ("그리퍼", "집게")
_ON_WORDS = ("켜", "집", "붙", "빨", "닫", "쥐", "on")
_OFF_WORDS = ("놓", "떼", "풀", "열", "벌", "꺼", "끄", "해제", "off")
# 복합 명령을 단계로 나누는 접속어.
_STEP_SPLIT = re.compile(
    r"\s*(?:그리고|그다음에?|그 다음에?|그 ?후에?|후에|한 뒤에?|하고 나서|하고|갔다가|갔다|가서|"
    r"간 다음|다음에?|,|→|그런 다음)\s*"
)
_CM = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:cm|센티미터|센치|센티)", re.IGNORECASE)
_MM = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:mm|밀리미터|밀리)", re.IGNORECASE)

# 비전 지칭 명령(H1 VLA §2c): "<명사구>(을|를)? 집어" / "<명사구>(에|위에|옆에) 놔".
#   맨 동사("집어"/"놓아", 명사구 없음)는 기존대로 흡착 on/off 로 남긴다.
_VISION_PICK = re.compile(r"^(.+?)\s*(?:을|를)\s*집|^(.+?)\s+집")
_VISION_PLACE = re.compile(r"^(.+?)\s*(?:위에|옆에|에)\s*(?:내려\s*)?(?:놔|놓아|놓고|놓기)")
# 방향/지시어만 남은 "명사구"는 비전 타깃이 아니다("위에 놔" → 비전 아님).
_VISION_TARGET_STOPWORDS = {
    "위", "아래", "앞", "뒤", "옆", "왼쪽", "오른쪽", "여기", "거기", "저기",
    "위로", "아래로", "제자리", "바닥",
}

MOTION_SYSTEM_PROMPT = (
    "너는 로봇팔 동작 계획기다. 사용자의 자연어 명령을 아래 스키마의 JSON 배열로만 출력한다. "
    "설명·마크다운 없이 JSON 배열만 출력하라. 복합 명령이면 순서대로 여러 동작을 배열에 담아라.\n"
    "가능한 동작:\n"
    '  {"action":"home"}\n'
    '  {"action":"move_to","x":220,"y":0,"z":40,"r":0}\n'
    '  {"action":"move_relative","dx":0,"dy":0,"dz":20,"dr":0}\n'
    '  {"action":"suck","on":true}   {"action":"grip","on":true}\n'
    '  {"action":"pump_off"}   # 공압 펌프 완전 정지(흡착만 해제가 아니라 펌프 회로 OFF)\n'
    '  {"action":"speed","velocity":50,"acceleration":50}\n'
    '  {"action":"vision_pick","target":"빨간 블록"}    # 카메라에 보이는 물체 집기\n'
    '  {"action":"vision_place","target":"컵"}          # 보이는 위치 옆/위에 내려놓기\n'
    "방향 규약: 오른쪽=+Y, 왼쪽=-Y, 앞=+X, 뒤=-X, 위=+Z, 아래=-Z (mm). "
    "카메라에 보이는 물체를 지칭하는 명령은 vision_pick/vision_place 로 출력하고 "
    "target 에 한국어 명사구를 그대로 담아라. "
    '예) "보이는 빨간 블록 집어" → [{"action":"vision_pick","target":"빨간 블록"}] · '
    '"지우개를 컵 옆에 놔" → [{"action":"vision_pick","target":"지우개"},'
    '{"action":"vision_place","target":"컵"}]. '
    "이해할 수 없으면 [{\"action\":\"unknown\",\"reason\":\"...\"}]."
)

__all__ = [
    "MOTION_SYSTEM_PROMPT", "normalize_action", "parse_actions_json",
    "parse_motion_local", "plan_motion", "execute_motion",
    "resolve_vision_actions",
]


# --------------------------------------------------------------------------- #
# 검증/정규화
# --------------------------------------------------------------------------- #
def _num(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "on", "yes", "y")
    return False


def normalize_action(obj: Any) -> dict[str, Any]:
    """원시 dict 를 검증된 동작 dict 로. 실패 시 {'action':'unknown',...}."""
    if not isinstance(obj, dict) or not isinstance(obj.get("action"), str):
        return {"action": "unknown", "reason": "형식 오류"}
    a = obj["action"].strip().lower()
    if a == "home":
        return {"action": "home"}
    if a == "pump_off":
        return {"action": "pump_off"}
    if a == "move_to":
        return {"action": "move_to", "x": _num(obj.get("x"), 0.0), "y": _num(obj.get("y"), 0.0),
                "z": _num(obj.get("z"), 0.0), "r": _num(obj.get("r"), 0.0)}
    if a == "move_relative":
        return {"action": "move_relative", "dx": _num(obj.get("dx"), 0.0),
                "dy": _num(obj.get("dy"), 0.0), "dz": _num(obj.get("dz"), 0.0),
                "dr": _num(obj.get("dr"), 0.0)}
    if a in ("suck", "grip"):
        return {"action": a, "on": _bool(obj.get("on"))}
    if a == "speed":
        return {"action": "speed", "velocity": _num(obj.get("velocity"), 100.0),
                "acceleration": _num(obj.get("acceleration"), 100.0)}
    if a in ("vision_pick", "vision_place"):
        target = str(obj.get("target") or "").strip()
        if not target:  # target 이 비면 unknown 처리(H1 VLA §2c)
            return {"action": "unknown", "reason": f"{a}: target 없음"}
        return {"action": a, "target": target}
    if a == "unknown":
        return {"action": "unknown", "reason": str(obj.get("reason", "unknown"))}
    return {"action": "unknown", "reason": f"미지원 action: {a}"}


def parse_actions_json(text: str) -> list[dict[str, Any]]:
    """LLM 원문 → 검증된 동작 리스트. 예외 없이, 실패 시 []."""
    if not text:
        return []
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    cand = m.group(1) if m else text
    s, e = cand.find("["), cand.rfind("]")
    if s == -1 or e == -1 or e < s:
        return []
    try:
        data = json.loads(cand[s:e + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = [normalize_action(it) for it in data]
    return [a for a in out if a["action"] != "unknown"]


# --------------------------------------------------------------------------- #
# 로컬 규칙 파서(무모델·무API, 다단계)
# --------------------------------------------------------------------------- #
def _distance_mm(text: str, default: float) -> float:
    m = _CM.search(text)
    if m:
        return float(m.group(1)) * 10.0
    m = _MM.search(text)
    if m:
        return float(m.group(1))
    m = re.search(r"(-?\d+(?:\.\d+)?)", text)   # 단위 없는 숫자는 mm 로 간주
    return float(m.group(1)) if m else default


def _parse_one(step: str) -> dict[str, Any] | None:
    c = step.strip()
    if not c:
        return None
    if any(w in c for w in _HOME_WORDS):
        return {"action": "home"}
    # 펌프 완전 정지: '펌프' + 끄기/정지 → 흡착 해제(suck False)가 아니라 pump_off.
    #   (suck(False) 는 진공만 풀 뿐 펌프 회로는 계속 돌기 때문)
    if "펌프" in c and (any(w in c for w in _OFF_WORDS) or "정지" in c):
        return {"action": "pump_off"}
    # 흡착/그리퍼. on/off 판정: 끄기 동사만 있으면 off, 아니면 on(맨 '흡착'도 on).
    is_grip = any(w in c for w in _GRIP_WORDS)
    has_suck = "흡착" in c or "석션" in c
    on = any(w in c for w in _ON_WORDS)
    off = any(w in c for w in _OFF_WORDS)
    if has_suck or is_grip:
        name = "grip" if is_grip else "suck"
        return {"action": name, "on": not (off and not on)}
    # 카메라에 보이는 물체 지칭(H1 VLA): "<명사구> 집어" → vision_pick,
    #   "<명사구>(에|위에|옆에) 놔" → vision_place. 맨 동사는 아래 흡착 규칙으로.
    m = _VISION_PLACE.search(c)
    if m:
        target = _vision_target(m.group(1))
        if target:
            return {"action": "vision_place", "target": target}
    m = _VISION_PICK.search(c)
    if m:
        target = _vision_target(m.group(1) or m.group(2) or "")
        if target:
            return {"action": "vision_pick", "target": target}
    if (on or off) and not _has_direction(c):   # 맨 동사 "집어"/"놓아" → 흡착
        return {"action": "suck", "on": not (off and not on)}
    # 속도
    if "속도" in c or "빠르" in c or "느리" in c:
        v = 100.0 if "빠르" in c else (30.0 if "느리" in c else 0.0)
        m = re.search(r"(\d+(?:\.\d+)?)", c)
        if m:
            v = float(m.group(1))
        if v:
            return {"action": "speed", "velocity": v, "acceleration": v}
    # 방향 상대 이동
    direction = _first_direction(c)
    if direction is not None:
        axis, sign = _DIRECTION_AXIS[direction]
        dist = _distance_mm(c, 20.0)
        act = {"action": "move_relative", "dx": 0.0, "dy": 0.0, "dz": 0.0, "dr": 0.0}
        act[axis] = sign * dist
        return act
    return {"action": "unknown", "reason": f"해석 불가: {step!r}"}


def _vision_target(raw: str) -> str:
    """비전 명령에서 추출한 명사구를 다듬는다. 빈 문자열이면 '비전 아님' 신호.

    - 접두 수식("보이는", "카메라에 보이는")은 지운다.
    - "지우개를 컵" 처럼 목적어 조사(을/를) 뒤에 참조물이 이어지면 그쪽만 남긴다
      (vision_place 의 기준 물체 추출: "지우개를 컵 옆에 놔" → "컵").
    - 방향/지시어만 남으면("위", "옆" 등) 비전 타깃이 아니므로 "" 를 돌려준다.
    """
    t = (raw or "").strip()
    t = re.sub(r"^(?:카메라에\s*)?보이는\s*", "", t)
    m = re.search(r"(?:을|를)\s+(\S.*)$", t)
    if m:
        t = m.group(1)
    t = t.strip()
    return "" if t in _VISION_TARGET_STOPWORDS else t


def _has_direction(c: str) -> bool:
    return _first_direction(c) is not None


def _first_direction(c: str) -> str | None:
    for d, words in _DIRECTION_WORDS.items():
        if any(w in c for w in words):
            return d
    return None


def parse_motion_local(command: str) -> list[dict[str, Any]]:
    """자연어 명령을 규칙으로 동작 리스트로 분해(다단계). 색 무관, 무API."""
    steps = [s for s in _STEP_SPLIT.split(command or "") if s.strip()]
    if not steps:
        return []
    out: list[dict[str, Any]] = []
    for s in steps:
        act = _parse_one(s)
        if act is not None and act["action"] != "unknown":
            out.append(act)
    return out


# --------------------------------------------------------------------------- #
# 비전 액션 치환(H1 VLA §2c) — vision_pick/vision_place → 좌표 액션 시퀀스
# --------------------------------------------------------------------------- #
_VISION_ACTIONS = ("vision_pick", "vision_place")


def _vision_z(name: str, default: float) -> float:
    """config 의 VISION_Z_* 상수(mm)를 읽는다(없으면 default). # 실측 필요(config 참조)"""
    try:
        return float(getattr(_config, name))
    except (TypeError, ValueError, AttributeError):
        return default


def resolve_vision_actions(actions: list[dict[str, Any]], frame: Any,
                           grounding: Any, calib: Any,
                           ) -> tuple[list[dict[str, Any]], list[str]]:
    """vision_pick/vision_place 를 카메라(눈)+캘리브레이션으로 좌표 액션에 치환한다.

    파라미터
    --------
    actions   : plan_motion 이 만든 동작 리스트(비전 액션 포함 가능).
    frame     : 카메라 프레임(np.ndarray HxWx3) 또는 None.
    grounding : GroundingClient/MockGrounding 규약 — point(frame, target) → (px,py)|None.
    calib     : common.calibration.Calibration 규약 — is_solved, pixel_to_robot(px,py).

    "모르면 멈춘다" — 아래 4중 중단 경로에서는 ([], [사유]) 를 반환해
    상위(run_visual_command/GUI)가 **아무 동작도 실행하지 않게** 한다:
      1) frame 이 None            → ["카메라 프레임 없음"]
      2) calib 미해결(is_solved X) → ["캘리브레이션 필요"]
      3) grounding.point 가 None  → ["'{target}' 못 찾음"]
      4) 변환 좌표가 작업영역 밖   → ["... 작업영역 밖 — 캘리브레이션을 다시 하세요"]
         (execute_motion 의 clamp 가 '조용히' 경계로 끌어당겨 엉뚱한 곳을 집는 것 방지)

    vision_* 가 없으면 (actions 그대로, []) 를 반환한다(비전 무관 경로 무변화).
    치환 시퀀스: move_to(hover) → move_to(pick 높이) → 집기(grip|suck) → move_to(hover).
    집기 명령은 config.EFFECTOR("gripper"→grip / "suction"→suck)에 맞춰 생성한다.

    반환: (치환 완료 액션 리스트, GUI/콘솔 표시용 메시지 리스트).
    """
    if not any(a.get("action") in _VISION_ACTIONS for a in actions):
        return list(actions), []
    if frame is None:
        return [], ["카메라 프레임 없음"]
    if not bool(getattr(calib, "is_solved", False)):
        return [], ["캘리브레이션 필요"]

    z_hover = _vision_z("VISION_Z_HOVER", 40.0)   # 접근(호버) 높이  # 실측 필요
    z_pick = _vision_z("VISION_Z_PICK", -40.0)    # 집기 하강 높이   # 실측 필요
    # 엔드이펙터에 맞는 집기 명령: 그리퍼면 grip, 흡착컵이면 suck (RobotController.grasp 와 동일 분기).
    grasp_action = "suck" if str(getattr(_config, "EFFECTOR", "gripper")) == "suction" else "grip"
    resolved: list[dict[str, Any]] = []
    messages: list[str] = []
    for act in actions:
        name = act.get("action")
        if name not in _VISION_ACTIONS:
            resolved.append(dict(act))
            continue
        target = str(act.get("target", ""))
        xy = grounding.point(frame, target)       # 눈: 자연어 → 픽셀 좌표
        if xy is None:
            return [], [f"'{target}' 못 찾음"]
        px, py = float(xy[0]), float(xy[1])
        try:
            rx, ry = calib.pixel_to_robot(px, py)  # 픽셀 → 로봇 작업평면 mm
        except Exception as e:                     # 특이점 등 — 실행 없이 중단
            return [], [f"좌표 변환 실패: {e}"]
        rx, ry = float(rx), float(ry)
        # 4번째 중단: 변환 좌표가 작업영역 밖이면 clamp 로 실행하지 말고 전체 중단.
        ok, why = _check_move(rx, ry, z_pick)
        if not ok:
            return [], [f"'{target}' 좌표({rx:.0f}, {ry:.0f})mm 가 작업영역 밖 "
                        f"— 캘리브레이션을 다시 하세요 ({why.splitlines()[0]})"]
        on = name == "vision_pick"
        messages.append(f"[{name}] '{target}' → 픽셀({px:.0f}, {py:.0f}) "
                        f"→ 로봇({rx:.1f}, {ry:.1f})mm")
        resolved.extend([
            {"action": "move_to", "x": rx, "y": ry, "z": z_hover, "r": 0.0},
            {"action": "move_to", "x": rx, "y": ry, "z": z_pick, "r": 0.0},
            {"action": grasp_action, "on": on},
            {"action": "move_to", "x": rx, "y": ry, "z": z_hover, "r": 0.0},
        ])
    return resolved, messages


# --------------------------------------------------------------------------- #
# 계획(LLM 우선, 로컬 폴백) + 실행
# --------------------------------------------------------------------------- #
def _is_real_llm(llm: Any) -> bool:
    return llm is not None and not getattr(llm, "mock", False) and callable(
        getattr(llm, "complete", None)
    )


def plan_motion(command: str, llm: Any = None) -> tuple[list[dict[str, Any]], str]:
    """명령 → (동작 리스트, 원문). 실제 LLM 있으면 그걸로, 없으면 로컬 규칙."""
    if _is_real_llm(llm):
        raw = llm.complete(
            messages=[{"role": "user", "content": command}], system=MOTION_SYSTEM_PROMPT
        )
        actions = parse_actions_json(raw)
        if not actions:  # 1회 재질문(self-repair)
            raw = llm.complete(
                messages=[{"role": "user",
                           "content": "이전 출력이 올바른 JSON 배열이 아니었다. JSON 배열만 다시 출력하라.\n" + command}],
                system=MOTION_SYSTEM_PROMPT,
            )
            actions = parse_actions_json(raw)
        return actions, raw
    actions = parse_motion_local(command)
    return actions, json.dumps(actions, ensure_ascii=False)


def execute_motion(actions: list[dict[str, Any]], bot: Any) -> list[str]:
    """검증된 동작 리스트를 안전검사 후 순서대로 실행. 반환: 단계별 로그."""
    logs: list[str] = []
    for act in actions:
        a = act["action"]
        try:
            if a == "home":
                bot.home()
                logs.append("[home] 원점 복귀")
            elif a == "move_to":
                cx, cy, cz, cr = safety.clamp_move(act["x"], act["y"], act["z"], act["r"])
                bot.move_to(cx, cy, cz, cr)
                logs.append(f"[move_to] ({cx},{cy},{cz},r={cr})")
            elif a == "move_relative":
                p = bot.get_pose()
                tx, ty, tz = p["x"] + act["dx"], p["y"] + act["dy"], p["z"] + act["dz"]
                tr = p.get("r", 0.0) + act["dr"]
                cx, cy, cz, cr = safety.clamp_move(tx, ty, tz, tr)
                bot.move_to(cx, cy, cz, cr)
                logs.append(f"[move_relative] → ({cx},{cy},{cz})")
            elif a in ("suck", "grip"):
                getattr(bot, a)(act["on"])
                logs.append(f"[{a}] {'ON' if act['on'] else 'OFF'}")
            elif a == "pump_off":
                fn = getattr(bot, "pump_off", None)
                if callable(fn):
                    fn()
                    logs.append("[pump_off] 공압 펌프 완전 정지(isCtrlEnabled=0)")
                else:  # 폴백: 최소한 흡착 해제
                    getattr(bot, "suck", lambda _v: None)(False)
                    logs.append("[pump_off] pump_off 미지원 — 흡착 해제로 대체")
            elif a == "speed":
                fn = getattr(bot, "speed", None)
                if callable(fn):
                    fn(act["velocity"], act["acceleration"])
                    logs.append(f"[speed] v={act['velocity']} a={act['acceleration']}")
                else:
                    logs.append("[speed] 이 로봇은 속도 설정 미지원 — 생략")
            else:
                logs.append(f"[건너뜀] 알 수 없는 동작: {a}")
        except Exception as e:  # 실행 예외는 로그로만(파이프라인 중단 방지)
            logs.append(f"[오류] {a}: {e}")
    return logs
