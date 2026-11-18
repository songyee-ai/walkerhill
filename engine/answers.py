"""저장된 응답을 찾아 재생한다 (docs/FORMATS.md 10.3절).

LLM 없이 돌릴 때 쓰는 "정해 둔 답"도 저장된 응답의 모양(`<request_hash>.json`)으로 둔다.
원장에서 업장을 고른 줄은 저장된 응답에서 나온 것이어야 하기 때문이다.
LLM 이 돌려준 글을 응답으로 읽는 것, 검사를 통과한 응답과 어긋난 응답을 저장하는 것도 여기 있다.
LLM 을 부르는 것은 `engine/llm.py` 다.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from engine.formats.choice import ChoiceRequest, ChoiceResponse
from engine.formats.io import write_json
from engine.formats.run import RejectedResponse, SavedResponse, compute_request_hash


def request_as_json(request: ChoiceRequest) -> dict[str, Any]:
    """요청을 해시를 내고 파일에 적을 모양으로 바꾼다."""
    return request.model_dump(mode="json", by_alias=True)


class AnswerBook:
    """폴더들에서 저장된 응답을 찾는다. 앞의 폴더부터 본다."""

    def __init__(self, folders: list[Path], provider: str, model: str) -> None:
        self.folders = folders
        self.provider = provider
        self.model = model

    def hash_of(self, request: ChoiceRequest) -> str:
        return compute_request_hash(self.provider, self.model, request_as_json(request))

    def find(self, request: ChoiceRequest) -> tuple[str, Path | None, SavedResponse | None, str | None]:
        """(해시, 찾은 파일, 읽은 응답, 읽지 못한 이유)를 돌려준다. 파일이 없으면 뒤의 셋은 None 이다.

        파일에 적힌 요청으로 해시를 다시 내 파일 이름과 견준다. 요청을 손으로 고친 파일은 쓰지 않는다.
        """
        request_hash = self.hash_of(request)
        for folder in self.folders:
            path = folder / f"{request_hash}.json"
            if not path.is_file():
                continue
            raw = path.read_bytes()
            try:
                saved = SavedResponse.model_validate_json(raw, strict=True)
                written = compute_request_hash(saved.provider, saved.model, json.loads(raw)["request"])
            except (ValidationError, ValueError) as exc:
                return request_hash, path, None, f"저장된 응답을 읽을 수 없다: {type(exc).__name__}"
            if written != request_hash or saved.request_hash != request_hash:
                return request_hash, path, None, "저장된 응답의 요청이 파일 이름의 해시와 맞지 않는다"
            return request_hash, path, saved, None
        return request_hash, None, None, None


def old_style_folder(folders: list[Path]) -> Path | None:
    """요청에 `scenario_id` 가 든 옛 모양의 저장된 응답이 있는 첫 폴더. 없으면 None (11-18, T121).

    옛 모양의 답은 해시가 달라 조용히 재생되지 않는다. 돌리기 전에 알려 주려고 본다.
    폴더마다 파일 하나만 읽는다. 변환 도구(`tools/rehash_answers.py`)가 폴더를 통째로 바꾸기 때문이다.
    """
    for folder in folders:
        first = next(iter(sorted(folder.glob("*.json"))), None)
        if first is None:
            continue
        try:
            request = json.loads(first.read_bytes()).get("request")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(request, dict) and "scenario_id" in request:
            return folder
    return None


def read_reply(raw_text: str) -> tuple[ChoiceResponse | None, list[str]]:
    """LLM 이 돌려준 글을 응답으로 읽는다. (응답, 읽지 못한 이유)를 돌려준다.

    글의 앞뒤에 코드 울타리나 말이 붙어 있으면 맨 바깥의 `{ … }` 만 읽는다. 그 안은 적힌 그대로 엄격하게 본다.
    """
    start, end = raw_text.find("{"), raw_text.rfind("}")
    if start < 0 or end < start:
        return None, ["응답에 JSON 이 없다"]
    try:
        return ChoiceResponse.model_validate_json(raw_text[start : end + 1], strict=True), []
    except ValidationError as exc:
        where = sorted({".".join(str(part) for part in error["loc"]) or "(맨 위)" for error in exc.errors()})
        return None, [f"응답이 형식에 맞지 않는다: {', '.join(where)}"]


def save_response(
    folder: Path,
    provider: str,
    model: str,
    request: ChoiceRequest,
    response: ChoiceResponse,
    created_at: datetime,
    raw_text: str,
    input_tokens: int,
    output_tokens: int,
) -> str:
    """검사를 통과한 응답 하나를 저장한다 (docs/FORMATS.md 10.3절). 해시를 돌려준다."""
    request_json = request_as_json(request)
    request_hash = compute_request_hash(provider, model, request_json)
    data = {
        "format_version": 1,
        "request_hash": request_hash,
        "provider": provider,
        "model": model,
        "created_at": created_at.isoformat(),
        "request": request_json,
        "response": response.model_dump(mode="json"),
        "raw_text": raw_text,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
    # 형식 검사가 받지 않을 파일을 쓰지 않는다. 쓰기 전에 같은 모델로 본다.
    SavedResponse.model_validate(data)
    write_json(folder / f"{request_hash}.json", data)
    return request_hash


def save_answer(
    folder: Path,
    provider: str,
    model: str,
    request: ChoiceRequest,
    response: ChoiceResponse,
    created_at: datetime,
) -> str:
    """정해 둔 답 하나를 저장된 응답의 모양으로 쓴다. 해시를 돌려준다.

    LLM 이 답한 것이 아니므로 `raw_text` 에는 응답을 JSON 으로 적은 글을 넣고 `usage` 는 0 이다.
    """
    raw_text = json.dumps(response.model_dump(mode="json"), ensure_ascii=False)
    return save_response(folder, provider, model, request, response, created_at, raw_text, 0, 0)


def save_rejected(
    folder: Path,
    provider: str,
    model: str,
    request: ChoiceRequest,
    created_at: datetime,
    llm_call: str,
    raw_text: str,
    problems: list[str],
    input_tokens: int,
    output_tokens: int,
) -> str:
    """검사에서 어긋난 응답 하나를 남긴다 (docs/FORMATS.md 10.3절의 "어긋난 응답"). 재생에는 쓰지 않는다. 해시를 돌려준다."""
    request_json = request_as_json(request)
    request_hash = compute_request_hash(provider, model, request_json)
    data = {
        "format_version": 1,
        "request_hash": request_hash,
        "provider": provider,
        "model": model,
        "created_at": created_at.isoformat(),
        "llm_call": llm_call,
        "request": request_json,
        "raw_text": raw_text,
        "problems": problems,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
    RejectedResponse.model_validate(data)
    write_json(folder / f"{request_hash}.json", data)
    return request_hash
