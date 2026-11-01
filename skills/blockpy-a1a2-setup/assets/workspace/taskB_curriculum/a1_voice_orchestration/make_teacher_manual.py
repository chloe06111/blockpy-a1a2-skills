"""a1_voice_orchestration/make_teacher_manual.py — A1 강사용 매뉴얼(.docx) 생성 스크립트

차시: A1 · 하이브리드(Advanced) · 110분
주제: "LLM 오케스트레이터 — 음성 명령 다단계 분해·실행"

목적(COR-004 강사 자립): 강사가 이 문서 한 부만 들고 수업을 완결할 수 있도록
차시 개요·운영 팁·예상 오류 대응·하드웨어 트러블슈팅·Q&A·평가 루브릭·안전수칙을 담는다.

실행:
    python a1_voice_orchestration/make_teacher_manual.py
생성물:
    a1_voice_orchestration/강사매뉴얼.docx
"""

# ── sys.path 부트스트랩 2줄 (taskB_curriculum 을 import 루트로 추가) ──────────
import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.docx_builder import DocxBuilder   # 공통 문서 빌더(표지/표/코드/체크리스트)


def build() -> str:
    """A1 강사 매뉴얼 문서를 만들어 같은 폴더에 저장하고 절대경로를 반환한다."""
    doc = DocxBuilder(
        "LLM 오케스트레이터 — 음성 명령 다단계 분해·실행",
        subtitle="하이브리드(Advanced) 트랙 · A1차시 · 110분 · 강사용 매뉴얼",
    )

    # ===================================================================
    # 1. 차시 개요
    # ===================================================================
    doc.heading("1. 차시 개요", level=1)
    doc.para(
        "사람의 한 마디 음성 명령(\"블록들을 색깔별로 정리해\")을 STT(음성→텍스트) → "
        "LLM 오케스트레이터(복합 명령을 작은 단계로 분해) → 사람 검토(안전 게이트) → "
        "로봇 순차 실행(감지→분류→픽앤플레이스→복귀)의 파이프라인으로 처리하는 "
        "오케스트레이션(지휘) 개념을 체험한다."
    )
    doc.para("핵심 학습 목표", bold=True)
    doc.table(
        ["구분", "내용"],
        [
            ["대상/난이도", "하이브리드(Advanced) — 코딩 경험자, LLM·로봇 융합 PBL"],
            ["수업 시간", "110분 (5E 모형 기반)"],
            ["교육 철학", "Logic-First, Syntax-Later — 먼저 '무엇을 어떤 순서로'(논리)를 설계"],
            ["산업 연계", "공장 자동화·물류: 자연어 지시 → 작업 계획(plan) → 순차 실행(pipeline)"],
            ["핵심 역량", "복합 명령 분해, 파이프라인 단계 간 데이터 전달, 안전 게이트(사람 승인)"],
            ["안전 정책", "SFR-002: LLM 계획은 사람 승인 후에만 실행, 이동 직전 check_move 검사, 이중 클램프"],
            ["실행 환경", "ADR-0004: 하드웨어·API 키 없이 mock으로 끝까지 동작"],
        ],
    )
    doc.para("핵심 코드 자산", bold=True)
    doc.table(
        ["파일", "역할"],
        [
            ["a1_voice_orchestration/solution.py", "모범답안(완성본). 강사 시연·정답 확인용"],
            ["a1_voice_orchestration/scaffold.py", "학생 실습 골격(# TODO 5곳). 채우면 solution과 동일 동작"],
            ["common/ai_clients.py", "STTClient, LLMClient (mock 자동 폴백)"],
            ["common/dobot_ctl.py", "get_robot() / RobotController (mock 자동)"],
            ["common/vision.py", "Camera, detect_colors (합성 프레임 색 블록 검출)"],
            ["common/safety.py", "check_move(작업영역 검사), WORKSPACE 범위"],
        ],
    )

    # ===================================================================
    # 2. 5E 수업 운영 흐름 (110분)
    # ===================================================================
    doc.page_break()
    doc.heading("2. 5E 수업 운영 흐름 (110분)", level=1)
    doc.para(
        "5E(Engage·Explore·Explain·Elaborate·Evaluate)로 진행한다. 각 단계의 시간은 "
        "권장값이며 학생 수준에 따라 ±5분 조정한다."
    )
    doc.table(
        ["단계(5E)", "시간", "활동 내용", "강사 포인트"],
        [
            ["Engage (도입)", "15분",
             "\"블록을 색깔별로 정리해\" 음성 한 마디로 로봇이 알아서 일하는 시연(solution.py mock)",
             "‘말 한마디 vs 단계 분해’의 간극을 체감시킨다"],
            ["Explore (탐구)", "20분",
             "복합 명령을 종이에 직접 단계로 쪼개보기(detect/sort/pick_place/home)",
             "Logic-First: 코드 전에 순서도부터 그리게 한다"],
            ["Explain (설명)", "25분",
             "STT→LLM→게이트→실행 파이프라인 구조, JSON 계획 형식, 안전 게이트 원리 설명",
             "decompose_command의 JSON 파싱·폴백 흐름을 슬라이드로 짚는다"],
            ["Elaborate (적용)", "35분",
             "scaffold.py의 # TODO 5곳 채우기(listen/decompose/detect/sort/pick_place·home)",
             "막히면 ‘힌트’ 주석을 먼저 읽게 하고, _safe_move·suck OFF를 강조"],
            ["Evaluate (평가)", "15분",
             "각자 실행 결과(블록 3개 이동) 확인, 루브릭으로 자기·동료 평가, 회고",
             "안전 게이트를 끄면 왜 위험한지 토론으로 마무리"],
        ],
    )

    # ===================================================================
    # 3. 수업 운영 팁
    # ===================================================================
    doc.heading("3. 수업 운영 팁", level=1)
    doc.checklist([
        "수업 시작 전 CURRICULUM_FORCE_MOCK=1 환경에서 solution.py가 끝까지 도는지 미리 1회 확인한다.",
        "Logic-First 원칙: 학생이 코드부터 치려 하면, 먼저 단계 순서(순서도)를 말로 설명하게 한다.",
        "LLM 계획은 JSON 배열이라는 점을 강조 — 파싱 실패 시 _fallback_plan(결정적 표준 계획)으로 동작함을 보여준다.",
        "안전 게이트(review_plan)는 ‘사람 승인 후에만 실행’이라는 산업 안전의 핵심임을 반복 강조한다.",
        "pick_place 한 사이클(접근→하강→흡착ON→상승→이동→하강→흡착OFF→상승) 8단계를 손동작으로 시연한다.",
        "흡착을 켰으면 반드시 끄게(suck(False)) 한다 — 안전·다음 학생 실습을 위해.",
        "실하드웨어 사용 반은 1조당 1대로 제한하고, 이동 속도는 50% 이하로 시작한다.",
        "mock 반과 실하드웨어 반을 섞어 운영할 때는 결과(좌표·이동 개수)가 동일함을 비교하게 한다.",
    ])

    # ===================================================================
    # 4. 실습 단계별 예상 오류 및 대응표
    # ===================================================================
    doc.page_break()
    doc.heading("4. 실습 단계별 예상 오류 및 대응표", level=1)
    doc.table(
        ["실습 단계", "증상 / 오류 메시지", "원인", "대응(강사 안내)"],
        [
            ["import/실행",
             "ModuleNotFoundError: common",
             "sys.path 부트스트랩 2줄 누락 또는 잘못된 폴더에서 실행",
             "파일 상단 2줄 확인, taskB_curriculum 폴더 기준 경로로 실행"],
            ["listen_command",
             "text가 빈 문자열, [1] 인식 결과 ''",
             "stt.transcribe(...) 호출 TODO 미완성",
             "stt.transcribe(audio_path) 반환값을 return 하도록 안내"],
            ["decompose_command",
             "단계 수가 0 또는 의도와 다름",
             "raw 미수신/JSON 추출 누락 → 폴백도 안 탐",
             "llm.complete(...) 결과를 raw에 담고, 실패 시 _fallback_plan(command) 반환 확인"],
            ["decompose_command",
             "json.JSONDecodeError / ValueError",
             "‘[’ ‘]’ 슬라이싱 또는 mock의 비JSON 응답",
             "try/except (ValueError, json.JSONDecodeError)로 감싸 폴백으로 보내게 한다"],
            ["step_detect",
             "감지된 블록: [] (빈 리스트)",
             "cam.read()/detect_colors(frame) TODO 미완성",
             "frame=cam.read(); blocks=detect_colors(frame) 두 줄 작성 안내"],
            ["step_sort",
             "분류 결과가 비어 pick_place가 0개 이동",
             "grouped.setdefault(...).append(b) 루프 누락",
             "blocks를 돌며 같은 색끼리 모으는 루프 작성 안내"],
            ["step_pick_place",
             "이동은 하나 블록을 안 옮김 / 흡착이 안 떨어짐",
             "_safe_move 8단계 순서 오류 또는 suck(False) 누락",
             "접근→하강→ON→상승→이동→하강→OFF→상승 순서·흡착 OFF 확인"],
            ["step_home",
             "종료 후 흡착이 켜진 채 남음",
             "suck(False) 생략",
             "home 전 흡착을 먼저 끄도록(bot.suck(False)) 안내"],
            ["안전 게이트",
             "검토 없이 바로 실행되어 학생이 위험성 못 느낌",
             "approver=None(자동 승인) 데모만 본 경우",
             "input 기반 approver를 넣어 거부(n) 시 ‘아무 동작 안 함’을 체험시킨다"],
            ["콘솔 출력",
             "한글/특수문자(⚠, ☐)가 깨짐",
             "Windows cp949 콘솔",
             "sys.stdout.reconfigure(encoding='utf-8') 적용 또는 chcp 65001"],
        ],
    )

    # ===================================================================
    # 5. 하드웨어 트러블슈팅
    # ===================================================================
    doc.page_break()
    doc.heading("5. 하드웨어 트러블슈팅", level=1)
    doc.para("실하드웨어(Dobot Magician Lite) 사용 시 자주 겪는 문제와 대응이다. mock 모드는 해당 없음.", bold=True)
    doc.table(
        ["분류", "증상", "점검/원인", "조치"],
        [
            ["연결",
             "로봇이 응답 없음 / connect 실패",
             "USB 케이블·전원 미연결, 다른 프로그램이 포트 점유(DobotStudio 등)",
             "전원 LED 확인, DobotStudio 종료 후 재연결, 케이블 교체"],
            ["COM 포트",
             "could not open port / 포트 못 찾음",
             "잘못된 COM 번호, pyserial/pydobot 미설치",
             "장치 관리자에서 COM 번호 확인 후 지정, pip install pyserial pydobot; 미설치면 자동 mock 폴백"],
            ["좌표",
             "엉뚱한 위치로 이동 / 블록을 못 집음",
             "픽셀→로봇 보정(pixel_to_robot) 근사값, 책상 위 색 칸 위치 불일치",
             "DROP_ZONES 좌표를 실제 정리함 위치로 강사가 보정, 카메라 고정·조명 일정 유지"],
            ["작업영역 초과",
             "⚠ 안전경고(...) 출력 / 이동이 클램프됨",
             "목표 좌표가 WORKSPACE(x:180~320, y:-150~150, z:-60~150) 밖",
             "DROP_ZONES·PICK_Z·SAFE_Z를 범위 안으로 조정(이중 클램프로 충돌은 방지됨)"],
            ["충돌",
             "팔이 다른 블록·정리함과 부딪힘",
             "SAFE_Z(80mm)보다 낮은 높이로 가로 이동",
             "이동은 반드시 SAFE_Z로 상승 후 수평 이동, 책상 위 장애물 제거"],
            ["홈(원점)",
             "전원 직후 좌표가 어긋남 / 이동이 부정확",
             "홈(SetHOMECmd) 미실행",
             "전원 직후 반드시 bot.home() 먼저 실행, 홈 동작 중 팔 경로 비우기"],
            ["흡착",
             "블록이 안 붙거나 안 떨어짐",
             "흡착 컵 이물질, 공기펌프 소음/오프, suck 타이밍",
             "흡착 컵 청소·밀착 확인, 하강 후 충분히 접촉한 뒤 suck(True), 놓을 때 suck(False)"],
        ],
    )

    # ===================================================================
    # 6. Q&A 대응표
    # ===================================================================
    doc.page_break()
    doc.heading("6. 예상 Q&A 대응표", level=1)
    doc.table(
        ["학생 질문", "강사 답변"],
        [
            ["LLM이 매번 다른 계획을 주면 위험하지 않나요?",
             "그래서 안전 게이트가 있습니다. 계획은 사람이 검토·승인한 뒤에만 실행되고, mock·파싱 실패 시엔 결정적 표준 계획(_fallback_plan)으로 안전하게 대체됩니다."],
            ["오케스트레이터가 정확히 무슨 일을 하나요?",
             "복합 명령(한 문장)을 로봇이 실행 가능한 작은 단계 목록(JSON)으로 ‘분해(plan)’하는 지휘자 역할입니다. 실행은 execute_plan이 순서대로 합니다."],
            ["JSON이 왜 필요한가요?",
             "사람 말은 모호하지만, 기계는 정해진 구조가 필요합니다. {action,target,desc} 형식의 JSON 배열이 사람↔로봇의 ‘계약’ 역할을 합니다."],
            ["API 키나 로봇이 없어도 되나요?",
             "네. STT·LLM·로봇 모두 mock으로 끝까지 동작합니다(ADR-0004). CURRICULUM_FORCE_MOCK=1로 강제할 수 있습니다."],
            ["detect 다음에 sort를 안 하면요?",
             "execute_plan이 방어적으로 보정해, pick_place 직전에 grouped가 비어 있으면 자동으로 sort를 한 번 수행합니다."],
            ["실제 공장에서도 이렇게 하나요?",
             "구조가 같습니다. 자연어/지시 → 작업 계획 → 순차 실행(파이프라인)이 물류·제조 자동화의 표준 패턴입니다."],
            ["픽셀 좌표가 어떻게 로봇 좌표가 되나요?",
             "pixel_to_robot이 화면 가로→로봇 Y, 화면 세로→로봇 X로 선형 보간합니다. 실제로는 캘리브레이션이 필요하지만 교육용 근사로 충분합니다."],
        ],
    )

    # ===================================================================
    # 7. 평가 루브릭 (채점 기준표)
    # ===================================================================
    doc.heading("7. 평가 루브릭 (채점 기준표)", level=1)
    doc.para("5개 항목 × 4수준. 항목별 5점 환산(우수 5 / 보통 3 / 미흡 1), 총 25점 만점.", bold=True)
    doc.table(
        ["평가 항목", "우수 (5)", "보통 (3)", "미흡 (1)"],
        [
            ["논리 설계(Logic-First)",
             "코드 전에 단계 순서를 스스로 설계·설명",
             "힌트를 보고 순서를 정리",
             "순서 설계 없이 코드부터 시도"],
            ["명령 분해 이해",
             "STT→LLM→게이트→실행 흐름과 JSON 계획을 정확히 설명",
             "흐름은 알지만 일부 단계 혼동",
             "파이프라인 개념을 설명하지 못함"],
            ["구현 완성도(TODO)",
             "5개 TODO 모두 채워 블록 3개 이동 성공",
             "일부 TODO 완성, 부분 동작",
             "대부분 미완성, 미동작"],
            ["안전 의식",
             "안전 게이트·흡착 OFF·작업영역 의미를 설명·실천",
             "안내 시 안전 절차 준수",
             "안전 절차를 빠뜨림"],
            ["협업/회고",
             "동료 피드백을 반영하고 개선점을 명확히 정리",
             "회고에 참여",
             "참여 소극적, 회고 미작성"],
        ],
    )

    # ===================================================================
    # 8. 학생 안전 주의사항
    # ===================================================================
    doc.page_break()
    doc.heading("8. 학생 안전 주의사항", level=1)
    doc.checklist([
        "로봇이 움직이는 동안 작업 반경 안에 손·얼굴·물건을 넣지 않는다.",
        "전원을 켠 직후 반드시 홈(원점 복귀)을 먼저 실행한다.",
        "LLM이 만든 계획은 반드시 사람이 검토·승인한 뒤에만 실행한다(안전 게이트).",
        "이동 속도는 50% 이하로 시작해 동작을 확인한 뒤 점차 높인다.",
        "흡착(석션)을 켰으면 작업이 끝날 때 반드시 끈다.",
        "작업영역(WORKSPACE) 밖 좌표를 의도적으로 넣지 않는다 — 경고가 떠도 무시하지 않는다.",
        "이상 동작·소음·충돌 시 즉시 전원/실행을 멈추고 강사를 부른다.",
        "실습 종료 시 로봇 연결을 안전하게 해제하고 주변을 정리한다.",
    ])

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "강사매뉴얼.docx")
    return doc.save(out_path)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    saved = build()
    print(f"[A1 강사매뉴얼] 저장 완료: {saved}")
