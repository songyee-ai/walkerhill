"""근거 보기 탭 (T22): 화면의 값이 어디서 왔는지 보인다.

- 업장: 값(상품, 프로모션, 영업시간, 예약)마다 근거 등급, 출처, 확인일. 가격이 비었거나 표기를 모르면 "가격 미확인".
- 페르소나: 속성 묶음마다 근거 등급과 근거가 된 후기 번호. 방문 모습·기호·구매 성향에 후기가 없으면 "이유 근거 부족".
- 가중치: 실행 하나의 고객군 배수, 페르소나 가중치, 묶음 비율의 근거 등급과 그 실행의 검증 결과("검증 건수 부족").

기본 데이터로 돌린 실행의 가중치 수치는 보이지 않고 등급만 보인다. 발표 화면에서도 가린다 (PRD 17절, 11-18 화면 담당과 팀장이 "가림"을 추천해 나머지 동의를 기다림. 그동안도 가린다).
가릴지의 기준은 화면 전체가 같게 `app/results.py` 의 `shows_numbers` 하나다.
표를 만드는 함수는 Streamlit 없이 돌아 테스트가 직접 본다. 그리는 것은 `render` 뿐이다.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.results import shows_numbers
from engine.formats import KO, Calibration, Persona, Venue, merged_persona, read_model
from engine.formats.persona import EVIDENCE_KEYS, REASON_EVIDENCE_KEYS
from engine.formats.run import RunRecord

BASE_NUMBERS_NOTE = "기본 데이터로 돌린 실행이라 수치는 가리고 근거 등급만 보입니다 (PRD 17절)."

GRADE = KO["grade"]
# 근거 등급의 순서 (강한 것부터). 표를 이 순서로 센다.
GRADE_ORDER = ("internal", "official", "review", "assumption", "unknown")
# 요약 표에서 등급마다 센 칸의 이름. "내부 매출 자료"를 그대로 칸 이름으로 쓰면 금액 칸처럼 읽혀(화면의 금액 칸에는 "가상"을 붙인다) 짧게 쓴다.
GRADE_COUNT = {"internal": "내부 자료", "official": "공식 사실", "review": "후기 관찰", "assumption": "설계 가정", "unknown": "미확인"}

# 페르소나의 근거 묶음 이름 (FORMATS.md 5절)
EVIDENCE_LABEL = {
    "share_in_group": "고객군 안의 몫",
    "visit": "방문 모습",
    "budget": "예산",
    "preferences": "기호와 제약",
    "buying": "구매 성향",
    "revisit": "다시 오는 이유·떠나는 이유",
    "compares_with": "견주는 업장",
}
REASON_LACK = "이유 근거 부족"
PRICE_UNKNOWN = "가격 미확인"
BASIS_UNKNOWN = "가격 표기 미확인"
# 엔진은 가상 예시 값으로 돌릴 때도 집계 파일로 단가를 채운다 (engine.weights.fill_prices).
# 11-17 업장 데이터 담당이 "기본 데이터로 돌릴 때만"이라는 옛 문구가 실제와 다르다고 찾아 줌.
PRICE_FILL_NOTE = (
    "가격이 비어 있어, 엔진이 돌릴 때마다 집계 파일의 낸 금액 ÷ 수량으로 단가를 채웁니다. "
    "가상 예시 값으로 돌리면 지어낸 단가로 채워집니다. 집계 파일에 팔린 것이 없으면 후보에서 뺍니다."
)
# 영업시간과 예약은 형식에 등급 칸이 없다 (FORMATS.md 3절). 지어내지 않고 출처만 보인다.
NO_GRADE = "등급 칸 없음 (출처만)"
# 후기 번호는 많으면 앞의 것만 표에 보이고 나머지는 수로 적는다. 전체는 펼쳐 본다.
REFS_SHOWN = 6


@dataclass(frozen=True)
class SourceView:
    title: str
    checked_on: str
    url: str


def venues(root: Path) -> dict[str, Venue]:
    """업장 정의 모두. 워커힐 업장을 먼저, 그다음 경쟁 업장을 이름 순으로."""
    found = [read_model(p, Venue) for p in sorted((root / "data" / "venues").glob("*.json"))]
    return {v.venue_id: v for v in sorted(found, key=lambda v: (v.is_competitor, v.name))}


def source_of(venue: Venue, source_id: str | None) -> SourceView:
    """값의 출처. `source_id` 가 비면 업장의 기본 출처를 쓴다 (FORMATS.md 3절)."""
    wanted = source_id or venue.default_source_id
    for source in venue.sources:
        if source.source_id == wanted:
            return SourceView(f"{source.source_id} · {source.title}", source.checked_on.isoformat(), source.url)
    return SourceView(f"{wanted} (출처 목록에 없음)", "", "")


def price_flags(price: int | None, basis: str) -> str:
    flags = []
    if price is None:
        flags.append(PRICE_UNKNOWN)
    elif basis == "unknown":
        flags.append(BASIS_UNKNOWN)
    return ", ".join(flags)


def venue_value_rows(venue: Venue) -> list[dict]:
    """업장의 값마다 한 줄: 무엇, 값, 근거 등급, 출처, 확인일, 표시."""
    rows: list[dict] = []

    def add(kind: str, what: str, value: str, grade: str | None, source_id: str | None, flag: str = "") -> None:
        source = source_of(venue, source_id)
        rows.append(
            {
                "갈래": kind,
                "무엇": what,
                "값": value,
                "근거 등급": GRADE[grade] if grade else NO_GRADE,
                "출처": source.title,
                "확인일": source.checked_on,
                "표시": flag,
            }
        )

    for product in venue.products:
        price = f"{product.price:,}원 ({KO['price_basis'][product.price_basis]})" if product.price is not None else "비어 있음"
        add("상품", product.name, price, product.grade, product.source_id, price_flags(product.price, product.price_basis))
    for promo in venue.promotions:
        add("프로모션", promo.name, _benefit(promo.benefit.type, promo.benefit.value), promo.grade, promo.source_id)
    for hours in venue.hours or []:
        when = f"{KO['meal'].get(hours.meal, hours.meal) if hours.meal else '영업'} · {KO['day_type'][hours.day_type]}"
        add("영업시간", when, f"{hours.open} ~ {hours.close}", None, hours.source_id)
    if venue.reservation is not None:
        reservation = venue.reservation
        add("예약", "예약", "필요" if reservation.required else "필요 없음", None, reservation.source_id)
    return rows


def _benefit(kind: str, value: int | float | str) -> str:
    if kind == "discount_pct":
        return f"{value:g}% 할인"
    if kind == "discount_amount":
        return f"{int(value):,}원 할인"
    return f"증정: {value}"


def venue_overview(found: dict[str, Venue]) -> list[dict]:
    """업장마다 한 줄: 값의 수, 등급별 수, 가격 미확인 수, 출처의 확인일 범위."""
    rows = []
    for venue in found.values():
        graded = [p.grade for p in venue.products] + [p.grade for p in venue.promotions]
        dates = sorted(s.checked_on.isoformat() for s in venue.sources)
        row = {"업장": venue.name, "구분": "경쟁" if venue.is_competitor else "워커힐", "상품·프로모션": len(graded)}
        row |= {GRADE_COUNT[g]: graded.count(g) for g in GRADE_ORDER}
        row[PRICE_UNKNOWN] = sum(p.price is None for p in venue.products)
        row["출처 확인일"] = dates[0] if dates[0] == dates[-1] else f"{dates[0]} ~ {dates[-1]}"
        rows.append(row)
    return rows


def personas(root: Path, with_private: bool = False) -> dict[str, Persona]:
    """페르소나 정의 모두. `with_private` 면 엔진처럼 비공개 층(`private/personas/`)을 합친다 (이 PC 에서만)."""
    found: dict[str, Persona] = {}
    for path in sorted((root / "personas").glob("*.json")):
        public = json.loads(path.read_text(encoding="utf-8"))
        private_path = root / "private" / "personas" / path.name
        private = json.loads(private_path.read_text(encoding="utf-8")) if with_private and private_path.is_file() else None
        persona = merged_persona(public, private)
        found[persona.persona_id] = persona
    return found


def has_private_layer(root: Path) -> bool:
    return any((root / "private" / "personas").glob("*.json"))


def ref_label(ref: str, found: dict[str, Venue]) -> str:
    """근거 번호를 읽을 수 있게. `<venue_id>:<source_id>` 는 업장 이름과 출처 제목으로 바꾸고, 후기 번호는 그대로 둔다."""
    if ":" not in ref:
        return ref
    venue_id, source_id = ref.split(":", 1)
    venue = found.get(venue_id)
    if venue is None:
        return ref
    source = source_of(venue, source_id)
    return f"{venue.name} {source.title} ({source.checked_on})"


def short_refs(refs: list[str]) -> str:
    if len(refs) <= REFS_SHOWN:
        return ", ".join(refs)
    return ", ".join(refs[:REFS_SHOWN]) + f" 외 {len(refs) - REFS_SHOWN}건"


def persona_evidence_rows(persona: Persona, found: dict[str, Venue]) -> list[dict]:
    """근거 묶음마다 한 줄: 묶음, 근거 등급, 후기 수, 후기 번호, 업장 출처, 메모, 비공개 층, 표시."""
    rows = []
    for key in EVIDENCE_KEYS:
        item = getattr(persona.evidence, key)
        reviews = [r for r in item.refs if ":" not in r]
        sources = [ref_label(r, found) for r in item.refs if ":" in r]
        lacks = key in REASON_EVIDENCE_KEYS and not reviews
        rows.append(
            {
                "묶음": EVIDENCE_LABEL.get(key, key),
                "근거 등급": GRADE[item.grade],
                "후기 수": len(reviews),
                "후기 번호": short_refs(reviews),
                "업장 출처": ", ".join(sources),
                "메모": item.note,
                "비공개 층": "예" if any(k == key or k.startswith(f"{key}.") for k in persona.overridden_by_private) else "",
                "표시": "후기 없음" if lacks else "",
            }
        )
    return rows


def persona_overview(found: dict[str, Persona]) -> list[dict]:
    """페르소나마다 한 줄: 고객군, 후기 번호 수(겹친 것은 한 번), 묶음의 등급별 수, "이유 근거 부족"."""
    rows = []
    for persona in found.values():
        grades = [getattr(persona.evidence, key).grade for key in EVIDENCE_KEYS]
        row = {"페르소나": persona.name, "고객군": persona.customer_group, "후기 번호": len(set(persona.review_refs()))}
        row |= {GRADE_COUNT[g]: grades.count(g) for g in GRADE_ORDER}
        row["표시"] = REASON_LACK if persona.lacks_reason_evidence() else ""
        rows.append(row)
    return rows


def baseline_runs(folder: Path) -> list[str]:
    """가중치를 정한 기준 실행 (새것부터). 다른 상황은 기준 실행의 가중치를 그대로 쓴다 (PRD 7.2절)."""
    if not folder.is_dir():
        return []
    found = [p.name for p in folder.iterdir() if (p / "run.json").is_file() and p.name.endswith("-baseline")]
    return sorted(found, reverse=True)


def _value(value: float, record: RunRecord) -> str:
    return f"{value:,.4g}" if shows_numbers(record) else "가림"


def weight_rows(record: RunRecord, names: dict[str, str]) -> dict[str, list[dict]]:
    """가중치 세 가지의 표. 기본 데이터 실행이면 수치 칸은 "가림"이다."""
    weights, grades = record.weights, record.weights.grades
    groups = [
        {"고객군": group, "고객군 배수": _value(value, record), "근거 등급": GRADE[grades.group_multiplier[group]]}
        for group, value in sorted(weights.group_multiplier.items())
    ]
    people = [
        {
            "페르소나": names.get(persona_id, persona_id),
            "가중치": _value(value, record),
            "근거 등급": GRADE[grades.persona_weight[persona_id]],
        }
        for persona_id, value in sorted(weights.persona_weight.items())
    ]
    ratios = [
        {
            "고객군": group,
            "방문 조건": names.get(condition_id, condition_id),
            "묶음 비율": _value(value, record),
            "근거 등급": GRADE[grades.condition_ratio[group][condition_id]],
        }
        for group, by_condition in sorted(weights.condition_ratio.items())
        for condition_id, value in by_condition.items()
    ]
    return {"고객군 배수": groups, "페르소나 가중치": people, "묶음 비율": ratios}


def load_calibration(run_dir: Path) -> Calibration | None:
    """기준 실행의 보정 대조 결과 (T116, `FORMATS.md` 10.4절). 대조 명령을 돌린 실행에만 있다."""
    path = run_dir / "calibration.json"
    return read_model(path, Calibration) if path.is_file() else None


def calibration_rows(calibration: Calibration, record: RunRecord, names: dict[str, str]) -> list[dict]:
    """고객군마다 보정의 통과·미달 (PRD 6.5절).

    기본 데이터 실행이면 비중 수치와 어느 업장이 가장 큰지는 가리고, 가장 큰 업장이 같은지와 차이가 기준 안인지만 보인다
    (PRD 17절, 11-18 팀장 회신). 가상 예시 값의 실행은 수치까지 보인다.
    """
    criteria = calibration.criteria
    rows = []
    for group, result in sorted(calibration.groups.items()):
        few = result.personas is not None and result.personas < criteria.diff_min_personas
        widest = max((abs(v.diff_pp) for v in result.venues.values()), default=0.0)
        if few:
            diff = f"보지 않음 (페르소나 {result.personas}명)"
        else:
            diff = f"기준 안 ({criteria.max_diff_pp:g}%p 이내)" if widest <= criteria.max_diff_pp else f"기준 넘음 ({criteria.max_diff_pp:g}%p 초과)"
        row = {
            "고객군": group,
            "페르소나 수": "" if result.personas is None else result.personas,
            "가장 큰 업장이 같음": "예" if result.top_sim is not None and result.top_sim == result.top_base else "아니오",
            "업장별 비중 차이": diff,
            "결과": "통과" if result.passed else "미달",
        }
        if shows_numbers(record):
            row |= {
                "가장 큰 업장 (시뮬레이션)": names.get(result.top_sim or "", result.top_sim or ""),
                "가장 큰 업장 (집계 파일)": names.get(result.top_base or "", result.top_base or ""),
                "가장 큰 차이 (%p)": round(widest, 1),
            }
        rows.append(row)
    return rows


def product_notes(record: RunRecord, found: dict[str, Venue]) -> list[str]:
    """그 실행에서 가격을 집계 파일로 채운 상품과 채우지 못해 뺀 상품. 단가는 보이지 않는다."""

    def label(ref: str) -> str:
        venue_id, _, product_id = ref.partition(":")
        venue = found.get(venue_id)
        product = next((p for p in venue.products if p.product_id == product_id), None) if venue else None
        return f"{venue.name} {product.name}" if venue and product else ref

    notes = []
    if record.filled_products:
        notes.append(f"가격이 비어 집계 파일로 단가를 채운 상품: {', '.join(label(r) for r in record.filled_products)}")
    if record.skipped_products:
        notes.append(f"{PRICE_UNKNOWN}이라 후보에서 뺀 상품: {', '.join(label(r) for r in record.skipped_products)}")
    return notes


def render(repo_root: Path) -> None:
    """근거 보기 탭을 그린다."""
    import streamlit as st

    from app.results import load_run, names_from_files, run_sources
    from app.simulator import show_validation

    st.caption("화면의 값이 어디서 왔는지 봅니다. 근거 등급은 " + " > ".join(GRADE[g] for g in GRADE_ORDER) + " 순으로 강합니다.")
    part = st.segmented_control("볼 것", ["업장", "페르소나", "가중치와 검증"], default="업장", key="ev_part") or "업장"
    found_venues = venues(repo_root)

    if part == "업장":
        st.dataframe(venue_overview(found_venues), hide_index=True)
        venue_id = st.selectbox("업장", list(found_venues), format_func=lambda v: found_venues[v].name, key="ev_venue")
        venue = found_venues[venue_id]
        rows = venue_value_rows(venue)
        unknown = [r["무엇"] for r in rows if r["표시"] == PRICE_UNKNOWN]
        if unknown:
            st.warning(f"{PRICE_UNKNOWN}: {', '.join(unknown)} — {PRICE_FILL_NOTE}")
        st.dataframe(rows, hide_index=True)
        st.caption("영업시간과 예약은 형식에 근거 등급 칸이 없어 출처만 보입니다. 출처가 비어 있는 값은 업장의 기본 출처를 씁니다.")
        with st.expander("출처 목록"):
            st.dataframe(
                [{"출처": s.source_id, "제목": s.title, "확인일": s.checked_on.isoformat(), "주소": s.url} for s in venue.sources],
                hide_index=True,
                column_config={"주소": st.column_config.LinkColumn("주소")},
            )

    elif part == "페르소나":
        with_private = False
        if has_private_layer(repo_root):
            with_private = st.toggle("비공개 층까지 합쳐 보기 (이 PC 에서만)", key="ev_private")
        found = personas(repo_root, with_private)
        if not found:
            st.info("페르소나 정의가 아직 없습니다.")
            return
        st.dataframe(persona_overview(found), hide_index=True)
        persona_id = st.selectbox("페르소나", list(found), format_func=lambda p: found[p].name, key="ev_persona")
        persona = found[persona_id]
        if persona.lacks_reason_evidence():
            st.warning(f"{REASON_LACK}: 방문 모습·기호·구매 성향에 근거가 된 후기 번호가 하나도 없습니다.")
        st.caption(f"고객군 안의 몫 {persona.share_in_group.value:g} · {GRADE[persona.share_in_group.grade]} · {persona.share_in_group.basis}")
        st.dataframe(persona_evidence_rows(persona, found_venues), hide_index=True)
        with st.expander("후기 번호 전체"):
            for key in EVIDENCE_KEYS:
                refs = [r for r in getattr(persona.evidence, key).refs if ":" not in r]
                st.markdown(f"**{EVIDENCE_LABEL[key]}** ({len(refs)}건) " + (", ".join(refs) or "없음"))

    else:
        sources = [s for s in run_sources(repo_root) if baseline_runs(s.folder)]
        if not sources:
            st.info("가중치를 정한 기준 실행이 없습니다. 시뮬레이터에서 한 번 돌리면 생깁니다.")
            return
        source = st.selectbox("실행을 읽을 곳", sources, format_func=lambda s: s.label, key="ev_source")
        run_id = st.selectbox("기준 실행", baseline_runs(source.folder), key="ev_run")
        run = load_run(source.folder / run_id)
        record = run.record
        names = names_from_files(repo_root) | {v.venue_id: v.name for v in found_venues.values()}
        st.caption(f"실행 `{record.run_id}` · {'기본 데이터' if record.data_mode == 'private' else '가상 예시 값'} · 페르소나 {len(record.persona_ids)}명")
        if not shows_numbers(record):
            st.info(BASE_NUMBERS_NOTE)
        for title, rows in weight_rows(record, names).items():
            st.markdown(f"**{title}**")
            st.dataframe(rows, hide_index=True)
        for note in product_notes(record, found_venues):
            st.caption(note)
        try:
            calibration = load_calibration(source.folder / run_id)
        except (OSError, ValueError) as error:
            calibration = None
            st.warning(f"보정 대조 결과를 읽지 못했습니다: {error}")
        if calibration is not None:
            st.markdown(f"**보정 대조** · {'모든 고객군 통과' if calibration.passed else '미달인 고객군이 있음'}")
            st.dataframe(calibration_rows(calibration, record, names), hide_index=True)
            if calibration.uncovered_groups:
                st.caption("페르소나가 없어 대조하지 않은 고객군: " + ", ".join(calibration.uncovered_groups))
        show_validation(source.folder / run_id, names)
        if not (source.folder / run_id / "validation.json").is_file():
            st.caption("이 실행에는 검증 결과가 없습니다. 검증(T19)을 돌린 실행에서 업장별 검증 건수와 \"검증 건수 부족\"이 보입니다.")
