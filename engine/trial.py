"""2단계 방식을 정하는 작은 실험 (T212, 11-20 wilstein91). 본 실행(`python -m engine`)과 따로 돌고 본 실행의 답을 건드리지 않는다.

같은 방문을 두 방식으로 물어 견준다.
- 여러 번 묻기(`ask`): 지금의 요청을 그대로 N번 묻고, 고른 곳을 세어 비율을 낸다.
- 점수 받기(`score`): 같은 요청에 "후보마다 고를 몫(%)"을 함께 적게 해 M번 묻는다. 점수의 평균과, 점수가 부를 때마다 얼마나 흔들리는지를 본다.
점수 받기의 지시는 프롬프트 파일을 고치지 않고 이 실험에서만 시스템 프롬프트 끝에 붙인다 (`SCORE_NOTE`). 방식이 정해지면 페르소나 담당이 프롬프트에 옮긴다.

가상 예시 값(`--data sample`)으로만 돈다. 기본 데이터의 요약을 보내지 않는다.
받은 답과 요약은 `private/trials/<시각>/` 에 쓴다 (깃이 무시한다). 호출 수가 `--limit` 을 넘을 계획이면 부르기 전에 멈춘다.

    uv run python -m engine.trial --personas couple-anniversary --conditions meal-dinner-weekend dessert-weekend --ask 10 --score 2 --limit 25
"""

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from engine.answers import read_reply
from engine.candidates import build_request, run_condition
from engine.formats.choice import ChoiceRequest, problems_in_response
from engine.ledger import amount_problems
from engine.llm import (
    LlmError,
    LlmFatal,
    Provider,
    load_prompt,
    make_provider,
    response_schema,
    settings_from_env,
    user_message,
)
from engine.runner import load_inputs

NONE = "none"

SCORE_NOTE = """

## 이번 요청에 더하는 것 (실험, 2단계 방식 정하기)

위의 답에 더해 `scores` 를 적는다. 이 손님이 같은 상황을 백 번 맞는다면 후보마다 몇 번 그곳을 고를지를 정수(%)로 적는다.
후보의 `venue_id` 마다 하나, 이용하지 않음은 `none` 으로 하나 적고, 모두 더하면 100 이다.
`choice` 에는 지금처럼 이번 한 번의 선택을 적는다."""


def score_schema(request: ChoiceRequest) -> dict[str, Any]:
    """점수 받기의 응답 모양: 지금의 응답에 `scores` 를 더한다."""
    schema = response_schema(request)
    places = [c.venue_id for c in request.candidates] + [NONE]
    schema["properties"]["scores"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "venue_id": {"type": "string", "enum": places},
                "percent": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "required": ["venue_id", "percent"],
            "additionalProperties": False,
        },
    }
    schema["required"] = [*schema["required"], "scores"]
    return schema


def places_of(request: ChoiceRequest) -> list[str]:
    return [c.venue_id for c in request.candidates] + [NONE]


def score_problems(scores: Any, places: list[str]) -> list[str]:
    """점수가 후보마다(이용하지 않음 포함) 하나씩 있고 합이 100 인가."""
    if not isinstance(scores, list):
        return ["scores 가 없다"]
    seen = [s.get("venue_id") for s in scores if isinstance(s, dict)]
    problems = []
    if sorted(seen) != sorted(places):
        problems.append(f"scores 의 후보가 요청과 다르다: {sorted(seen)}")
    if sum(int(s.get("percent", 0)) for s in scores if isinstance(s, dict)) != 100:
        problems.append("scores 의 합이 100 이 아니다")
    return problems


def ask_once(provider: Provider, system: str, request: ChoiceRequest, venues: dict, with_scores: bool) -> dict[str, Any]:
    """한 번 묻는다. 고른 곳, 점수, 어긋난 점, 토큰을 돌려준다. 호출이 실패해도 결과에 남긴다 (LlmFatal 만 위로 올린다)."""
    schema = score_schema(request) if with_scores else response_schema(request)
    try:
        reply = provider.complete(system + (SCORE_NOTE if with_scores else ""), user_message(request), schema)
    except LlmError as exc:
        if isinstance(exc, LlmFatal):
            raise
        return {"chosen": None, "scores": None, "problems": [str(exc)], "tokens_in": 0, "tokens_out": 0, "raw": None}
    text = reply.text
    scores = None
    if with_scores:
        start, end = text.find("{"), text.rfind("}")
        try:
            data = json.loads(text[start : end + 1])
            scores = data.pop("scores", None)
            text = json.dumps(data, ensure_ascii=False)
        except ValueError:
            pass
    response, problems = read_reply(text)
    if response is not None:
        problems = problems_in_response(request, response) or amount_problems(request, response, venues)
    if with_scores:
        problems += score_problems(scores, places_of(request))
    chosen = (response.choice.venue_id or NONE) if response is not None else None
    return {
        "chosen": chosen,
        "scores": {s["venue_id"]: s["percent"] for s in scores} if isinstance(scores, list) else None,
        "problems": problems,
        "tokens_in": reply.input_tokens,
        "tokens_out": reply.output_tokens,
        "raw": reply.text,
    }


def summarize(places: list[str], asks: list[dict], scores: list[dict]) -> list[dict[str, Any]]:
    """후보마다: 여러 번 묻기의 비율과 그 흔들림(표준 오차), 점수의 평균·가장 작은 값·가장 큰 값."""
    chosen = Counter(a["chosen"] for a in asks if a["chosen"] is not None)
    n = sum(chosen.values())
    good_scores = [s["scores"] for s in scores if s["scores"] is not None and not s["problems"]]
    rows = []
    for place in places:
        share = chosen[place] / n if n else None
        row: dict[str, Any] = {
            "place": place,
            "ask_count": chosen[place],
            "ask_n": n,
            "ask_pct": None if share is None else round(100 * share, 1),
            # 비율의 표준 오차 (%p). 같은 실험을 다시 하면 비율이 대략 이만큼 움직인다.
            "ask_se_pp": None if share is None or n == 0 else round(100 * math.sqrt(share * (1 - share) / n), 1),
        }
        values = [s.get(place, 0) for s in good_scores]
        row["score_mean"] = round(sum(values) / len(values), 1) if values else None
        row["score_min"] = min(values) if values else None
        row["score_max"] = max(values) if values else None
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.trial", description="2단계 방식(여러 번 묻기·점수 받기)을 가상 예시 값으로 견준다 (T212).")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--personas", nargs="+", required=True)
    parser.add_argument("--conditions", nargs="+", required=True)
    parser.add_argument("--ask", type=int, default=10, help="여러 번 묻기의 횟수 (방문마다)")
    parser.add_argument("--score", type=int, default=2, help="점수 받기의 횟수 (방문마다)")
    parser.add_argument("--limit", type=int, required=True, help="이 실험에서 부를 수 있는 가장 많은 수")
    parser.add_argument("--prompt", default="p3")
    args = parser.parse_args(argv)

    load_dotenv(Path.cwd() / ".env")
    root = args.root.resolve()
    planned = len(args.personas) * len(args.conditions) * (args.ask + args.score)
    if planned > args.limit:
        print(f"계획한 호출 {planned}번이 상한 {args.limit}번을 넘어 부르지 않는다", file=sys.stderr)
        return 1
    inputs = load_inputs(root, "sample", persona_ids=args.personas, base_profile_mode="none")
    settings = settings_from_env()
    provider = make_provider(settings)
    system = load_prompt(root, args.prompt)
    out = root / "private" / "trials" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    print(f"실험 폴더: {out}")
    print(f"공급자 {settings.provider} · 모델 {settings.model} · 프롬프트 {args.prompt} · 계획한 호출 {planned}번")

    visits = []
    calls = 0
    for persona_id in args.personas:
        persona = inputs.personas[persona_id]
        for condition_id in args.conditions:
            condition = run_condition(inputs.conditions.condition(condition_id), persona)
            request, _ = build_request(
                prompt_version=args.prompt,
                persona=inputs.persona_json[persona_id],
                condition=condition,
                venues=list(inputs.venues.values()),
                vocab=inputs.vocab,
            )
            visit_id = f"{persona_id}__{condition_id}"
            if request is None:
                print(f"{visit_id}: 후보가 없어 건너뛴다")
                continue
            asks, scores = [], []
            try:
                for k in range(args.ask):
                    asks.append(ask_once(provider, system, request, inputs.venues, with_scores=False))
                    calls += 1
                    print(f"  {visit_id} 여러 번 묻기 {k + 1}/{args.ask}: {asks[-1]['chosen']}")
                for k in range(args.score):
                    scores.append(ask_once(provider, system, request, inputs.venues, with_scores=True))
                    calls += 1
                    print(f"  {visit_id} 점수 받기 {k + 1}/{args.score}: {scores[-1]['scores']}")
            except LlmFatal as exc:
                print(f"멈춘다: {exc}", file=sys.stderr)
                visits.append({"visit_id": visit_id, "asks": asks, "scores": scores})
                break
            places = places_of(request)
            visits.append({"visit_id": visit_id, "places": places, "asks": asks, "scores": scores, "summary": summarize(places, asks, scores)})
    tokens_in = sum(r["tokens_in"] for v in visits for r in v["asks"] + v["scores"])
    tokens_out = {
        "ask": [r["tokens_out"] for v in visits for r in v["asks"] if r["tokens_out"]],
        "score": [r["tokens_out"] for v in visits for r in v["scores"] if r["tokens_out"]],
    }
    result = {"calls": calls, "tokens_in": tokens_in, "tokens_out": tokens_out, "visits": visits}
    (out / "trial.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    for visit in visits:
        print(f"\n{visit['visit_id']}")
        for row in visit.get("summary", []):
            print(
                f"  {row['place']:<28} 여러 번 묻기 {row['ask_count']}/{row['ask_n']} ({row['ask_pct']}% ± {row['ask_se_pp']}%p)"
                f" · 점수 평균 {row['score_mean']} (가장 작은 {row['score_min']} ~ 가장 큰 {row['score_max']})"
            )
        bad = [p for r in visit["asks"] + visit["scores"] for p in r["problems"]]
        if bad:
            print(f"  어긋난 답 {len(bad)}건: {bad[:3]}")
    print(f"\n부른 수 {calls}번 · 입력 토큰 합 {tokens_in}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
