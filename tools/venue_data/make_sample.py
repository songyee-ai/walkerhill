"""가상 예시 값 data/samples/base_summary.csv 를 만든다 (docs/FORMATS.md 8절, T13).

기본 데이터를 읽지 않는다. 업장 정의(data/venues)와 라벨 값 목록(data/evidence/vocab.json)만 읽고,
수량은 고정한 씨앗으로 무작위로 정한다. 단가는 업장 정의의 공개 가격을 쓰고,
가격이 비어 있는 상품은 지어낸 단가(SAMPLE_UNIT_PRICE)를 쓴다.

주의: 11-13 에 팀장이 형식을 바꾸면서 저장소의 예시 파일을 직접 새 형식으로 옮겼다(옛 130줄을 달마다 나눔).
이 스크립트로 다시 만들면 그 파일과 값이 달라진다. 다시 만들 필요가 생길 때만 --write 로 덮어쓴다.

    uv run python -m tools.venue_data.make_sample            # 만들어 검사만 한다 (파일을 바꾸지 않음)
    uv run python -m tools.venue_data.make_sample --write    # data/samples/base_summary.csv 를 덮어쓴다
    uv run python -m tools.venue_data.make_sample --add-people  # 지금 예시 파일의 값은 그대로 두고 people 열만 채운다 (T402)

인원(people)은 업장 정의로 센다: per_person 은 수량, per_serves 는 수량 × serves, choice(더하는 상품·포장)는 빈 칸.
기본 데이터는 상품 설명의 인원을 쓰지만(build_summary), 예시 값은 지어낸 값이라 공개된 업장 정의만 쓴다.
people 은 형식(FORMATS 8절, engine/formats/summary.py)에 들어온 뒤부터 파일에 써진다.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
from pathlib import Path

from engine.formats.summary import SUMMARY_COLUMNS, SummaryRow

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261113
SAMPLE_UNIT_PRICE = 50000  # 가격이 비어 있는 상품에 쓰는 지어낸 단가 (세금 포함)
OUT = ROOT / "data" / "samples" / "base_summary.csv"
DAYS = {"weekday": ["weekday"], "weekend": ["weekend"], "all": ["weekday", "weekend"]}


def people_for(product: dict, quantity: int) -> str:
    """업장 정의의 상품 하나와 수량으로 인원을 센다. 사람이 아닌 상품(choice)은 빈 칸."""
    if product["qty_rule"] == "per_person":
        return str(quantity)
    if product["qty_rule"] == "per_serves":
        return str(quantity * product["serves"])
    return ""


def load_products(venues_dir: Path = ROOT / "data" / "venues") -> dict[tuple[str, str], dict]:
    out = {}
    for f in venues_dir.glob("*.json"):
        v = json.loads(f.read_text(encoding="utf-8"))
        for p in v["products"]:
            out[(v["venue_id"], p["product_id"])] = p
    return out


def add_people(path: Path = OUT, venues_dir: Path = ROOT / "data" / "venues") -> list[dict[str, str]]:
    """예시 파일의 줄은 그대로 두고 people 을 채운 줄을 돌려준다. 파일은 쓰지 않는다."""
    products = load_products(venues_dir)
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["people"] = people_for(products[(row["venue_id"], row["product_id"])], int(float(row["quantity"])))
        SummaryRow.from_row({k: v for k, v in row.items() if k in SUMMARY_COLUMNS})
    return rows


def build(venues_dir: Path = ROOT / "data" / "venues", vocab: Path = ROOT / "data" / "evidence" / "vocab.json",
          seed: int = SEED) -> list[dict[str, str]]:
    rng = random.Random(seed)
    groups = json.loads(vocab.read_text(encoding="utf-8"))["customer_group"]
    rows = []
    for f in sorted(venues_dir.glob("*.json")):
        v = json.loads(f.read_text(encoding="utf-8"))
        if v["is_competitor"]:
            continue  # 집계 파일은 워커힐 업장만 담는다
        for p in v["products"]:
            months = p["months"] or v["months"] or list(range(1, 13))
            price = p["price"] if p["price"] is not None else SAMPLE_UNIT_PRICE
            unconfirmed = "Y" if p["price"] is None else "N"
            pairs = sorted({(s["meal"], d) for s in p["slots"] for d in DAYS[s["day_type"]]}, key=str)
            for group in sorted(rng.sample(groups, rng.randint(2, 4))):
                for meal, dtype in pairs:
                    for month in months:
                        qty = rng.randint(1, 40)
                        paid = qty * price
                        row = {"customer_group": group, "venue_id": v["venue_id"], "product_id": p["product_id"],
                               "occasion": p["occasion"], "meal": meal or "", "day_type": dtype, "month": str(month),
                               "unit": p["unit"], "quantity": str(qty), "paid": str(paid),
                               "revenue_net": str(round(paid / 1.1)), "price_unconfirmed": unconfirmed,
                               "people": people_for(p, qty)}
                        SummaryRow.from_row({k: v for k, v in row.items() if k in SUMMARY_COLUMNS})
                        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="가상 예시 집계 파일을 만든다 (T13)")
    parser.add_argument("--write", action="store_true", help="data/samples/base_summary.csv 를 덮어쓴다")
    parser.add_argument("--add-people", action="store_true",
                        help="지금 예시 파일의 값은 그대로 두고 people 열만 채워 쓴다 (형식에 people 이 있어야 한다)")
    args = parser.parse_args(argv)
    if args.add_people:
        if "people" not in SUMMARY_COLUMNS:
            raise SystemExit("형식(engine/formats/summary.py)에 people 열이 아직 없다. 형식이 바뀐 뒤에 돌린다")
        rows = add_people()
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=SUMMARY_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        OUT.write_text("﻿" + buf.getvalue(), encoding="utf-8", newline="")
        print(f"가상 예시 값 {len(rows)}줄에 people 을 채워 {OUT.relative_to(ROOT)} 에 썼다")
        return
    rows = build()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=SUMMARY_COLUMNS, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    if args.write:
        OUT.write_text("﻿" + buf.getvalue(), encoding="utf-8", newline="")
        print(f"가상 예시 값 {len(rows)}줄을 {OUT.relative_to(ROOT)} 에 썼다")
    else:
        print(f"가상 예시 값 {len(rows)}줄을 만들어 형식을 확인했다 (파일은 바꾸지 않음, --write 로 덮어씀)")


if __name__ == "__main__":
    main()
