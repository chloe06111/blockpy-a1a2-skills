# -*- coding: utf-8 -*-
"""A1 · A2 BlockPy 실습 기본 세팅 — 이 PC 를 '실습 파일이 들어 있고, 로봇 패널이 되고, 음성 인식이 되는' 상태로 만든다.

  python setup.py            ① 실습 파일 넣기 ② 로봇 패널 보정 ③ 음성 부품 설치 ④ 로봇 연결 점검
  python setup.py --model    ⑤ 음성 모델(medium, 약 1.5GB) 받기 — 오래 걸려서 따로 실행
  python setup.py --check    ④ 점검만

반드시 BlockPy 파이썬으로 실행한다: %APPDATA%\\blockpy-harness-playground\\runtime\\python\\python.exe
작업 폴더에 이미 있는 파일이 내용이 다르면 덮어쓰기 전에 _백업_날짜시각 폴더로 옮겨 둔다.
"""
import filecmp
import os
import shutil
import socket
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
APPDATA = os.environ.get("APPDATA", "")
LOCAL = os.environ.get("LOCALAPPDATA", "")
RUNTIME_PY = os.path.join(APPDATA, "blockpy-harness-playground", "runtime", "python", "python.exe")
SITE = os.path.join(APPDATA, "blockpy-harness-playground", "runtime", "python", "Lib", "site-packages")
UNPACKED = os.path.join(LOCAL, "Programs", "BlockPy", "resources", "app.asar.unpacked")
WORKSPACE = os.path.join(os.path.expanduser("~"), "BlockPyWorkspace")
결과 = []


def 기록(ok, 이름, 설명=""):
    결과.append((ok, 이름, 설명))
    print(("  ✔ " if ok else "  ✖ ") + 이름 + (f" — {설명}" if 설명 else ""))


def 같은_파이썬인가():
    return os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(os.path.abspath(RUNTIME_PY))


def 실습파일_넣기():
    print("\n① 실습 파일을 BlockPyWorkspace 에 넣어요")
    if not os.path.isdir(WORKSPACE):
        기록(False, "BlockPyWorkspace 없음", "BlockPy 를 한 번 켠 뒤 다시 실행하세요")
        return
    src_root = os.path.join(ASSETS, "workspace")
    백업 = os.path.join(WORKSPACE, "_백업_" + time.strftime("%Y%m%d_%H%M"))
    새로, 같음, 옮김 = 0, 0, 0
    for root, _dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        for f in files:
            s = os.path.join(root, f)
            d = os.path.normpath(os.path.join(WORKSPACE, rel, f))
            if os.path.exists(d):
                if filecmp.cmp(s, d, shallow=False):
                    같음 += 1
                    continue
                b = os.path.normpath(os.path.join(백업, rel, f))
                os.makedirs(os.path.dirname(b), exist_ok=True)
                shutil.move(d, b)
                옮김 += 1
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            새로 += 1
    기록(True, "실습 파일", f"새로 넣음 {새로} · 이미 같음 {같음}" + (f" · 원래 파일 {옮김}개는 {os.path.basename(백업)} 에 보관" if 옮김 else ""))


def 패널_보정():
    print("\n② 로봇 패널 보정 (BlockPy 1.1.0 '로봇 브리지 응답 파싱 실패' 고치기)")
    if not os.path.isdir(SITE) or not os.path.isdir(UNPACKED):
        기록(False, "로봇 패널 보정", "BlockPy 설치 또는 첫 실행이 안 됨")
        return
    fix = os.path.join(ASSETS, "panel_fix")
    os.makedirs(os.path.join(UNPACKED, "scripts"), exist_ok=True)
    shutil.copy2(os.path.join(fix, "robot_bridge.py"), os.path.join(UNPACKED, "scripts", "robot_bridge.py"))
    shutil.copy2(os.path.join(fix, "_blockpy_asar_fix.py"), os.path.join(SITE, "_blockpy_asar_fix.py"))
    shutil.copy2(os.path.join(fix, "_blockpy_asar_fix.pth"), os.path.join(SITE, "_blockpy_asar_fix.pth"))
    기록(True, "로봇 패널 보정")


def 음성부품():
    print("\n③ 음성 인식 부품 설치 (faster-whisper · sounddevice) — 인터넷 필요")
    try:
        import faster_whisper  # noqa: F401
        import sounddevice  # noqa: F401
        기록(True, "음성 부품", "이미 설치됨")
        return
    except Exception:
        pass
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                        "faster-whisper", "sounddevice"])
    기록(r.returncode == 0, "음성 부품", "설치함" if r.returncode == 0 else "pip 설치 실패 — 인터넷 확인 후 다시")


def 음성모델():
    print("\n⑤ 음성 모델 medium 받기 (약 1.5GB · 처음 한 번 10분쯤)")
    try:
        from faster_whisper import WhisperModel
        t = time.time()
        WhisperModel("medium", device="cpu", compute_type="int8")
        기록(True, "음성 모델 medium", f"준비됨 ({time.time() - t:.0f}초)")
    except Exception as e:
        기록(False, "음성 모델 medium", f"{type(e).__name__}: {e} — 인터넷 확인 후 다시 (받던 것은 이어서 받음)")


def 모델_있음():
    hub = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub", "models--Systran--faster-whisper-medium")
    return os.path.isdir(os.path.join(hub, "snapshots"))


def 점검():
    print("\n④ 점검")
    for 이름, 경로 in (("BlockPy 설치", UNPACKED), ("BlockPy 파이썬", RUNTIME_PY), ("BlockPyWorkspace", WORKSPACE),
                       ("수업 코드 taskB_curriculum", os.path.join(WORKSPACE, "taskB_curriculum", "class_robot.py"))):
        기록(os.path.exists(경로), 이름)
    try:
        import dobotkit  # noqa: F401
        기록(True, "dobotkit")
    except Exception as e:
        기록(False, "dobotkit", str(e))
    try:
        import faster_whisper  # noqa: F401
        import sounddevice as sd
        기록(True, "음성 부품")
        try:
            기록(sd.query_devices(kind="input") is not None, "마이크")
        except Exception as e:
            기록(False, "마이크", f"입력 장치를 못 찾음 ({e})")
    except Exception:
        기록(False, "음성 부품", "setup.py 를 다시 실행")
    기록(모델_있음(), "음성 모델 medium", "" if 모델_있음() else "python setup.py --model 로 받기")
    try:
        socket.create_connection(("127.0.0.1", 9090), timeout=2).close()
        기록(True, "DobotLink 실행 중")
    except OSError:
        기록(False, "DobotLink 실행 중", "DobotLink 를 실행하세요(작업 표시줄 ^ 안에 아이콘)")
        return
    try:
        from dobotkit import MagicianLite
        arm = MagicianLite(port="auto", auto_connect=False)
        후보 = [p for p in (arm.cmds.search() or []) if "Bluetooth" not in p.get("description", "")]
        기록(bool(후보), "로봇팔 보임", 후보[0]["portName"] + " · " + 후보[0].get("description", "") if 후보
             else "로봇 USB(데이터 선) · 전원 확인")
    except Exception as e:
        기록(False, "로봇팔 보임", f"{type(e).__name__}: {e}")


def main():
    print("A1 · A2 BlockPy 실습 기본 세팅")
    if not 같은_파이썬인가():
        print(f"⚠️  BlockPy 파이썬이 아니에요: {sys.executable}\n   이렇게 실행하세요: \"{RUNTIME_PY}\" \"{os.path.abspath(__file__)}\"")
        if not os.path.exists(RUNTIME_PY):
            print("   (BlockPy 가 설치되지 않았거나 한 번도 켜지 않았어요)")
        sys.exit(2)
    if "--model" in sys.argv:
        음성모델()
    elif "--check" in sys.argv:
        점검()
    else:
        실습파일_넣기()
        패널_보정()
        음성부품()
        점검()
    실패 = [r for r in 결과 if not r[0]]
    print("\n결과:", "모두 됨 ✔" if not 실패 else f"안 된 것 {len(실패)}개 — " + ", ".join(r[1] for r in 실패))
    if "--model" not in sys.argv and not 모델_있음():
        print("다음: 음성 모델 받기 → python setup.py --model")
    print("사람이 할 일: BlockPy 껐다 켜기 → 왼쪽 '로봇' → Magician Lite → [조회] → USB 직렬 장치 COM → [연결]")


if __name__ == "__main__":
    main()
