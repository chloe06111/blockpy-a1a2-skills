# -*- coding: utf-8 -*-
"""카메라 추상화 — 로봇 K210(C타입) / 저장 이미지 폴더(SD) / 모의 카메라를 단일 인터페이스로.

수업 코드가 하드웨어에 독립적이 되게 한다. CURRICULUM_FORCE_MOCK=1 또는 pyserial 미설치 시
MockCamera(라인 위치를 프레임에 반영한 합성 도로)로 자동 폴백 — 무하드웨어 학습·검증 가능.
K210 소스는 검증된 뷰어 방식(COM16 CP210x 115200 → REPL 확보 → 캡처 루프 → FRM:base64) 재사용.
"""
from __future__ import annotations

import glob
import io
import os
import sys
import time
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

import numpy as np

try:
    import serial  # type: ignore[import-untyped]  # noqa: F401
    _HAS_SERIAL = True
except Exception:  # pragma: no cover
    _HAS_SERIAL = False


def cam_is_mock() -> bool:
    """CURRICULUM_FORCE_MOCK=1 이거나 pyserial이 없으면 True(모의 카메라 사용)."""
    if os.environ.get("CURRICULUM_FORCE_MOCK", "").strip() == "1":
        return True
    return not _HAS_SERIAL


class MockCamera:
    """라인 위치를 프레임에 반영하는 합성 도로 카메라.

    라인은 가우시안 명암 프로파일(부드러운 경계)로 렌더링한다. 실제 카메라가 담는
    라인도 경계가 흐려지므로, 하드 이진 줄무늬보다 학습된 정책이 인접 위치 간에
    일반화하기 쉬운 연속적인 특징을 제공한다(암기가 아닌 진짜 학습을 검증하려면
    프레임이 위치에 따라 부드럽게 변해야 한다).
    """

    is_mock = True
    _SIGMA = 5.0  # 라인 흐림 폭(px) — 다운샘플 격자보다 넓어 인접 위치 간 특징이 겹치게 함

    def __init__(self, w: int = 64, h: int = 48) -> None:
        self.w, self.h = int(w), int(h)
        self._pos = 0.0

    def set_line_pos(self, x: float) -> None:
        self._pos = max(-1.0, min(1.0, float(x)))

    def get_frame(self) -> np.ndarray:
        cx = (self._pos + 1.0) * 0.5 * (self.w - 1)
        xs = np.arange(self.w, dtype=np.float64)
        dist = np.abs(xs - cx)
        darkness = np.exp(-(dist ** 2) / (2 * self._SIGMA ** 2))
        col_val = (220 - darkness * 200).astype(np.uint8)
        img = np.empty((self.h, self.w, 3), dtype=np.uint8)
        img[:, :, :] = col_val[None, :, None]
        return img

    def close(self) -> None:
        pass


class FolderCamera:
    """폴더의 이미지들을 정렬 순환 공급(저장 데이터셋/SD용)."""

    is_mock = False

    def __init__(self, folder: str) -> None:
        exts = ("*.jpg", "*.jpeg", "*.png", "*.bmp")
        files: list[str] = []
        for e in exts:
            files.extend(glob.glob(os.path.join(folder, e)))
        self._files = sorted(files)
        self._i = 0

    def get_frame(self) -> Optional[np.ndarray]:
        if not self._files:
            return None
        from PIL import Image
        path = self._files[self._i % len(self._files)]
        self._i += 1
        return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)

    def close(self) -> None:
        pass


class K210Camera:  # pragma: no cover - 하드웨어 필요, 단위테스트 제외
    """로봇 K210 카메라(C타입 시리얼) 라이브 프레임. 하드웨어 필요.

    중요한 타이밍: 이 카메라 펌웨어는 frozen 라인검출 앱이 부팅하며 센서를 독점한다.
    앱이 센서를 완전히 잡기 *전*의 짧은 부팅 창에서 인터럽트하고 캡처 루프를 주입해야
    스트리밍이 된다(부팅 대기가 3초처럼 길면 앱이 먼저 센서를 잡아 리셋됨). 그래서
    포트를 새로 열어(=CP210x DTR 토글로 리셋 유발) 짧게 대기 후 즉시 인터럽트하고,
    첫 유효 프레임이 올 때까지 검증한다. 실패하면 포트를 닫고 다시 여는 식으로
    재시도(=뷰어의 [재연결])한다 — 실측 적중률이 시도당 ~75%라 몇 번 재시도로 안정화.
    """

    is_mock = False
    _CAP = (
        "import sensor,ubinascii,gc\ngc.collect()\nsensor.reset()\n"
        "sensor.set_pixformat(sensor.RGB565)\nsensor.set_framesize(sensor.QQVGA)\n"
        "sensor.run(1)\nsensor.skip_frames(time=500)\nwhile True:\n"
        "  img=sensor.snapshot()\n  img.compress(quality=50)\n"
        "  print('FRM:'+ubinascii.b2a_base64(img.to_bytes()).decode().strip())\n"
    )
    _B64 = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
    _BOOT_WAIT = 1.2  # 갓 부팅 창(초) — 앱이 센서를 잡기 전에 인터럽트하려면 짧아야 함
    _VERIFY = 6.0     # 스트리밍 시작 검증 대기(초) — 첫 프레임까지 여유
    _DEBUG = os.environ.get("K210_DEBUG", "").strip() == "1"

    def __init__(self, port: str = "COM16", baud: int = 115200, attempts: int = 6) -> None:
        import serial as _s
        self._serial_mod = _s
        self.port = port
        self.baud = baud
        self._ser: Any = None  # pyserial(untyped) 핸들 또는 None
        self._buf = b""
        self._first: Optional[np.ndarray] = None
        last = ""
        for k in range(max(1, attempts)):
            try:
                if self._try_start():
                    if self._DEBUG:
                        print("[K210] 연결 성공(시도 %d)" % (k + 1), file=sys.stderr)
                    return
                if self._DEBUG:
                    print("[K210] 시도 %d: 프레임 미검증" % (k + 1), file=sys.stderr)
            except Exception as e:  # 포트 오류 등 — 닫고 재시도
                last = str(e)
                if self._DEBUG:
                    print("[K210] 시도 %d 예외: %s" % (k + 1, e), file=sys.stderr)
            self._close_ser()
            time.sleep(1.0)
        raise RuntimeError(
            "K210 라이브 스트리밍 시작 실패(%d회 시도) — USB-C를 뺐다 꽂고 다시 연결하세요. %s"
            % (attempts, last))

    def _try_start(self) -> bool:
        """포트 새로 열기 → 갓 부팅 창 대기 → 인터럽트 → 캡처 루프 주입 → 첫 프레임 검증."""
        self._ser = self._serial_mod.Serial(self.port, self.baud, timeout=0.2)
        time.sleep(0.2)
        t0 = time.time()
        while time.time() - t0 < self._BOOT_WAIT:
            self._ser.read(8192)
        if not self._enter_repl():
            if self._DEBUG:
                print("[K210]   REPL 확보 실패", file=sys.stderr)
            return False
        self._ser.write(("exec(" + repr(self._CAP) + ")\r\n").encode())
        self._buf = b""
        frame = self._read_frame(timeout=self._VERIFY)  # 실제로 스트리밍이 시작됐는지 검증
        if frame is not None:
            self._first = frame
            return True
        return False

    def _enter_repl(self) -> bool:
        # 부팅 창이 좁아 시도를 짧게(3회) — 실패하면 상위에서 포트 재오픈 재시도.
        for _ in range(3):
            for _ in range(3):
                self._ser.write(b"\x03")
                time.sleep(0.12)
            self._ser.write(b"\r\n")
            time.sleep(0.25)
            self._ser.reset_input_buffer()
            self._ser.write(b"print('P9')\r\n")
            time.sleep(0.4)
            if b"P9" in self._ser.read(65536):
                return True
        return False

    def _read_frame(self, timeout: float = 2.0) -> Optional[np.ndarray]:
        import base64
        from PIL import Image
        t0 = time.time()
        while time.time() - t0 < timeout:
            self._buf += self._ser.read(16384)
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                i = line.rfind(b"FRM:")
                if i < 0:
                    continue
                tok = bytes(c for c in line[i + 4:] if c in self._B64)
                if len(tok) < 100:
                    continue
                tok += b"=" * (-len(tok) % 4)
                try:
                    raw = base64.b64decode(tok)
                except Exception:
                    continue
                if raw[:2] == b"\xff\xd8" and raw[-2:] == b"\xff\xd9":
                    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.uint8)
            if len(self._buf) > 262144:  # 폭주 방지
                self._buf = self._buf[-65536:]
        return None

    def get_frame(self) -> Optional[np.ndarray]:
        if self._first is not None:  # 시작 검증에서 받은 첫 프레임 재사용
            f, self._first = self._first, None
            return f
        return self._read_frame(timeout=2.0)

    def _close_ser(self) -> None:
        try:
            if self._ser is not None:
                self._ser.write(b"\x03")
                time.sleep(0.1)
                self._ser.close()
        except Exception:
            pass
        self._ser = None

    def close(self) -> None:
        self._close_ser()


def get_camera(source: Optional[str] = None, mock: Optional[bool] = None):
    """카메라 팩토리 — source/mock에 따라 MockCamera/FolderCamera/K210Camera를 반환."""
    use_mock = cam_is_mock() if mock is None else bool(mock)
    if use_mock:
        return MockCamera()
    if source and source.lower().startswith("k210:"):  # pragma: no cover
        return K210Camera(source.split(":", 1)[1] or "COM16")
    if source and os.path.isdir(source):
        return FolderCamera(source)
    return K210Camera("COM16")  # pragma: no cover
