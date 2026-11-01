"""common/safety.py — SFR-002 안전필터 (학생용 두봇 라이트 교육 플랫폼).

목적
----
초·중·고 학생이 작성한 로봇 제어 코드와 실시간 좌표 명령이
로봇팔(또는 사람)을 다치게 하지 않도록 "한 번 더" 걸러 주는 안전 계층.

세 가지 역할
-------------
1) check_move(x, y, z, r)  : 한 점이 작업영역(WORKSPACE) 안인지 검사 → (안전여부, 한국어메시지)
2) clamp_move(x, y, z, r)  : 작업영역을 벗어난 좌표를 경계값으로 "끌어당겨" 보정
3) scan_code(source)       : 학생 코드 문자열을 정규식+AST로 정적 분석 →
                             위험 패턴([{line, severity, message}]) 목록 반환
                             (Z 과다 하강, 좌표/관절 범위 초과, while True 무한루프+정지없음,
                              큐 미정지, 흡착/그리퍼 미해제 등)

설계 원칙
---------
- WORKSPACE 는 common/config.py 에서 import 한다(단일 출처). config.py 가 아직
  없거나 import 실패해도 동작하도록 try/except 로 감싸 CONTRACTS.md 의
  기본값으로 자동 폴백한다(하드웨어·키 없이 import/실행 보장).
- AST 파싱이 SyntaxError 로 실패하면(학생 코드가 아직 미완성) 정규식 결과만 반환한다.
- 모든 경고문은 학생이 바로 이해할 수 있는 친절한 한국어로 작성한다.

사용법
------
    from common.safety import check_move, clamp_move, scan_code

    ok, msg = check_move(200, 0, 50)          # (True, "안전")
    x, y, z, r = clamp_move(500, 0, -200)     # 경계값으로 보정
    for w in scan_code(open("student.py").read()):
        print(w["line"], w["severity"], w["message"])

직접 실행(자가 데모, mock):
    python -m common.safety        # 또는  python common/safety.py
"""

from __future__ import annotations

import ast       # AST 기반 코드 분석(무한루프/큐 미정지 등 구조적 패턴 탐지)
import re        # 정규식 기반 1차 스캔(좌표/관절 숫자 추출 등)

# ---------------------------------------------------------------------------
# WORKSPACE 가져오기 — config 단일 출처, 실패 시 CONTRACTS.md 기본값으로 폴백
# ---------------------------------------------------------------------------
try:
    # 정상 경로: 패키지 설치/sys.path 가 taskB_curriculum 인 경우
    from common.config import WORKSPACE  # type: ignore
except Exception:  # pragma: no cover - import 실패는 폴백으로 흡수
    try:
        # 상대 import 폴백(같은 패키지 내부에서 호출될 때)
        from .config import WORKSPACE  # type: ignore
    except Exception:
        # 최종 폴백: config.py 가 아직 없어도 import/실행이 되도록 기본값 사용
        # (값은 CONTRACTS.md 의 WORKSPACE 와 동일하게 유지할 것)
        WORKSPACE = {
            "x": (180, 320),    # 전후(mm)
            "y": (-150, 150),   # 좌우(mm)
            "z": (-60, 150),    # 상하(mm) — z 하한(-60)보다 더 내려가면 책상/지그 충돌 위험
            "r": (-150, 150),   # 엔드이펙터 회전(deg)
        }

# 관절(Joint) 각도 보수적 한계(deg). config 에는 없으므로 여기서 정의.
# 학생 코드가 j1~j4 또는 joint 값을 직접 다룰 때 범위 초과를 경고하는 데 쓴다.
JOINT_LIMITS = {
    "j1": (-90, 90),
    "j2": (0, 85),
    "j3": (-10, 90),
    "j4": (-150, 150),
}

# 심각도 단계 — 학생/검수자가 우선순위를 빠르게 파악하도록 3단계로 통일
SEV_CRITICAL = "critical"   # 즉시 충돌·고장 위험 (실행 금지 권장)
SEV_WARNING = "warning"     # 위험 가능성 (확인 후 실행)
SEV_INFO = "info"           # 권장사항 (안전 습관)


# ===========================================================================
# 1) 이동 좌표 검사 / 보정
# ===========================================================================
def check_move(x, y, z, r=0.0):
    """좌표 한 점이 작업영역(WORKSPACE) 안에 있는지 검사한다.

    반환: (bool 안전여부, str 한국어 메시지)
    - 안전하면 (True, "안전")
    - 벗어나면 (False, "어느 축이 어떻게 벗어났는지" 설명)
    """
    problems = []  # 위반 사항을 모아 한 번에 안내(학생이 여러 축을 동시에 고치도록)

    # 각 축을 (값, 라벨, 단위)로 묶어 동일한 로직으로 검사 → 코드 중복 제거
    for value, key, unit, label in (
        (x, "x", "mm", "X(전후)"),
        (y, "y", "mm", "Y(좌우)"),
        (z, "z", "mm", "Z(상하)"),
        (r, "r", "deg", "R(회전)"),
    ):
        lo, hi = WORKSPACE[key]          # 해당 축의 (하한, 상한)
        if value < lo:                   # 하한보다 작음
            extra = " ⚠ 너무 깊게 내려가 책상/물체와 충돌할 수 있어요." if key == "z" else ""
            problems.append(
                f"{label} 값 {value}{unit} 이(가) 최소 {lo}{unit} 보다 작습니다.{extra}"
            )
        elif value > hi:                 # 상한보다 큼
            problems.append(
                f"{label} 값 {value}{unit} 이(가) 최대 {hi}{unit} 을(를) 넘었습니다."
            )

    if problems:
        # 여러 위반을 줄바꿈으로 묶어 친절하게 안내
        return False, "작업영역을 벗어났습니다:\n  - " + "\n  - ".join(problems)
    return True, "안전"


def clamp_move(x, y, z, r=0.0):
    """작업영역을 벗어난 좌표를 경계값으로 끌어당겨 보정한다.

    로봇이 명령을 거부하는 대신 "가장 가까운 안전한 점"으로 옮겨 주는 용도.
    반환: (x, y, z, r) — 모두 WORKSPACE 범위 안으로 보정된 float 튜플
    """
    def _clamp(value, key):
        lo, hi = WORKSPACE[key]
        # max(lo, min(value, hi)) : 하한과 상한 사이로 가둔다(클램프)
        return float(max(lo, min(float(value), hi)))

    return (_clamp(x, "x"), _clamp(y, "y"), _clamp(z, "z"), _clamp(r, "r"))


# ===========================================================================
# 2) 코드 정적 분석 (정규식 + AST)
# ===========================================================================
def scan_code(source: str):
    """학생 코드 문자열을 분석해 위험 패턴 목록을 반환한다.

    반환: list[dict] — 각 항목 {"line": int, "severity": str, "message": str}
                       (line 은 1부터, 줄을 특정할 수 없으면 0)

    탐지 항목:
      - Z 과다 하강            : z 가 WORKSPACE['z'] 하한보다 낮은 이동 명령
      - 좌표/관절 범위 초과     : move_to / SetPTPCmd 좌표, joint 각도 범위 밖
      - while True 무한루프     : 내부에 break/return/정지 호출이 없는 경우
      - 큐 미정지              : start_exec 만 있고 stop_exec 가 없음
      - 엔드이펙터 미해제       : suck(True)/grip(True) 후 해제(False) 없음
      - 안전 검사 누락(info)    : 이동 명령은 있는데 check_move/clamp_move 호출이 전혀 없음
    """
    findings: list[dict] = []  # 결과 누적
    if not source or not source.strip():
        return findings

    lines = source.splitlines()

    # ----- (A) 정규식 1차 스캔: 줄 단위로 좌표/관절 숫자를 직접 검사 -----
    findings.extend(_scan_regex(lines))

    # ----- (B) AST 2차 스캔: 구조적 패턴(무한루프·큐/이펙터 미해제) 검사 -----
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        # 학생 코드가 아직 문법 오류면 AST 분석은 건너뛰고 안내만 추가
        findings.append({
            "line": e.lineno or 0,
            "severity": SEV_INFO,
            "message": "코드에 문법 오류가 있어 구조 분석은 건너뛰었어요. "
                       "먼저 문법 오류부터 고쳐 주세요.",
        })
    else:
        findings.extend(_scan_ast(tree, source))

    # 줄 번호 → 심각도 순으로 정렬해 보기 좋게 반환
    sev_rank = {SEV_CRITICAL: 0, SEV_WARNING: 1, SEV_INFO: 2}
    findings.sort(key=lambda f: (f["line"], sev_rank.get(f["severity"], 9)))
    return findings


# --- 정규식 1차 스캔 -------------------------------------------------------
# move_to(...) / SetPTPCmd(...) 안의 숫자 좌표를 잡아내기 위한 패턴들
_MOVE_CALL_RE = re.compile(r"\b(?:move_to|go)\s*\(([^)]*)\)")
_PTP_CALL_RE = re.compile(r"\bSetPTPCmd\s*\(([^)]*)\)")
# joint/관절 값을 숫자로 직접 대입하는 흔한 형태: j1 = 120, joint1=120 등
_JOINT_ASSIGN_RE = re.compile(r"\b(?:joint|j)\s*([1-4])\s*=\s*(-?\d+(?:\.\d+)?)")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")  # 인자 문자열에서 숫자만 추출


def _scan_regex(lines):
    """줄 단위 정규식 스캔 — Z 과다 하강 / 좌표·관절 범위 초과 탐지."""
    out = []
    z_lo, z_hi = WORKSPACE["z"]
    x_lo, x_hi = WORKSPACE["x"]
    y_lo, y_hi = WORKSPACE["y"]

    for i, line in enumerate(lines, start=1):
        # 주석은 분석 제외(# 뒤 무시) — 단순하지만 교육용으로 충분
        code = line.split("#", 1)[0]

        # move_to(x, y, z, ...) / go(...) 좌표 검사
        m = _MOVE_CALL_RE.search(code)
        if m:
            out.extend(_check_xyz_args(_NUM_RE.findall(m.group(1)), i,
                                       x_lo, x_hi, y_lo, y_hi, z_lo, z_hi))

        # SetPTPCmd(api, mode, x, y, z, r, ...) — 앞의 api/mode 2개를 건너뛴 좌표
        m = _PTP_CALL_RE.search(code)
        if m:
            nums = _NUM_RE.findall(m.group(1))
            # mode 가 숫자(0~9)로 들어오는 경우가 많아 첫 숫자(mode)는 제외
            coord_nums = nums[1:] if nums else nums
            out.extend(_check_xyz_args(coord_nums, i,
                                       x_lo, x_hi, y_lo, y_hi, z_lo, z_hi))

        # joint/관절 직접 대입 검사
        for jm in _JOINT_ASSIGN_RE.finditer(code):
            jkey = "j" + jm.group(1)
            val = float(jm.group(2))
            lo, hi = JOINT_LIMITS[jkey]
            if not (lo <= val <= hi):
                out.append({
                    "line": i,
                    "severity": SEV_CRITICAL,
                    "message": f"관절 {jkey} 각도 {val}° 가 안전 범위({lo}°~{hi}°)를 "
                               f"벗어났어요. 무리한 각도는 모터 손상·충돌을 일으킬 수 있어요.",
                })
    return out


def _check_xyz_args(nums, line, x_lo, x_hi, y_lo, y_hi, z_lo, z_hi):
    """이동 호출에서 추출한 숫자 리스트(x, y, z, ...)의 범위를 검사."""
    out = []
    if len(nums) < 3:
        # 좌표가 변수일 수 있음(숫자 3개 미만) → 정적 분석 대상 아님
        return out
    x, y, z = float(nums[0]), float(nums[1]), float(nums[2])

    # Z 과다 하강은 가장 흔하고 위험한 실수 → 별도 critical 메시지
    if z < z_lo:
        out.append({
            "line": line,
            "severity": SEV_CRITICAL,
            "message": f"Z={z}mm 로 너무 깊게 내려갑니다(하한 {z_lo}mm). "
                       f"로봇팔이 책상이나 물체에 부딪힐 수 있어요. "
                       f"Z 값을 {z_lo}mm 이상으로 올려 주세요.",
        })
    elif z > z_hi:
        out.append({
            "line": line, "severity": SEV_WARNING,
            "message": f"Z={z}mm 가 상한 {z_hi}mm 을 넘었어요. 도달하지 못할 수 있어요.",
        })

    # X, Y 범위 검사
    if not (x_lo <= x <= x_hi):
        out.append({
            "line": line, "severity": SEV_WARNING,
            "message": f"X={x}mm 가 작업영역({x_lo}~{x_hi}mm)을 벗어났어요.",
        })
    if not (y_lo <= y <= y_hi):
        out.append({
            "line": line, "severity": SEV_WARNING,
            "message": f"Y={y}mm 가 작업영역({y_lo}~{y_hi}mm)을 벗어났어요.",
        })
    return out


# --- AST 2차 스캔 ----------------------------------------------------------
# 큐/이펙터 관련 메서드 이름(정지·해제 여부 판단에 사용)
_QUEUE_START = {"_set_queued_cmd_start_exec", "SetQueuedCmdStartExec", "start_exec"}
_QUEUE_STOP = {"_set_queued_cmd_stop_exec", "SetQueuedCmdStopExec",
               "SetQueuedCmdForceStopExec", "stop_exec", "close", "disconnect"}
_LOOP_STOP_CALLS = {"close", "disconnect", "stop", "stop_exec",
                    "SetQueuedCmdStopExec", "SetQueuedCmdForceStopExec"}
# 이동/안전 관련 호출 이름
_MOVE_NAMES = {"move_to", "go", "SetPTPCmd"}
_SAFETY_NAMES = {"check_move", "clamp_move", "scan_code"}


def _call_name(node):
    """ast.Call 노드에서 호출되는 함수/메서드 이름(마지막 식별자)을 추출."""
    func = node.func
    if isinstance(func, ast.Name):          # foo(...)
        return func.id
    if isinstance(func, ast.Attribute):     # obj.foo(...)
        return func.attr
    return None


def _collect_call_names(node):
    """주어진 AST 서브트리 안의 모든 호출 이름 집합을 모은다."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            n = _call_name(sub)
            if n:
                names.add(n)
    return names


def _scan_ast(tree, source):
    """AST 기반 구조 분석 — 무한루프 / 큐 미정지 / 이펙터 미해제 / 안전검사 누락."""
    out = []

    # (1) while True / while 1 무한루프 + 정지 수단 없음
    for node in ast.walk(tree):
        if isinstance(node, ast.While) and _is_constant_true(node.test):
            body_calls = _collect_call_names(node)
            has_break = any(isinstance(s, ast.Break) for s in ast.walk(node))
            has_return = any(isinstance(s, ast.Return) for s in ast.walk(node))
            has_stop = bool(body_calls & _LOOP_STOP_CALLS)
            if not (has_break or has_return or has_stop):
                out.append({
                    "line": node.lineno,
                    "severity": SEV_CRITICAL,
                    "message": "while True 무한 반복 안에 멈출 방법(break·return·정지/연결해제)이 "
                               "없어요. 로봇이 영원히 멈추지 않을 수 있으니 종료 조건을 넣어 주세요.",
                })

    # (2) 전체 코드 호출 이름 집합 — 큐/이펙터/안전 검사 판단에 사용
    all_calls = _collect_call_names(tree)

    # 큐 시작은 있는데 정지가 없음
    if (all_calls & _QUEUE_START) and not (all_calls & _QUEUE_STOP):
        out.append({
            "line": _first_call_line(tree, _QUEUE_START),
            "severity": SEV_WARNING,
            "message": "명령 큐를 시작(start_exec)했지만 정지(stop_exec)나 연결 해제(close)가 "
                       "없어요. 작업이 끝나면 큐를 멈추고 로봇 연결을 해제해 주세요.",
        })

    # (3) 흡착/그리퍼 ON 후 OFF 없음 — suck(True)/grip(True) 만 있고 해제 없음
    out.extend(_scan_effector_release(tree))

    # (4) 이동 명령은 있는데 안전 검사(check_move/clamp_move)가 전혀 없음(권장)
    if (all_calls & _MOVE_NAMES) and not (all_calls & _SAFETY_NAMES):
        out.append({
            "line": _first_call_line(tree, _MOVE_NAMES),
            "severity": SEV_INFO,
            "message": "이동 명령 전에 check_move()/clamp_move() 로 좌표를 한 번 확인하면 "
                       "더 안전해요. 안전 검사를 습관화해 보세요.",
        })

    return out


def _is_constant_true(test):
    """while 의 조건이 항상 참(True 또는 1)인지 판단."""
    if isinstance(test, ast.Constant):
        return bool(test.value)  # True 또는 0이 아닌 상수
    return False


def _first_call_line(tree, names):
    """주어진 이름 집합에 해당하는 첫 호출의 줄 번호(없으면 0)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in names:
            return node.lineno
    return 0


def _scan_effector_release(tree):
    """suck(True)/grip(True) 로 켠 뒤 해제(False) 호출이 없으면 경고."""
    out = []
    turned_on = {}   # {"suck": line, "grip": line} — 켠 위치 기록
    turned_off = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in ("suck", "grip"):
            continue
        # 첫 인자(또는 enable=) 가 True/1 이면 ON, False/0 이면 OFF 로 판단
        on = _first_bool_arg(node)
        if on is True:
            turned_on.setdefault(name, node.lineno)
        elif on is False:
            turned_off.add(name)

    label = {"suck": "흡착(suck)", "grip": "그리퍼(grip)"}
    for name, line in turned_on.items():
        if name not in turned_off:
            out.append({
                "line": line,
                "severity": SEV_WARNING,
                "message": f"{label[name]} 을(를) 켰지만(True) 끄는 명령(False)이 없어요. "
                           f"작업이 끝나면 {label[name]} 을(를) 꺼서 물체를 놓아 주세요.",
            })
    return out


def _first_bool_arg(node):
    """호출의 첫 위치 인자 또는 enable= 키워드에서 True/False 를 추출(없으면 None)."""
    # 위치 인자 우선
    if node.args:
        a = node.args[0]
        if isinstance(a, ast.Constant) and isinstance(a.value, (bool, int)):
            return bool(a.value)
    # 키워드 인자(enable=, on=) 확인
    for kw in node.keywords:
        if kw.arg in ("enable", "on") and isinstance(kw.value, ast.Constant):
            return bool(kw.value.value)
    return None


# ===========================================================================
# 자가 데모 (mock) — 하드웨어/키 없이 위험 코드 샘플을 스캔해 결과 출력
# ===========================================================================
if __name__ == "__main__":
    # Windows cp949 콘솔에서도 한글·특수문자(— 등)가 깨지지 않도록 UTF-8로 재설정
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Python 3.7+
    except Exception:
        pass
    print("=" * 64)
    print(" SFR-002 안전필터 자가 데모 (mock, 하드웨어 불필요)")
    print(f" 작업영역 WORKSPACE = {WORKSPACE}")
    print("=" * 64)

    # --- check_move / clamp_move 데모 ---
    print("\n[1] check_move / clamp_move")
    for pt in [(200, 0, 50, 0), (500, 0, -200, 0), (250, 200, 80, 0)]:
        ok, msg = check_move(*pt)
        clamped = clamp_move(*pt)
        mark = "OK " if ok else "거부"
        print(f"  좌표 {pt} → {mark} | {msg.splitlines()[0]}")
        if not ok:
            print(f"        보정(clamp) → {clamped}")

    # --- scan_code 데모: 일부러 위험하게 작성한 학생 코드 샘플 ---
    print("\n[2] scan_code — 위험 코드 샘플 스캔")
    risky_code = '''\
import pydobot
device = pydobot.Dobot(port="COM3")

device.move_to(200, 0, -150)      # Z 과다 하강(책상 충돌)
device.move_to(500, 200, 50)      # X, Y 작업영역 초과
joint1 = 200                      # 관절 범위 초과

device.suck(True)                 # 흡착 켜고 끄지 않음
device._set_queued_cmd_start_exec()   # 큐 시작만 하고 정지 없음

while True:                       # 정지 조건 없는 무한루프
    device.move_to(200, 0, 50)
'''
    results = scan_code(risky_code)
    print(f"  탐지된 위험: {len(results)} 건\n")
    for f in results:
        print(f"  [{f['severity'].upper():8}] {f['line']:>2}번째 줄: {f['message']}")

    # --- 안전한 코드 샘플(경고가 거의 없어야 함) ---
    print("\n[3] scan_code — 안전한 코드 샘플")
    safe_code = '''\
from common.safety import clamp_move
import pydobot
device = pydobot.Dobot(port="COM3")

x, y, z, r = clamp_move(200, 0, 50)
device.move_to(x, y, z, r)
device.suck(True)
device.move_to(x, y, 80, r)
device.suck(False)
device.close()
'''
    safe_results = scan_code(safe_code)
    if safe_results:
        for f in safe_results:
            print(f"  [{f['severity'].upper():8}] {f['line']:>2}번째 줄: {f['message']}")
    else:
        print("  위험 패턴 없음 — 안전한 코드입니다. 잘했어요!")

    print("\n자가 데모 완료.")
