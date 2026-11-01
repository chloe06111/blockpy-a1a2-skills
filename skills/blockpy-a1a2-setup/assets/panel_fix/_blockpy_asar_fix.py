# [임시 보정 · 2026-11-01] BlockPy 1.1.0 설치본의 로봇 패널 '조회/연결' 실패 고치기.
# 원인: 서버가 `resources\app.asar\scripts\robot_bridge.py` 를 파이썬으로 실행하는데, 이 파일이 압축 묶음(app.asar)
#       안에만 있어 파이썬이 열지 못한다 → 출력이 비어 "로봇 브리지 응답 파싱 실패".
# 보정: 파이썬이 켜질 때(.pth) 실행할 파일 경로가 app.asar 안이고 실제로 없으면, app.asar.unpacked 의 같은 파일로 바꿔 실행한다.
# 다른 프로그램에는 아무 영향이 없다(경로에 '\app.asar\' 가 들어 있을 때만 움직인다).
import os
import sys


def _run():
    a = sys.argv[0] if sys.argv else ""
    if not a or os.path.exists(a):
        return
    low = a.replace("/", "\\").lower()
    if "\\app.asar\\" not in low:
        return
    i = low.index("\\app.asar\\")
    alt = a[:i] + "\\app.asar.unpacked\\" + a[i + len("\\app.asar\\"):]
    if not os.path.exists(alt):
        return
    import runpy
    sys.argv[0] = alt
    sys.path.insert(0, os.path.dirname(alt))
    code = 0
    try:
        runpy.run_path(alt, run_name="__main__")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(code)


_run()
