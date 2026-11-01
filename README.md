# BlockPy A1 · A2 실습 세팅 skill

국립부산과학관 A1(음성 명령) · A2(보드게임 AI) 실습을 BlockPy 에서 실제 로봇팔로 할 수 있게 PC 를 세팅하는 skill 입니다.

## 설치 (PC 마다 한 번)

준비: BlockPy 설치 후 한 번 켜기 · DobotLink 설치 · Node.js 22.20 이상 · 로봇 USB·전원

PowerShell 에서:

```powershell
cd $HOME\BlockPyWorkspace
npx skills add chloe06111/blockpy-a1a2-skills --skill blockpy-a1a2-setup -a opencode -a claude-code -y --copy
```

그다음 BlockPy 를 다시 켜고 오른쪽 AI 도우미에 입력:

```
blockpy-a1a2-setup skill 로 세팅해 줘
```

AI 없이 하려면 `BlockPyWorkspace\.agents\skills\blockpy-a1a2-setup\SETUP.bat` 더블클릭.

## 세팅이 하는 일

1. 실습 파일(`taskB_curriculum`, A0 · A1 · A2 파일, `정답`)을 `BlockPyWorkspace` 에 넣기 — 내용이 다른 기존 파일은 `_백업_날짜시각` 에 보관
2. BlockPy 1.1.0 로봇 패널 '조회' 버그 보정
3. 음성 인식 부품(faster-whisper · sounddevice) 설치
4. 점검 — BlockPy · 마이크 · DobotLink · 로봇팔 포트 (로봇은 움직이지 않음)
5. 음성 모델 medium(약 1.5GB) 받기

세팅 뒤: BlockPy 왼쪽 **로봇** → Magician Lite → [조회] → USB 직렬 장치 COM → [연결] → 실습 파일 열고 ▶ 실행.
