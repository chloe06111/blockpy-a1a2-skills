"""make_docs.py — 차시 A1 "LLM 오케스트레이터 — 음성 명령 다단계 분해·실행"
문서 2종(강의계획서.docx, 활동지.docx)을 공통 빌더로 생성한다.

차시: A1 · 하이브리드(Advanced) · 110분
실행:  python a1_voice_orchestration/make_docs.py
"""

# ── sys.path 부트스트랩 2줄 (taskB_curriculum 을 import 루트로 추가) ──────────
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.docx_builder import DocxBuilder

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
SUBTITLE = "하이브리드(Advanced) 트랙 · 차시 A1 · 110분"
TITLE = "LLM 오케스트레이터 — 음성 명령 다단계 분해·실행"


# ===========================================================================
# 1) 강의계획서 (강사용)
# ===========================================================================
def build_lesson_plan() -> str:
    doc = DocxBuilder(TITLE, subtitle=SUBTITLE + " · 강의계획서")

    # ── 산업연계 도입(PBL) ──────────────────────────────────────────
    doc.heading("산업 연계 도입 — 문제 상황(PBL)", level=1)
    doc.para(
        "스마트 물류 센터의 작업자는 키보드 대신 한 마디 음성으로 로봇에게 일을 시킨다. "
        "\"섞여 있는 블록들을 색깔별로 정리해\"라는 한 문장에는 '감지 → 분류 → 집기 → 옮기기 → 복귀'라는 "
        "여러 작업이 숨어 있다. 사람은 자연어로 말하지만, 로봇은 작은 단계의 명령만 실행할 수 있다."
    )
    doc.para("프로젝트 미션 (PBL)", bold=True)
    doc.para(
        "여러분은 물류 자동화 스타트업의 'AI 오케스트레이션 엔지니어'다. 음성 한 마디를 받아 "
        "STT(음성→텍스트) → LLM(복합명령→단계 계획) → 사람 검토(안전 게이트) → 로봇 순차 실행으로 "
        "이어지는 파이프라인을 완성해, 두봇이 색깔별 정리를 끝까지 수행하도록 만든다."
    )
    doc.para(
        "핵심 질문: \"사람의 한 문장을, 로봇이 실행 가능한 단계들로 어떻게 안전하게 분해할 것인가?\"",
        bold=True,
    )

    # ── 학습 목표 ──────────────────────────────────────────────────
    doc.heading("학습 목표", level=1)
    doc.para("1. 음성 명령이 STT → LLM 계획 분해 → 실행으로 이어지는 오케스트레이션 구조를 설명할 수 있다.")
    doc.para("2. LLM이 복합 명령을 JSON 단계 목록(plan)으로 분해하는 과정을 이해하고, 분해 결과를 검증할 수 있다.")
    doc.para("3. '사람 검토(안전 게이트)'가 자율 실행 전에 왜 필요한지 설명하고, 승인/거부 흐름을 구현할 수 있다.")
    doc.para("4. 분해된 계획을 단계별 실행기(감지·분류·픽앤플레이스·복귀)로 순차 실행하고 진행을 보고할 수 있다.")
    doc.para("5. LLM 분해 실패 시 결정적 폴백(fallback) 계획으로 안전하게 대처하는 방어적 설계를 적용할 수 있다.")

    # ── 성취기준 ───────────────────────────────────────────────────
    doc.heading("성취기준", level=1)
    doc.table(
        ["코드", "성취기준", "평가 단계(5E)"],
        [
            ["AC-A1-1", "음성→텍스트→계획→실행의 4단계 파이프라인을 도식으로 그리고 각 단계의 입력/출력을 말할 수 있다.", "Explain"],
            ["AC-A1-2", "LLM이 반환한 JSON 계획을 파싱해 단계 목록으로 변환하고, 누락/오류를 검출한다.", "Explore·Elaborate"],
            ["AC-A1-3", "사람 검토 게이트를 통과한 계획만 로봇이 실행하도록 코드로 보장한다(안전).", "Elaborate"],
            ["AC-A1-4", "분해→실행 사이클을 mock 환경에서 끝까지 무중단 실행해 블록 정리를 완료한다.", "Evaluate"],
            ["AC-A1-5", "LLM 실패 상황을 가정해 폴백 계획이 동작함을 테스트로 증명한다.", "Evaluate"],
        ],
    )

    # ── 준비물 ─────────────────────────────────────────────────────
    doc.heading("준비물 리스트", level=1)
    doc.para("로봇 / 하드웨어", bold=True)
    doc.checklist([
        "두봇 매지션 라이트(Dobot Magician Lite) 본체 1대 (모둠당)",
        "흡착(석션컵) 엔드이펙터 + 에어펌프 키트 (장착·기밀 확인)",
        "USB 연결 케이블 및 전원 어댑터 (전원 직후 홈 실행 필수)",
        "비상 정지 버튼 접근 가능 위치 확보",
    ])
    doc.para("PC / 소프트웨어", bold=True)
    doc.checklist([
        "실습용 PC 1대 (모둠당), Python 3.10+ 설치",
        "패키지: python-docx, pydobot, opencv-python (사전 설치)",
        "STT(Whisper)·LLM(Claude) 클라이언트 — 키 없으면 자동 mock 폴백(CURRICULUM_FORCE_MOCK=1)",
        "scaffold.py / solution.py / hardware_test.py 배포본 (USB 또는 사내망)",
    ])
    doc.para("웹캠 / 비전", bold=True)
    doc.checklist([
        "USB 웹캠 1대 (모둠당), 작업대 상단 고정 거치대",
        "균일 조명(LED 스탠드) — 색 검출 안정화용",
        "흰색/단색 작업 매트 (배경 대비 확보)",
    ])
    doc.para("물리 교구", bold=True)
    doc.checklist([
        "색깔 블록 세트: 빨강·초록·파랑 각 2~3개 (흡착 가능한 평면 상단)",
        "색깔별 정리함(드롭존) 라벨: red / green / blue 칸 표시 (작업영역 내)",
        "마이크(헤드셋 또는 PC 내장) — 음성 명령 입력용",
        "좌표 보정용 자/줄자 (드롭존 mm 좌표 캘리브레이션)",
    ])

    # ── 110분 5E 타임테이블 ────────────────────────────────────────
    doc.heading("110분 5E 수업 타임테이블", level=1)
    doc.table(
        ["단계(5E)", "시간", "주요 활동", "산출물/체크"],
        [
            ["Engage\n(도입)", "15분",
             "음성 명령 데모 시청: \"블록들을 색깔별로 정리해\" 한 마디로 로봇이 움직이는 영상. "
             "물류센터 PBL 미션 제시. \"한 문장 속에 몇 개의 작업이 숨어 있나?\" 브레인스토밍.",
             "미션 카드 작성, 숨은 단계 추측 목록"],
            ["Explore\n(탐구)", "20분",
             "mock 환경에서 solution.py 실행 관찰. STT 출력(텍스트)과 LLM이 반환한 JSON 계획을 "
             "활동지에 그대로 기록. 입력 명령을 바꿔가며 계획이 어떻게 달라지는지 탐구.",
             "활동지 실험 결과 기록표(명령→계획 매핑)"],
            ["Explain\n(설명)", "25분",
             "4단계 파이프라인(STT→LLM 분해→사람 검토→순차 실행) 강의. JSON 계획 스키마와 단계 실행기 "
             "(detect/sort/pick_place/home) 역할 설명. '안전 게이트'의 의미 명확화.",
             "파이프라인 순서도 완성(빈칸 채우기)"],
            ["Elaborate\n(정교화)", "35분",
             "scaffold.py의 TODO 5곳 구현: listen_command, decompose_command의 JSON 파싱, "
             "step_detect 감지, step_sort 그룹화, step_pick_place 사이클, step_home. 모둠별 페어 코딩. 강사 순회 지원.",
             "동작하는 scaffold.py (solution과 동일 동작)"],
            ["Evaluate\n(평가)", "15분",
             "hardware_test.py로 turnkey 3회 구동 검증(위험 0건, exit 0). LLM 실패→폴백 시나리오 시연. "
             "모둠 발표: 우리 파이프라인은 안전한가? 자기/동료 평가 루브릭 작성.",
             "검증 로그 3/3 통과, 평가 루브릭 제출"],
        ],
    )
    doc.para("합계: 15 + 20 + 25 + 35 + 15 = 110분", bold=True)

    # ── 평가 방법 ──────────────────────────────────────────────────
    doc.heading("평가 방법", level=1)
    doc.table(
        ["평가 영역", "방법", "배점", "성취기준 연계"],
        [
            ["개념 이해", "파이프라인 순서도·구술 평가(Explain)", "20%", "AC-A1-1"],
            ["탐구 기록", "명령→계획 매핑 기록표의 정확성(Explore)", "15%", "AC-A1-2"],
            ["구현 완성도", "scaffold TODO 구현이 solution과 동일 동작(Elaborate)", "35%", "AC-A1-2,3"],
            ["검증/실행", "hardware_test 3/3 통과, 위험 0건(Evaluate)", "20%", "AC-A1-4"],
            ["방어적 설계", "폴백 시나리오 테스트 증명, 자기·동료평가(Evaluate)", "10%", "AC-A1-5"],
        ],
    )
    doc.para(
        "형성평가: 단계별 산출물(미션카드·기록표·순서도)을 누적 확인. 총괄평가: 동작하는 scaffold + 검증 로그."
    )

    path = os.path.join(OUT_DIR, "강의계획서.docx")
    return doc.save(path)


# ===========================================================================
# 2) 활동지 (학생 워크시트 + 강사용 정답키)
# ===========================================================================
def build_worksheet() -> str:
    doc = DocxBuilder(TITLE, subtitle=SUBTITLE + " · 학생 활동지")

    doc.para("모둠명: ______________    이름: ______________    날짜: ______________")

    # ── 탐구 질문 ──────────────────────────────────────────────────
    doc.heading("1. 탐구 질문 (Engage · Explore)", level=1)
    doc.para("아래 질문에 답을 적으며 음성 오케스트레이션의 원리를 탐구하자.")
    doc.para("Q1. \"블록들을 색깔별로 정리해\"라는 한 문장에는 몇 개의 작업이 숨어 있을까? 단계로 나눠 적어보자.")
    doc.para("→ ________________________________________________________________")
    doc.para("Q2. STT(음성→텍스트)의 '입력'과 '출력'은 각각 무엇인가?")
    doc.para("→ 입력: __________________________   출력: __________________________")
    doc.para("Q3. LLM은 왜 명령을 'JSON 계획'으로 돌려줄까? 사람이 바로 실행하면 안 되는 이유는?")
    doc.para("→ ________________________________________________________________")
    doc.para("Q4. 로봇이 계획을 곧바로 실행하지 않고 '사람 검토'를 거치는 이유는? (안전 게이트)")
    doc.para("→ ________________________________________________________________")

    # ── 실험 결과 기록표 ────────────────────────────────────────────
    doc.heading("2. 실험 결과 기록표 (Explore)", level=1)
    doc.para("solution.py를 mock으로 실행하고, 명령을 바꿔가며 LLM이 반환한 계획을 관찰해 기록하자.")
    doc.table(
        ["#", "입력한 음성 명령(텍스트)", "LLM이 분해한 단계(plan)", "실행된 단계 수", "이동한 블록 수"],
        [
            ["1", "블록들을 색깔별로 정리해", "", "", ""],
            ["2", "", "", "", ""],
            ["3", "", "", "", ""],
            ["4", "(LLM 실패를 가정 → 폴백 계획)", "", "", ""],
        ],
    )

    # ── 알고리즘 설계 순서도 (빈칸) ─────────────────────────────────
    doc.heading("3. 알고리즘 설계 순서도 (Explain) — 빈칸을 채우자", level=1)
    doc.para("음성 오케스트레이션 파이프라인의 흐름이다. ①~⑤ 빈칸에 알맞은 단계 이름을 써넣자.")
    doc.code(
        "┌─────────────────────────────────────────────┐\n"
        "│  [시작] 마이크로 음성 입력                    │\n"
        "└───────────────────┬─────────────────────────┘\n"
        "                    ▼\n"
        "        ①  ______________________  (음성 → 텍스트)\n"
        "                    ▼\n"
        "        ②  ______________________  (텍스트 → JSON 단계 계획)\n"
        "                    ▼\n"
        "        ③  ______________________  (안전 게이트: 승인?)\n"
        "             │거부→ [중단/재계획]\n"
        "             │승인\n"
        "                    ▼\n"
        "   ┌──── 계획의 각 단계를 순서대로 ────┐\n"
        "   │  detect → ④ __________ → pick_place│\n"
        "   └──────────────────┬────────────────┘\n"
        "                    ▼\n"
        "        ⑤  ______________________  (작업 후 원점 복귀)\n"
        "                    ▼\n"
        "                 [완료] 진행/소요시간 보고"
    )
    doc.para("보너스: 매 로봇 이동 직전에 호출해야 하는 안전 검사 함수 이름은? → ________________")

    # ── 디버깅 체크리스트 ──────────────────────────────────────────
    doc.heading("4. 디버깅 체크리스트 (Elaborate)", level=1)
    doc.para("scaffold.py의 TODO를 구현하다 막히면 아래를 점검하자.")
    doc.checklist([
        "전원 직후 home()을 먼저 실행했는가? (좌표 신뢰성)",
        "listen_command가 STT 결과 '텍스트'를 반환하는가? (객체가 아니라 문자열)",
        "decompose_command에서 LLM 응답을 json.loads로 파싱했는가? 예외를 try/except로 감쌌는가?",
        "LLM 파싱 실패 시 _fallback_plan으로 폴백되는가? (프로그램이 죽지 않음)",
        "step_sort가 블록을 색깔(red/green/blue)별로 올바르게 그룹화하는가?",
        "step_pick_place가 SAFE_Z로 올라간 뒤 이동하는가? (블록 충돌 방지)",
        "흡착 ON 후에 들어올리고, 목적지 도착 후에 흡착 OFF 하는가? (순서)",
        "각 이동 전에 safety.check_move로 작업영역을 검사하는가?",
        "계획은 '사람 검토 승인' 후에만 실행되는가? (안전 게이트)",
        "종료 시 로봇 연결을 해제(disconnect/close)했는가?",
        "CURRICULUM_FORCE_MOCK=1 로 키·하드웨어 없이 끝까지 실행되는가?",
    ])

    doc.page_break()

    # ── 강사용 정답키 ──────────────────────────────────────────────
    doc.heading("[강사용 정답키]", level=1)
    doc.para("※ 이 페이지는 강사용입니다. 학생 배포 시 제거하세요.", bold=True)

    doc.heading("탐구 질문 정답", level=2)
    doc.para("A1. 5단계가 숨어 있음 — ① 감지(detect): 블록 위치/색 인식 → ② 분류(sort): 색깔별 그룹화 → "
             "③ 집기/옮기기(pick_place): 색깔 칸으로 이동 → ④ (반복) → ⑤ 복귀(home).")
    doc.para("A2. STT 입력 = 음성(오디오 파형/마이크 신호), 출력 = 텍스트(문자열) 명령.")
    doc.para("A3. LLM은 복합 명령을 기계가 실행 가능한 '작은 단계 목록'으로 구조화하기 위해 JSON 계획을 반환한다. "
             "JSON은 단계·인자를 명확히 표현해 파싱·검증·순차 실행이 쉽다. 바로 실행하면 잘못된/위험한 계획을 "
             "거를 기회가 없다.")
    doc.para("A4. LLM 계획은 오류·환각·위험 동작을 포함할 수 있으므로, 자율 실행 전에 사람이 검토·승인하는 "
             "'안전 게이트'를 둔다(SFR-002). mock은 자동 승인, 실수업은 input() 기반 승인.")

    doc.heading("실험 결과 기록표 — 예시 정답(mock 기준)", level=2)
    doc.table(
        ["#", "입력 명령", "LLM 분해 단계(plan)", "실행 단계", "이동 블록"],
        [
            ["1", "블록들을 색깔별로 정리해", "detect → sort → pick_place → home", "4", "3 (red/green/blue)"],
            ["4", "(LLM 실패 가정)", "_fallback_plan: detect→sort→pick_place→home(결정적)", "4", "3"],
        ],
    )
    doc.para("※ mock 데모는 red/green/blue 블록 3개를 정상 이동하고 exit 0으로 종료한다.")

    doc.heading("알고리즘 순서도 정답", level=2)
    doc.table(
        ["빈칸", "정답", "설명"],
        [
            ["①", "listen_command (STT)", "음성 → 텍스트 변환 (Whisper, mock)"],
            ["②", "decompose_command (LLM)", "텍스트 → JSON 단계 계획 분해 (Claude, mock)"],
            ["③", "review_plan (사람 검토)", "안전 게이트: 승인된 계획만 실행"],
            ["④", "step_sort", "감지된 블록을 색깔별로 그룹화"],
            ["⑤", "step_home", "작업 종료 후 원점(홈) 복귀"],
        ],
    )
    doc.para("보너스 정답: safety.check_move  (매 이동 직전 작업영역 검사)")

    doc.heading("디버깅 체크리스트 — 핵심 채점 포인트", level=2)
    doc.para("1) json.loads 예외를 try/except로 감싸 _fallback_plan으로 폴백  "
             "2) 사람 검토 승인 후에만 execute_plan 호출  "
             "3) 모든 이동 전 safety.check_move  "
             "4) 흡착 순서(ON→들기→이동→OFF)  "
             "5) SAFE_Z 경유 이동  "
             "6) 종료 시 연결 해제. 이 6가지가 모두 충족되면 solution과 동일 동작.")

    doc.heading("참고 — 핵심 코드 흐름(solution)", level=2)
    doc.code(
        "text = listen_command(audio, stt)          # ① STT 음성→텍스트\n"
        "plan = decompose_command(text, llm)        # ② LLM 텍스트→JSON 계획\n"
        "if review_plan(plan, approver):            # ③ 안전 게이트(사람 검토)\n"
        "    execute_plan(plan, bot, cam)           # ④ 단계 순차 실행\n"
        "# 실행기: step_detect→step_sort→step_pick_place→step_home\n"
        "# _safe_move() 가 매 이동 전 safety.check_move 로 작업영역 검사"
    )

    path = os.path.join(OUT_DIR, "활동지.docx")
    return doc.save(path)


if __name__ == "__main__":
    p1 = build_lesson_plan()
    p2 = build_worksheet()
    for p in (p1, p2):
        size = os.path.getsize(p) if os.path.exists(p) else -1
        print(f"[생성완료] {p}  ({size} bytes)")
