"""ai_clients.py — 공급자무관 AI 클라이언트 래퍼 (ADR-0001).

목적
----
LLM(대형언어모델)·VLM(비전언어모델)·STT(음성→텍스트) 세 가지 AI 기능을
**하나의 일관된 인터페이스**로 제공한다. 차시(P2) 코드와 검수 스크립트는
이 래퍼만 바라보면 되므로, 실제 백엔드(anthropic/whisper)가 바뀌어도
교육 코드를 고치지 않아도 된다(= 공급자무관, provider-agnostic).

핵심 안전장치 (교육용·무하드웨어 원칙, ADR-0004)
------------------------------------------------
- anthropic / whisper / numpy 같은 무거운(또는 키가 필요한) 의존성은
  파일 상단에서 try/except 로 감싸 **없으면 자동으로 Mock 백엔드로 폴백**한다.
- API 키가 없거나 config.is_mock()이 True면 역시 Mock 으로 동작한다.
- Mock 백엔드는 **결정적(deterministic)** 인 캔드(canned) 응답을 돌려주고,
  호출 인자를 self.calls 리스트에 기록한다(테스트·디버깅용).

사용법
------
    from common.ai_clients import LLMClient, VLMClient, STTClient

    llm = LLMClient()                                  # 키 없으면 자동 Mock
    answer = llm.complete(
        messages=[{"role": "user", "content": "안녕?"}],
        system="너는 친절한 조수야.",
    )

    vlm = VLMClient()
    desc = vlm.describe(image="photo.png", prompt="무엇이 보이나요?")
    # image 는 파일 경로(str) 또는 numpy 배열(ndarray) 모두 허용

    stt = STTClient()
    text = stt.transcribe("recording.wav")

이 파일을 직접 실행하면(python ai_clients.py) mock 자가 데모가 돈다.
"""

from __future__ import annotations

import base64
import io
import json
import os
from typing import Any

# ──────────────────────────────────────────────────────────────────────────
# 1) 의존성 import — 없으면 None 으로 두고, 이후 mock 으로 폴백한다.
#    (하드웨어/키 없는 교실 PC에서도 import 자체는 반드시 성공해야 함)
# ──────────────────────────────────────────────────────────────────────────
try:
    import anthropic  # 실제 LLM/VLM 백엔드(Claude)
except Exception:  # pragma: no cover - 미설치 환경 폴백
    anthropic = None  # type: ignore[assignment]

try:
    import whisper  # 실제 STT 백엔드(OpenAI Whisper, 로컬 모델)
except Exception:  # pragma: no cover
    whisper = None  # type: ignore[assignment]

# faster-whisper(CTranslate2): 같은 정확도로 훨씬 빠르고(int8 CPU) 메모리도 적게 써서
# medium/large 모델을 교실 PC에서도 현실적으로 돌릴 수 있다. 있으면 우선 사용한다.
try:
    from faster_whisper import WhisperModel as _FasterWhisperModel
except Exception:  # pragma: no cover
    _FasterWhisperModel = None  # type: ignore[assignment]

try:
    import numpy as np  # ndarray 이미지 인코딩에 사용
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]

# ── config 연동 (선택적) ──────────────────────────────────────────────────
# config.py 는 다른 단계에서 만들어진다. 아직 없을 수도 있으므로 방어적으로 읽는다.
try:
    from common import config as _config  # type: ignore
except Exception:  # pragma: no cover - config 미존재 시 환경변수로 대체
    _config = None  # type: ignore[assignment]


# 계약(CONTRACTS.md)에 명시된 기본 모델명.
# config.py 가 있으면 그 값을 우선 사용하고, 없으면 아래 기본값을 쓴다.
_DEFAULT_LLM_MODEL = getattr(_config, "LLM_MODEL", "claude-sonnet-4-6")
_DEFAULT_VLM_MODEL = getattr(_config, "VLM_MODEL", "claude-sonnet-4-6")

# MiniMax(OpenAI 호환) 설정 — 키가 있으면 실제 호출, 없으면 mock 으로 폴백.
_DEFAULT_MINIMAX_MODEL = getattr(_config, "MINIMAX_MODEL", None) \
    or os.environ.get("MINIMAX_MODEL", "MiniMax-M2.5")
_MINIMAX_BASE_URL = (getattr(_config, "MINIMAX_BASE_URL", None)
                     or os.environ.get("MINIMAX_BASE_URL")
                     or "https://api.minimax.io/v1").rstrip("/")


def _get_minimax_key() -> str | None:
    """MiniMax API 키를 config 또는 환경변수(MINIMAX_API_KEY)에서 읽는다."""
    if _config is not None and getattr(_config, "MINIMAX_API_KEY", None):
        return _config.MINIMAX_API_KEY  # type: ignore[attr-defined]
    return os.environ.get("MINIMAX_API_KEY")


def _resolve_mock(mock: bool | None) -> bool:
    """이 클라이언트가 mock 으로 동작해야 하는지 최종 판정한다.

    우선순위:
      1) 호출자가 mock=True/False 를 명시하면 그대로 따른다.
      2) config.is_mock() 이 있으면 그 값을 따른다(키/하드웨어 자동판정).
      3) 그 외에는 ANTHROPIC_API_KEY 환경변수 유무로 판정한다.
    """
    if mock is not None:          # (1) 명시값이 최우선
        return bool(mock)
    if _config is not None:
        # AI 전용 판정(ai_is_mock: 키 유무로만 결정)을 우선. 구버전 호환 is_mock 폴백.
        decider = getattr(_config, "ai_is_mock", None) or getattr(_config, "is_mock", None)
        if decider is not None:
            try:
                return bool(decider())  # (2) AI mock 자동판정(키 없으면 True)
            except Exception:  # pragma: no cover
                pass
    # (3) 키가 없으면 mock
    return not os.environ.get("ANTHROPIC_API_KEY")


def _get_api_key() -> str | None:
    """ANTHROPIC API 키를 config 또는 환경변수에서 읽는다."""
    if _config is not None and getattr(_config, "ANTHROPIC_API_KEY", None):
        return _config.ANTHROPIC_API_KEY  # type: ignore[attr-defined]
    return os.environ.get("ANTHROPIC_API_KEY")


def _is_ndarray(obj: Any) -> bool:
    """주어진 객체가 numpy 배열인지 안전하게 확인한다(numpy 미설치 대비)."""
    return np is not None and isinstance(obj, np.ndarray)


def _encode_image_to_base64(image: Any) -> tuple[str, str]:
    """이미지를 base64 문자열로 인코딩한다.

    반환: (media_type, base64_data)
    - image 가 파일 경로(str): 파일을 읽어 확장자로 media_type 추론.
    - image 가 ndarray: PNG 로 임시 인코딩(메모리 상에서). PIL 사용.
    """
    # (A) 파일 경로인 경우: 바이트를 그대로 읽는다.
    if isinstance(image, str):
        ext = os.path.splitext(image)[1].lower().lstrip(".")
        media = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                 "gif": "gif", "webp": "webp"}.get(ext, "png")
        with open(image, "rb") as f:
            data = f.read()
        return f"image/{media}", base64.standard_b64encode(data).decode("utf-8")

    # (B) numpy 배열인 경우: PNG 로 임시 인코딩한다.
    if _is_ndarray(image):
        try:
            from PIL import Image  # 지연 import (필요할 때만)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "ndarray 이미지를 인코딩하려면 Pillow(PIL)가 필요합니다. "
                "`pip install pillow` 후 다시 시도하세요."
            ) from exc
        buf = io.BytesIO()
        # ndarray(H,W,3) 등을 이미지로 변환해 PNG 바이트로 저장.
        Image.fromarray(image).save(buf, format="PNG")
        return "image/png", base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    # (C) 그 외 타입은 지원하지 않음.
    raise TypeError(
        f"image 는 파일 경로(str) 또는 numpy.ndarray 여야 합니다. (받은 타입: {type(image).__name__})"
    )


# ──────────────────────────────────────────────────────────────────────────
# 2) Mock 백엔드 — 결정적 캔드 응답 + 호출 인자 기록
#    (하드웨어/키 없이도 차시 코드와 테스트가 끝까지 돌게 해 준다)
# ──────────────────────────────────────────────────────────────────────────
class _MockBackend:
    """모든 Mock 클라이언트의 공통 부모.

    self.calls 에 (메서드명, 인자딕셔너리) 튜플을 차곡차곡 기록한다.
    테스트에서 `client.calls[-1]` 로 마지막 호출 인자를 검사할 수 있다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []  # 호출 기록(검수·테스트용)

    def _record(self, method: str, **kwargs: Any) -> None:
        """호출 한 건을 기록한다."""
        self.calls.append((method, kwargs))


# ──────────────────────────────────────────────────────────────────────────
# 3) LLMClient — 텍스트 대화/생성
# ──────────────────────────────────────────────────────────────────────────
class LLMClient(_MockBackend):
    """공급자무관 LLM 래퍼. 기본 공급자는 anthropic(Claude)."""

    def __init__(self, provider: str = "anthropic", model: str | None = None,
                 mock: bool | None = None, *, _http_post: Any = None) -> None:
        super().__init__()                       # self.calls 초기화
        self.provider = provider
        self._http_post = _http_post             # (minimax) 테스트용 주입 가능한 전송기
        self._client = None
        if provider == "minimax":
            # MiniMax(OpenAI 호환) — 키가 있으면 실제, 없으면 mock 으로 폴백.
            self.model = model or _DEFAULT_MINIMAX_MODEL
            self._base_url = _MINIMAX_BASE_URL
            self._api_key = _get_minimax_key()
            # mock 판정은 MINIMAX 키 유무로만(anthropic 키/라이브러리와 무관).
            self.mock = bool(mock) if mock is not None else (not self._api_key)
        else:
            # 기존 anthropic(Claude) 경로 — 동작 불변.
            self.model = model or _DEFAULT_LLM_MODEL  # 계약상 기본: claude-sonnet-4-6
            self.mock = _resolve_mock(mock) or anthropic is None
            if not self.mock:
                self._client = anthropic.Anthropic(api_key=_get_api_key())

    def complete(self, messages: list[dict], system: str = "") -> str:
        """대화 메시지 목록을 받아 모델의 답변 텍스트(str)를 돌려준다.

        messages: [{"role": "user"/"assistant", "content": "..."}] 형식.
        system  : 시스템 프롬프트(역할/말투 지시). 비어 있으면 생략.
        """
        if self.mock:
            # ── Mock: 호출 인자 기록 후 결정적 응답 생성 ──
            self._record("complete", messages=messages, system=system)
            # 마지막 사용자 발화를 추려 응답에 echo (결정적·디버깅 친화).
            last_user = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_user = str(m.get("content", ""))
                    break
            return f"[MOCK-LLM] system={system!r} | 마지막입력={last_user!r}"

        # ── 실제(MiniMax, OpenAI 호환 chat completions) ──
        if self.provider == "minimax":
            return self._complete_minimax(messages, system)

        # ── 실제(Claude Messages API, claude-api 스킬 가이드 준수) ──
        # adaptive thinking 권장값 사용, max_tokens 는 비스트리밍 안전값.
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system or anthropic.NOT_GIVEN,
            messages=messages,
        )
        # content 는 블록 리스트 → text 블록만 모아 이어 붙인다.
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")

    # -- MiniMax(OpenAI 호환) 실제 호출 -------------------------------------- #
    def _complete_minimax(self, messages: list[dict], system: str = "") -> str:
        """MiniMax 의 /chat/completions(OpenAI 호환)를 호출해 답변 텍스트를 돌려준다."""
        msgs = ([{"role": "system", "content": system}] if system else []) + list(messages)
        payload = json.dumps(
            {"model": self.model, "messages": msgs, "temperature": 0.0}
        ).encode("utf-8")
        raw = self._minimax_post(f"{self._base_url}/chat/completions", payload)
        data = json.loads(raw)
        content = str(data["choices"][0]["message"]["content"])
        # MiniMax 추론 모델(M2.x 등)은 <think>...</think> 로 사고과정을 먼저 낸다.
        # 그 안의 대괄호/예시가 다운스트림 JSON 파서를 오작동시키므로, 실제 답변만
        # 남기려고 마지막 </think> 뒤만 취한다(추론 태그 없으면 원문 그대로).
        if "</think>" in content:
            content = content.rsplit("</think>", 1)[-1]
        return content.strip()

    def _minimax_post(self, url: str, payload: bytes) -> str:
        """MiniMax 로 POST. 테스트 시 _http_post(url, payload, api_key) 주입으로 대체."""
        if self._http_post is not None:            # 테스트/대체 전송기
            return str(self._http_post(url, payload, self._api_key))
        import urllib.request

        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - 신뢰 엔드포인트
            return resp.read().decode("utf-8")


# ──────────────────────────────────────────────────────────────────────────
# 4) VLMClient — 이미지 설명(비전)
# ──────────────────────────────────────────────────────────────────────────
class VLMClient(_MockBackend):
    """공급자무관 VLM 래퍼. 이미지+질문 → 설명 텍스트."""

    def __init__(self, provider: str = "anthropic", model: str | None = None,
                 mock: bool | None = None) -> None:
        super().__init__()
        self.provider = provider
        self.model = model or _DEFAULT_VLM_MODEL  # 계약상 기본: claude-sonnet-4-6
        self.mock = _resolve_mock(mock) or anthropic is None
        self._client = None
        if not self.mock:
            self._client = anthropic.Anthropic(api_key=_get_api_key())

    def describe(self, image: Any, prompt: str) -> str:
        """이미지를 보고 prompt 질문에 대한 설명 텍스트(str)를 돌려준다.

        image: 파일 경로(str) 또는 numpy.ndarray(임시 인코딩) 모두 허용.
        """
        if self.mock:
            # ── Mock: 인자 기록(이미지 타입만 요약 기록) 후 결정적 응답 ──
            img_kind = "ndarray" if _is_ndarray(image) else f"path:{image}"
            self._record("describe", image=img_kind, prompt=prompt)
            return f"[MOCK-VLM] 이미지({img_kind})에 대한 설명 - 질문={prompt!r}"

        # ── 실제: 이미지를 base64 로 인코딩해 vision 메시지 구성 ──
        media_type, b64 = _encode_image_to_base64(image)
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {  # 이미지 블록(텍스트보다 앞에 두는 것이 권장)
                        "type": "image",
                        "source": {"type": "base64",
                                   "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


# ──────────────────────────────────────────────────────────────────────────
# 5) STTClient — 음성 파일 → 텍스트
# ──────────────────────────────────────────────────────────────────────────
# 로봇 명령 도메인 어휘 힌트 — whisper 가 이 문맥으로 인식해 정확도가 오른다.
_STT_PROMPT = ("로봇 팔 제어 명령. 홈, 이동, 위로, 아래로, 왼쪽, 오른쪽, "
               "앞으로, 뒤로, 흡착, 그리퍼, 펌프, 정지, 센티미터, 밀리미터.")


class STTClient(_MockBackend):
    """공급자무관 STT 래퍼(로컬 whisper).

    백엔드는 둘 중 가용한 것을 자동 선택한다:
      - faster-whisper(있으면 우선): CTranslate2 기반, 같은 정확도로 빠르고 가벼움 →
        medium/large 를 CPU 에서도 현실적으로 사용.
      - openai-whisper: 순정 구현(폴백).
    둘 다 없으면 mock 으로 동작한다.
    """

    def __init__(self, provider: str = "whisper", mock: bool | None = None,
                 model_name: str | None = None) -> None:
        super().__init__()
        self.provider = provider
        # STT 는 API 키가 아니라 whisper 계열 라이브러리 설치 여부로 판정한다.
        _has_stt = (_FasterWhisperModel is not None) or (whisper is not None)
        self.mock = (mock if mock is not None else False) or (not _has_stt)
        # config 강제 mock 도 반영(키/하드웨어 자동판정).
        if mock is None and _config is not None and hasattr(_config, "is_mock"):
            try:
                self.mock = self.mock or bool(_config.is_mock())
            except Exception:  # pragma: no cover
                pass
        # 모델 크기: 인자 > config.WHISPER_MODEL > 환경변수 > 기본 "medium".
        # (small/base 는 한국어 정확도가 낮음. faster-whisper 면 medium 도 충분히 빠르다.)
        self.model_name = (
            model_name
            or getattr(_config, "WHISPER_MODEL", None)
            or os.environ.get("WHISPER_MODEL")
            or "medium"
        )
        self.backend = None        # "faster" | "openai" | None(mock)
        self._model = None         # 지연 로드될 모델
        if not self.mock:
            if _FasterWhisperModel is not None:
                # int8 양자화로 CPU 에서 빠르게. GPU 가 있으면 자동으로 활용된다.
                self._model = _FasterWhisperModel(
                    self.model_name, device="auto", compute_type="int8")
                self.backend = "faster"
            else:
                self._model = whisper.load_model(self.model_name)
                self.backend = "openai"

    def _resolve_audio(self, audio_path: str):
        """가능하면 WAV 를 직접 배열로 읽어 ffmpeg 의존을 없앤다.

        whisper 계열은 기본적으로 ffmpeg 로 오디오를 로드한다(Windows 에서 ffmpeg
        미설치 시 FileNotFoundError [WinError 2]). A1 녹음은 16kHz mono WAV 이므로
        직접 float32 배열로 읽어 넘기면 ffmpeg 없이 인식된다. 실패하면 경로로 폴백.
        """
        if str(audio_path).lower().endswith(".wav"):
            try:
                from common.audio import load_wav_float32
                data, rate = load_wav_float32(audio_path)
                if rate == 16000:
                    return data
            except Exception:
                pass
        return audio_path

    def transcribe(self, audio_path: str) -> str:
        """음성 파일 경로를 받아 인식된 텍스트(str)를 돌려준다."""
        if self.mock:
            # ── Mock: 인자 기록 후 결정적 응답 ──
            self._record("transcribe", audio_path=audio_path)
            return f"[MOCK-STT] {audio_path!r} 음성을 텍스트로 변환한 결과입니다."

        audio_input = self._resolve_audio(audio_path)

        if self.backend == "faster":
            # faster-whisper: 세그먼트 이터레이터를 이어붙인다.
            segments, _info = self._model.transcribe(
                audio_input,
                language="ko",
                condition_on_previous_text=False,
                initial_prompt=_STT_PROMPT,
            )
            return "".join(seg.text for seg in segments).strip()

        # openai-whisper 폴백.
        result = self._model.transcribe(
            audio_input,
            language="ko",
            fp16=False,
            condition_on_previous_text=False,
            initial_prompt=_STT_PROMPT,
        )
        return str(result.get("text", "")).strip()


# ──────────────────────────────────────────────────────────────────────────
# 6) 자가 데모 — mock 으로 LLM/VLM/STT 각각 1회 호출
#    (하드웨어·키 없이 `python ai_clients.py` 로 동작 확인 가능)
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== ai_clients.py mock 자가 데모 ===\n")

    # LLM: mock 강제(키가 있어도 데모는 mock 으로)
    llm = LLMClient(mock=True)
    out = llm.complete(
        messages=[{"role": "user", "content": "두봇 로봇팔이 뭐예요?"}],
        system="너는 친절한 로봇 교육 조수야.",
    )
    print("[LLM]", out)
    print("     기록된 호출:", llm.calls[-1][0], "\n")

    # VLM: 파일 경로 입력 예시(실제 파일은 필요 없음 — mock 이므로 읽지 않음)
    vlm = VLMClient(mock=True)
    out = vlm.describe(image="sample.png", prompt="이 사진에 무엇이 보이나요?")
    print("[VLM]", out)
    print("     기록된 호출:", vlm.calls[-1][0], "\n")

    # STT: 음성 파일 경로 입력 예시
    stt = STTClient(mock=True)
    out = stt.transcribe("recording.wav")
    print("[STT]", out)
    print("     기록된 호출:", stt.calls[-1][0], "\n")

    print("=== 데모 완료 (모든 백엔드 mock 폴백 정상) ===")
