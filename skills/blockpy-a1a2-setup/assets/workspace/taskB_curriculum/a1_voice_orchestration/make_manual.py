"""make_manual.py — 차시 A1 "LLM 오케스트레이터 — 음성 명령 다단계 분해·실행"
강사용 매뉴얼(강사매뉴얼.docx)을 공통 빌더(common.docx_builder.DocxBuilder)로 생성한다.

목적 (COR-004 · 강사 자립)
--------------------------
강사가 이 매뉴얼 1권만으로 110분 수업을 처음부터 끝까지 운영할 수 있도록,
차시 개요·운영 팁·실습 단계별 예상 오류 대응·하드웨어 트러블슈팅·Q&A 대응표·
평가 루브릭·학생 안전 주의를 모두 담는다.

근거 코드/문서 (같은 폴더·common)
---------------------------------
- solution.py            : 모범답안 파이프라인(listen_command→decompose_command→review_plan→execute_plan)
- scaffold.py            : 학생 시작 코드(TODO 4곳)
- hardware_test.py       : turnkey 3회 구동 검증(--port COM3 / --mock)
- 강의계획서.docx        : 5E 타임테이블·성취기준·평가 방법(make_docs.py)
- common/safety.py       : check_move / clamp_move / WORKSPACE
- common/dobot_ctl.py    : get_robot / RobotController(자동 mock 폴백)

차시: A1 · 하이브리드(Advanced) · 110분
실행:  python a1_voice_orchestration/make_manual.py
        (또는 CURRICULUM_FORCE_MOCK=1 python a1_voice_orchestration/make_manual.py)
"""

# ── sys.path 부트스트랩 2줄 (taskB_curriculum 을 import 루트로 추가) ──────────
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.docx_builder import DocxBuilder

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
TITLE = "LLM 오케스트레이터 — 음성 명령 다단계 분해·실행"
SUBTITLE = "하이브리드(Advanced) 트랙 · 차시 A1 · 110분 · 강사용 매뉴얼"


def build_manual() -> str:
    doc = DocxBuilder(TITLE, subtitle=SUBTITLE)

    # =====================================================================
    # 0) 이 매뉴얼 사용법
    # =====================================================================
    doc.heading("0. 이 매뉴얼 사용법 (강사 자립 가이드)", level=1)
    doc.para(
        "이 한 권으로 110분 수업을 단독 운영할 수 있도록 구성했습니다. "
        "수업 전 '1. 차시 개요'와 '4. 하드웨어 트러블슈팅'을 먼저 읽고, "
        "실습 중에는 '3. 실습 단계별 예상 오류'와 '6. Q&A 대응표'를 펼쳐 두세요. "
        "하드웨어가 없거나 막히면 즉시 mock 모드로 전환해 수업 흐름을 유지합니다."
    )
    doc.para("핵심 안전 원칙 (SFR-002): LLM이 만든 계획은 '사람 검토(승인) 후에만' 실행된다.", bold=True)
    doc.para("핵심 무중단 원칙 (ADR-0004): 키·하드웨어가 없어도 mock으로 끝까지 동작한다.", bold=True)

    # =====================================================================
    # 1) 차시 개요
    # =====================================================================
    doc.heading("1. 차시 개요", level=1)
    doc.para(
        "사람의 한 마디 음성 명령(예: \"블록들을 색깔별로 정리해\")을 STT(Whisper)로 텍스트로 바꾸고, "
        "LLM(오케스트레이터)이 그 복합 명령을 작은 단계들(감지→분류→픽앤플레이스→복귀)로 분해(plan)하며, "
        "사람이 계획을 검토(안전 게이트)한 뒤, 로봇이 단계를 차례로 실행하며 진행을 보고하는 "
        "'파이프라인/오케스트레이션' 개념을 체험합니다."
    )
    doc.heading("1.1 한눈에 보는 파이프라인", level=2)
    doc.table(
        ["순서", "단계", "함수(solution.py)", "입력 → 출력"],
        [
            ["①", "듣기(STT)", "listen_command", "음성 파일 → 텍스트 명령"],
            ["②", "분해(LLM)", "decompose_command", "텍스트 → JSON 단계 계획[plan]"],
            ["③", "검토(안전 게이트)", "review_plan", "계획 → 승인/거부(bool)"],
            ["④", "실행(순차)", "execute_plan", "계획 → detect→sort→pick_place→home"],
        ],
    )
    doc.heading("1.2 학습 목표 요약", level=2)
    doc.para("1) STT→LLM 분해→검토→실행 오케스트레이션 구조 설명")
    doc.para("2) LLM이 복합 명령을 JSON 단계 목록으로 분해·검증")
    doc.para("3) 사람 검토(안전 게이트)의 필요성 설명·구현")
    doc.para("4) 분해된 계획을 단계 실행기로 순차 실행·진행 보고")
    doc.para("5) LLM 분해 실패 시 결정적 폴백(_fallback_plan)으로 방어적 대처")

    doc.heading("1.3 110분 운영 흐름(5E) 빠른 참조", level=2)
    doc.table(
        ["단계", "시간", "강사 핵심 행동"],
        [
            ["Engage", "15분", "음성 데모 시청 → \"한 문장에 몇 작업이 숨었나?\" 발문, PBL 미션 제시"],
            ["Explore", "25분", "mock으로 solution.py 실행, STT 텍스트·LLM JSON 계획을 활동지에 기록"],
            ["Explain", "20분", "4단계 파이프라인 강의, JSON 스키마·실행기·안전 게이트 설명"],
            ["Elaborate", "35분", "scaffold.py TODO 4곳 페어코딩, 강사 순회 지원"],
            ["Evaluate", "15분", "hardware_test.py 3회 구동(위험 0건), 폴백 시연, 루브릭 작성"],
        ],
    )

    doc.page_break()

    # =====================================================================
    # 2) 수업 운영 팁
    # =====================================================================
    doc.heading("2. 수업 운영 팁", level=1)
    doc.heading("2.1 수업 전 (셋업 체크리스트)", level=2)
    doc.checklist([
        "각 PC에서 'CURRICULUM_FORCE_MOCK=1 python a1_voice_orchestration/solution.py' 가 끝까지 도는지 사전 확인",
        "python-docx / pydobot / opencv-python 설치 여부 확인 (없으면 자동 mock 폴백되나 비전·로봇은 mock)",
        "웹캠 거치대 고정·조명 균일화 (색 검출 안정화), 흰색/단색 매트 깔기",
        "색 블록(red/green/blue) 배치, 드롭존(red/green/blue 칸) mm 좌표 라벨 부착",
        "비상 정지 버튼 위치를 모든 모둠이 알도록 안내",
        "전원 직후 home() 먼저 실행 — 좌표 신뢰성 확보 습관화",
    ])
    doc.heading("2.2 수업 중 (진행 팁)", level=2)
    doc.checklist([
        "Logic-First: 코드 문법보다 '무엇을 어떤 순서로'(계획) 먼저 그리게 한다 — 순서도 빈칸 채우기 활용",
        "Explore에서 입력 명령을 바꿔 LLM 계획 변화를 관찰시키되, mock은 결정적 폴백이라 같은 계획이 나올 수 있음을 미리 설명",
        "Elaborate 페어코딩: TODO 1곳 완성마다 mock 실행으로 즉시 피드백 — 큰 덩어리 한 번에 X",
        "안전 게이트(review_plan)는 '왜 사람이 승인하나'를 항상 말로 묻고 답하게 한다",
        "막힌 모둠은 활동지 '디버깅 체크리스트' 11항목으로 자가 점검 유도",
    ])
    doc.heading("2.3 시간이 부족/남을 때", level=2)
    doc.table(
        ["상황", "대응"],
        [
            ["Elaborate가 길어짐", "JSON 파싱(decompose_command) 1곳만 직접 완성시키고 나머지는 solution 비교로 설명 전환"],
            ["하드웨어 셋업 지연", "전 모둠 mock 모드로 통일해 진도 유지, 실하드웨어는 Evaluate에서 시연만"],
            ["시간이 남음", "입력 명령을 다양화해 LLM 계획 비교, 폴백 트리거(잘못된 JSON 가정) 실험 추가"],
        ],
    )

    # =====================================================================
    # 3) 실습 단계별 예상 오류 및 대응
    # =====================================================================
    doc.heading("3. 실습 단계별 예상 오류 및 대응", level=1)
    doc.para("scaffold.py의 TODO를 구현하는 Elaborate 단계에서 가장 자주 나오는 오류입니다.", bold=True)
    doc.table(
        ["단계/함수", "증상·오류 메시지", "원인", "대응"],
        [
            ["환경 부트스트랩",
             "ModuleNotFoundError: No module named 'common'",
             "스크립트를 common 상위(taskB_curriculum)가 아닌 곳에서 실행",
             "파일 상단 sys.path 부트스트랩 2줄 유지, 또는 taskB_curriculum 폴더에서 실행"],
            ["①listen_command",
             "계획 분해가 이상하거나 TypeError",
             "STT 결과(문자열)가 아니라 객체/None을 반환",
             "stt.transcribe(audio_path)의 반환 '문자열'을 그대로 return 하는지 확인"],
            ["②decompose_command",
             "json.JSONDecodeError / ValueError",
             "LLM 응답에서 [ ] 구간 추출·파싱 미흡, 예외 미처리",
             "raw.index('[')~rindex(']')로 잘라 json.loads, try/except로 감싸 _fallback_plan 폴백"],
            ["②decompose_command",
             "프로그램이 죽음(예외 전파)",
             "파싱 실패 시 폴백 경로가 없음",
             "except (ValueError, json.JSONDecodeError) 후 return _fallback_plan(command)"],
            ["③review_plan",
             "검토 없이 바로 실행됨",
             "승인 결과를 확인하지 않고 execute_plan 호출",
             "if not review_plan(plan, approver): return — 승인된 계획만 실행"],
            ["④step_sort",
             "분류가 비거나 KeyError",
             "색상 키 그룹화 누락",
             "grouped.setdefault(b['color'], []).append(b) 로 색깔별 묶기"],
            ["④step_pick_place",
             "블록끼리 충돌/끌림",
             "SAFE_Z 경유 없이 수평 이동",
             "SAFE_Z(80mm)로 올린 뒤 이동, 픽/플 위치에서만 하강(PICK_Z=5)"],
            ["④step_pick_place",
             "블록을 못 집거나 못 놓음",
             "흡착 순서 오류",
             "순서 고정: 하강→suck(True)→상승→이동→하강→suck(False)→상승"],
            ["④step_pick_place",
             "'red 칸이 없어 건너뜁니다'",
             "DROP_ZONES에 해당 색 없음",
             "감지 색과 DROP_ZONES 키 일치 확인(red/green/blue/yellow)"],
            ["⑤step_home",
             "종료 후 흡착이 켜진 채 남음",
             "home 전에 suck(False) 누락",
             "step_home에서 suck(False) 후 home() 호출"],
            ["전체 실행",
             "한글이 깨져 출력(cp949)",
             "Windows 콘솔 인코딩",
             "sys.stdout.reconfigure(encoding='utf-8') (solution에 이미 포함)"],
            ["전체 실행",
             "키/하드웨어 없어 멈춤",
             "실모드 강제 시도",
             "CURRICULUM_FORCE_MOCK=1 로 mock 강제 — 끝까지 동작(ADR-0004)"],
        ],
    )

    doc.page_break()

    # =====================================================================
    # 4) 하드웨어 트러블슈팅 가이드
    # =====================================================================
    doc.heading("4. 하드웨어 트러블슈팅 가이드", level=1)
    doc.para(
        "원칙: 어떤 하드웨어 문제든 수업을 멈추지 않습니다. 연결 실패 시 dobot_ctl이 "
        "친절한 경고를 남기고 자동으로 mock 모드로 폴백하므로, 먼저 mock으로 흐름을 잇고 "
        "아래 표로 원인을 좁혀 가세요.", bold=True,
    )

    doc.heading("4.1 연결 / 전원", level=2)
    doc.table(
        ["증상", "점검·원인", "대응"],
        [
            ["전원이 안 들어옴 / LED 무점등", "어댑터 분리, 전원 스위치 OFF", "정품 어댑터 연결·스위치 ON, 다른 콘센트 시도"],
            ["연결 직후 좌표가 엉뚱함", "전원 직후 홈 미실행", "bot.home() 먼저 실행 — 좌표계 원점 재설정"],
            ["'로봇 연결에 실패했습니다 … mock 모드로 전환'", "포트·드라이버 문제로 자동 폴백됨", "수업은 mock으로 진행, 4.2 COM 점검 병행"],
            ["연결은 되나 명령 무반응", "펌웨어/통신 상태 이상", "전원 재투입(off 5초 후 on)→home, USB 케이블 교체"],
        ],
    )

    doc.heading("4.2 COM 포트 / 시리얼", level=2)
    doc.table(
        ["증상", "점검·원인", "대응"],
        [
            ["포트를 못 찾음(자동탐지 실패)", "list_ports.comports()가 비어 첫 포트 선택 불가", "--port COM3 처럼 명시 지정, 장치관리자에서 포트 번호 확인"],
            ["SerialException / 접근 거부", "다른 프로그램(DobotStudio 등)이 포트 점유", "점유 프로그램 종료 후 재실행 — 포트는 한 번에 한 프로그램만"],
            ["드라이버 미설치(장치 ! 표시)", "USB-시리얼(CH340 등) 드라이버 없음", "해당 드라이버 설치 후 재연결, USB 재삽입"],
            ["pydobot import 실패", "pydobot 미설치", "pip install pydobot — 단, 미설치면 자동 mock 폴백되어 수업은 진행 가능"],
            ["포트 번호가 매번 바뀜", "USB 허브·포트 변경", "동일 USB 포트 사용 고정, config.DOBOT_PORT 활용"],
        ],
    )

    doc.heading("4.3 좌표 / 작업영역(WORKSPACE)", level=2)
    doc.para(
        "작업영역(common/safety.py): x=(180,320), y=(-150,150), z=(-60,150) mm. "
        "z 하한(-60)보다 더 내려가면 책상/지그 충돌 위험. 이동 직전 check_move로 검사하고, "
        "RobotController가 내부적으로 다시 clamp_move 하므로 이중 안전이 걸립니다.", bold=True,
    )
    doc.table(
        ["증상", "점검·원인", "대응"],
        [
            ["'안전경고(…): …' 출력", "목표 좌표가 WORKSPACE 밖 → check_move 경고", "DROP_ZONES·픽 좌표를 범위 안으로 재보정"],
            ["블록을 살짝 빗나가 집음", "픽셀→로봇 좌표 근사 변환 오차", "웹캠 위치 고정 후 pixel_to_robot/FRAME_W,H, 드롭존 mm 재캘리브레이션(자/줄자)"],
            ["로봇이 칸을 못 맞춤", "DROP_ZONES 좌표가 실제 칸과 불일치", "실제 칸 중심을 mm로 재측정해 DROP_ZONES 갱신"],
            ["좌표가 누적으로 틀어짐", "전원 직후 홈 미실행/스텝 손실", "매 회차 시작 시 home() 실행, 속도 50% 이하로 검증"],
        ],
    )

    doc.heading("4.4 충돌 / 안전 동작", level=2)
    doc.table(
        ["증상", "점검·원인", "대응"],
        [
            ["Z 과다 하강(책상/지그 충돌)", "PICK_Z/드롭 z가 z하한(-60) 미만", "PICK_Z=5, SAFE_Z=80 유지, z 하한 위로만 하강"],
            ["이동 중 다른 블록을 침", "SAFE_Z 경유 없이 수평 이동", "이동은 반드시 SAFE_Z(80mm)에서 수행"],
            ["하드웨어가 갑자기 멈춤", "충돌 보호로 정지", "전원 재투입→home, 주변 장애물 제거, 속도 낮춤"],
            ["흡착이 안 끊겨 블록 끌림", "종료/실패 시 안전정지 누락", "with get_robot() 사용(종료 시 _safe_stop), step_home에서 suck(False)"],
        ],
    )
    doc.para(
        "검증 도구: 'python a1_voice_orchestration/hardware_test.py --port COM3' (또는 --mock). "
        "이동을 가로채 좌표초과/Z과다하강을 집계하고, 3회 모두 성공·위험 0건이면 exit 0(통과)입니다.",
    )

    doc.page_break()

    # =====================================================================
    # 5) (이전 4) Q&A 대응표
    # =====================================================================
    doc.heading("5. Q&A 대응표 (학생 예상 질문)", level=1)
    doc.table(
        ["학생 질문", "강사 답변 핵심"],
        [
            ["LLM이 직접 로봇을 움직이면 안 되나요?",
             "LLM은 환각·오류·위험 동작을 만들 수 있어요. 그래서 '계획'만 만들게 하고, 사람이 검토·승인한 뒤에만 실행합니다(안전 게이트)."],
            ["왜 계획을 JSON으로 받나요?",
             "단계·인자를 명확히 표현해 파싱·검증·순차 실행이 쉽기 때문이에요. 자연어 그대로는 기계가 안전히 실행하기 어렵습니다."],
            ["LLM이 이상한 JSON을 주면요?",
             "_fallback_plan(결정적 표준 계획)으로 폴백합니다. 그래서 프로그램이 죽지 않고 데모가 끝까지 동작해요."],
            ["mock인데 계획이 항상 똑같아요. 정상인가요?",
             "정상입니다. mock은 결정적(같은 입력→같은 출력)이라 폴백 계획이 동일하게 나올 수 있어요. 실제 LLM은 달라질 수 있습니다."],
            ["오케스트레이션이 뭐예요?",
             "여러 작은 작업을 '순서대로 지휘'해 하나의 큰 일을 끝내는 거예요. 공장·물류 로봇이 자연어→계획→순차 실행으로 똑같이 동작합니다."],
            ["왜 SAFE_Z로 올라갔다 이동하나요?",
             "낮게 수평 이동하면 다른 블록과 충돌하니까요. 안전 높이(80mm)로 올린 뒤 이동하고 목표에서만 내려갑니다."],
            ["하드웨어가 없는데 실습할 수 있나요?",
             "네. CURRICULUM_FORCE_MOCK=1 로 STT·LLM·로봇 모두 mock으로 끝까지 동작합니다(ADR-0004)."],
            ["check_move가 위험이라는데 왜 멈추지 않죠?",
             "경고만 남기고, 실제 이동은 컨트롤러가 작업영역 안으로 clamp(보정)해 실행해요. 검사+클램프 이중 안전입니다."],
        ],
    )

    # =====================================================================
    # 6) 평가 루브릭
    # =====================================================================
    doc.heading("6. 평가 루브릭 (채점 기준표)", level=1)
    doc.para("성취기준(AC-A1-1~5)·5E와 연계한 4수준 루브릭입니다. 영역 점수 합 100점.", bold=True)
    doc.table(
        ["평가 영역(배점)", "우수 (A)", "보통 (B)", "미흡 (C)", "연계"],
        [
            ["개념 이해 (20)",
             "파이프라인 4단계 입출력을 도식+구술로 정확히 설명",
             "4단계를 대체로 설명하나 입출력 일부 모호",
             "단계 순서·역할 혼동",
             "AC-A1-1"],
            ["탐구 기록 (15)",
             "명령→계획 매핑을 정확·완결되게 기록, 변화 해석",
             "기록은 했으나 해석/누락 일부",
             "기록 부정확·미완",
             "AC-A1-2"],
            ["구현 완성도 (35)",
             "TODO 4곳이 solution과 동일 동작, 폴백·순서 모두 충족",
             "대부분 동작하나 1~2개 결함(예: 폴백 누락)",
             "핵심 단계 미동작(파싱·픽앤플레이스 실패)",
             "AC-A1-2,3"],
            ["검증/실행 (20)",
             "hardware_test 3/3 통과·위험 0건(exit 0)",
             "1~2회 성공 또는 경미한 경고",
             "실행 실패 또는 위험 다수",
             "AC-A1-4"],
            ["방어적 설계 (10)",
             "폴백 시나리오를 테스트로 증명, 안전 게이트 구현",
             "폴백/게이트 중 일부만 충족",
             "예외 시 프로그램 중단",
             "AC-A1-5"],
        ],
    )
    doc.para(
        "채점 핵심 6포인트(모두 충족 = solution 동일 동작): "
        "1) json.loads 예외 try/except→_fallback_plan  2) 승인 후에만 execute_plan  "
        "3) 매 이동 전 safety.check_move  4) 흡착 순서(ON→들기→이동→OFF)  "
        "5) SAFE_Z 경유 이동  6) 종료 시 연결 해제.",
    )

    # =====================================================================
    # 7) 학생 안전 주의
    # =====================================================================
    doc.heading("7. 학생 안전 주의 사항", level=1)
    doc.checklist([
        "로봇 동작 중에는 작업영역(팔 반경) 안에 손·얼굴을 넣지 않는다.",
        "비상 정지 버튼 위치를 먼저 확인하고, 이상 시 즉시 전원/정지.",
        "전원 직후 반드시 home()을 실행한 뒤 동작을 시작한다(좌표 신뢰성).",
        "처음에는 속도를 50% 이하로 낮춰 동작을 검증한다.",
        "LLM이 만든 계획은 반드시 사람이 검토·승인한 뒤 실행한다(안전 게이트).",
        "흡착 펌프·케이블에 손가락·머리카락이 끼지 않도록 주의한다.",
        "작업대 위 물·음료를 두지 않는다(전기/합선 위험).",
        "실습 종료 시 흡착 OFF·홈 복귀·전원 차단·연결 해제 순으로 정리한다.",
        "이상음·과열·끼임 발생 시 즉시 중단하고 강사를 부른다.",
    ])

    doc.heading("부록 A. 핵심 명령어 빠른 참조", level=2)
    doc.code(
        "# mock 데모(키·하드웨어 없이 끝까지)\n"
        "CURRICULUM_FORCE_MOCK=1 python a1_voice_orchestration/solution.py\n"
        "\n"
        "# 실하드웨어 3회 구동 검증(turnkey)\n"
        "python a1_voice_orchestration/hardware_test.py --port COM3\n"
        "python a1_voice_orchestration/hardware_test.py --mock        # mock 점검\n"
        "\n"
        "# 안전 핵심 값 (common/safety.py)\n"
        "WORKSPACE x=(180,320) y=(-150,150) z=(-60,150) mm   # z 하한 미만 = 충돌 위험\n"
        "SAFE_Z=80  PICK_Z=5   # 이동은 SAFE_Z, 하강은 PICK_Z\n"
        "\n"
        "# 안전 컨텍스트(종료 시 안전정지+해제 보장)\n"
        "with get_robot() as bot:\n"
        "    bot.home(); ...; bot.suck(False)"
    )

    path = os.path.join(OUT_DIR, "강사매뉴얼.docx")
    return doc.save(path)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = build_manual()
    size = os.path.getsize(p) if os.path.exists(p) else -1
    print(f"[생성완료] {p}  ({size} bytes)")
