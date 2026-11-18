"""기본 데이터 집계 파일을 만든다 (docs/FORMATS.md 8절, T13).

저장소 맨 위에서 이렇게 돌린다:
    uv run python -m tools.venue_data.build_summary

읽는 것 (data/venues 말고는 모두 private/ 에 있고 깃에 올라가지 않는다)
- private/base/source.json  기본 데이터 파일의 위치, 열 이름, 다이닝 줄을 고르는 값
- 그 기본 데이터 파일
- private/base/map.json     기본 데이터 상품 → venue_id·product_id 대응표
- data/venues/*.json        업장 정의 (단위, 파는 때 slots, 파는 달 months)

만드는 것 (private/base/)
- summary.csv  집계 파일 (한 줄 = 한 달 동안 그 고객군이 그 상품을 그 조건에서 산 것의 합)
- meta.json    기준 기간, 만든 날, 줄 수, 바꾸지 못한 줄 수, 대조 결과, 업장 정의의 파는 때·달과 어긋난 줄

기본 데이터의 열 이름과 코드 값은 공개 저장소라 이 코드에 적지 않고 source.json 에서 읽는다 (tools/venue_data/README.md 의 "지킬 것").
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from engine.formats.summary import SUMMARY_COLUMNS, SummaryRow

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "private" / "base" / "source.json"
MAP = ROOT / "private" / "base" / "map.json"
OUT_DIR = ROOT / "private" / "base"
VENUES = ROOT / "data" / "venues"

# source.json 의 "columns" 에 있어야 하는 열 (코드가 쓰는 이름 → 기본 데이터의 열 이름)
COLUMN_KEYS = ("date", "business_unit", "venue", "product_id", "customer_group", "quantity", "paid", "revenue_net",
               "price_unconfirmed")

# 2026 공휴일 (대체공휴일 포함). 출처: 한국천문연구원 특일 정보(공공데이터포털)와 같은 값인 인사혁신처 발표·「관공서의 공휴일에 관한 규정」
# (2026-05-01 시행 개정으로 노동절·제헌절 추가), 6-03 지방선거일. 확인 2026-11-13.
HOLIDAYS_2026 = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01", "2026-03-02",
    "2026-05-01", "2026-05-05", "2026-05-24", "2026-05-25", "2026-06-03", "2026-06-06",
    "2026-07-17", "2026-08-15", "2026-08-17", "2026-09-24", "2026-09-25", "2026-09-26",
    "2026-10-03", "2026-10-05", "2026-10-09", "2026-12-25",
}
CALENDAR_SOURCE = ("한국천문연구원 특일 정보 기준 2026 공휴일(대체공휴일 포함, 노동절·제헌절·6-03 지방선거일 포함). "
                   "인사혁신처 발표·「관공서의 공휴일에 관한 규정」으로 확인 2026-11-13")
DAYS = {"weekday": {"weekday"}, "weekend": {"weekend"}, "all": {"weekday", "weekend"}}


def day_type(date: str) -> str:
    """토·일과 공휴일은 weekend, 나머지는 weekday."""
    d = dt.date.fromisoformat(date)
    return "weekend" if d.weekday() >= 5 or date in HOLIDAYS_2026 else "weekday"


def load_source(path: Path = SOURCE) -> dict:
    """source.json 을 읽고 빠진 열 이름이 없는지 본다."""
    source = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in COLUMN_KEYS if k not in source.get("columns", {})]
    for key in ("base_file", "dining_prefix", "unconfirmed_value", "scope_label"):
        if key not in source:
            missing.append(key)
    if missing:
        raise ValueError(f"{path} 에 없는 값: {', '.join(missing)}")
    return source


def load_products(venues_dir: Path = VENUES) -> dict[tuple[str, str], dict]:
    """(venue_id, product_id) → 단위, 이용 상황, 파는 때, 파는 달."""
    out = {}
    for f in venues_dir.glob("*.json"):
        v = json.loads(f.read_text(encoding="utf-8"))
        for p in v["products"]:
            months = p["months"] if p["months"] is not None else v["months"]
            out[(v["venue_id"], p["product_id"])] = {
                "unit": p["unit"], "occasion": p["occasion"], "slots": p["slots"], "months": months,
            }
    return out


def meal_for(product: dict, dtype: str) -> str:
    """그 요일에 이 상품을 파는 끼니가 하나뿐이면 그 끼니, 여럿이면 빈 칸(assumed_splits 로 나눔). 식사가 아니면 빈 칸."""
    if product["occasion"] != "meal":
        return ""
    meals = {s["meal"] for s in product["slots"] if dtype in DAYS[s["day_type"]]}
    return meals.pop() if len(meals) == 1 else ""


def build(source: dict, base_file: Path, mapping: dict, products: dict) -> tuple[list[dict[str, str]], dict]:
    """기본 데이터를 읽어 집계 줄과 meta 를 만든다. 파일은 쓰지 않는다."""
    col = source["columns"]
    by_product = {(m["base_venue"], m["base_product_id"]): m for m in mapping["products"]}

    sums: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    total_rows = dining_rows = 0
    unmapped: dict[str, int] = defaultdict(int)
    dining_paid = dining_net = 0
    outside = defaultdict(lambda: {"rows": 0, "reasons": set()})
    dates = []
    with base_file.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            total_rows += 1
            if not r[col["business_unit"]].startswith(source["dining_prefix"]):
                continue
            dining_rows += 1
            paid, net = int(r[col["paid"]]), int(r[col["revenue_net"]])
            dining_paid += paid
            dining_net += net
            date = r[col["date"]]
            dates.append(date)
            m = by_product.get((r[col["venue"]], r[col["product_id"]]))
            prod = products.get((m["venue_id"], m["product_id"])) if m else None
            if m is None or prod is None:
                unmapped["대응표나 업장 정의에 없는 상품" if m is None else "업장 정의에 상품이 없음"] += 1
                continue
            dtype = day_type(date)
            month = int(date[5:7])
            key_out = (m["venue_id"], m["product_id"])
            if not any(dtype in DAYS[s["day_type"]] for s in prod["slots"]):
                outside[key_out]["rows"] += 1
                outside[key_out]["reasons"].add(f"파는 요일 밖({dtype})")
            if prod["months"] is not None and month not in prod["months"]:
                outside[key_out]["rows"] += 1
                outside[key_out]["reasons"].add(f"파는 달 밖({month}월)")
            unconfirmed = "Y" if r[col["price_unconfirmed"]] == source["unconfirmed_value"] else "N"
            key = (r[col["customer_group"]], m["venue_id"], m["product_id"], prod["occasion"], meal_for(prod, dtype),
                   dtype, month, prod["unit"], unconfirmed)
            s = sums[key]
            s[0] += int(float(r[col["quantity"]]))
            s[1] += paid
            s[2] += net

    rows = []
    for key in sorted(sums):
        group, venue, product, occ, meal, dtype, month, unit, unconfirmed = key
        qty, paid, net = sums[key]
        row = {"customer_group": group, "venue_id": venue, "product_id": product, "occasion": occ, "meal": meal,
               "day_type": dtype, "month": str(month), "unit": unit, "quantity": str(qty), "paid": str(paid),
               "revenue_net": str(net), "price_unconfirmed": unconfirmed}
        SummaryRow.from_row(row)  # 형식에 맞는지 모델로 확인한다
        rows.append(row)

    summary_paid = sum(int(r["paid"]) for r in rows)
    summary_net = sum(int(r["revenue_net"]) for r in rows)
    unmapped_total = sum(unmapped.values())
    match = unmapped_total == 0 and summary_paid == dining_paid and summary_net == dining_net
    meta = {
        "format_version": 1,
        "base_period": {"from": min(dates), "to": max(dates)} if dates else None,
        "made_on": dt.date.today().isoformat(),
        "scope": source["scope_label"],
        "input_rows": total_rows,
        "dining_rows": dining_rows,
        "summary_rows": len(rows),
        "unmapped_rows": unmapped_total,
        "unmapped_reasons": dict(unmapped),
        "revenue_check": {"dining_paid": dining_paid, "summary_paid": summary_paid,
                          "dining_revenue_net": dining_net, "summary_revenue_net": summary_net, "match": match},
        "outside_venue_definition": {f"{v}/{p}": {"rows": o["rows"], "reasons": sorted(o["reasons"])}
                                     for (v, p), o in sorted(outside.items())},
        "day_type_calendar": CALENDAR_SOURCE,
        "meal_rule": "업장 정의의 slots 로 정한다. 그 요일에 파는 끼니가 하나면 그 끼니, 여럿이면 빈 칸",
        "unit": "업장 정의(data/venues)의 unit 으로 바꿔 적음",
    }
    return rows, meta


def write(rows: list[dict[str, str]], meta: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="기본 데이터 집계 파일을 만든다 (T13)")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="summary.csv·meta.json 을 쓸 폴더 (기본 private/base)")
    args = parser.parse_args(argv)

    source = load_source()
    mapping = json.loads(MAP.read_text(encoding="utf-8"))
    rows, meta = build(source, ROOT / source["base_file"], mapping, load_products())
    write(rows, meta, args.out)

    match = meta["revenue_check"]["match"]
    print(f"집계 줄 {len(rows)}개, 바꾸지 못한 줄 {meta['unmapped_rows']}개, 매출 합 대조 {'일치' if match else '불일치'}")
    outside = meta["outside_venue_definition"]
    print(f"업장 정의의 파는 때·달과 어긋난 상품 {len(outside)}개")
    for key, o in outside.items():
        print(f"  {key}: {o['rows']}줄, {', '.join(o['reasons'])}")
    return 0 if match else 1


if __name__ == "__main__":
    raise SystemExit(main())
