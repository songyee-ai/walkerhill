"""검증 결과 보기: 떼어 둔 후기로 잰 결과를 업장별 건수와 한계와 함께 보여 준다 (T19 의 결과를 화면에, T22·T24).

검증 결과(`validation.json`)는 기본 데이터로 돌린 실행 폴더(`private/runs/<run_id>/`)에만 생긴다 (docs/FORMATS.md 10.5절).
값은 비율이 아니라 건수로 보여 준다 ("12건 중 8건"). 5건 미만인 업장은 "검증 건수 부족"으로 보여 주고 일치 건수를 말하지 않는다.

검증 결과를 보여 줄 때는 업장별 검증 건수와 아래 한계를 함께 보여 준다 (11-16 팀원 요청).
한계의 원문은 docs/REVIEW_RULES.md 6절 "이 규칙보다 먼저 나눈 파일"이다. 그 절이 바뀌면 여기도 고친다.
"""

from pathlib import Path

from engine.formats import Validation, read_model

LIMITS_SOURCE = "docs/REVIEW_RULES.md 6절"
VALIDATION_LIMITS = {
    "geumryong": "후기를 나눌 때 쓴 무작위 값(씨앗)이 남아 있지 않아, 같은 나눔을 다시 만들어 확인할 수 없습니다. 줄 수와 작성자 겹침만 확인했습니다.",
    "myongwolgwan": "떼어 둔 후기가 페르소나 쪽에서 미리 태그 분포를 본 시험 파일에서 나왔습니다. 이미 본 셈이라 결과가 실제보다 좋게 나올 수 있습니다.",
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
