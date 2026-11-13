"""저장된 응답을 찾아 재생한다 (docs/FORMATS.md 10.3절).

LLM 없이 돌릴 때 쓰는 "정해 둔 답"도 저장된 응답의 모양(`<request_hash>.json`)으로 둔다.
원장에서 업장을 고른 줄은 저장된 응답에서 나온 것이어야 하기 때문이다.
LLM 을 실제로 부르고 그 응답을 저장하는 것은 T05 에서 여기에 더한다.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from engine.formats.choice import ChoiceRequest, ChoiceResponse
from engine.formats.io import write_json
from engine.formats.run import SavedResponse, compute_request_hash


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
    request_json = request_as_json(request)
    request_hash = compute_request_hash(provider, model, request_json)
    response_json = response.model_dump(mode="json")
    write_json(
        folder / f"{request_hash}.json",
        {
            "format_version": 1,
            "request_hash": request_hash,
            "provider": provider,
            "model": model,
            "created_at": created_at.isoformat(),
            "request": request_json,
            "response": response_json,
            "raw_text": json.dumps(response_json, ensure_ascii=False),
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    )
    return request_hash
