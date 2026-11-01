# -*- coding: utf-8 -*-
"""로컬 자연어 이해(Local NLU) 모듈.

한국어 자연어 명령을 로봇 의도(intent)로 변환하는 규칙/키워드 기반 모듈입니다.

설계 원칙(ADR-0004):
    - 무거운 의존성 없이(import) 동작해야 합니다. 순수 표준 라이브러리(re 등)만 사용합니다.
    - API 키 없이, 클라우드 호출 없이 결정적(deterministic)으로 동작합니다.
    - 교실 안전(classroom-safe): 외부 LLM/VLM 없이 규칙으로만 의도를 추출합니다.

H1(자연어 제어)과 A1(음성 오케스트레이션)의 클라우드 LLM 경로를 대체합니다.
    - parse_move_intent(): H1 용. 색상/방향/거리 의도 추출.
    - decompose_voice_command(): A1 용. 명령을 순서 있는 단계로 분해.

키워드 매칭은 부분 문자열(substring) 매칭을 사용하되, '파'가 엉뚱한 단어 안에서
잘못 매칭되는 것을 줄이기 위해 긴 키워드를 먼저 검사합니다.
"""

import re

# ---------------------------------------------------------------------------
# 키워드 사전(canonical 색상/방향 -> 한국어/영어 키워드 목록)
# ---------------------------------------------------------------------------

#: 정규 색상 -> 한국어/영어 키워드 목록. canonical: red/green/blue/yellow
#  주의: 한 글자 키워드('빨','파','노')는 '파스타'·'노트북'·'빨래' 같은 무관한 단어 안에서
#  오탐(substring false positive)을 일으키므로 **쓰지 않는다**. 실제 명령은 거의 항상
#  2글자 이상 형태(빨강/빨간, 파랑/파란, 노랑/노란)를 쓰므로 recall 손실은 사실상 없다.
COLOR_KEYWORDS = {
    "red": ["빨강색", "빨강", "빨간", "red"],
    "green": ["초록색", "초록", "녹색", "green"],
    "blue": ["파랑색", "파랑", "파란", "blue"],
    "yellow": ["노랑색", "노랑", "노란", "yellow"],
}

#: 정규 방향 -> 한국어/기호 키워드 목록. canonical: right/left/forward/back
DIRECTION_KEYWORDS = {
    "right": ["오른", "우측", "→"],
    "left": ["왼", "좌측", "←"],
    "forward": ["앞", "위쪽", "멀리"],
    "back": ["뒤", "아래쪽", "가까이"],
}


def _first_match(command, mapping):
    """주어진 mapping(정규값 -> 키워드 목록) 중에서 명령에 가장 먼저 등장하는
    정규값을 반환합니다.

    매칭 규칙:
        - 명령 문자열 안에서 키워드가 나타나는 '위치(index)'가 가장 앞선 것을 우선합니다.
        - 같은 위치라면 더 긴 키워드를 우선합니다('파'보다 '파랑').
        - 어떤 키워드도 없으면 None.

    Args:
        command: 사용자 명령 문자열.
        mapping: 정규값 -> 키워드 목록 딕셔너리.

    Returns:
        가장 먼저 등장한 정규값(str) 또는 None.
    """
    if not command:
        return None

    best_canonical = None
    best_pos = None
    best_len = -1

    for canonical, keywords in mapping.items():
        # 긴 키워드를 먼저 검사하여(같은 위치일 때) 더 구체적인 매칭을 선호합니다.
        for kw in sorted(keywords, key=len, reverse=True):
            pos = command.find(kw)
            if pos == -1:
                continue
            # 더 앞선 위치를 우선, 같은 위치면 더 긴 키워드를 우선.
            if best_pos is None or pos < best_pos or (pos == best_pos and len(kw) > best_len):
                best_canonical = canonical
                best_pos = pos
                best_len = len(kw)
            # 한 정규값에 대해 가장 먼저(가장 앞 위치) 매칭된 키워드 하나면 충분하므로
            # 다음 정규값으로 넘어갑니다.
            break
    return best_canonical


def detect_color(command):
    """명령에서 처음 발견되는 색상을 정규값(red/green/blue/yellow)으로 반환합니다.

    Args:
        command: 사용자 명령 문자열.

    Returns:
        정규 색상 문자열 또는 None.
    """
    return _first_match(command, COLOR_KEYWORDS)


def detect_direction(command):
    """명령에서 처음 발견되는 방향을 정규값(right/left/forward/back)으로 반환합니다.

    Args:
        command: 사용자 명령 문자열.

    Returns:
        정규 방향 문자열 또는 None.
    """
    return _first_match(command, DIRECTION_KEYWORDS)


def parse_distance_mm(command, default=80.0):
    """명령에서 거리를 mm 단위로 파싱합니다.

    지원 형식(숫자 + 단위):
        - "N cm" / "Ncm" / "N 센티" / "N센티미터"  -> N * 10 (mm)
        - "N mm" / "Nmm" / "N 밀리" / "N밀리미터"  -> N (mm)

    단위/숫자가 없으면 default를 반환합니다.

    Args:
        command: 사용자 명령 문자열.
        default: 매칭 실패 시 반환할 기본 거리(mm).

    Returns:
        거리(mm) float.
    """
    if not command:
        return float(default)

    # cm/센티 계열을 먼저 검사(센티미터에 '미터'가 포함되어 mm와 혼동되지 않도록).
    # 숫자(소수 허용) + 공백(선택) + 단위.
    cm_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(?:cm|센티미터|센치|센티)", re.IGNORECASE)
    mm_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mm|밀리미터|밀리)", re.IGNORECASE)

    m = cm_pattern.search(command)
    if m:
        return float(m.group(1)) * 10.0

    m = mm_pattern.search(command)
    if m:
        return float(m.group(1))

    return float(default)


def parse_move_intent(command):
    """H1용: 한국어 명령에서 이동 의도를 추출합니다.

    색상이 없으면 의도가 성립하지 않으므로 None을 반환합니다.

    Args:
        command: 사용자 명령 문자열.

    Returns:
        {"color": <canonical>, "direction": <dir|None>, "distance_mm": float}
        또는 색상이 없으면 None.
    """
    color = detect_color(command)
    if color is None:
        return None
    direction = detect_direction(command)
    distance_mm = parse_distance_mm(command)
    return {
        "color": color,
        "direction": direction,
        "distance_mm": distance_mm,
    }


# ---------------------------------------------------------------------------
# A1용: 음성 명령 분해(decompose)
# ---------------------------------------------------------------------------

#: 색상 정규값 -> 사람이 읽기 좋은 한국어 색상 이름.
_COLOR_KO = {
    "red": "빨강",
    "green": "초록",
    "blue": "파랑",
    "yellow": "노랑",
}

# 정리/분류를 뜻하는 키워드.
_SORT_KEYWORDS = ["정리", "분류", "색깔별", "색깔 별", "sort"]
# 홈/원점 복귀를 뜻하는 키워드.
_HOME_KEYWORDS = ["홈", "원점", "처음 위치", "처음위치", "home"]
# 특정 색을 치우라는 동작 키워드.
_CLEANUP_KEYWORDS = ["치워", "옮겨", "담아", "집어", "빼"]


def _step(action, target, desc):
    """단일 단계 딕셔너리를 생성하는 헬퍼."""
    return {"action": action, "target": target, "desc": desc}


def _sort_pipeline():
    """표준 정리(분류) 파이프라인 4단계를 반환합니다."""
    return [
        _step("detect", "all", "테이블 위의 모든 블록을 인식합니다."),
        _step("sort", "all", "인식한 블록을 색깔별로 분류합니다."),
        _step("pick_place", "all", "분류 결과대로 블록을 하나씩 집어 옮깁니다."),
        _step("home", "all", "작업을 마치고 홈(원점) 위치로 복귀합니다."),
    ]


def _contains_any(command, keywords):
    """명령에 키워드 중 하나라도 포함되면 True."""
    return any(kw in command for kw in keywords)


def decompose_voice_command(command):
    """A1용: 음성 명령을 순서 있는 실행 단계 목록으로 분해합니다.

    각 단계는 {"action", "target", "desc"} 형태입니다.
        action: "detect" | "sort" | "pick_place" | "home"
        target: "all" | <canonical color>
        desc:   친근한 한국어 한 줄 설명.

    의도 규칙(우선순위 순):
        1) 정리|분류|sort|색깔별 -> 표준 정리 파이프라인 4단계.
        2) (특정 색) + (치워|옮겨|담아|집어|빼) -> [detect(all), pick_place(color), home(all)].
        3) 홈|원점|처음 위치|home -> [home(all)].
        4) 그 외(알 수 없음) -> 안전 기본값으로 표준 정리 파이프라인.

    Args:
        command: 사용자(음성 인식 결과) 명령 문자열.

    Returns:
        단계 딕셔너리들의 순서 있는 리스트.
    """
    text = command or ""

    # 1) 정리/분류
    if _contains_any(text, _SORT_KEYWORDS):
        return _sort_pipeline()

    # 2) 특정 색 + 치우기 동작
    color = detect_color(text)
    if color is not None and _contains_any(text, _CLEANUP_KEYWORDS):
        color_ko = _COLOR_KO.get(color, color)
        return [
            _step("detect", "all", "테이블 위의 모든 블록을 인식합니다."),
            _step("pick_place", color, "{0} 블록을 집어 정해진 위치로 옮깁니다.".format(color_ko)),
            _step("home", "all", "작업을 마치고 홈(원점) 위치로 복귀합니다."),
        ]

    # 3) 홈/원점 복귀
    if _contains_any(text, _HOME_KEYWORDS):
        return [_step("home", "all", "홈(원점) 위치로 복귀합니다.")]

    # 4) 알 수 없는 명령 -> 안전 기본값(표준 정리 파이프라인)
    return _sort_pipeline()


# ---------------------------------------------------------------------------
# 모듈 자체 데모(self-demo)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== local_nlu 자체 데모 ===")

    samples_move = [
        "빨간 블록을 오른쪽으로 옮겨",
        "초록 왼쪽",
        "파랑 블록 앞으로 5cm 이동",
        "노란 블록 30mm 뒤로",
        "아무말",
    ]
    print("\n[parse_move_intent]")
    for s in samples_move:
        print("  {0!r} -> {1}".format(s, parse_move_intent(s)))

    samples_voice = [
        "블록들을 색깔별로 정리해",
        "빨간거 치워",
        "원점으로",
        "이상한 명령",
    ]
    print("\n[decompose_voice_command]")
    for s in samples_voice:
        steps = decompose_voice_command(s)
        print("  {0!r} -> {1}단계".format(s, len(steps)))
        for i, st in enumerate(steps, 1):
            print("      {0}. [{1}] target={2} : {3}".format(
                i, st["action"], st["target"], st["desc"]))

    print("\n[parse_distance_mm]")
    for s in ["5cm 이동", "30mm", "10 센티", "거리 없음"]:
        print("  {0!r} -> {1} mm".format(s, parse_distance_mm(s)))
