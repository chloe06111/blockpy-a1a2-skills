---
name: blockpy-a1a2-setup
description: 이 PC 를 국립부산과학관 A1(음성 명령)·A2(보드게임 AI) BlockPy 실습을 실제 로봇팔로 바로 할 수 있는 상태로 세팅한다 — 실습 파일을 BlockPyWorkspace 에 넣고, 로봇 패널 조회 버그를 고치고, 음성 인식(faster-whisper + medium 모델)을 설치하고, DobotLink·로봇·마이크를 점검한다. "A1 A2 세팅", "실습 세팅", "기본 세팅 해 줘", "실습 준비 해 줘", "setup" 같은 말이 나오면 쓴다. 수업 진행 안내나 빈칸 채우기는 하지 않는다.
---

# A1 · A2 BlockPy 실습 기본 세팅

목표: 이 PC 를 **사람이 BlockPy 에서 A1·A2 실습 파일을 열고 ▶ 실행하면 실제 로봇팔이 움직이고, A1 은 마이크로 말할 수 있는 상태**로 만든다.
수업 진행 안내나 빈칸(TODO) 채우기는 **하지 않는다** — 세팅이 끝나면 사람이 직접 조작한다.

## 할 일 (순서대로, 결과를 짧게 보고)
BlockPy 파이썬 = `%APPDATA%\blockpy-harness-playground\runtime\python\python.exe`. **이 파이썬으로만** 실행한다(다른 python 은 안 됨).
이 SKILL.md 가 있는 폴더를 `<SKILL>` 이라 한다(`BlockPyWorkspace\.agents\skills\blockpy-a1a2-setup` 또는 `BlockPyWorkspace\.claude\skills\blockpy-a1a2-setup`).

1. 세팅 실행 (1~3분):
   - PowerShell: `& "$env:APPDATA\blockpy-harness-playground\runtime\python\python.exe" "<SKILL>\setup.py"`
   - bash: `"$APPDATA/blockpy-harness-playground/runtime/python/python.exe" "<SKILL>/setup.py"`
   하는 일: ① 실습 파일을 `~\BlockPyWorkspace` 에 넣기(내용이 다른 기존 파일은 `_백업_날짜시각` 폴더에 보관, 지우지 않음) ② 로봇 패널 보정 ③ faster-whisper·sounddevice 설치 ④ 점검.
2. 음성 모델 받기 (약 1.5GB · 10분쯤 · 인터넷 필요 · 명령 시간 제한을 최대로):
   `... python.exe "<SKILL>\setup.py" --model`
   시간 초과로 끊기면 같은 명령을 다시 실행한다(받던 것을 이어서 받는다). A2 만 할 거면 건너뛰어도 된다.
3. 점검만 다시: `... python.exe "<SKILL>\setup.py" --check`
4. 마지막 `결과:` 줄과 ✖ 항목을 사람에게 그대로 알려 주고, 아래 "사람이 해야 하는 일" 중 남은 것을 알려 준다.

## ✖ 가 나오면
| ✖ 항목 | 할 일 |
|---|---|
| BlockPy 파이썬이 아니에요 | 위 경로의 python.exe 로 다시 실행 |
| BlockPyWorkspace 없음 · BlockPy 설치 | BlockPy(BlockPy-Setup-1.1.0.exe) 설치 후 **한 번 켜기** → 다시 실행 |
| 음성 부품 · 음성 모델 | 인터넷 연결 확인 후 다시 실행 |
| 마이크 | Windows 설정 → 시스템 → 소리 → 입력 장치 확인, 마이크 볼륨 100 |
| DobotLink 실행 중 | DobotLink 설치·실행(`%LOCALAPPDATA%\Programs\DobotLink\DobotLink.exe`, 창 없이 작업 표시줄 ^ 안) → `--check` |
| 로봇팔 보임 | 로봇 전원 · USB **데이터 선**(충전 전용 선 X) · 다른 USB 구멍 → `--check` |

## 사람이 해야 하는 일 (AI 가 못 함)
- BlockPy · DobotLink 설치, 로봇 USB·전원 연결.
- 세팅 뒤 **BlockPy 껐다 켜기** → 왼쪽 **로봇** → Magician Lite → [조회] → "USB 직렬 장치" COM(블루투스 COM 아님) → [연결] → "연결됨".
- 실습: 파일 목록에서 `A1_1_정답데모_슬라이드8.py` / `A1_2_…` / `A2_1_…` / `A2_2_…` 열고 ▶ 실행.
- 로봇이 이상하면 ■ 정지 → `A0_로봇_멈춤.py` ▶ 실행 → 그래도 움직이면 로봇 전원.

## 하지 말 것
- 작업 폴더의 AGENTS.md · CLAUDE.md · main.py · examples 는 고치지 않는다(세팅 스크립트도 건드리지 않음).
- `_백업_…` 폴더를 지우지 않는다.
- 세팅 중 로봇을 움직이는 코드를 실행하지 않는다(점검은 포트만 찾고 움직이지 않음).
