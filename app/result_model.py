"""결과 페이지의 데이터 묶음: 시나리오 결과 하나(app/result_store.py)를 화면 스크립트(app/report/)가 읽는 사전으로 바꾼다 (T130).

계산은 엔진과 기존 화면 코드가 한 것을 가져다 쓴다 (app/compare.py, app/results.py, app/breakdown.py, app/evidence.py).
기간의 합은 화면 스크립트가 낸다: 사람이 기간을 바꿀 때마다 파이썬을 다시 부르지 않게, 달마다의 값을 모두 넘긴다
(docs/FORMATS.md 10.1절 "여러 달을 합치는 법": 달마다 더하고, 변화율은 더한 금액으로 다시 낸다. 집계가 없는 달은 빼고 더한다).
금액은 모두 시뮬레이션이 낸 가상 값이다.
"""

import json
from pathlib import Path

from app.compare import Comparison, compare, venue_names
from app.evidence import load_calibration, personas, venues
from app.result_store import ResultRecord, data_root, list_records, read_record, runs_path
from app.results import LoadedRun, load_run, visit_view
from app.validation import load_validation
from engine.formats import KO, read_model
from engine.formats.changes import Changes
from engine.formats.persona import EVIDENCE_KEYS
from engine.formats.run import VISIT_ID_SEPARATOR
from engine.formats.scenario import Scenario

SCHEMA = 1
STATIC = "/app/static"
# 업장마다 지도와 업장 카드에 그리는 건물 그림 (app/static/icons/buildings/). 업장 정의에는 그림 칸이 없어 화면이 정한다.
VENUE_ICON = {
    "fourseasons-maru": "glass-competitor",
    "geumryong": "hall-walkerhill",
    "grandhyatt-steakhouse": "terrace-competitor",
    "josun-deli": "awning-josun",
    "lepassage": "awning-walkerhill",
    "lotte-mugunghwa": "tower-mugunghwa",
    "moegi": "hall-moegi",
    "myongwolgwan": "gable-walkerhill",
    "ondal": "gable-ondal",
    "parnas-mercato521": "awning-competitor",
    "parnas-weilou": "tower-competitor",
    "pavilion": "atrium-walkerhill",
    "pizzahill": "villa-walkerhill",
    "shilla-ariake": "hall-competitor",
    "shilla-parkview": "atrium-competitor",
    "thebuffet": "glass-walkerhill",
}
# 그림이 없는 업장(새로 더한 업장)의 기본 그림
DEFAULT_ICON = {"walkerhill": "hall-walkerhill", "competitor": "tower-competitor"}
# 배너 그림이 있는 워커힐 업장 (결정 68). 파일 이름이 venue_id 와 같다
BANNER_VENUES = ("thebuffet", "geumryong", "myongwolgwan", "ondal", "pizzahill", "pavilion", "lepassage", "moegi")
# 페르소나 카드의 두 줄 이름. 나누는 자리가 이름마다 달라 화면이 정한다. 없으면 이름 한 줄
NAME_LINES = {
    "couple-anniversary": ["기념일을 챙기는", "부부·연인"],
    "couple-date": ["일상 데이트를 하는", "부부·연인"],
    "family-kids": ["아이를 데려온", "가족"],
    "family-parents": ["부모님을 모시는", "성인 자녀 가족"],
    "friends-gathering": ["친구·동료", "모임"],
    "gourmet-explorer": ["호텔 다이닝을", "찾아다니는 미식가"],
}
PERSONA_ICONS = set(NAME_LINES)


def persona_icon(persona_id: str) -> str:
    """페르소나 그림 이름. 그림이 없는 페르소나(예시 자료, 새로 더한 페르소나)는 이름 앞부분이 같은 그림을 쓴다."""
    if persona_id in PERSONA_ICONS:
        return persona_id
    for prefix, icon in (("family", "family-parents"), ("couple", "couple-date"), ("friends", "friends-gathering")):
        if persona_id.startswith(prefix):
            return icon
    return "gourmet-explorer"
# 근거 등급의 짧은 이름 (표 칸에 들어간다). 긴 이름은 KO["grade"]
GRADE_SHORT = {
    "internal": "내부",
    "official": "공식",
    "literature": "학술",
    "statistic": "통계",
    "review": "후기",
    "industry": "업계",
    "article": "기사",
    "assumption": "가정",
    "unknown": "미확인",
}
# 근거 후기가 이만큼보다 적으면 "근거 제한적" (시안의 근거 표 안내)
FEW_REVIEWS = 5
# 검증 합계의 높고 낮음을 보는 최소 건수 (app/validation.py 의 합계 줄)
VALIDATION_MIN = 5
WEATHER_NOTE = "날씨는 검토했으나 근거가 부족해 넣지 않았습니다."
DATA_MODE_LABEL = {"sample": "가상 예시 데이터", "private": "기본 데이터"}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def condition_texts(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """방문 조건의 긴 말("평일 점심 식사")과 짧은 말("평일 점심")."""
    long: dict[str, str] = {}
    short: dict[str, str] = {}
    for c in _read_json(root / "engine" / "conditions.json").get("conditions", []):
        try:
            day = KO["day_type"][c["day_type"]]
            occasion = KO["occasion"][c["occasion"]]
            meal = KO["meal"][c["meal"]] if c.get("meal") else None
        except (KeyError, TypeError):
            continue
        long[c["condition_id"]] = " ".join(x for x in (day, meal, occasion) if x)
        short[c["condition_id"]] = f"{day} {meal}" if meal else f"{day} {occasion}"
    return long, short


def months_label(months: list[int | None]) -> str:
    """기간의 이름: "12월", "12월~1월", 달 없이 돌렸으면 "일 년 전체"."""
    real = [m for m in months if m is not None]
    if not real:
        return "일 년 전체"
    return f"{real[0]}월" if len(real) == 1 else f"{real[0]}월~{real[-1]}월"


def change_text(change, venue_names_: dict[str, str], product_names: dict[str, str]) -> str:
    """바꿀 것 한 줄 (배너의 바꾼 조건). 만들기 페이지의 카드 요약과 같은 말을 쓴다."""
    venue = venue_names_.get(change.venue_id, change.venue_id)
    if change.op == "set_price":
        product = product_names.get(f"{change.venue_id}:{change.product_id}", change.product_id)
        return f"{venue} {product} 가격 {change.price:,}원"
    if change.op == "change_price_pct":
        what = product_names.get(f"{change.venue_id}:{change.product_id}", change.product_id) if change.product_id else "메뉴 전체"
        sign = "인상" if change.pct > 0 else "인하"
        return f"{venue} {what} 가격 {abs(change.pct):g}% {sign}"
    if change.op == "add_product":
        return f"{venue} 한정 메뉴 더하기: {change.product.name}"
    if change.op == "remove_product":
        return f"{venue} 메뉴 빼기: {product_names.get(f'{change.venue_id}:{change.product_id}', change.product_id)}"
    if change.op == "add_promotion":
        return f"{venue} 프로모션: {change.promotion.name}"
    if change.op == "remove_promotion":
        return f"{venue} 프로모션 끝내기"
    return venue


def banner_of(side: str, changes: list) -> str:
    """배너 그림 (결정 68): ① 워커힐 밖 시나리오 ② 첫 번째 바꿀 것의 워커힐 업장 ③ 공통."""
    if side == "outside":
        return "outside"
    first = changes[0].venue_id if changes else None
    return first if first in BANNER_VENUES else "common"


def _load_scenario(root: Path, scenario_id: str) -> Scenario | None:
    path = root / "scenarios" / f"{scenario_id}.json"
    try:
        return read_model(path, Scenario) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _load_changes(scen: LoadedRun, base: LoadedRun) -> Changes | None:
    path = scen.run_dir / "changes.json" if scen.run_dir else None
    if path is None or not path.is_file():
        return None
    try:
        changes = read_model(path, Changes)
    except (OSError, ValueError):
        return None
    if changes.run_id != scen.record.run_id or changes.baseline_run_id != base.record.run_id:
        return None
    return changes


def _side(run: LoadedRun, persona_id: str, condition_id: str, names: dict[str, str]) -> dict:
    """방문 한쪽(기본 시나리오 또는 바꾼 뒤)의 곳·주문·금액·이유."""
    view = visit_view(run, persona_id, condition_id)
    rows = [r for r in run.rows if r.persona_id == persona_id and r.condition_id == condition_id and r.choice_kind == view.choice_kind]
    venue_id = next((r.venue_id for r in rows if r.venue_id), None)
    order = ", ".join(f"{line.product} {line.quantity}{line.unit or ''}".strip() for line in view.lines)
    key = "|".join(sorted(f"{r.product_id}x{r.quantity}" for r in rows if r.product_id))
    return {
        "venue_name": names.get(venue_id or "", view.venue or "") if venue_id else "",
        "order": order,
        "order_key": key,
        "paid": view.total_paid,
        "list_price": sum(line.list_price * max(line.quantity, 1) for line in view.lines),
        "reason": view.reason_text,
        "reason_labels": list(view.reason_labels),
        "failed": view.failed_reason,
        "rejected": [
            {"name": item.venue, "kind": item.kind, "pain_labels": list(item.pain_labels), "text": item.text}
            for item in view.not_chosen
        ],
    }


def _place(place) -> dict:
    return {"kind": place.kind, "venue_id": place.venue_id}


def month_model(
    base: LoadedRun, scen: LoadedRun, comparison: Comparison, names: dict[str, str], visit_numbers: dict[str, str], month: int | None
) -> dict:
    """한 달의 방문·매출·근거. `month` 는 묶음에 적힌 그 짝의 달이다 (엔진이 쓴 실행 기록의 달과 같다)."""
    changes = _load_changes(scen, base)
    by_visit = {v.visit_id: v for v in changes.visits} if changes else {}
    visits = []
    excluded = []
    for move in comparison.moves:
        visit_id = f"{move.persona_id}{VISIT_ID_SEPARATOR}{move.condition_id}"
        if move.move == "failed":
            excluded.append(visit_id)
            continue
        change = by_visit.get(visit_id)
        # 매출 갈래와 맞추려고 changes.json 의 곳(몫이 가장 큰 곳)을 쓴다. 파일이 없는 달만 원장의 고른 곳 (FORMATS.md 10.6절)
        before = _place(change.before) if change else _place(move.before)
        after = _place(change.after) if change else _place(move.after)
        before |= _side(base, move.persona_id, move.condition_id, names)
        after |= _side(scen, move.persona_id, move.condition_id, names)
        parts = [{"venue_id": p.venue_id, "part": p.part, "amount": p.amount} for p in (change.parts if change else [])]
        price_changed = any(p["part"] == "price" and p["amount"] != 0 for p in parts) or (
            change is None and before["order_key"] == after["order_key"] and before["paid"] != after["paid"]
        )
        visits.append(
            {
                "visit_id": visit_id,
                "visit_no": visit_numbers.get(visit_id, ""),
                "persona_id": move.persona_id,
                "condition_id": move.condition_id,
                "represented": move.represented,
                "kept_baseline": move.kept_baseline,
                "price_changed": price_changed,
                "before": before,
                "after": after,
                "parts": parts,
            }
        )
    sales = None
    if changes is not None and changes.walkerhill.total == comparison.total_after - comparison.total_before:
        part_visits: dict[str, list[str]] = {}
        for visit in changes.visits:
            for part in visit.parts:
                if part.amount != 0:
                    part_visits.setdefault(part.part, []).append(visit.visit_id)
        sales = {
            "before": comparison.total_before,
            "after": comparison.total_after,
            "parts": changes.walkerhill.model_dump(),
            "part_visits": {k: sorted(set(v)) for k, v in part_visits.items()},
            "venues": [{"venue_id": v.venue_id, "before": v.before, "after": v.after, "parts": v.parts.model_dump()} for v in changes.venues],
        }
    record = base.record
    grades = record.weights.grades
    weakest = _weakest(
        list(grades.group_multiplier.values())
        + list(grades.persona_weight.values())
        + [g for by in grades.condition_ratio.values() for g in by.values()]
    )
    return {
        "month": month,
        "label": f"{month}월" if month else "일 년 전체",
        "base_run_id": base.record.run_id,
        "scen_run_id": scen.record.run_id,
        "visits": visits,
        "excluded_visits": excluded,
        "sales": sales,
        "venue_totals": [{"venue_id": v.venue_id, "before": v.before, "after": v.after} for v in comparison.venues],
        "zero_groups": sorted(g for g, v in record.weights.group_multiplier.items() if v == 0),
        "evidence": {
            "weights": [
                {"key": "group_multiplier", "label": "고객군의 크기", "grade": _weakest(list(grades.group_multiplier.values()))},
                {"key": "condition_ratio", "label": "방문 조건의 몫", "grade": _weakest([g for by in grades.condition_ratio.values() for g in by.values()])},
                {"key": "persona_weight", "label": "페르소나의 몫", "grade": _weakest(list(grades.persona_weight.values()))},
            ],
            "weakest": weakest,
            "people_coverage": record.weights.people_coverage,
            "share_method": scen.record.share_method,
            "constants_applied": [
                {"constant_id": c.constant_id, "name": c.name, "value": c.value, "unit": c.unit, "grade": GRADE_SHORT.get(c.grade, c.grade)}
                for c in (scen.record.constants or [])
                if getattr(c, "applied", False)
            ],
        },
        "kept_count": comparison.kept_count,
    }


# 근거 등급의 세기 (약한 것이 뒤). 표에는 묶음마다 가장 약한 등급을 보인다
GRADE_RANK = ("internal", "official", "statistic", "literature", "industry", "article", "review", "assumption", "unknown")


def _weakest(grades: list[str]) -> str | None:
    known = [g for g in grades if g in GRADE_RANK]
    return max(known, key=GRADE_RANK.index) if known else None


def _venue_list(root: Path) -> tuple[list[dict], dict[str, str]]:
    found = venues(root)
    rows = []
    product_names: dict[str, str] = {}
    for venue in found.values():
        kind = "competitor" if venue.is_competitor else "walkerhill"
        rows.append(
            {
                "id": venue.venue_id,
                "name": venue.name,
                "hotel": venue.hotel,
                "kind": kind,
                "pair": venue.competes_with[0] if venue.competes_with else None,
                "icon": VENUE_ICON.get(venue.venue_id, DEFAULT_ICON[kind]),
            }
        )
        product_names |= {f"{venue.venue_id}:{p.product_id}": p.name for p in venue.products}
    return rows, product_names


def _venue_evidence(root: Path, venue_ids: list[str]) -> list[dict]:
    """근거 보기(업장): 시나리오가 바꾼 업장과 바뀐 방문이 고른 업장의 상품·프로모션."""
    found = venues(root)
    rows = []
    from app.evidence import price_flags, source_of

    for venue_id in venue_ids:
        venue = found.get(venue_id)
        if venue is None:
            continue
        for product in venue.products:
            source = source_of(venue, product.source_id)
            rows.append(
                {
                    "venue": venue.name,
                    "what": product.name,
                    "value": f"{product.price:,}원" if product.price is not None else "비어 있음",
                    "grade": KO["grade"].get(product.grade, product.grade),
                    "grade_key": product.grade,
                    "source": source.title,
                    "checked_on": source.checked_on,
                    "flag": price_flags(product.price, product.price_basis),
                }
            )
        for promo in venue.promotions:
            source = source_of(venue, promo.source_id)
            rows.append(
                {
                    "venue": venue.name,
                    "what": promo.name,
                    "value": "프로모션",
                    "grade": KO["grade"].get(promo.grade, promo.grade),
                    "grade_key": promo.grade,
                    "source": source.title,
                    "checked_on": source.checked_on,
                    "flag": "",
                }
            )
    return rows


def _persona_info(root: Path, persona_ids: list[str]) -> dict:
    found = personas(root)
    info = {}
    for persona_id in persona_ids:
        persona = found.get(persona_id)
        if persona is None:
            info[persona_id] = {"name_lines": NAME_LINES.get(persona_id, [persona_id]), "evidence": None}
            continue
        reviews = len(set(persona.review_refs()))
        info[persona_id] = {
            "name_lines": NAME_LINES.get(persona_id, [persona.name]),
            "group": persona.customer_group,
            "evidence": {
                "grades": {key: GRADE_SHORT.get(getattr(persona.evidence, key).grade, "") for key in EVIDENCE_KEYS},
                "reviews": reviews,
                "limited": reviews < FEW_REVIEWS,
            },
        }
    return info


def _calibration(record: ResultRecord, repo_root: Path) -> dict | None:
    """보정 결과: 달 없이 돌린 가장 새 기준 실행의 `calibration.json` (FORMATS.md 10.4절. 달을 준 실행에는 없다)."""
    folder = runs_path(record, repo_root)
    for run_dir in sorted((p for p in folder.glob("*-baseline") if (p / "calibration.json").is_file()), reverse=True):
        found = load_calibration(run_dir)
        if found is None:
            continue
        groups = list(found.groups.values())
        passed = sum(1 for g in groups if g.passed)
        return {"passed": passed, "groups": len(groups), "run_id": run_dir.name}
    return None


def _validation(base: LoadedRun) -> dict | None:
    if base.run_dir is None:
        return None
    found = load_validation(base.run_dir)
    if found is None:
        return None
    total = found.total
    return {
        "n": total.n,
        "venue_match": total.venue_match,
        "venue_expected": getattr(total, "venue_expected", None),
        "baseline": total.venue_match_baseline,
        # 합계 줄은 5건 이상일 때만 높고 낮음을 본다 (app/validation.py 와 같은 기준)
        "enough": total.n >= VALIDATION_MIN,
    }


def _saved(repo_root: Path, current: ResultRecord, current_root: Path, long_conditions: dict[str, str]) -> list[dict]:
    """저장된 시나리오 창의 줄. 결과가 있는 것만 (실행 전 시나리오는 만들기 페이지와 함께 넣는다)."""
    rows = []
    for record in list_records(repo_root):
        root = data_root(record, repo_root)
        scenario = _load_scenario(root, record.scenario_id)
        try:
            run = read_record(runs_path(record, repo_root) / record.pairs[-1].scenario)
        except (OSError, ValueError):
            continue
        condition = _condition_line(run.condition_ids, long_conditions)
        line = f"{DATA_MODE_LABEL.get(record.data_mode, record.data_mode)} · 페르소나 {len(run.persona_ids)}명 · {months_label(record.months)} · {condition}"
        rows.append(
            {
                "id": record.result_id,
                "name": scenario.name if scenario else record.scenario_id,
                "state": "has",
                "ran_at": record.created_at,
                "condition_line": line,
                "current": record.result_id == current.result_id,
                "differs": False,
                "side": "outside" if scenario and scenario.kind == "competitor" else "inside",
                "_key": (record.data_mode, tuple(run.persona_ids), tuple(record.months), tuple(sorted(run.condition_ids))),
            }
        )
    mine = next((r["_key"] for r in rows if r["current"]), None)
    for row in rows:
        row["differs"] = mine is not None and row["_key"] != mine
        row.pop("_key")
    return rows


def _condition_line(condition_ids: list[str], long_conditions: dict[str, str]) -> str:
    if len(condition_ids) >= len(long_conditions) and long_conditions:
        return "방문 조건 전체"
    if len(condition_ids) <= 2:
        return ", ".join(long_conditions.get(c, c) for c in condition_ids)
    return f"방문 조건 {len(condition_ids)}가지"


def build(record: ResultRecord, repo_root: Path) -> dict:
    """화면 스크립트에 넘길 사전 하나."""
    root = data_root(record, repo_root)
    folder = runs_path(record, repo_root)
    loaded = [(load_run(folder / p.baseline), load_run(folder / p.scenario)) for p in record.pairs]
    first_base, last_scen = loaded[0][0], loaded[-1][1]
    venue_rows, product_names = _venue_list(root)
    names = {v["id"]: v["name"] for v in venue_rows}
    for base, scen in loaded:
        names = venue_names(base, scen) | names
    long_conditions, short_conditions = condition_texts(root)
    persona_files = {p.persona_id: p.name for p in personas(root).values()}
    file_names = persona_files | long_conditions

    record_ids = [f"{p}{VISIT_ID_SEPARATOR}{c}" for p in first_base.record.persona_ids for c in first_base.record.condition_ids]
    visit_numbers = {visit_id: f"V{i:02d}" for i, visit_id in enumerate(record_ids, start=1)}
    months = []
    for pair, (base, scen) in zip(record.pairs, loaded, strict=True):
        comparison = compare(base, scen, None, file_names)
        month = pair.month if pair.month is not None else scen.record.month
        months.append(month_model(base, scen, comparison, names, visit_numbers, month))

    scenario = _load_scenario(root, record.scenario_id)
    side = "outside" if scenario is not None and scenario.kind == "competitor" else "inside"
    changes = scenario.changes if scenario else []
    changes_text = [change_text(c, names, product_names) for c in changes]
    banner = banner_of(side, changes)
    changed_venues = list(dict.fromkeys(c.venue_id for c in changes))
    chosen_venues = [
        v["after"]["venue_id"]
        for m in months
        for v in m["visits"]
        if v["after"]["venue_id"] and v["after"]["venue_id"] != v["before"]["venue_id"]
    ]
    persona_ids = list(first_base.record.persona_ids)
    kept = sum(m["kept_count"] for m in months)
    split = any(m["evidence"]["share_method"] in ("scores", "mixed") for m in months)
    return {
        "schema": SCHEMA,
        "result_id": record.result_id,
        "title": scenario.name if scenario else record.scenario_id,
        "description": " · ".join(changes_text),
        "venues": venue_rows,
        "personas": {p: persona_files.get(p, p) for p in persona_ids},
        "conditions": {c: long_conditions.get(c, c) for c in first_base.record.condition_ids},
        "condition_short": {c: short_conditions.get(c, long_conditions.get(c, c)) for c in first_base.record.condition_ids},
        "months": months,
        "scenario": {
            "id": record.scenario_id,
            "name": scenario.name if scenario else record.scenario_id,
            "side": side,
            "changes_text": changes_text,
            "banner": banner,
            "data_mode": record.data_mode,
            "data_mode_label": DATA_MODE_LABEL.get(record.data_mode, record.data_mode),
            "persona_count": len(persona_ids),
            "period_label": months_label(record.months),
            "condition_label": _condition_line(list(first_base.record.condition_ids), long_conditions),
            "ran_at": last_scen.record.created_at.isoformat(timespec="minutes"),
        },
        "assets": {
            "banner": f"{STATIC}/banners/banner-{banner}.webp",
            "personas": {p: f"{STATIC}/icons/personas/{persona_icon(p)}.svg" for p in persona_ids},
            "buildings": f"{STATIC}/icons/buildings/",
            "plates": f"{STATIC}/icons/plates/",
        },
        "persona_info": _persona_info(root, persona_ids),
        "evidence": {
            "venues": _venue_evidence(root, list(dict.fromkeys(changed_venues + chosen_venues))),
            "calibration": _calibration(record, repo_root),
            "validation": _validation(first_base),
            "weather_note": WEATHER_NOTE,
        },
        "notes": {"kept": kept, "split_assumption": split},
        "grade_names": dict(KO["grade"]),
        "saved": _saved(repo_root, record, root, long_conditions),
    }
