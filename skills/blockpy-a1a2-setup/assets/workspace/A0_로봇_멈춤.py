# ── 로봇 멈추기 — 이상하면 ■ 정지 다음에 이 파일을 ▶ 실행하세요 ──────────────────
# BlockPy 의 ■ 정지는 '프로그램'만 끝냅니다. 로봇에게 이미 보낸 동작은 DobotLink 에 남아 끝까지 갑니다.
# 이 파일은 로봇의 동작 대기열을 멈추고(QueuedCmdStop) 비운 뒤(QueuedCmdClear), 펌프를 끄고 연결을 정리합니다.
# 로봇을 움직이지 않습니다. 그래도 움직이면 로봇 전원을 끕니다.
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "taskB_curriculum"))
from dobotkit import MagicianLite

arm = MagicianLite(port="auto", auto_connect=False)
후보 = [p for p in (arm.cmds.search() or []) if "Bluetooth" not in p.get("description", "")]
if not 후보:
    print("로봇이 보이지 않아요 — 로봇 전원 · USB · DobotLink 를 확인하세요.")
    sys.exit(1)
arm.cmds.port_name = 후보[0]["portName"]
print("로봇:", arm.cmds.port_name)
for 이름, 할일 in (("연결", arm.cmds.connect),
                   ("대기열 멈춤", arm.cmds.queue_stop),
                   ("대기열 비움", arm.cmds.queue_clear),
                   ("펌프 끔", arm.pump_off),
                   ("연결 끊기", arm.cmds.disconnect)):
    try:
        할일()
        print("  ✔", 이름)
    except Exception as e:
        print("  ·", 이름, "—", type(e).__name__, e)
print("끝. 다시 실습하려면 실습 파일을 ▶ 실행하세요.")
