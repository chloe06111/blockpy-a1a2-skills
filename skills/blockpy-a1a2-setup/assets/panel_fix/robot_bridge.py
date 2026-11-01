# -*- coding: utf-8 -*-
"""DobotLink bridge for the BlockPy Robot tab (server.js /api/robot/* 엔드포인트가 spawn).

stdin 으로 JSON 명령 하나를 받아 dobotkit로 DobotLink에 대해 **한 동작**을 수행하고,
결과 JSON을 stdout으로 출력하고 종료한다. 동작별 단발(stateless) 모델 — DobotLink.exe가
하드웨어를 쥐고 있으므로 매 동작마다 WebSocket만 짧게 열고 닫는다(프로세스 상주 없음).

DobotLink는 장치 연결 상태를 프로세스 간에 유지한다. 그래서 ConnectDobot가 "이미 열림"을
낼 수 있는데, 이는 정상(이미 연결됨)이므로 성공으로 간주한다. 실제 해제는 'disconnect'
액션에서만 수행한다.

stdin  : {"action","device","port","x","y","z","home"}
stdout : {"ok":true, ...}  |  {"ok":false,"error":..,"hint":..}

전제: DobotLink.exe 실행 + dobotkit 설치. 셸로 예외를 던지지 않는다 — 모든 실패는
{"ok":false} JSON으로 보고해 백엔드가 그대로 사용자에게 전달한다.
"""
from __future__ import annotations

import json
import sys

# 캘리브레이션 이동 시 기본 z(mm). 카메라에서 엔드이펙터가 보이는 높이로, 하드웨어에 맞게 조정.
DEFAULT_Z = 40.0
# GO 포트를 명시하지 않았을 때의 기본값(무선 동글은 보통 CP210x = 첫 포트).
DEFAULT_GO_PORT = "COM5"


def _emit(obj) -> int:
    print(json.dumps(obj, ensure_ascii=False))
    return 0


def _ok(**kw) -> int:
    kw["ok"] = True
    return _emit(kw)


def _fail(error, hint: str = "") -> int:
    return _emit({"ok": False, "error": str(error), "hint": hint})


def _extract_ports(raw):
    """dobotkit search 응답 → 포트 이름 list[str] (best-effort, 순서 보존 중복 제거)."""
    out = []

    def _from_list(items):
        for it in items:
            if isinstance(it, dict) and it.get("portName"):
                out.append(it["portName"])
            elif isinstance(it, str):
                out.append(it)

    if isinstance(raw, list):
        _from_list(raw)
    elif isinstance(raw, dict):
        for key in ("ports", "result", "data"):
            v = raw.get(key)
            if isinstance(v, list):
                _from_list(v)
        if raw.get("portName"):
            out.append(raw["portName"])
    seen = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def _connect_tolerant(fn) -> None:
    """ConnectDobot 호출 — 이미 열린 장치면('already' 메시지) 성공으로 간주."""
    from dobotkit.exceptions import DobotLinkError

    try:
        fn()
    except DobotLinkError as e:
        if "already" not in str(e).lower():
            raise


def _resolve_arm(dobotkit, client, port):
    """auto 포트 해석 후 MagicianLite(자동연결 없이, 주입된 client 사용) 반환."""
    from dobotkit.exceptions import DobotConnectionError

    arm = dobotkit.MagicianLite(port=port, auto_connect=False, _client=client)
    if arm.cmds.port_name == "":  # port == "auto"
        ports = arm.cmds.search() or []
        if not ports:
            raise DobotConnectionError("DobotLink에서 Dobot 포트를 찾지 못했습니다")
        arm.cmds.port_name = ports[0]["portName"]
    return arm


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"bad request json: {e}")

    action = req.get("action")
    device = req.get("device", "lite")
    port = req.get("port") or "auto"

    try:
        import dobotkit
        from dobotkit import DobotConnectionError, DobotError
        from dobotkit.link import DobotLinkClient
    except Exception as e:  # noqa: BLE001
        return _fail(f"dobotkit import 실패: {e}", "백엔드 파이썬에 'pip install dobotkit' 하세요.")

    try:
        if action == "ports":
            method = "MagicianGO.SearchDobot" if device == "go" else "Magician.SearchDobot"
            with DobotLinkClient() as c:
                raw = c.call(method)
            return _ok(ports=_extract_ports(raw), raw=raw, device=device)

        if action == "connect":
            client = DobotLinkClient().connect()
            try:
                if device == "go":
                    go = dobotkit.MagicianGO(client, port_name=(port if port != "auto" else DEFAULT_GO_PORT))
                    _connect_tolerant(go.connect_robot)
                    return _ok(device="go", port=go.port_name, status={"battery": go.battery()})
                arm = _resolve_arm(dobotkit, client, port)
                _connect_tolerant(arm.cmds.connect)
                arm.cmds.queue_clear()
                arm.cmds.queue_start()
                return _ok(device="lite", port=arm.cmds.port_name, status={"pose": arm.get_pose()})
            finally:
                client.close()  # 소켓만 닫음 — 장치는 DobotLink에 연결된 채로 둔다

        if action == "disconnect":
            # 실제 장치 해제(DisconnectDobot). best-effort — 이미 해제됐어도 성공 처리.
            client = DobotLinkClient().connect()
            try:
                if device == "go":
                    dobotkit.MagicianGO(client, port_name=(port if port != "auto" else DEFAULT_GO_PORT)).disconnect_robot()
                else:
                    _resolve_arm(dobotkit, client, port).cmds.disconnect()
            except Exception:  # noqa: BLE001 - 해제는 관용적으로 성공 처리
                pass
            finally:
                client.close()
            return _ok(device=device)

        if action == "move_preset":
            # 캘리브레이션: 팔을 알려진 (x, y) 프리셋으로 절대 이동. home=True면 먼저 원점복귀.
            x = float(req.get("x"))
            y = float(req.get("y"))
            z = float(req.get("z", DEFAULT_Z))
            client = DobotLinkClient().connect()
            arm = None
            try:
                arm = _resolve_arm(dobotkit, client, port)
                _connect_tolerant(arm.cmds.connect)
                arm.cmds.queue_clear()
                arm.cmds.queue_start()
                # 미검증 모션 경로 — 보수적(느린) 속도로 첫 실기 이동을 안전하게. 필요 시 조정.
                try:
                    arm.set_speed(50, 50)
                except Exception:  # noqa: BLE001 - 속도 설정 실패가 이동을 막지 않도록
                    pass
                if req.get("home"):
                    arm.home(wait=True)
                arm.move_to(x, y, z, wait=True)
                return _ok(moved=True, target=[x, y, z], pose=arm.get_pose())
            finally:
                if arm is not None:
                    try:
                        arm.cmds.queue_stop()
                    except Exception:  # noqa: BLE001
                        pass
                client.close()

        return _fail(f"unknown action: {action}")

    except DobotConnectionError as e:
        return _fail(str(e), "DobotLink.exe를 실행한 뒤 다시 시도하세요.")
    except DobotError as e:
        return _fail(str(e), "DobotLink/로봇 상태를 확인하세요(컨트롤러 알람이면 전원 리셋).")
    except Exception as e:  # noqa: BLE001
        return _fail(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
