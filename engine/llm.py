"""LLM 연결 (docs/FORMATS.md 9절, docs/PRD.md 7.3절).

엔진은 "선택 요청을 주면 답을 적은 글을 돌려받는다"는 한 가지 모양으로만 LLM 을 부른다.
공급자마다 다른 부분은 이 파일 안에 감춘다.

- 시스템 프롬프트: `personas/prompts/<prompt_version>.md` 의 글 그대로다 (페르소나 담당이 쓴다). 엔진은 글을 덧붙이지 않는다.
- 사용자 메시지: 9절의 요청을 JSON 으로 적은 글이다.
- 돌려받는 글: 9절의 응답을 JSON 으로 적은 것이어야 한다. 맞는지는 엔진이 다시 검사한다 (`engine/runner.py`).

공급자, 모델, 호출 상한, 키는 환경 변수에서 읽는다 (`.env.example`). 키는 이 파일에서 다루지 않고 화면에도 찍지 않는다.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import anthropic

from engine.answers import request_as_json
from engine.formats.choice import ChoiceRequest

DEFAULT_PROVIDER = "anthropic"
# 모델 이름을 적는 곳은 여기 하나다. 바꿀 때는 코드를 고치지 않고 .env 의 LLM_MODEL 에 적는다 (CLAUDE.md 의 "스택").
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5"}
DEFAULT_CALL_LIMIT = 200

# 답 하나에 쓸 수 있는 가장 긴 길이. 답은 짧지만 모델이 생각하는 데 쓰는 몫이 여기서 나간다.
MAX_TOKENS = 16000
# OpenAI 호환 주소를 부를 때 기다리는 시간(초).
HTTP_TIMEOUT = 120

PROMPT_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_STRINGS = {"type": "array", "items": {"type": "string"}}
# 응답의 모양 (docs/FORMATS.md 9절의 "응답"). 모양만 묶는다. 후보에 있는 업장인지, 라벨이 값 목록에 있는지 같은 것은
# 엔진이 답을 받은 뒤에 검사한다. `engine.formats.ChoiceResponse` 와 키가 같은지는 테스트가 본다.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {
            "type": "object",
            "properties": {
                "venue_id": _NULLABLE_STRING,
                "option_id": _NULLABLE_STRING,
                "addons": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"product_id": {"type": "string"}, "quantity": {"type": "integer"}},
                        "required": ["product_id", "quantity"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["venue_id", "option_id", "addons"],
            "additionalProperties": False,
        },
        "reason_labels": _STRINGS,
        "reason_text": {"type": "string"},
        "used_attributes": _STRINGS,
        "rejected": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"venue_id": {"type": "string"}, "pain_labels": _STRINGS, "text": {"type": "string"}},
                "required": ["venue_id", "pain_labels", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["choice", "reason_labels", "reason_text", "used_attributes", "rejected"],
    "additionalProperties": False,
}


class LlmError(Exception):
    """이번 호출이 실패했다. 그 방문을 실패로 남기고 다음 방문으로 넘어간다."""


class LlmFatal(LlmError):
    """설정이 틀려 다시 불러도 같은 실패가 난다 (키, 모델 이름, 주소). 실행을 멈춘다."""


@dataclass(frozen=True)
class LlmReply:
    text: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    def complete(self, system: str, user: str) -> LlmReply:
        """시스템 프롬프트와 사용자 메시지를 주고 답을 적은 글을 받는다. 실패하면 `LlmError` 를 낸다."""
        ...


def _short(exc: BaseException) -> str:
    """오류의 글을 원장의 한 칸에 들어가게 한 줄로 줄인다."""
    return f"{type(exc).__name__}: {' '.join(str(exc).split())}"[:300]


class AnthropicProvider:
    """Anthropic Claude. 키는 SDK 가 환경(`ANTHROPIC_API_KEY`)에서 읽는다."""

    def __init__(self, model: str) -> None:
        self.model = model
        try:
            self.client = anthropic.Anthropic()
        except anthropic.AnthropicError as exc:
            raise LlmFatal(f"Anthropic 연결을 만들지 못했다: {_short(exc)}") from exc

    def complete(self, system: str, user: str) -> LlmReply:
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
            )
        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.NotFoundError,
            anthropic.BadRequestError,
        ) as exc:
            raise LlmFatal(f"Anthropic 이 요청을 받지 않았다 (키와 모델 이름을 확인한다): {_short(exc)}") from exc
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            # 요청 한도(429), 서버 오류(5xx), 연결 오류는 SDK 가 이미 두 번 다시 불러 본 뒤다.
            raise LlmError(f"Anthropic 호출이 실패했다: {_short(exc)}") from exc
        except TypeError as exc:
            # 키를 찾지 못하면 SDK 가 요청을 보내기 전에 TypeError 를 낸다. 다른 TypeError 는 코드의 잘못이라 그대로 올린다.
            if "Could not resolve authentication" not in str(exc):
                raise
            raise LlmFatal("Anthropic 의 키를 찾지 못했다. .env 에 ANTHROPIC_API_KEY 를 넣는다") from exc
        if message.stop_reason == "refusal":
            raise LlmError("모델이 답하기를 거절했다 (stop_reason 이 refusal)")
        if message.stop_reason == "max_tokens":
            raise LlmError("답이 끝나기 전에 길이 한도에 닿았다 (stop_reason 이 max_tokens)")
        text = next((block.text for block in message.content if block.type == "text"), "")
        return LlmReply(text, message.usage.input_tokens, message.usage.output_tokens)


LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """다른 주소로 넘기는 답(3xx)을 따라가지 않는다. 따라가면 키가 든 헤더가 넘겨진 곳으로 함께 간다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None



class OpenAICompatibleProvider:
    """OpenAI 의 chat completions 와 같은 모양으로 받는 주소 (다른 공급자나 로컬 모델).

    패키지를 더하지 않으려고 표준 라이브러리로 부른다. 주소는 `LLM_BASE_URL`, 키는 `LLM_API_KEY` 다
    (키 없이 받는 로컬 주소면 비워 둔다). 주소는 https 여야 하고, http 는 이 PC 의 주소(localhost, 127.0.0.1, ::1)일 때만 받는다.
    """

    def __init__(self, model: str, base_url: str, api_key: str | None) -> None:
        address = urllib.parse.urlsplit(base_url)
        if address.scheme not in ("http", "https") or not address.hostname:
            raise LlmFatal("LLM_BASE_URL 은 http:// 나 https:// 로 시작하는 주소다 (예: https://api.openai.com/v1)")
        local = address.hostname in LOCAL_HOSTS
        if address.scheme == "http" and not local:
            # 암호화하지 않은 주소로 키와 요청을 내보내지 않는다. 이 PC 의 로컬 모델만 http 로 부른다.
            raise LlmFatal("LLM_BASE_URL 이 이 PC 의 주소(localhost, 127.0.0.1, ::1)가 아니면 https:// 로 적는다")
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        # 이 PC 의 주소는 프록시를 거치지 않고 바로 부른다. PC 에 프록시가 설정돼 있으면 로컬 요청이 그리로 나갈 수 있다.
        handlers = [_NoRedirect, urllib.request.ProxyHandler({})] if local else [_NoRedirect]
        self.opener = urllib.request.build_opener(*handlers)

    def complete(self, system: str, user: str) -> LlmReply:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=HTTP_TIMEOUT) as answer:
                payload = json.load(answer)
            choice = payload["choices"][0]
            text = choice["message"]["content"]
            usage = payload.get("usage") or {}
            tokens_in, tokens_out = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
            if not isinstance(text, str):
                raise TypeError("message.content 가 글이 아니다")
            if tokens_in < 0 or tokens_out < 0:
                raise ValueError("usage 의 토큰 수가 0 보다 작다")
            finish_reason = choice.get("finish_reason")
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise LlmFatal(f"주소가 다른 곳으로 넘기려 한다. 넘겨진 곳을 LLM_BASE_URL 에 직접 적는다: HTTP {exc.code}") from exc
            if exc.code in (400, 401, 403, 404):
                raise LlmFatal(f"주소가 요청을 받지 않았다 (키, 모델 이름, 주소를 확인한다): HTTP {exc.code}") from exc
            raise LlmError(f"호출이 실패했다: HTTP {exc.code}") from exc
        except OSError as exc:  # 연결 오류와 시간 초과 (URLError 는 OSError 다)
            raise LlmError(f"호출이 실패했다: {_short(exc)}") from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LlmError(f"돌아온 것이 chat completions 의 모양이 아니다: {_short(exc)}") from exc
        if finish_reason == "length":
            raise LlmError("답이 끝나기 전에 길이 한도에 닿았다 (finish_reason 이 length)")
        return LlmReply(text, tokens_in, tokens_out)


PROVIDERS = ("anthropic", "openai-compatible")


@dataclass(frozen=True)
class LlmSettings:
    provider: str
    model: str
    call_limit: int


def settings_from_env(env: Mapping[str, str] | None = None) -> LlmSettings:
    """환경 변수에서 공급자, 모델, 호출 상한을 읽는다. 적지 않은 것은 `.env.example` 에 적힌 기본값을 쓴다.

    키가 없어도 읽힌다. 저장된 응답을 재생만 할 때도 공급자와 모델은 알아야 하기 때문이다 (요청의 해시에 들어간다).
    """
    env = os.environ if env is None else env
    provider = env.get("LLM_PROVIDER", "").strip() or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        raise LlmFatal(f"LLM_PROVIDER 가 '{provider}' 다. 쓸 수 있는 값은 {', '.join(PROVIDERS)} 다")
    model = env.get("LLM_MODEL", "").strip() or DEFAULT_MODELS.get(provider, "")
    if not model:
        raise LlmFatal(f"공급자 '{provider}' 에는 기본 모델이 없다. LLM_MODEL 에 모델 이름을 적는다")
    raw_limit = env.get("LLM_CALL_LIMIT", "").strip()
    try:
        call_limit = int(raw_limit) if raw_limit else DEFAULT_CALL_LIMIT
    except ValueError:
        call_limit = -1
    if call_limit < 0:
        raise LlmFatal(f"LLM_CALL_LIMIT 은 0 이상의 정수다: '{raw_limit}'")
    return LlmSettings(provider, model, call_limit)


def make_provider(settings: LlmSettings, env: Mapping[str, str] | None = None) -> Provider:
    """설정에 적힌 공급자를 만든다. 공급자를 바꾸는 것은 환경 변수뿐이다."""
    env = os.environ if env is None else env
    if settings.provider == "anthropic":
        return AnthropicProvider(settings.model)
    base_url = env.get("LLM_BASE_URL", "").strip()
    if not base_url:
        raise LlmFatal("공급자가 openai-compatible 이면 LLM_BASE_URL 에 주소를 적는다")
    return OpenAICompatibleProvider(settings.model, base_url, env.get("LLM_API_KEY", "").strip() or None)


def prompt_path(root: Path, prompt_version: str) -> Path:
    """프롬프트 파일의 자리. 판 이름이 곧 파일 이름이다."""
    if not PROMPT_VERSION_RE.match(prompt_version):
        raise ValueError(f"prompt_version 은 영어 소문자, 숫자, '.', '_', '-' 로 적는다: '{prompt_version}'")
    return root / "personas" / "prompts" / f"{prompt_version}.md"


def load_prompt(root: Path, prompt_version: str) -> str:
    path = prompt_path(root, prompt_version)
    if not path.is_file():
        raise FileNotFoundError(f"프롬프트 파일이 없다: {path} (페르소나 담당이 personas/prompts/ 에 둔다)")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"프롬프트 파일이 비어 있다: {path}")
    return text


def user_message(request: ChoiceRequest) -> str:
    """LLM 에 보내는 사용자 메시지: 요청을 JSON 으로 적은 글."""
    return json.dumps(request_as_json(request), ensure_ascii=False, indent=2)
