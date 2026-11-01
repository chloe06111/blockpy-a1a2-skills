"""docx_builder — python-docx 래퍼로 교육 문서(.docx)를 일관된 표지/스타일로 생성한다.

목적
----
국립부산과학관 두봇(Dobot) 커리큘럼의 강사 매뉴얼·차시 교안·체크리스트 등을
코드로 손쉽게 생성하기 위한 얇은 래퍼다. 표지(머리말/트랙/차시), 표 스타일,
코드 단락(고정폭 글꼴)을 한 곳에서 통일해 문서 품질을 일정하게 유지한다.

사용법
------
    from common.docx_builder import DocxBuilder

    doc = DocxBuilder("두봇 라이트 픽앤플레이스", subtitle="기초 트랙 · 3차시")
    doc.heading("학습 목표", level=1)
    doc.para("석션컵으로 블록을 집어 옮기는 동작을 이해한다.")
    doc.table(["단계", "동작"], [["1", "물체 위로 이동"], ["2", "흡착 ON"]])
    doc.checklist(["전원 직후 홈 실행", "작업 공간 확보", "속도 50% 이하"])
    doc.code("device.move_to(200, 0, 50, 0, wait=True)")
    doc.page_break()
    doc.save("교안.docx")

설계 메모
--------
- python-docx 가 설치되어 있다고 가정한다(계약서 명시). 다만 하드웨어/키 없는
  환경 정책(ADR-0004)에 맞춰, import 실패 시에도 모듈 자체는 임포트되도록
  try/except로 감싸 친절한 한국어 안내를 남긴다(실제 사용 시 설치를 요구).
- 로봇 제어 모듈이 아니므로 런타임 하드웨어 의존성은 없다. 자가 데모는
  샘플 문서 1개를 임시 경로에 저장한다(저장 경로 출력, 실패는 무시).

인터페이스 계약: deliverables/pm/CONTRACTS.md 의 common/docx_builder.py 시그니처.
"""

from __future__ import annotations  # 타입 힌트 문자열화(구버전 파이썬 호환)

import os
import tempfile

# ── python-docx 임포트(설치 가정) ──────────────────────────────────
# 정책상 설치되어 있지만, 무하드웨어/무키 환경에서도 import 자체는 깨지지 않도록
# try/except로 감싸 폴백한다. 미설치 시 실제 메서드 호출에서 친절히 안내.
try:
    from docx import Document  # 문서 객체 생성
    from docx.shared import Pt, RGBColor, Inches  # 글꼴 크기/색/길이 단위
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # 단락 정렬
    from docx.enum.table import WD_TABLE_ALIGNMENT  # 표 정렬
    from docx.oxml.ns import qn  # OOXML 네임스페이스 한정자(셀 음영 등 저수준 제어)
    from docx.oxml import OxmlElement  # 저수준 XML 요소 생성
    _DOCX_AVAILABLE = True  # 사용 가능 플래그
except Exception as _e:  # noqa: BLE001 — 어떤 임포트 오류든 폴백
    Document = None  # type: ignore
    _DOCX_AVAILABLE = False
    _DOCX_IMPORT_ERROR = _e  # 나중에 안내 메시지에 사용

# ── 문서 전반 스타일 상수(한 곳에서 통일) ──────────────────────────
HEADER_TEXT = "국립부산과학관 · 두봇(Dobot) 코딩 교육"  # 모든 문서 공통 머리말
BRAND_COLOR = (0x1F, 0x4E, 0x79)  # 진한 청색(표지/제목 강조용 RGB)
MONO_FONT = "Consolas"  # 코드 단락 고정폭 글꼴(한글 환경 가용)
BODY_FONT = "맑은 고딕"  # 본문 기본 글꼴
TABLE_HEADER_BG = "1F4E79"  # 표 머리행 음영(16진 RGB 문자열)


def _require_docx() -> None:
    """python-docx 미설치 시 학생/강사가 이해할 친절한 한국어 예외를 던진다."""
    if not _DOCX_AVAILABLE:
        # 설치 명령을 함께 안내해 막힘 없이 진행하도록 돕는다.
        raise RuntimeError(
            "python-docx 가 설치되어 있지 않습니다. 다음 명령으로 설치하세요:\n"
            "    pip install python-docx\n"
            f"(원인: {_DOCX_IMPORT_ERROR!r})"
        )


class DocxBuilder:
    """일관된 표지/스타일을 가진 .docx 문서를 단계적으로 쌓아 만드는 빌더.

    계약(CONTRACTS.md):
        __init__(title, subtitle="")
        heading(text, level=1); para(text, bold=False)
        table(headers, rows); checklist(items); code(src, lang="python")
        page_break(); save(path)
    """

    def __init__(self, title: str, subtitle: str = "") -> None:
        """문서를 만들고 표지(머리말/제목/부제: 트랙·차시)를 그린다.

        Args:
            title: 문서 제목(표지 큰 글씨).
            subtitle: 부제. 보통 "기초 트랙 · 3차시" 처럼 트랙/차시를 표기.
        """
        _require_docx()  # 미설치면 여기서 친절히 중단

        self.title = title  # 표지/속성에 사용할 제목 보관
        self.subtitle = subtitle  # 트랙·차시 표기 보관
        self.doc = Document()  # 빈 docx 문서 생성

        self._setup_base_style()  # 본문 기본 글꼴 등 전역 스타일 적용
        self._setup_header()  # 페이지 머리말(국립부산과학관) 설정
        self._build_cover()  # 표지(제목/부제/구분선) 작성

    # ── 내부 헬퍼: 전역 스타일/머리말/표지 ──────────────────────

    def _setup_base_style(self) -> None:
        """문서 기본(Normal) 스타일의 글꼴을 한글 본문용으로 지정한다."""
        normal = self.doc.styles["Normal"]  # 기본 단락 스타일
        normal.font.name = BODY_FONT  # 라틴 글꼴 이름
        normal.font.size = Pt(11)  # 본문 크기 11pt
        # 한글(East Asian) 글꼴은 별도 속성으로 지정해야 적용된다.
        rpr = normal.element.get_or_add_rPr()  # 실행 속성 요소
        rfonts = rpr.get_or_add_rFonts()  # 글꼴 지정 요소
        rfonts.set(qn("w:eastAsia"), BODY_FONT)  # 동아시아 글꼴 지정

    def _setup_header(self) -> None:
        """모든 페이지 상단에 공통 머리말을 넣는다(브랜드 일관성)."""
        section = self.doc.sections[0]  # 첫 섹션(문서 전체)
        header = section.header  # 머리말 영역
        p = header.paragraphs[0]  # 머리말 기본 단락 재사용
        p.text = HEADER_TEXT  # 머리말 문구
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT  # 우측 정렬
        run = p.runs[0]  # 방금 넣은 텍스트 실행
        run.font.size = Pt(9)  # 머리말은 작게
        run.font.color.rgb = RGBColor(*BRAND_COLOR)  # 브랜드 색

    def _build_cover(self) -> None:
        """표지: (브랜드 라벨) + 큰 제목 + 부제(트랙·차시) + 구분선."""
        # 표지 상단 여백을 줘 제목이 가운데쯤 오도록 한다.
        spacer = self.doc.add_paragraph()  # 여백용 빈 단락
        spacer.add_run("\n\n\n")  # 줄바꿈으로 위쪽 공간 확보

        # 브랜드 라벨(작은 글씨)
        label = self.doc.add_paragraph()  # 라벨 단락
        label.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 가운데 정렬
        lrun = label.add_run("국립부산과학관 두봇 교육 자료")  # 라벨 문구
        lrun.font.size = Pt(12)  # 라벨 크기
        lrun.font.color.rgb = RGBColor(*BRAND_COLOR)  # 브랜드 색
        lrun.bold = True  # 강조

        # 큰 제목
        ttl = self.doc.add_paragraph()  # 제목 단락
        ttl.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 가운데 정렬
        trun = ttl.add_run(self.title)  # 제목 텍스트
        trun.font.size = Pt(28)  # 큰 글씨
        trun.bold = True  # 굵게
        trun.font.color.rgb = RGBColor(0x20, 0x20, 0x20)  # 거의 검정

        # 부제(트랙·차시) — 있을 때만
        if self.subtitle:
            sub = self.doc.add_paragraph()  # 부제 단락
            sub.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 가운데 정렬
            srun = sub.add_run(self.subtitle)  # 부제 텍스트
            srun.font.size = Pt(14)  # 부제 크기
            srun.font.color.rgb = RGBColor(0x55, 0x55, 0x55)  # 회색

        # 구분선 역할의 가로줄(밑줄 친 공백)
        rule = self.doc.add_paragraph()  # 구분선 단락
        rule.alignment = WD_ALIGN_PARAGRAPH.CENTER  # 가운데 정렬
        rrun = rule.add_run("―" * 20)  # 가로 막대 문자
        rrun.font.color.rgb = RGBColor(*BRAND_COLOR)  # 브랜드 색

        self.page_break()  # 표지 이후 본문은 새 페이지에서 시작

    # ── 공개 API(계약) ──────────────────────────────────────────

    def heading(self, text: str, level: int = 1) -> "DocxBuilder":
        """제목(머리글)을 추가한다.

        Args:
            text: 머리글 문구.
            level: 1~9 단계(1이 가장 큼). 범위를 벗어나면 안전하게 보정.
        """
        # python-docx는 level 0(=Title)도 지원하나, 본문 머리글은 1~9로 제한.
        safe_level = max(1, min(int(level), 9))  # 안전 범위로 클램프
        h = self.doc.add_heading(text, level=safe_level)  # 머리글 추가
        # 머리글에도 한글 글꼴/브랜드 색을 적용해 일관성 유지.
        for run in h.runs:  # 머리글 내 모든 실행
            run.font.color.rgb = RGBColor(*BRAND_COLOR)  # 브랜드 색
        return self  # 메서드 체이닝 지원

    def para(self, text: str, bold: bool = False) -> "DocxBuilder":
        """본문 단락을 추가한다.

        Args:
            text: 단락 내용.
            bold: True면 굵게 표시(소제목/강조용).
        """
        p = self.doc.add_paragraph()  # 단락 생성
        run = p.add_run(text)  # 텍스트 실행 추가
        run.bold = bold  # 굵기 적용
        return self  # 체이닝

    def table(self, headers: list, rows: list) -> "DocxBuilder":
        """머리행이 강조된 표를 추가한다.

        Args:
            headers: 열 제목 리스트. 예: ["단계", "동작"].
            rows: 각 행을 나타내는 리스트들의 리스트. 셀 개수가 headers보다
                  적으면 빈칸으로, 많으면 잘려서 표시된다.
        """
        n_cols = len(headers)  # 열 개수 기준
        if n_cols == 0:  # 빈 헤더 방어
            raise ValueError("표에는 최소 1개 이상의 열 제목(headers)이 필요합니다.")

        # 머리행 1줄을 포함해 표 생성. 'Table Grid'로 모든 칸에 테두리 적용.
        table = self.doc.add_table(rows=1, cols=n_cols)  # 표 생성(머리행만)
        try:
            table.style = "Table Grid"  # 격자 스타일(테두리)
        except KeyError:
            pass  # 일부 템플릿에 스타일이 없을 수 있어 무시
        table.alignment = WD_TABLE_ALIGNMENT.CENTER  # 표 가운데 정렬

        # 머리행 채우기 + 음영/굵게 스타일.
        hdr_cells = table.rows[0].cells  # 머리행 셀들
        for i, htext in enumerate(headers):  # 각 열 제목
            cell = hdr_cells[i]  # 해당 셀
            cell.text = str(htext)  # 텍스트 설정
            self._shade_cell(cell, TABLE_HEADER_BG)  # 음영 적용
            # 머리행 글자는 흰색·굵게로 가독성 확보.
            for p in cell.paragraphs:  # 셀 내 단락
                for run in p.runs:  # 단락 내 실행
                    run.bold = True  # 굵게
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)  # 흰색

        # 데이터 행 채우기.
        for row in rows:  # 각 데이터 행
            cells = table.add_row().cells  # 새 행의 셀들
            for i in range(n_cols):  # 열 개수만큼만(초과 셀 무시)
                # row가 짧으면 빈 문자열로 채워 IndexError 방지.
                value = row[i] if i < len(row) else ""  # 안전 인덱싱
                cells[i].text = str(value)  # 셀 텍스트 설정
        return self  # 체이닝

    def checklist(self, items: list) -> "DocxBuilder":
        """체크박스(☐) 목록을 추가한다(안전 점검표·준비물 등).

        Args:
            items: 점검 항목 문자열 리스트.
        """
        for item in items:  # 각 항목
            p = self.doc.add_paragraph()  # 항목 단락
            # 빈 체크박스 기호 + 공백 + 항목 텍스트.
            p.add_run("☐ ")  # ☐ (BALLOT BOX)
            p.add_run(str(item))  # 항목 내용
        return self  # 체이닝

    def code(self, src: str, lang: str = "python") -> "DocxBuilder":
        """코드 단락을 고정폭 글꼴 + 연회색 배경으로 추가한다.

        Args:
            src: 코드 문자열(여러 줄 가능).
            lang: 언어 라벨(현재는 표시용 메타데이터, 강조엔 영향 없음).
        """
        p = self.doc.add_paragraph()  # 코드용 단락
        # 줄바꿈을 보존하기 위해 한 실행(run) 안에서 add_break로 줄을 나눈다.
        lines = str(src).splitlines() or [""]  # 빈 코드도 1줄로 처리
        run = p.add_run()  # 코드 실행 생성
        run.font.name = MONO_FONT  # 고정폭 글꼴(라틴)
        # 동아시아 글꼴도 고정폭으로 맞춰 한글 주석 정렬 깨짐을 줄인다.
        rpr = run._element.get_or_add_rPr()  # 실행 속성
        rfonts = rpr.get_or_add_rFonts()  # 글꼴 요소
        rfonts.set(qn("w:eastAsia"), MONO_FONT)  # 동아시아 글꼴
        run.font.size = Pt(10)  # 코드 크기
        run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)  # 진회색

        for i, line in enumerate(lines):  # 각 코드 줄
            if i > 0:  # 첫 줄 제외하고
                run.add_break()  # 줄바꿈 삽입
            run.add_text(line)  # 줄 내용 추가

        # 단락 배경(연회색 음영)으로 코드 블록임을 시각적으로 구분.
        self._shade_paragraph(p, "F2F2F2")  # 옅은 회색
        return self  # 체이닝

    def page_break(self) -> "DocxBuilder":
        """페이지 나누기를 삽입한다(다음 내용은 새 페이지에서 시작)."""
        self.doc.add_page_break()  # 페이지 브레이크
        return self  # 체이닝

    def save(self, path: str) -> str:
        """문서를 지정 경로에 저장하고, 저장 경로를 반환한다.

        Args:
            path: 저장할 .docx 경로. 상위 폴더가 없으면 생성한다.

        Returns:
            저장된 절대 경로 문자열.
        """
        # 상위 디렉터리가 없으면 만들어 저장 실패를 예방한다.
        parent = os.path.dirname(os.path.abspath(path))  # 상위 폴더
        if parent and not os.path.isdir(parent):  # 없으면
            os.makedirs(parent, exist_ok=True)  # 생성

        # 문서 핵심 속성(제목/부제)도 채워 파일 정보에 반영.
        self.doc.core_properties.title = self.title  # 제목 속성
        if self.subtitle:  # 부제가 있으면
            self.doc.core_properties.subject = self.subtitle  # 주제 속성

        self.doc.save(path)  # 실제 저장
        return os.path.abspath(path)  # 절대 경로 반환

    # ── 저수준 스타일 헬퍼(셀/단락 음영) ────────────────────────

    @staticmethod
    def _shade_cell(cell, hex_color: str) -> None:
        """표 셀에 배경색(음영)을 적용한다(OOXML 직접 조작)."""
        tc_pr = cell._tc.get_or_add_tcPr()  # 셀 속성 요소
        shd = OxmlElement("w:shd")  # 음영 요소 생성
        shd.set(qn("w:val"), "clear")  # 패턴 없음
        shd.set(qn("w:color"), "auto")  # 전경색 자동
        shd.set(qn("w:fill"), hex_color)  # 채움색(16진)
        tc_pr.append(shd)  # 셀 속성에 추가

    @staticmethod
    def _shade_paragraph(paragraph, hex_color: str) -> None:
        """단락 전체에 배경색(음영)을 적용한다(코드 블록 구분용)."""
        p_pr = paragraph._p.get_or_add_pPr()  # 단락 속성 요소
        shd = OxmlElement("w:shd")  # 음영 요소
        shd.set(qn("w:val"), "clear")  # 패턴 없음
        shd.set(qn("w:color"), "auto")  # 전경색 자동
        shd.set(qn("w:fill"), hex_color)  # 채움색
        p_pr.append(shd)  # 단락 속성에 추가


# ── 자가 데모(mock) — 무하드웨어/무키 실행 가능 ──────────────────
if __name__ == "__main__":
    # 샘플 문서 1개를 임시 경로에 만들어 저장 경로를 출력한다.
    # python-docx 미설치 등 어떤 실패가 나도 데모는 조용히 넘어간다(정책).
    try:
        # 빌더 생성: 표지에 제목/트랙·차시 부제가 자동으로 들어간다.
        doc = DocxBuilder(
            "두봇 라이트 픽 앤 플레이스 기초",
            subtitle="기초 트랙 · 3차시 · 강사용 교안",
        )

        doc.heading("학습 목표", level=1)  # 1단계 머리글
        doc.para("석션컵으로 블록을 집어 다른 위치로 옮기는 픽앤플레이스 동작을 이해한다.")
        doc.para("핵심 개념", bold=True)  # 굵은 소제목
        doc.para("전원 직후에는 반드시 홈(원점복귀)을 먼저 실행해 좌표 신뢰성을 확보한다.")

        doc.heading("동작 순서", level=2)  # 2단계 머리글
        doc.table(
            ["단계", "동작", "비고"],  # 표 머리행
            [
                ["1", "물체 위로 이동", "z를 안전 높이로"],
                ["2", "내려가기", "INC 모드로 소량 테스트 권장"],
                ["3", "흡착 ON", "suck(True)"],
                ["4", "들어 목적지로 이동", ""],
                ["5", "흡착 OFF(놓기)", "suck(False)"],
            ],
        )

        doc.heading("안전 점검표", level=2)  # 체크리스트 머리글
        doc.checklist(
            [
                "전원을 켠 직후 홈(SetHOMECmd)을 실행했는가?",
                "로봇 주변 작업 공간을 비웠는가?",
                "속도를 50% 이하로 낮춰 먼저 검증했는가?",
                "종료 시 연결을 해제(disconnect/close)했는가?",
            ]
        )

        doc.heading("예제 코드", level=2)  # 코드 머리글
        doc.code(
            "from common.dobot_ctl import get_robot  # 로봇 컨트롤러\n"
            "\n"
            "with get_robot() as bot:          # 종료 시 자동 안전정지+해제\n"
            "    bot.home()                    # 전원 직후 홈 필수\n"
            "    bot.move_to(200, 0, 50)       # 물체 위로\n"
            "    bot.move_to(200, 0, -30)      # 내려가기\n"
            "    bot.suck(True)                # 흡착 ON\n"
            "    bot.move_to(200, 0, 50)       # 들기\n"
            "    bot.move_to(100, 150, 50)     # 목적지로\n"
            "    bot.suck(False)               # 놓기"
        )

        doc.page_break()  # 다음 내용은 새 페이지
        doc.para("이상으로 3차시 교안을 마칩니다.")

        # 임시 디렉터리에 저장(저장 경로 출력).
        out_path = os.path.join(tempfile.gettempdir(), "docx_builder_demo.docx")
        saved = doc.save(out_path)  # 저장 후 절대 경로
        print(f"[docx_builder] 데모 문서를 저장했습니다: {saved}")
    except Exception as exc:  # noqa: BLE001 — 데모 실패는 무시(정책)
        # 무하드웨어/무키 또는 미설치 환경에서도 모듈 동작 확인이 목적이므로
        # 실패해도 프로그램을 중단하지 않고 안내만 남긴다.
        print(f"[docx_builder] 데모를 건너뜁니다(무시 가능): {exc!r}")
