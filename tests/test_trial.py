"""2단계 방식을 정하는 작은 실험 (T212, `engine/trial.py`). 실제 LLM 은 부르지 않고 가짜 공급자로 본다."""

import json
import shutil

import pytest

from engine import trial
from engine.llm import LlmReply
from tests.conftest import EXAMPLE_ROOT

PERSONA, CONDITION = "family-elders", "meal-dinner-weekend"


class FakeProvider:
    """요청의 첫 후보의 첫 주문을 고르고, 점수를 달라고 하면 첫 후보에 60, 이용하지 않음에 40 을 준다."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, system: str, user: str, schema: dict | None = None) -> LlmReply:
        request = json.loads(user)
        first = request["candidates"][0]
        answer = {
            "choice": {"venue_id": first["venue_id"], "option_id": first["options"][0]["option_id"], "addons": []},
            "reason_labels": [request["vocab"]["reasons_chosen"][0]],
            "reason_text": "가짜 이유",
            "used_attributes": [],
            "rejected": [
                {"venue_id": c["venue_id"], "pain_labels": [request["vocab"]["pain_points"][0]], "text": "가짜"}
                for c in request["candidates"][1:]
            ],
        }
        with_scores = trial.SCORE_NOTE in system
        self.calls.append("score" if with_scores else "ask")
        if with_scores:
            answer["scores"] = [{"venue_id": c["venue_id"], "percent": 0} for c in request["candidates"]] + [
                {"venue_id": "none", "percent": 40}
            ]
            answer["scores"][0]["percent"] = 60
        return LlmReply(json.dumps(answer, ensure_ascii=False), 100, 10)


@pytest.fixture
def copy_root(tmp_path):
    root = tmp_path / "example"
    shutil.copytree(EXAMPLE_ROOT, root)
    return root


def test_trial_refuses_a_plan_over_the_limit(copy_root, monkeypatch):
    """계획한 호출이 상한을 넘으면 한 번도 부르지 않고 멈춘다."""
    fake = FakeProvider()
    monkeypatch.setattr(trial, "make_provider", lambda settings: fake)
    code = trial.main(["--root", str(copy_root), "--personas", PERSONA, "--conditions", CONDITION, "--ask", "10", "--score", "2", "--limit", "11", "--prompt", "p1"])
    assert code == 1 and fake.calls == []


def test_trial_counts_choices_and_averages_scores(copy_root, monkeypatch):
    """여러 번 묻기는 고른 곳을 세고, 점수 받기는 후보마다 평균을 낸다. 결과는 private/trials/ 에만 쓴다."""
    fake = FakeProvider()
    monkeypatch.setattr(trial, "make_provider", lambda settings: fake)
    code = trial.main(["--root", str(copy_root), "--personas", PERSONA, "--conditions", CONDITION, "--ask", "3", "--score", "2", "--limit", "5", "--prompt", "p1"])
    assert code == 0
    assert fake.calls == ["ask"] * 3 + ["score"] * 2
    (out,) = (copy_root / "private" / "trials").iterdir()
    result = json.loads((out / "trial.json").read_text(encoding="utf-8"))
    assert result["calls"] == 5
    (visit,) = result["visits"]
    assert all(not r["problems"] for r in visit["asks"] + visit["scores"])
    first, *_, none = visit["summary"]
    assert (first["ask_count"], first["ask_n"], first["ask_pct"], first["ask_se_pp"]) == (3, 3, 100.0, 0.0)
    assert (first["score_mean"], none["place"], none["score_mean"]) == (60.0, "none", 40.0)


def test_score_problems_wants_every_place_once_and_a_total_of_100():
    places = ["geumryong", "none"]
    assert trial.score_problems([{"venue_id": "geumryong", "percent": 70}, {"venue_id": "none", "percent": 30}], places) == []
    assert trial.score_problems([{"venue_id": "geumryong", "percent": 70}], places)
    assert trial.score_problems([{"venue_id": "geumryong", "percent": 70}, {"venue_id": "none", "percent": 20}], places)
    assert trial.score_problems(None, places) == ["scores 가 없다"]


def test_trial_on_base_data_needs_the_same_confirmation_as_the_engine(copy_root, monkeypatch):
    """기본 데이터로 돌리면 본 실행처럼 BASE_PROFILE_CONFIRMED_FOR 가 받는 곳과 같아야 한다. 없으면 부르지 않는다."""
    fake = FakeProvider()
    monkeypatch.setattr(trial, "make_provider", lambda settings: fake)
    monkeypatch.setattr(trial, "load_dotenv", lambda path: None)
    monkeypatch.delenv("BASE_PROFILE_CONFIRMED_FOR", raising=False)
    code = trial.main(["--root", str(copy_root), "--data", "private", "--personas", PERSONA, "--conditions", CONDITION, "--ask", "1", "--score", "0", "--limit", "1"])
    assert code == 1 and fake.calls == []
