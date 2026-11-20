"""방문이 몫으로 나뉘어 여러 곳에 간 원장 (T212 의 2단계 방식, docs/FORMATS.md 9절 "점수와 몫", 10.2절).

예시 묶음의 사본에서 점수를 묻는 판(`p4`, 사본에만 둔다)으로 엔진을 돌린다. LLM 대신 테스트가 끼운 공급자가 점수를 나눈 답을 준다.
형식 검사(`tools.check_formats`)와 위반 세기(`engine.audit`)가 곳마다 나눠 보는지, 손으로 고친 원장을 잡는지 본다.
"""

import json
import shutil
from pathlib import Path

from engine.audit import violations
from engine.formats import ChoiceRequest, ChoiceResponse, LedgerRow
from engine.llm import LlmReply
from engine.runner import run
from tests.conftest import load_csv, save_csv
from tests.test_engine import DINNER, MODEL, NOW, PROVIDER, Played, answer, edit, product_of, venue_file
from tools.check_formats import check

PROMPT = "p4"  # 점수를 묻는 판 (SINGLE_ANSWER_PROMPTS 밖)
# 금룡 60, 예시호텔 중식당 30, 이용하지 않음 10. k 와 업장 상수가 1 이면 몫은 0.6, 0.3, 0.1 이다.
PERCENTS: dict[str | None, int] = {"geumryong": 60, "examplehotel-chinese": 30, None: 10}


def scored(request: ChoiceRequest, percents: dict[str | None, int], chosen: str = "geumryong") -> ChoiceResponse:
    """`chosen` 의 첫 주문을 고르고, 후보마다와 "이용하지 않음"에 점수를 적은 답. 점수가 0 보다 큰 곳은 첫 주문을 고른다."""
    base = answer(request, chosen, request.candidate(chosen).options[0].option_id)
    entries = [
        {
            "venue_id": c.venue_id,
            "percent": percents.get(c.venue_id, 0),
            "option_id": c.options[0].option_id if percents.get(c.venue_id, 0) else None,
            "addons": [],
        }
        for c in request.candidates
    ]
    entries.append({"venue_id": None, "percent": percents.get(None, 0), "option_id": None, "addons": []})
    return ChoiceResponse.model_validate({**base.model_dump(mode="json"), "scores": entries})


class Scoring:
    """테스트가 끼우는 공급자. 요청을 받아 점수를 나눈 답을 준다."""

    def __init__(self, percents: dict[str | None, int]) -> None:
        self.percents = percents

    def complete(self, system: str, user: str, schema: dict | None = None) -> LlmReply:
        request = ChoiceRequest.model_validate_json(user)
        response = scored(request, self.percents)
        return LlmReply(json.dumps(response.model_dump(mode="json"), ensure_ascii=False), 11, 7)


def play_scored(root: Path, percents: dict[str | None, int] = PERCENTS) -> Played:
    prompts = root / "personas" / "prompts"
    shutil.copy(prompts / "p1.md", prompts / f"{PROMPT}.md")
    run_dir = run(
        root,
        data_mode="sample",
        now=NOW,
        provider=PROVIDER,
        model=MODEL,
        prompt_version=PROMPT,
        answers=[],
        persona_ids=["family-elders"],
        condition_ids=[DINNER],
        engine_commit="0000000",
        llm=Scoring(percents),
        call_limit=10,
    )
    return Played(root, run_dir, {})


def ledger_of(played: Played) -> Path:
    return played.run_dir / "ledger.csv"


def errors(root: Path) -> list[str]:
    return [str(p) for p in check(root, strict=True)]


def has(problems: list[str], text: str) -> bool:
    return any(text in p for p in problems)


def weighted(row: dict, share: float) -> str:
    """고른 몫을 바꾼 줄의 가중 매출 (원 단위 반올림). 줄 하나의 검사에는 걸리지 않게 맞춘다."""
    value = int(row["revenue_net"]) * float(row["represented"]) * float(row["counted_share"]) * share
    return str(int(value + 0.5))


def test_scored_visit_is_split_across_places_and_passes(example_copy):
    played = play_scored(example_copy)
    assert played.record.share_method == "scores"
    rows = played.visit("family-elders", DINNER)
    shares = {row.venue_id: (row.choice_share, row.score) for row in rows}
    assert shares == {"geumryong": (0.6, 60), "examplehotel-chinese": (0.3, 30), None: (0.1, 10)}
    # 고른 이유는 choice 에 적은 곳(금룡)의 줄에만 있다.
    assert [row.venue_id for row in rows if row.reason_text] == ["geumryong"]
    assert errors(example_copy) == []
    assert played.violations() == []


def test_checker_catches_a_tampered_split(example_copy):
    played = play_scored(example_copy)
    path = ledger_of(played)
    original = load_csv(path)

    def tampered(change) -> list[str]:
        rows = [dict(row) for row in original]
        change(rows)
        save_csv(path, rows)
        return errors(example_copy)

    def at(rows: list[dict], venue_id: str) -> dict:
        return next(row for row in rows if row["venue_id"] == venue_id)

    # 금룡의 몫을 0.5 로, 이용하지 않음을 0.2 로: 합은 1 이지만 점수로 낸 몫과 다르다.
    def move_share(rows):
        at(rows, "geumryong").update(choice_share="0.5", weighted_revenue=weighted(at(rows, "geumryong"), 0.5))
        at(rows, "").update(choice_share="0.2")

    problems = tampered(move_share)
    assert has(problems, "'geumryong' 의 choice_share 가 점수와 결정 상수로 다시 낸 몫(0.6)과 다르다"), problems
    assert has(problems, "'이용하지 않음' 의 choice_share 가"), problems
    assert not has(problems, "더하면 1 이어야"), problems

    # 몫의 합이 1 이 아니다.
    problems = tampered(lambda rows: at(rows, "").update(choice_share="0.3"))
    assert has(problems, "곳마다의 choice_share 를 더하면 1 이어야 하는데"), problems

    # 점수가 0 보다 큰 곳의 줄을 뺐다.
    problems = tampered(lambda rows: rows.remove(at(rows, "examplehotel-chinese")))
    assert has(problems, "점수가 0 보다 큰 곳 'examplehotel-chinese' 의 줄이 원장에 없다"), problems

    # 점수가 응답과 다르다.
    problems = tampered(lambda rows: at(rows, "examplehotel-chinese").update(score="31"))
    assert has(problems, "'examplehotel-chinese' 의 줄의 score 가 저장된 응답의 점수(30)와 다르다"), problems

    # 고르지 않은 곳의 줄에 이유를 적었다.
    def reasons_elsewhere(rows):
        chosen = at(rows, "geumryong")
        at(rows, "examplehotel-chinese").update({k: chosen[k] for k in ("reason_labels", "reason_text", "used_attributes")})

    problems = tampered(reasons_elsewhere)
    assert has(problems, "고른 이유는 응답의 choice 에 적은 곳의 줄에만 적는다"), problems

    # 고른 곳의 이유가 응답과 다르다.
    problems = tampered(lambda rows: at(rows, "geumryong").update(reason_text="다른 이유"))
    assert has(problems, "고른 이유(reason_labels, reason_text, used_attributes)가 저장된 응답과 다르다"), problems

    # 다른 곳의 주문이 scores 의 주문과 다르다 (같은 금액 계산이라 줄 하나의 검사에는 걸리지 않는다).
    def other_order(rows):
        row = at(rows, "examplehotel-chinese")
        row.update(quantity="3", paid=str(3 * int(row["list_price"]) - int(row["discount"])))

    problems = tampered(other_order)
    assert has(problems, "원장의 줄이 저장된 응답에서 고른 주문과 다르다 ('examplehotel-chinese'"), problems

    # 원래대로 돌리면 통과한다.
    save_csv(path, original)
    assert errors(example_copy) == []


def test_checker_needs_k_in_the_run_record(example_copy):
    played = play_scored(example_copy)
    record = played.run_dir / "run.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["constants"] = [c for c in data["constants"] if c["constant_id"] != "share-sharpness-k"]
    record.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    assert has(errors(example_copy), "실행 기록의 constants 에 'share-sharpness-k'")


def test_audit_checks_each_place(example_copy):
    played = play_scored(example_copy)
    assert played.violations() == []

    # 점수가 0 인 곳으로 간 줄은 응답과 다르다.
    zeroed = {}
    for key, entry in played.saved.items():
        scores = [s.model_copy(update={"percent": 0}) if s.venue_id == "examplehotel-chinese" else s for s in entry.response.scores]
        zeroed[key] = entry.model_copy(update={"response": entry.response.model_copy(update={"scores": scores})})
    found = played_violations(played, saved=zeroed)
    assert any("응답과 다른 곳" in v and "examplehotel-chinese" in v for v in found), found

    # 업장마다 따로 본다: 경쟁 업장의 표시가만 틀린 원장은 그 업장에서만 한 건 나온다.
    rows = [
        r.model_copy(update={"list_price": r.list_price + 1, "paid": r.paid + r.quantity}) if r.venue_id == "examplehotel-chinese" else r
        for r in played.rows
    ]
    found = played_violations(played, rows=rows)
    assert len(found) == 1 and "금액 불일치" in found[0] and "course" in found[0], found


def played_violations(played: Played, *, rows: list[LedgerRow] | None = None, saved=None) -> list[str]:
    return violations(
        played.rows if rows is None else rows,
        played.venues,
        played.saved if saved is None else saved,
        played.personas,
        played.bundle,
        month=played.record.month,
    )


def test_seasonal_place_has_its_own_gap_row(example_copy):
    """석 달만 파는 금룡의 몫: 금룡 줄의 counted_share 는 0.25, 나머지 0.75 는 season_gap_of 가 금룡인 줄이고 몫은 금룡의 것이다."""
    edit(venue_file(example_copy, "geumryong"), lambda d: product_of(d, "course-a").update(months=[4, 5, 6]))
    played = play_scored(example_copy)
    rows = played.visit("family-elders", DINNER)
    (gap,) = [row for row in rows if row.season_gap_of == "geumryong"]
    assert (gap.counted_share, gap.choice_share, gap.score) == (0.75, 0.6, 60)
    (unused,) = [row for row in rows if row.choice_kind == "none" and row.season_gap_of is None]
    assert (unused.counted_share, unused.choice_share) == (1.0, 0.1)
    assert errors(example_copy) == []
    assert played.violations() == []

    path = ledger_of(played)
    original = load_csv(path)

    def tampered(change) -> list[str]:
        rows_ = [dict(row) for row in original]
        change(rows_)
        save_csv(path, rows_)
        return errors(example_copy)

    def gap_row(rows_: list[dict]) -> dict:
        return next(row for row in rows_ if row["season_gap_of"] == "geumryong")

    # 나머지 몫의 줄이 어느 곳의 것인지 지웠다: "이용하지 않음"의 줄이 둘이 되고 금룡의 나머지 몫이 없다.
    problems = tampered(lambda rows_: gap_row(rows_).update(season_gap_of=""))
    assert has(problems, "일부 달에만 파는 곳을 고른 방문에는 '이용하지 않음' 줄이 하나 더 있어야 한다"), problems
    assert has(problems, "'이용하지 않음'의 몫을 센 줄이 둘 이상이다"), problems

    # 나머지 몫의 줄의 choice_share 가 그 곳의 몫과 다르다.
    problems = tampered(lambda rows_: gap_row(rows_).update(choice_share="0.5"))
    assert has(problems, "곳 'geumryong' 의 줄들('파는 달이 아님' 줄 포함)의 choice_share 가 서로 다르다"), problems

    # 위반 세기도 금룡의 나머지 몫이 없으면 잡는다. "이용하지 않음"의 몫을 센 줄은 금룡의 나머지로 치지 않는다.
    no_gap = [row for row in played.rows if row.season_gap_of is None]
    assert any("몫 불일치" in v for v in played_violations(played, rows=no_gap))
