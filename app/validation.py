"""검증 결과 보기: 떼어 둔 후기로 잰 결과를 업장별 건수와 한계와 함께 보여 준다 (T19 의 결과를 화면에, T22·T24).

검증 결과(`validation.json`)는 기본 데이터로 돌린 실행 폴더(`private/runs/<run_id>/`)에만 생긴다 (docs/FORMATS.md 10.5절).
값은 비율이 아니라 건수로 보여 준다 ("12건 중 8건"). 5건 미만인 업장은 "검증 건수 부족"으로 보여 주고 일치 건수를 말하지 않는다.

검증 결과를 보여 줄 때는 업장별 검증 건수와 아래 한계를 함께 보여 준다 (11-16 팀원 요청).
한계의 원문은 docs/REVIEW_RULES.md 6절 "지금까지 나눈 것과 한계"다. 그 절의 문장이 바뀌면 `LIMITS_SOURCE_LINES` 가
원문에서 사라져 테스트(tests/app/test_app_compare.py)가 실패한다. 그때 원문을 다시 읽고 화면 문구를 함께 고친다.
(11-16, 원문이 PR #44 로 바뀐 것을 모르고 옛 문구를 보여 주던 것을 페르소나 담당이 찾아 줌)
"""

from pathlib import Path

from engine.formats import Validation, read_model

LIMITS_SECTION = "지금까지 나눈 것과 한계"
LIMITS_SOURCE = f'docs/REVIEW_RULES.md 6절 "{LIMITS_SECTION}"'
# 화면 문구가 옮겨 온 원문의 문장 (고칠 때 원문과 대조하려고 남긴다).
LIMITS_SOURCE_LINES = {
    "geumryong": "금룡은 11-13 에 지금과 다른 씨앗으로 나눴다. 그 씨앗과 프로그램도 업장 데이터 담당에게 넘어가 다시 나눠 같은 결과인 것을 확인했다.",
    "myongwolgwan": "명월관은 11-13 에 페르소나 쪽에서 태그 분포를 본 시험 파일을 그대로 나눴다 (본문은 읽지 않았다).",
}
VALIDATION_LIMITS = {
    "geumryong": "11-13 에 다른 업장과 다른 씨앗(무작위 값)으로 나눴습니다. 그 씨앗으로 다시 나눠 같은 결과인 것은 확인했지만, "
    "지금 씨앗과 달라 금룡 후기를 더 모으면 이어서 나누는 방법을 따로 정해야 합니다.",
    "myongwolgwan": "떼어 둔 후기가 11-13 에 페르소나 쪽에서 태그 분포를 본 시험 파일을 그대로 나눈 것입니다 (본문은 읽지 않았습니다).",
}


def load_validation(run_dir: Path) -> Validation | None:
    path = run_dir / "validation.json"
    return read_model(path, Validation) if path.is_file() else None


def _of(count: int | None, n: int) -> str:
    return "" if count is None else f"{n}건 중 {count}건"


def validation_rows(validation: Validation, names: dict[str, str]) -> list[dict]:
    """업장마다 한 줄: 검증 건수, 일치 건수(기준 방식과 함께), 상태, 한계."""
    rows = []
    for venue_id, result in sorted(validation.venues.items(), key=lambda item: names.get(item[0], item[0])):
        rows.append(
            {
                "업장": names.get(venue_id, venue_id),
                "검증 건수": result.n,
                "고른 업장이 같음": _of(result.venue_match, result.n),
                "같음 (단순 기준)": _of(result.venue_match_baseline, result.n),
                "이유가 겹침": _of(result.reason_match, result.n),
                "겹침 (단순 기준)": _of(result.reason_match_baseline, result.n),
                "상태": "" if result.enough else f"검증 건수 부족 ({validation.min_reviews}건 미만)",
                "한계": VALIDATION_LIMITS.get(venue_id, ""),
            }
        )
    return rows


def limits_not_in(validation: Validation) -> list[str]:
    """한계가 있는데 검증 결과에 없는 업장. 결과에 없더라도 한계는 감추지 않는다."""
    return [venue_id for venue_id in VALIDATION_LIMITS if venue_id not in validation.venues]
