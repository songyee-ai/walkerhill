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
# 모에기의 한계는 11-17 회의 사.에서 정했다. 그 문장을 "T19 결과, 화면의 검증 칸, 발표 자료에 똑같이 적는다".
MEETING_LIMITS_SECTION = "### 사."
LIMITS_SOURCE = f'docs/REVIEW_RULES.md 6절 "{LIMITS_SECTION}", 모에기는 docs/MEETING_1117.md 사.'
MEETING_LIMIT_LINES = {
    "moegi": "모에기의 검증 후기 5건 가운데 3건이 엔진 담당의 시험 자료에 들어 있었다. 페르소나 담당은 보지 않았다.",
}
# 화면 문구가 옮겨 온 원문의 문장 (고칠 때 원문과 대조하려고 남긴다).
LIMITS_SOURCE_LINES = {
    "geumryong": "금룡은 11-13 에 지금과 다른 씨앗으로 나눴다. 그 씨앗과 프로그램도 업장 데이터 담당에게 넘어가 다시 나눠 같은 결과인 것을 확인했다.",
    "myongwolgwan": "명월관은 11-13 에 페르소나 쪽에서 태그 분포를 본 시험 파일을 그대로 나눴다 (본문은 읽지 않았다).",
}
VALIDATION_LIMITS = {
    "geumryong": "11-13 에 다른 업장과 다른 씨앗(무작위 값)으로 나눴습니다. 그 씨앗으로 다시 나눠 같은 결과인 것은 확인했지만, "
    "지금 씨앗과 달라 금룡 후기를 더 모으면 이어서 나누는 방법을 따로 정해야 합니다.",
    "myongwolgwan": "떼어 둔 후기가 11-13 에 페르소나 쪽에서 태그 분포를 본 시험 파일을 그대로 나눈 것입니다 (본문은 읽지 않았습니다).",
    # 회의에서 문장을 똑같이 적기로 해 원문 그대로 둔다.
    "moegi": MEETING_LIMIT_LINES["moegi"],
}


def load_validation(run_dir: Path) -> Validation | None:
    path = run_dir / "validation.json"
    return read_model(path, Validation) if path.is_file() else None


TOTAL_LABEL = "모든 업장 합계"
TOTAL_NOTE = "검증 건수가 모자란 업장의 후기도 합계에는 들어갑니다."


def _of(count: int | None, n: int) -> str:
    return "" if count is None else f"{n}건 중 {count}건"


def _status(enough: bool, reason_enough: bool, min_reviews: int) -> str:
    """5건 기준은 업장 일치(`n`)와 이유 일치(`reason_n`)를 따로 본다 (PRD 6.6절, T117)."""
    if not enough:
        return f"검증 건수 부족 ({min_reviews}건 미만)"
    if not reason_enough:
        return f"이유는 검증 건수 부족 (고른 이유가 있는 후기 {min_reviews}건 미만)"
    return ""


def _versus(count: int | None, baseline: int | None) -> str:
    """일치 건수를 단순 기준과 견준 높고 낮음. 건수가 모자라 말하지 않는 칸은 비운다."""
    if count is None or baseline is None:
        return ""
    return "단순 기준보다 높음" if count > baseline else "단순 기준보다 낮음" if count < baseline else "단순 기준과 같음"


def _row(
    name: str, n: int, enough: bool, venue: tuple, reason_n: int, reason_enough: bool, reason: tuple, min_reviews: int, masked: bool
) -> dict:
    # 이유 일치의 분모는 고른 이유 라벨이 있는 후기 수(`reason_n`)다. `n` 으로 나누면 이유 일치가 낮아 보인다 (T117).
    if masked:
        # 기본 데이터 실행이면 일치 건수 대신 단순 기준과 견준 높고 낮음만 보인다. 단순 기준은 기본 데이터의 매출로 고른 업장이라
        # 그 건수로 고객군마다 매출이 가장 큰 업장이 짐작된다. 저장소에도 높고 낮음만 적는다 (11-18 T19 줄, borigunbbang 의 T23 알림 ②)
        return {
            "업장": name,
            "검증 건수": n,
            "고른 업장이 같음": _versus(*venue),
            "이유를 잰 건수": reason_n,
            "이유가 겹침": _versus(*reason),
            "상태": _status(enough, reason_enough, min_reviews),
        }
    return {
        "업장": name,
        "검증 건수": n,
        "고른 업장이 같음": _of(venue[0], n),
        "같음 (단순 기준)": _of(venue[1], n),
        "이유를 잰 건수": reason_n,
        "이유가 겹침": _of(reason[0], reason_n),
        "겹침 (단순 기준)": _of(reason[1], reason_n),
        "상태": _status(enough, reason_enough, min_reviews),
    }


def validation_rows(validation: Validation, names: dict[str, str], masked: bool = False) -> list[dict]:
    """업장마다 한 줄과 모든 업장을 합친 한 줄: 검증 건수, 일치 건수(기준 방식과 함께), 상태, 한계.

    `masked` 면 일치 건수 대신 단순 기준과 견준 높고 낮음을 보인다 (기본 데이터 실행. app/results.py 의 `shows_numbers`).
    """
    least = validation.min_reviews
    rows = []
    for venue_id, result in sorted(validation.venues.items(), key=lambda item: names.get(item[0], item[0])):
        row = _row(
            names.get(venue_id, venue_id),
            result.n,
            result.enough,
            (result.venue_match, result.venue_match_baseline),
            result.reason_n,
            result.reason_enough,
            (result.reason_match, result.reason_match_baseline),
            least,
            masked,
        )
        rows.append(row | {"한계": VALIDATION_LIMITS.get(venue_id, "")})
    # 합친 줄에도 5건 기준을 똑같이 적용한다. 형식에는 칸이 없어 화면이 건수로 정한다 (T117 팀장 알림).
    total = validation.total
    enough, reason_enough = total.n >= least, total.reason_n >= least
    row = _row(
        TOTAL_LABEL,
        total.n,
        enough,
        (total.venue_match, total.venue_match_baseline) if enough else (None, None),
        total.reason_n,
        reason_enough,
        (total.reason_match, total.reason_match_baseline) if reason_enough else (None, None),
        least,
        masked,
    )
    rows.append(row | {"한계": TOTAL_NOTE})
    return rows


def limits_not_in(validation: Validation) -> list[str]:
    """한계가 있는데 검증 결과에 없는 업장. 결과에 없더라도 한계는 감추지 않는다."""
    return [venue_id for venue_id in VALIDATION_LIMITS if venue_id not in validation.venues]
