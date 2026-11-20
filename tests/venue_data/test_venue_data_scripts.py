"""업장 데이터 담당의 집계 스크립트 (tools/venue_data, T13). 값과 열 이름은 모두 지어낸 것이다."""

import csv
import json

import pytest

from tools.venue_data import build_summary, make_sample

# 지어낸 열 이름 (기본 데이터의 실제 열 이름이 아니다)
SOURCE = {
    "base_file": "base.csv",
    "columns": {
        "date": "일자", "business_unit": "부문", "venue": "가게", "product_id": "품번", "customer_group": "손님",
        "quantity": "개수", "paid": "낸돈", "revenue_net": "번돈", "price_unconfirmed": "단가미정",
    },
    "dining_prefix": "식음",
    "unconfirmed_value": "예",
    "scope_label": "지어낸 범위",
}
FIELDS = list(SOURCE["columns"].values())


def _product(slots, occasion="meal", months=None):
    return {"product_id": "p1", "unit": "1인", "occasion": occasion, "slots": slots, "months": months}


def _venues(tmp_path, product):
    d = tmp_path / "venues"
    d.mkdir()
    (d / "v1.json").write_text(json.dumps({"venue_id": "v1", "months": None, "products": [product]}), encoding="utf-8")
    return d


def _base(tmp_path, rows):
    path = tmp_path / "base.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for date, unit, venue, pid, group, qty, paid, net, unconfirmed in rows:
            w.writerow(dict(zip(FIELDS, (date, unit, venue, pid, group, qty, paid, net, unconfirmed), strict=True)))
    return path


MAPPING = {"products": [{"base_venue": "가게A", "base_product_id": "X1", "venue_id": "v1", "product_id": "p1"}]}


@pytest.mark.parametrize(("date", "expected"), [
    ("2026-11-17", "weekday"),  # 화요일
    ("2026-11-21", "weekend"),  # 토요일
    ("2026-03-02", "weekend"),  # 월요일이지만 대체공휴일
])
def test_day_type(date, expected):
    assert build_summary.day_type(date) == expected


def test_meal_for():
    one = _product([{"meal": "dinner", "day_type": "all"}])
    two = _product([{"meal": "lunch", "day_type": "all"}, {"meal": "dinner", "day_type": "weekend"}])
    assert build_summary.meal_for(one, "weekday") == "dinner"
    assert build_summary.meal_for(two, "weekday") == "lunch"
    assert build_summary.meal_for(two, "weekend") == ""  # 그 요일에 끼니가 여럿이면 나눈다
    assert build_summary.meal_for(_product([{"meal": None, "day_type": "all"}], occasion="dessert"), "weekday") == ""


def test_build_sums_and_checks(tmp_path):
    products = build_summary.load_products(_venues(tmp_path, _product([{"meal": "dinner", "day_type": "all"}])))
    base = _base(tmp_path, [
        ("2026-11-17", "식음·지어냄", "가게A", "X1", "가족·친족", "2", "220", "200", "아니오"),
        ("2026-11-18", "식음·지어냄", "가게A", "X1", "가족·친족", "1.0", "110", "100", "아니오"),  # 같은 달·같은 요일 갈래로 합쳐짐
        ("2026-11-21", "식음·지어냄", "가게A", "X1", "가족·친족", "1", "110", "100", "예"),  # 주말, 단가 미정
        ("2026-11-17", "객실·지어냄", "가게A", "X1", "가족·친족", "9", "999", "999", "아니오"),  # 다이닝이 아님
    ])
    rows, meta = build_summary.build(SOURCE, base, MAPPING, products)
    assert [(r["day_type"], r["quantity"], r["paid"], r["revenue_net"], r["price_unconfirmed"]) for r in rows] == [
        ("weekday", "3", "330", "300", "N"),
        ("weekend", "1", "110", "100", "Y"),
    ]
    assert all(r["meal"] == "dinner" and r["month"] == "11" for r in rows)
    assert meta["input_rows"] == 4 and meta["dining_rows"] == 3
    assert meta["revenue_check"]["match"] is True
    assert meta["scope"] == "지어낸 범위"


def test_build_counts_unmapped_and_outside(tmp_path):
    products = build_summary.load_products(
        _venues(tmp_path, _product([{"meal": "lunch", "day_type": "weekday"}], months=[1, 2])))
    base = _base(tmp_path, [
        ("2026-11-21", "식음", "가게A", "X1", "커플·기념일", "1", "110", "100", "아니오"),  # 주말·11월: 파는 때 밖
        ("2026-11-17", "식음", "가게B", "Z9", "커플·기념일", "1", "110", "100", "아니오"),  # 대응표에 없음
    ])
    rows, meta = build_summary.build(SOURCE, base, MAPPING, products)
    assert len(rows) == 1
    assert meta["unmapped_rows"] == 1
    assert meta["revenue_check"]["match"] is False
    assert meta["outside_venue_definition"]["v1/p1"]["reasons"] == ["파는 달 밖(11월)", "파는 요일 밖(weekend)"]


def test_build_people(tmp_path):
    """인원 = 수량 × 한 개당 인원. 사람이 아닌 상품(None)은 빈 칸, 대응표에 값이 없으면 빈 칸으로 두고 meta 에 적는다."""
    d = tmp_path / "venues"
    d.mkdir()
    slots = [{"meal": "dinner", "day_type": "all"}]
    products = [{"product_id": pid, "unit": "세트", "occasion": "meal", "slots": slots, "months": None}
                for pid in ("set2", "goods", "unknown")]
    (d / "v1.json").write_text(json.dumps({"venue_id": "v1", "months": None, "products": products}), encoding="utf-8")
    mapping = {"products": [
        {"base_venue": "가게A", "base_product_id": "S", "venue_id": "v1", "product_id": "set2", "people_per_unit": 2},
        {"base_venue": "가게A", "base_product_id": "G", "venue_id": "v1", "product_id": "goods", "people_per_unit": None},
        {"base_venue": "가게A", "base_product_id": "U", "venue_id": "v1", "product_id": "unknown"},
    ]}
    base = _base(tmp_path, [
        ("2026-11-17", "식음", "가게A", "S", "친구·모임", "3", "330", "300", "아니오"),
        ("2026-11-18", "식음", "가게A", "S", "친구·모임", "1", "110", "100", "아니오"),
        ("2026-11-17", "식음", "가게A", "G", "친구·모임", "5", "550", "500", "아니오"),
        ("2026-11-17", "식음", "가게A", "U", "친구·모임", "1", "110", "100", "아니오"),
    ])
    rows, meta = build_summary.build(SOURCE, base, mapping, build_summary.load_products(d))
    assert {r["product_id"]: r["people"] for r in rows} == {"set2": "8", "goods": "", "unknown": ""}
    assert meta["people_blank_products"] == ["v1/goods", "v1/unknown"]
    assert meta["people_rule_missing"] == ["v1/unknown"]


def test_make_sample_people_for():
    assert make_sample.people_for({"qty_rule": "per_person", "serves": 1}, 3) == "3"
    assert make_sample.people_for({"qty_rule": "per_serves", "serves": 2}, 3) == "6"
    assert make_sample.people_for({"qty_rule": "choice", "serves": 1}, 3) == ""


def test_make_sample_add_people_keeps_values():
    """저장소의 예시 파일에 people 을 채워도 다른 칸의 값은 바뀌지 않는다."""
    rows = make_sample.add_people()
    with make_sample.OUT.open(encoding="utf-8-sig", newline="") as f:
        before = [{k: v for k, v in r.items() if k != "people"} for r in csv.DictReader(f)]
    assert [{k: v for k, v in r.items() if k != "people"} for r in rows] == before
    assert all(r["people"] == "" or int(r["people"]) >= int(float(r["quantity"])) for r in rows)


def _venue_with_sources(tmp_path):
    """상수 파일 테스트용 지어낸 업장 정의 하나 (상품 셋: 세트, 판, 1인)."""
    d = tmp_path / "cvenues"
    d.mkdir(parents=True)
    venue = {
        "venue_id": "v1", "name": "가게", "default_source_id": "S1",
        "sources": [{"source_id": "S1", "title": "지어낸 메뉴판", "url": "https://example.com/menu", "checked_on": "2026-11-01"}],
        "products": [
            {"product_id": "set2", "name": "두 사람 세트", "source_id": None},
            {"product_id": "pie", "name": "큰 판", "source_id": None},
            {"product_id": "one", "name": "한 사람 코스", "source_id": None},
        ],
    }
    (d / "v1.json").write_text(json.dumps(venue, ensure_ascii=False), encoding="utf-8")
    return d


def test_build_constants(tmp_path):
    """한 개당 인원이 1 이 아닌 상품만 상수가 되고, 근거 구분대로 등급과 출처가 붙는다."""
    from engine.formats.constants import ConstantsFile

    mapping = {"products": [
        {"venue_id": "v1", "product_id": "set2", "people_per_unit": 2, "people_basis": "official"},
        {"venue_id": "v1", "product_id": "pie", "people_per_unit": 3, "people_basis": "internal"},
        {"venue_id": "v1", "product_id": "one", "people_per_unit": 1},
    ]}
    out = build_summary.build_constants(mapping, _venue_with_sources(tmp_path), made_on="2026-11-20")
    assert [(c["constant_id"], c["value"], c["grade"]) for c in out] == [
        ("people-per-unit-v1-set2", 2, "official"), ("people-per-unit-v1-pie", 3, "internal")]
    assert out[0]["sources"] == [{"title": "지어낸 메뉴판", "kind": "official", "url": "https://example.com/menu"}]
    assert out[0]["checked_on"] == "2026-11-01" and out[1]["sources"] == [] and out[1]["checked_on"] == "2026-11-20"
    ConstantsFile.model_validate({"format_version": 1, "constants": out})
    with pytest.raises(ValueError, match="people_basis"):
        build_summary.build_constants({"products": [{"venue_id": "v1", "product_id": "pie", "people_per_unit": 3}]},
                                      _venue_with_sources(tmp_path / "again"))


def test_make_sample_constants_follow_venue_definitions():
    """저장소의 예시 파일로 만든 상수: per_serves 상품의 인원은 업장 정의의 serves 와 같고 형식에 맞는다."""
    from engine.formats.constants import ConstantsFile

    out = make_sample.sample_constants()
    ConstantsFile.model_validate({"format_version": 1, "constants": out})
    venues = {json.loads(f.read_text(encoding="utf-8"))["venue_id"]: json.loads(f.read_text(encoding="utf-8"))
              for f in (make_sample.ROOT / "data" / "venues").glob("*.json")}
    for c in out:
        if not c["constant_id"].startswith("people-per-unit-"):
            continue
        product = next(p for v in venues.values() for p in v["products"]
                       if c["constant_id"] == f"people-per-unit-{v['venue_id']}-{p['product_id']}")
        assert c["value"] == product["serves"] and product["qty_rule"] == "per_serves"
        assert (c["grade"] == "official") == (product["grade"] == "official")


def test_load_source_needs_every_key(tmp_path):
    broken = {**SOURCE, "columns": {k: v for k, v in SOURCE["columns"].items() if k != "paid"}}
    path = tmp_path / "source.json"
    path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="paid"):
        build_summary.load_source(path)


def test_make_sample_is_fixed_and_skips_competitors():
    first, second = make_sample.build(), make_sample.build()
    assert first == second  # 씨앗이 같으면 값이 같다
    venues = {json.loads(f.read_text(encoding="utf-8"))["venue_id"]: json.loads(f.read_text(encoding="utf-8"))
              for f in (make_sample.ROOT / "data" / "venues").glob("*.json")}
    assert not any(venues[r["venue_id"]]["is_competitor"] for r in first)
