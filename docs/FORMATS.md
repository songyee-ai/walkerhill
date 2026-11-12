# 데이터 형식 약속

- 상태: **초안** (2026-11-13). 형식을 쓰는 사람이 [PROGRESS.md](PROGRESS.md) 의 "알릴 것"에서 확인하면 확정한다.
- 무엇을 만드는지는 [PRD.md](PRD.md), 폴더 주인은 [STRUCTURE.md](STRUCTURE.md) 가 기준이다. 이 문서는 영역끼리 주고받는 파일의 모양만 정한다.
- 확정한 뒤 형식을 바꿀 때는 "알릴 것"에 적고, 그 형식을 쓰는 사람이 모두 체크한 뒤 바꾼다. 바꾸면 그 형식의 `format_version` 을 올린다.
- 이 문서의 예시에 든 가격, 비율, 금액, 업장 이름 "예시호텔"은 모두 **지어낸 값**이다. 실제 가격도 기본 데이터의 값도 아니다.
- 폴더 이름은 `STRUCTURE.md` 의 제안을 따랐다. 공통 틀을 만들 때 폴더 이름이 바뀌면 여기도 함께 고친다.

## 1. 한눈에 보기

| 절 | 형식 | 파일 | 만드는 사람 | 쓰는 사람 | 두는 곳 |
|---|---|---|---|---|---|
| 3 | 업장 정의 | `data/venues/<venue_id>.json` | 업장 데이터 | 엔진, 화면, 페르소나 | 저장소 |
| 4 | 후기 라벨 | `data/evidence/reviews/<venue_id>.csv` | 페르소나 | 페르소나, 엔진 | 저장소. 받은 참고 소스의 것과 떼어 둔 것은 `private/evidence/` |
| 4 | 라벨 값 목록 | `data/evidence/vocab.json` | 페르소나 | 업장 데이터, 엔진, 화면 | 저장소 |
| 4 | 후기 주소 목록 | `private/evidence/` 의 주소 목록 세 개 | 페르소나, 업장 데이터 | 페르소나, 업장 데이터 | `private/` |
| 5 | 페르소나 정의 | `personas/<persona_id>.json` 과 `private/personas/<persona_id>.json` | 페르소나 | 엔진, 화면 | 공개 층은 저장소, 비공개 층은 `private/` |
| 6 | 방문 조건 묶음 | `engine/conditions.json` | 엔진 | 업장 데이터, 화면 | 저장소 |
| 7 | 상황 정의 | `scenarios/<scenario_id>.json` | 화면 | 엔진 | 저장소 |
| 8 | 기본 데이터 집계 파일 | `private/base/summary.csv` | 업장 데이터 | 엔진, 페르소나 | `private/`. 가상 예시는 `data/samples/base_summary.csv` |
| 9 | 선택 요청과 응답 | 파일이 아니다. 엔진이 LLM 을 부를 때의 형식이다 | 엔진(요청), 페르소나(프롬프트) | 엔진 | — |
| 10 | 실행 결과 | `private/runs/<run_id>/` | 엔진 | 화면, 페르소나 | `private/`. 가상 예시로 만든 것은 `engine/samples/runs/` |

파일 하나는 한 사람이 쓴다. 남이 만든 파일은 읽기만 하고, 고칠 것은 주인에게 요청한다.

## 2. 공통 규칙

- **글자와 줄바꿈**: 모든 파일은 UTF-8, 줄바꿈은 LF 다. CSV 는 엑셀에서 한글이 깨지지 않도록 맨 앞에 BOM 을 붙인다.
  Python 에서는 쓸 때도 읽을 때도 `encoding="utf-8-sig"` 를 쓴다.
- **키 이름**: 영어 소문자와 밑줄을 쓴다 (`venue_id`). 사람이 읽는 이름, 설명, 라벨 값은 한국어로 쓴다.
- **식별자** (`venue_id`, `product_id`, `persona_id`, `scenario_id`, `condition_id`): 영어 소문자, 숫자, 하이픈만 쓴다.
  한번 정하면 바꾸지 않는다. 다른 파일이 이 값으로 서로를 가리키기 때문이다.
- **금액**: 원 단위 정수다. 쉼표와 "원"을 붙이지 않는다.
- **세금**: 고객이 낸 금액은 세금을 포함한 값이다. 세금을 뺀 매출은 낸 금액 ÷ 1.1 을 반올림한 정수다 (0.5 는 올린다).
  기본 데이터의 매출도 같은 방식으로 계산돼 있다 (11-13, 기본 데이터에 딸린 안내에서 확인). 출처의 가격이 세금을 따로 붙이는 표기면 3절의 `price_basis` 로 표시한다.
- **반올림**: 금액을 계산하다 소수가 나오면 언제나 원 단위로 반올림한다 (0.5 는 올린다).
- **날짜와 시각**: 날짜는 `2026-11-13`, 연월은 `2026-11`, 시각은 `18:30` (24시간), 날짜와 시각을 함께 적을 때는 `2026-11-17T10:15:00+09:00`.
- **빈 값**: JSON 은 `null`, CSV 는 빈 칸이다. "확인했는데 모른다"를 따로 적어야 하면 코드 값 `unknown` 을 쓴다.
- **여러 값**: CSV 의 한 칸에 값을 여러 개 넣을 때는 세미콜론(`;`)으로 나눈다.
- **`format_version`**: JSON 파일의 맨 위에 둔다. 지금은 모두 `1` 이다.

**코드 값** — 프로그램이 갈래를 나누는 값은 아래 영어 코드로만 적는다. 화면에는 한국어 뜻을 보여 준다.

| 뜻 | 키 | 코드 값 |
|---|---|---|
| 이용 상황 | `occasion` | `meal` 식사, `dessert` 디저트·차, `takeout` 포장·구매 |
| 끼니 | `meal` | `lunch` 점심, `dinner` 저녁, `breakfast` 조식. 식사가 아니면 `null` |
| 평일·주말 | `day_type` | `weekday` 평일, `weekend` 주말(토·일·공휴일). 업장 정의에서 둘 다 해당하면 `all` |
| 투숙 여부 | `stay` | `guest` 투숙객, `visitor` 비투숙 방문객. 구분하지 않으면 `null` |
| 달 | `month` | 1 ~ 12. 일 년 전체로 보면 `null` |
| 가격 표기 | `price_basis` | `included` 세금과 봉사료가 든 가격, `excluded` 따로 붙는 가격, `unknown` 모름 |
| 근거 등급 | `grade` | `internal` 내부 매출 자료, `official` 공식 사실, `review` 후기에서 관찰, `assumption` 설계 가정, `unknown` 미확인 |
| 상황의 종류 | `kind` | `baseline` 기준, `our_price` 우리 가격·구성 변경, `our_promo` 우리 프로모션, `competitor` 경쟁 호텔의 변경 |
| 고른 곳 | `choice_kind` | `walkerhill` 워커힐 업장, `competitor` 경쟁 업장, `none` 이용하지 않음 |
| 수량 규칙 | `qty_rule` | `per_person` 사람 수만큼, `per_serves` 한 단위가 여러 명분, `choice` 고객이 수량을 정함 (3절) |
| 대상 | `audience` | `adult` 성인, `child` 어린이, `all` 구분 없음 |
| 출처 종류 | `source_kind` | `blog` 블로그, `map` 지도 서비스, `booking` 예약 서비스, `reference` 받은 참고 소스 |
| 낮음·보통·높음 | `price_sensitivity`, `wait_tolerance` | `low`, `mid`, `high` |

**워커힐 업장의 `venue_id`**

| 업장 | `venue_id` | 업장 | `venue_id` |
|---|---|---|---|
| 금룡 | `geumryong` | 르파사쥬 | `lepassage` |
| 피자힐 | `pizzahill` | 명월관 | `myongwolgwan` |
| 더뷔페 | `thebuffet` | 더파빌리온 | `pavilion` |
| 온달 | `ondal` | 모에기 | `moegi` |

경쟁 업장의 `venue_id` 는 `<호텔을 줄인 이름>-<업장을 줄인 이름>` 으로 업장 데이터 담당이 정한다 (예: `examplehotel-chinese`).

**고객군**: `customer_group` 에는 기본 데이터의 `고객군` 열에 있는 값을 글자 그대로 쓴다. 쓸 수 있는 값은 라벨 값 목록(4절)에 둔다.

## 3. 업장 정의

워커힐 업장과 경쟁 업장이 같은 형식을 쓴다. 업장 하나가 파일 하나다.

| 키 | 뜻 | 비고 |
|---|---|---|
| `venue_id`, `name`, `hotel` | 식별자, 업장 이름, 호텔 이름 | |
| `is_competitor` | 경쟁 업장이면 `true` | |
| `competes_with` | 이 업장과 견주는 워커힐 업장의 `venue_id` 목록 | 경쟁 업장만 채운다. 워커힐 업장은 빈 목록 |
| `cuisine` | 음식 종류나 성격 | 한국어. 예: 중식, 뷔페, 라운지 디저트 |
| `occasions` | 이 업장에 해당하는 이용 상황 | 코드 값 목록 |
| `months` | 영업하는 달 (1 ~ 12 의 목록) | 일 년 내내면 `null` |
| `hours` | 영업 시간. 끼니와 평일·주말마다 한 줄: `meal`, `day_type`, `open`, `last_order`, `close` | 식사가 아닌 업장은 `meal` 을 `null` 로 둔다. 경쟁 업장은 모르면 `hours` 전체를 `null` 로 두고, 그러면 운영 시간 검사를 건너뛴다 |
| `reservation` | 예약 조건: `required` 필수인지, `party_min`·`party_max` 받을 수 있는 인원, `note` | 모르면 `null` |
| `products` | 상품 목록 (아래 표) | |
| `promotions` | 지금 진행 중인 프로모션 (아래 표) | 없으면 빈 목록 |
| `sources` | 출처 목록: `source_id`, `title`, `url`, `checked_on` | 확인일은 그 값을 마지막으로 확인한 날 |
| `default_source_id` | 항목에 `source_id` 가 없을 때 쓰는 출처 | |

**상품** (`products` 의 한 줄)

| 키 | 뜻 | 비고 |
|---|---|---|
| `product_id`, `name` | 업장 안에서 겹치지 않는 식별자, 상품 이름 | |
| `occasion` | 이 상품의 이용 상황 | 업장의 `occasions` 안에 있어야 한다 |
| `meals`, `day_types` | 파는 끼니와 요일 | 식사가 아니면 `meals` 는 빈 목록. 요일 구분이 없으면 `["weekday", "weekend"]` |
| `months` | 파는 달 | 업장과 같으면 `null` |
| `audience` | 누구의 가격인가 | 성인·어린이 가격이 따로면 상품을 둘로 나눈다 |
| `unit` | 판매 단위. 한국어로 적는다 | 예: `1인`, `세트`, `판`, `개`, `잔`, `건` |
| `serves` | 한 단위가 몇 명분인가 | `1인` 이면 1, 2인 세트면 2 |
| `qty_rule` | 수량을 정하는 규칙 | 아래 참고 |
| `qty_max` | `choice` 일 때 고를 수 있는 가장 큰 수량 | 다른 규칙이면 `null` |
| `price` | 출처에 표시된 가격 | 모르면 `null` 이고 `grade` 는 `unknown` |
| `price_basis` | 그 가격의 표기 | `excluded` 면 엔진이 1.1 을 곱해 고객이 낼 금액으로 바꾼다. `unknown` 은 `included` 로 보고 화면에 표시한다 |
| `grade`, `source_id` | 근거 등급과 출처 | 공식 사이트나 공식 발표, 그것을 전한 기사에서 온 값이면 `official` 이다. `source_id` 가 `null` 이면 `default_source_id` 를 쓴다 |

**상품의 이름과 가격을 적는 규칙**

- 공개 파일에는 공식 메뉴판이나 공식 발표에 있는 이름과 가격만 적는다. 기본 데이터에 적힌 이름과 단가를 옮겨 적지 않는다.
- 기본 데이터에는 있는데 공식 자료에서 확인하지 못한 상품은 이름을 일반적인 말로 적고 `price` 를 `null` 로 둔다.
- **`price` 가 `null` 인 상품**: 기본 데이터로 돌릴 때는 엔진이 집계 파일(8절)의 매출 ÷ 수량으로 단가를 채우고 등급을 `internal` 로 표시한다.
  가상 예시로 돌릴 때는 가상 예시 값에서 같은 방법으로 채운다. 어느 쪽에도 없으면 그 상품을 후보에서 빼고 실행 기록에 남긴다.

**수량 규칙** — 금액은 엔진이 이 규칙으로 계산한다. LLM 에 맡기지 않는다.

| `qty_rule` | 수량 | 예 |
|---|---|---|
| `per_person` | `audience` 에 해당하는 사람 수 | 뷔페 성인 가격: 성인 수만큼 |
| `per_serves` | 일행 수 ÷ `serves` 를 올림 | 2인 세트: 4명이면 2개, 5명이면 3개 |
| `choice` | 고객이 0 ~ `qty_max` 에서 고른다 | 음료, 추가 메뉴, 포장 상품 |

**프로모션** (`promotions` 의 한 줄. 상황 정의에서 프로모션을 더할 때도 이 모양을 쓴다)

| 키 | 뜻 |
|---|---|
| `promo_id`, `name` | 식별자, 이름 |
| `benefit` | `{"type": "discount_pct", "value": 10}` 처럼 적는다. `type` 은 `discount_pct` 퍼센트 할인, `discount_amount` 금액 할인, `gift` 증정 (`value` 에 무엇을 주는지 한국어로 적는다) |
| `applies_to` | 적용되는 `product_id` 목록. 모든 상품이면 `null` |
| `conditions` | 적용 조건: `day_type`, `meal`, `stay`, `party_min`. 조건이 없는 키는 `null` |
| `period` | `{"from": 날짜, "to": 날짜}`. 기간을 모르면 `null` |
| `grade`, `source_id` | 근거 등급과 출처 |

**프로모션을 금액에 넣는 규칙**

- `discount_pct`: 적용되는 상품의 줄마다 수량 × 단가 × 퍼센트를 깎는다.
- `discount_amount`: 주문 한 번에 한 번만 깎는다. 적용되는 상품의 첫 줄에서 뺀다.
- `gift`: 금액은 바뀌지 않는다. LLM 에게 무엇을 주는지만 알려 준다.
- 할인이 둘 이상 해당하면 깎이는 금액이 가장 큰 것 하나만 적용한다. 증정은 해당하는 것을 모두 알려 준다.
- 조건에 `stay` 가 적혀 있는데 방문 조건의 `stay` 가 `null` 이면 적용하지 않는다. 다른 조건 키도 같다.
- `period` 는 방문 조건에 `month` 가 있을 때만 견준다. `month` 가 `null` 이면 기간을 보지 않고 적용한다.

예시 — 워커힐 업장

```json
{
  "format_version": 1,
  "venue_id": "geumryong",
  "name": "금룡",
  "hotel": "워커힐",
  "is_competitor": false,
  "competes_with": [],
  "cuisine": "중식",
  "occasions": ["meal"],
  "months": null,
  "hours": [
    {"meal": "lunch", "day_type": "all", "open": "12:00", "last_order": "14:00", "close": "15:00"},
    {"meal": "dinner", "day_type": "all", "open": "18:00", "last_order": "20:30", "close": "22:00"}
  ],
  "reservation": {"required": false, "party_min": 1, "party_max": 12, "note": "별실은 예약 필수"},
  "products": [
    {
      "product_id": "course-a",
      "name": "코스 A",
      "occasion": "meal",
      "meals": ["lunch", "dinner"],
      "day_types": ["weekday", "weekend"],
      "months": null,
      "audience": "all",
      "unit": "1인",
      "serves": 1,
      "qty_rule": "per_person",
      "qty_max": null,
      "price": 150000,
      "price_basis": "included",
      "grade": "official",
      "source_id": null
    },
    {
      "product_id": "course-b",
      "name": "코스 B",
      "occasion": "meal",
      "meals": ["dinner"],
      "day_types": ["weekday", "weekend"],
      "months": null,
      "audience": "all",
      "unit": "1인",
      "serves": 1,
      "qty_rule": "per_person",
      "qty_max": null,
      "price": 200000,
      "price_basis": "included",
      "grade": "official",
      "source_id": null
    }
  ],
  "promotions": [],
  "sources": [
    {"source_id": "S1", "title": "업장 메뉴판 (예시)", "url": "https://example.com/menu", "checked_on": "2026-11-13"}
  ],
  "default_source_id": "S1"
}
```

예시 — 경쟁 업장 (지어낸 업장이다)

```json
{
  "format_version": 1,
  "venue_id": "examplehotel-chinese",
  "name": "예시호텔 중식당",
  "hotel": "예시호텔",
  "is_competitor": true,
  "competes_with": ["geumryong"],
  "cuisine": "중식",
  "occasions": ["meal"],
  "months": null,
  "hours": null,
  "reservation": null,
  "products": [
    {
      "product_id": "course",
      "name": "디너 코스",
      "occasion": "meal",
      "meals": ["lunch", "dinner"],
      "day_types": ["weekday", "weekend"],
      "months": null,
      "audience": "all",
      "unit": "1인",
      "serves": 1,
      "qty_rule": "per_person",
      "qty_max": null,
      "price": 140000,
      "price_basis": "included",
      "grade": "official",
      "source_id": null
    }
  ],
  "promotions": [],
  "sources": [
    {"source_id": "S1", "title": "예시호텔 메뉴 안내 (예시)", "url": "https://example.com/competitor-menu", "checked_on": "2026-11-13"}
  ],
  "default_source_id": "S1"
}
```

## 4. 후기 라벨과 값 목록

### 4.1 후기 라벨

후기 한 건이 한 줄이다. 업장마다 파일 하나다. 원문과 작성자 아이디와 주소는 적지 않는다 (PRD 5.2절).

| 열 | 뜻 | 비고 |
|---|---|---|
| `review_id` | 후기 번호 | 아래 규칙 |
| `venue_id` | 업장 | |
| `source_kind` | 출처 종류 | 코드 값 |
| `posted_ym` | 게시 연월 | 모르면 빈 칸 |
| `customer_group` | 고객군 | 값 목록에서 고른다. 판단할 수 없으면 빈 칸 |
| `purpose` | 방문 목적 | 값 목록에서 하나 |
| `party` | 동행 | 값 목록에서 하나 |
| `adults`, `children` | 성인 수, 어린이 수 | 글에 없으면 빈 칸 |
| `occasion`, `meal`, `day_type`, `stay` | 이용 상황, 끼니, 평일·주말, 투숙 여부 | 코드 값. 글에 없으면 빈 칸 |
| `ordered` | 주문한 것 | 업장 정의의 `product_id`. 여러 개면 `;` 로 나눈다. 정의에 없는 메뉴면 `이름:` 뒤에 한국어로 적는다 |
| `paid_total` | 일행이 낸 총액 | 글에 금액이 있을 때만 |
| `reasons_chosen` | 고른 이유 | 값 목록에서. 여러 개면 `;` |
| `pain_points` | 걸린 점 | 값 목록에서. 여러 개면 `;` |
| `compared_with` | 견준 곳 | 경쟁 업장의 `venue_id`. 정의에 없는 곳이면 `이름:` 뒤에 한국어로 적는다 |
| `would_return` | 다시 올 뜻 | `yes`, `no`, 글에 없으면 빈 칸 |
| `summary` | 한두 문장 요약 | 우리 말로 쓴다. 원문을 따오지 않는다 |
| `labeler`, `labeled_on` | 라벨을 붙인 사람(깃헙 아이디), 붙인 날 | |

**후기 번호**: `<종류>-<venue_id>-<네 자리 번호>`.

- 종류: `R` 은 만드는 데 쓰는 공개 후기, `H` 는 떼어 둔 후기, `P` 는 받은 참고 소스의 후기다.
- 번호대를 나눠 겹치지 않게 한다: 페르소나 담당은 0001 ~ 4999, 업장 데이터 담당은 5000 ~ 9999.

**어느 파일에 두나**

| 후기 | 파일 | 쓰는 사람 |
|---|---|---|
| 만드는 데 쓰는 공개 후기 (`R`) | `data/evidence/reviews/<venue_id>.csv` | 페르소나 담당 |
| 같은 후기 중 돕는 사람이 붙인 것 (`R`, 11-17 부터) | `data/evidence/extra/<venue_id>.csv` | 업장 데이터 담당. 이 폴더는 업장 데이터 담당의 것이다 |
| 떼어 둔 후기 (`H`) | `private/evidence/holdout/<venue_id>.csv` | 업장 데이터 담당. 페르소나가 다 만들어질 때까지 저장소에 올리지 않고 페르소나 담당에게 주지 않는다 |
| 받은 참고 소스의 후기 (`P`) | `private/evidence/reference/<venue_id>.csv` | 페르소나 담당. 저장소에 올리지 않는다 |

예시 (지어낸 후기다)

```csv
review_id,venue_id,source_kind,posted_ym,customer_group,purpose,party,adults,children,occasion,meal,day_type,stay,ordered,paid_total,reasons_chosen,pain_points,compared_with,would_return,summary,labeler,labeled_on
R-geumryong-0003,geumryong,blog,2026-05,가족·친족,가족 행사,3대 가족,5,1,meal,dinner,weekend,visitor,course-a,,별실;주차·접근,가격,examplehotel-chinese,yes,어르신 생신이라 별실이 있는 곳을 찾았고 주차가 편해 골랐다. 가격은 부담스러웠다고 적었다.,borigunbbang,2026-11-13
R-geumryong-0011,geumryong,map,2026-08,가족·친족,가족 행사,3대 가족,,,meal,lunch,weekend,,course-a,,별실;서비스,,,yes,상견례 자리였고 응대가 좋았다고 적었다.,borigunbbang,2026-11-13
```

### 4.2 라벨 값 목록

방문 목적, 동행, 고른 이유, 걸린 점, 고객군에 쓸 수 있는 값을 한 파일에 둔다. 목록에 없는 값이 필요하면 이 파일에 먼저 더한 뒤 쓴다.
아래 값은 모양을 보이기 위한 예시다. 첫 판은 페르소나 담당이 정한다.

```json
{
  "format_version": 1,
  "customer_group": ["가족·친족"],
  "purpose": ["가족 행사", "기념일", "일상 외식", "업무상 식사", "모임"],
  "party": ["3대 가족", "아이 동반 가족", "부부·연인", "친구", "동료·거래처", "혼자"],
  "reasons_chosen": ["맛", "분위기·전망", "별실", "서비스", "주차·접근", "가격 대비 만족", "아이 편의", "시즌 메뉴", "혜택·할인"],
  "pain_points": ["가격", "예약이 어려움", "대기", "소음", "양", "서비스", "주차·접근"]
}
```

`customer_group` 에는 기본 데이터의 고객군 값을 모두 적는다. 위 예시에는 하나만 적었다.

### 4.3 후기 주소 목록

후기를 읽기 전에 주소부터 모은다. 파일은 셋이고 모두 `private/evidence/` 에 둔다. 한 파일은 한 사람만 고친다.

| 파일 | 만드는 사람 | 내용 |
|---|---|---|
| `review_urls.csv` | 페르소나 담당 | 모은 주소 전체. 본문은 아직 읽지 않는다. 업장 데이터 담당에게 넘긴다 |
| `holdout_urls.csv` | 업장 데이터 담당 | 위 목록에서 무작위로 뽑은 20%. 업장 데이터 담당만 갖는다 |
| `build_urls.csv` | 업장 데이터 담당 | 나머지 80%. 페르소나 담당에게 돌려준다. 페르소나 담당은 이 목록의 후기만 읽는다 |

| 열 | 뜻 |
|---|---|
| `venue_id` | 업장 |
| `url` | 후기 주소. 이 세 파일에만 적는다 |
| `source_kind` | 출처 종류 |
| `review_id` | 라벨을 붙인 뒤 채운다 |
| `dropped` | 뺀 이유. 협찬·광고이거나 실제 방문인지 알 수 없으면 적는다 |

## 5. 페르소나 정의

페르소나 한 명이 파일 하나다. **공개 층**(`personas/`)과 **비공개 층**(`private/personas/`)이 같은 형식을 쓴다.

- 공개 층에는 공개 후기와 공식 정보에서 온 것만 적는다.
- 비공개 층에는 받은 참고 소스의 후기에서 온 근거와 값을 적는다. 필요한 키만 적으면 된다. 비공개 층이 없어도 된다.
- **합치는 규칙**: 기본 데이터로 돌릴 때만 두 층을 합친다. 가상 예시로 돌릴 때는 공개 층만 쓴다 (10절).
  - 묶음 안에 묶음이 있으면 몇 겹이든 끝까지 내려가 키마다 따로 합친다. 그래서 비공개 층에 `refs` 만 적어도 공개 층의 `grade` 는 남는다.
  - 값이 하나인 키는 비공개 층의 값을 쓴다. 엔진은 그렇게 바뀐 키를 합친 결과의 `overridden_by_private` 목록에 적는다.
  - 값이 목록인 키는 두 목록을 합치고 겹치는 값은 하나만 남긴다. 비공개 층으로 목록의 값을 지울 수는 없다.
  - 근거가 어느 층에서 왔는지는 후기 번호의 머리글자(`R`, `P`)로 안다.
- **"이유 근거 부족"**: 합친 뒤에도 `evidence` 의 `visit`, `preferences`, `buying` 에 후기 번호가 하나도 없으면 화면이 그 페르소나를 "이유 근거 부족"으로 보여 준다.
- 기본 데이터에서 계산하는 값(업장별 매출 비중, 사는 상품, 방문 시기, 유형, 성별·연령 구성)은 **파일에 적지 않는다.**
  엔진이 실행할 때 집계 파일(8절)에서 계산해 `base_profile` 로 붙인다.

| 키 | 뜻 | 비고 |
|---|---|---|
| `persona_id`, `name` | 식별자, 짧은 이름 | |
| `customer_group` | 속한 고객군 | |
| `share_in_group` | 고객군 안의 몫: `value` (0 ~ 1), `grade`, `basis` | 한 고객군의 페르소나 몫을 더하면 1 이어야 한다 |
| `visit` | 방문 모습: `purposes`, `party` (`label`, `adults`, `children`), `occasions`, `meals`, `day_types` | `purposes` 와 `party.label` 은 값 목록에서 |
| `budget` | 예산: `basis` (`per_person` 1인 기준, `party` 일행 전체 기준), `typical` 평소 쓰는 금액, `max` 이 금액을 넘으면 아예 고려하지 않는 금액 | 엔진은 `max` 를 넘는 주문만 후보에서 뺀다 (9절). `typical` 은 LLM 이 판단할 때 쓴다 |
| `preferences` | 기호와 제약: `cuisines_like`, `cuisines_avoid`, `dietary`, `atmosphere`, `needs` | `atmosphere` 는 항목마다 중요도 1 ~ 3 |
| `buying` | 구매 성향: `price_sensitivity`, `promo_response`, `reservation`, `wait_tolerance` | `promo_response` 와 `reservation` 은 한국어 한 문장 |
| `revisit` | 재방문: `returns_for`, `leaves_for` | 고른 이유·걸린 점의 값 목록에서 |
| `compares_with` | 견주는 경쟁 업장의 `venue_id` 목록 | |
| `evidence` | 위 묶음마다의 근거: `grade`, `refs`, `note` | `refs` 는 후기 번호나 `<venue_id>:<source_id>`. 묶음 일곱 개(`share_in_group`, `visit`, `budget`, `preferences`, `buying`, `revisit`, `compares_with`)가 모두 있어야 한다 |

예시 — 공개 층

```json
{
  "format_version": 1,
  "persona_id": "family-elders",
  "name": "어르신을 모신 행사 가족",
  "customer_group": "가족·친족",
  "share_in_group": {"value": 0.5, "grade": "assumption", "basis": "후기가 모자라 반반으로 둠"},
  "visit": {
    "purposes": ["가족 행사"],
    "party": {"label": "3대 가족", "adults": 4, "children": 0},
    "occasions": ["meal"],
    "meals": ["lunch", "dinner"],
    "day_types": ["weekend"]
  },
  "budget": {"basis": "per_person", "typical": 150000, "max": 220000},
  "preferences": {
    "cuisines_like": ["중식", "한식"],
    "cuisines_avoid": [],
    "dietary": [],
    "atmosphere": {"조용함": 3, "격식": 3, "전망": 1},
    "needs": ["별실", "어르신이 움직이기 편함"]
  },
  "buying": {
    "price_sensitivity": "low",
    "promo_response": "행사 자리라 혜택보다 자리 조건을 먼저 본다",
    "reservation": "늘 예약한다",
    "wait_tolerance": "low"
  },
  "revisit": {"returns_for": ["별실", "서비스"], "leaves_for": ["가격"]},
  "compares_with": ["examplehotel-chinese"],
  "evidence": {
    "share_in_group": {"grade": "assumption", "refs": [], "note": "후기 건수가 모자라 비율을 낼 수 없었다"},
    "visit": {"grade": "review", "refs": ["R-geumryong-0003", "R-geumryong-0011"], "note": ""},
    "budget": {"grade": "assumption", "refs": ["geumryong:S1"], "note": "후기에 금액이 드물어 메뉴 가격대에서 정했다"},
    "preferences": {"grade": "review", "refs": ["R-geumryong-0003", "R-geumryong-0011"], "note": ""},
    "buying": {"grade": "review", "refs": ["R-geumryong-0003"], "note": ""},
    "revisit": {"grade": "review", "refs": ["R-geumryong-0003", "R-geumryong-0011"], "note": ""},
    "compares_with": {"grade": "review", "refs": ["R-geumryong-0003"], "note": ""}
  }
}
```

예시 — 비공개 층 (받은 참고 소스의 후기에서 근거가 더 나온 경우)

```json
{
  "format_version": 1,
  "persona_id": "family-elders",
  "evidence": {
    "preferences": {"refs": ["P-geumryong-0002"]}
  }
}
```

## 6. 방문 조건 묶음

집계하려고 미리 정해 둔 방문 조건의 목록이다 (PRD 7.2절). 페르소나마다 이 목록의 조건마다 한 번씩 돌린다.

| 키 | 뜻 |
|---|---|
| `conditions` | 조건 목록. 조건마다 `condition_id`, `occasion`, `meal`, `day_type`, `stay`, `month` |
| `assumed_splits` | 기본 데이터로 나눌 수 없어 팀이 정한 비율. `split_id`, `applies_when`, `parts`, `grade`, `decided_on`, `note` |

- 묶음의 조건에는 인원과 예산을 넣지 않는다. 그러면 페르소나의 값을 쓴다. 화면에서 한 번만 돌릴 때는 인원과 예산을 직접 넣을 수 있다 (9절의 `condition`).
- 묶음마다의 비율은 고객군마다 다르고 기본 데이터에서 계산하므로 이 파일에 적지 않는다. 실행 기록(10절)에 남는다.
- 조식을 조건에 넣지 않으면 집계 파일의 조식 매출은 대조에서 뺀다.
- **달**: 묶음의 조건은 `month` 를 `null` 로 둔다. 일 년 전체로 본다는 뜻이고, 일부 달에만 파는 업장과 상품은 후보에 넣되 몫으로 센다 (10.2절의 `counted_share`).
  화면에서 한 번만 돌리거나 검증 사례를 넣을 때는 `month` 를 적을 수 있다. 그러면 엔진이 파는 달이 아닌 업장과 상품을 후보에서 뺀다.
- 페르소나의 `visit.occasions` 에 없는 이용 상황의 조건도 돌린다. 그 페르소나는 "이용하지 않음"을 고를 수 있다. 빼고 돌리면 그 고객군의 그 매출이 집계에서 사라지기 때문이다.

```json
{
  "format_version": 1,
  "conditions": [
    {"condition_id": "meal-lunch-weekday", "occasion": "meal", "meal": "lunch", "day_type": "weekday", "stay": null, "month": null},
    {"condition_id": "meal-lunch-weekend", "occasion": "meal", "meal": "lunch", "day_type": "weekend", "stay": null, "month": null},
    {"condition_id": "meal-dinner-weekday", "occasion": "meal", "meal": "dinner", "day_type": "weekday", "stay": null, "month": null},
    {"condition_id": "meal-dinner-weekend", "occasion": "meal", "meal": "dinner", "day_type": "weekend", "stay": null, "month": null},
    {"condition_id": "dessert-weekday", "occasion": "dessert", "meal": null, "day_type": "weekday", "stay": null, "month": null},
    {"condition_id": "dessert-weekend", "occasion": "dessert", "meal": null, "day_type": "weekend", "stay": null, "month": null},
    {"condition_id": "takeout-weekday", "occasion": "takeout", "meal": null, "day_type": "weekday", "stay": null, "month": null},
    {"condition_id": "takeout-weekend", "occasion": "takeout", "meal": null, "day_type": "weekend", "stay": null, "month": null}
  ],
  "assumed_splits": [
    {
      "split_id": "meal-lunch-dinner",
      "applies_when": "집계 파일에서 끼니가 비어 있는 식사 매출",
      "parts": {"lunch": 0.4, "dinner": 0.6},
      "grade": "assumption",
      "decided_on": "2026-11-13",
      "note": "예시 값이다. 엔진 담당이 정한다"
    }
  ]
}
```

## 7. 상황 정의

비교하려고 돌리는 조건 한 벌이다 (PRD 3절). 상황 하나가 파일 하나다. 기준 상황은 `scenarios/baseline.json` 이고 `changes` 가 비어 있다.

| 키 | 뜻 |
|---|---|
| `scenario_id`, `name`, `kind` | 식별자, 이름, 종류 (코드 값) |
| `description` | 무엇을 보려는 상황인지 한두 문장 |
| `changes` | 기준에서 바꾸는 것의 목록 (아래 표) |
| `note` | 바꾸는 값이 어디서 왔는지. 공개된 가격에서 정했는지, 가정인지 |

**바꾸는 것** (`changes` 의 한 줄)

| `op` | 뜻 | 함께 적는 키 |
|---|---|---|
| `set_price` | 가격을 정한 값으로 바꾼다 | `venue_id`, `product_id`, `price` |
| `change_price_pct` | 가격을 퍼센트로 올리거나 내린다. 바뀐 가격은 원 단위로 반올림한다 | `venue_id`, `product_id` (업장의 모든 상품이면 `null`), `pct` (내리면 음수) |
| `add_product` | 상품을 더한다 | `venue_id`, `product` (3절의 상품 한 줄) |
| `remove_product` | 상품을 뺀다 | `venue_id`, `product_id` |
| `add_promotion` | 프로모션을 붙인다 | `venue_id`, `promotion` (3절의 프로모션 한 줄) |
| `remove_promotion` | 프로모션을 뗀다 | `venue_id`, `promo_id` |

- `our_price` 와 `our_promo` 는 워커힐 업장만, `competitor` 는 경쟁 업장만 바꾼다.
- 상황은 업장 정의 파일을 고치지 않는다. 엔진이 실행할 때 업장 정의의 사본에 `changes` 를 순서대로 적용한다.

```json
{
  "format_version": 1,
  "scenario_id": "geumryong-course-price-up",
  "name": "금룡 코스 가격 인상",
  "kind": "our_price",
  "description": "코스 A 의 가격을 올렸을 때 누가 남고 누가 다른 곳으로 옮기는지 본다.",
  "changes": [
    {"op": "change_price_pct", "venue_id": "geumryong", "product_id": "course-a", "pct": 10}
  ],
  "note": "올리는 폭은 가정이다"
}
```

```json
{
  "format_version": 1,
  "scenario_id": "competitor-chinese-discount",
  "name": "경쟁 중식당의 주말 할인",
  "kind": "competitor",
  "description": "경쟁 업장이 주말에 할인을 열었을 때 누가 옮겨 가는지 본다.",
  "changes": [
    {
      "op": "add_promotion",
      "venue_id": "examplehotel-chinese",
      "promotion": {
        "promo_id": "weekend-10",
        "name": "주말 10% 할인",
        "benefit": {"type": "discount_pct", "value": 10},
        "applies_to": null,
        "conditions": {"day_type": "weekend", "meal": null, "stay": null, "party_min": null},
        "period": null,
        "grade": "assumption",
        "source_id": null
      }
    }
  ],
  "note": "할인 폭은 가정이다"
}
```

## 8. 기본 데이터 집계 파일

기본 데이터를 실행할 때마다 다시 읽지 않도록, 업장 데이터 담당이 한 번 계산해 `private/base/summary.csv` 에 둔다.
기본 데이터에서 나온 값이므로 저장소에 올리지 않는다 (PRD 10절).

한 줄은 기준 기간 전체에서 "그 고객군이 그 상품을 그 조건에서 산 것"의 합이다.

| 열 | 뜻 | 비고 |
|---|---|---|
| `customer_group` | 고객군 | 기본 데이터의 값 그대로 |
| `venue_id`, `product_id` | 업장, 상품 | 업장 정의(3절)의 식별자로 바꿔 적는다 |
| `occasion` | 이용 상황 | 코드 값 |
| `meal` | 끼니 | 상품으로 알 수 없으면 빈 칸. 그러면 6절의 `assumed_splits` 로 나눈다 |
| `day_type` | 평일·주말 | 기본 데이터의 날짜로 정한다 |
| `unit` | 판매 단위 | |
| `quantity` | 팔린 수량의 합 | |
| `revenue_net` | 세금을 뺀 매출의 합 | |
| `price_unconfirmed` | 기본 데이터가 가격을 확인하지 못했다고 표시한 줄이면 `Y`, 아니면 `N` | 이 열은 빈 칸을 쓰지 않는다. `Y` 면 화면에서 `unknown` 등급으로 보여 준다 |

- 기본 데이터의 업장 이름·상품 번호를 `venue_id`·`product_id` 로 바꾸는 표는 `private/base/map.json` 에 둔다. 기본 데이터의 이름이 들어 있으므로 저장소에 올리지 않는다.
- 함께 두는 `private/base/meta.json` 에 기준 기간, 만든 날, 줄 수, 식별자로 바꾸지 못한 줄 수를 적는다.
- **가상 예시**: `data/samples/base_summary.csv` 는 같은 열을 가진 지어낸 값이다. 기본 데이터의 수치를 따오지 않는다. 키나 기본 데이터가 없는 PC 는 이 파일로 돌린다.

엔진은 이 파일에서 아래를 계산한다.

| 계산하는 값 | 쓰는 곳 |
|---|---|
| 고객군마다 업장별 매출 비중 | 보정의 대조 (PRD 6.5절), 페르소나의 `base_profile` |
| 고객군마다 방문 조건 묶음의 비율 | 가중 합산 (PRD 7.2절) |
| 고객군의 다이닝 매출 합 | 고객군 배수 (PRD 7.2절) |
| 고객군과 이용 상황마다 매출이 가장 큰 업장 | 검증의 단순 기준 (PRD 6.6절) |

예시 (지어낸 값이다)

```csv
customer_group,venue_id,product_id,occasion,meal,day_type,unit,quantity,revenue_net,price_unconfirmed
가족·친족,geumryong,course-a,meal,,weekday,1인,300,40909091,N
가족·친족,geumryong,course-a,meal,,weekend,1인,500,68181818,N
가족·친족,geumryong,course-b,meal,dinner,weekend,1인,120,21818182,N
```

## 9. 선택 요청과 응답

엔진은 이 한 가지 형식으로만 LLM 을 부른다 (PRD 7.3절). 공급자마다 다른 부분은 엔진 안쪽에서 감춘다.
프롬프트의 문장은 페르소나 담당이 쓰고, 요청과 응답의 모양은 여기서 정한다.

**요청** — 엔진이 만든다.

| 키 | 뜻 |
|---|---|
| `prompt_version` | 프롬프트의 판 이름. 프롬프트를 고치면 바꾼다 |
| `scenario_id` | 어느 상황인가 |
| `persona` | 두 층을 합친 페르소나. 엔진이 붙인 `base_profile` 이 들어갈 수 있다 |
| `condition` | 이번 방문 조건. 6절의 조건에 `adults`, `children`, `budget`, `purpose`, `party` 를 더한 것. `purpose` 와 `party` 는 검증할 때 후기의 라벨을 넣고, 다른 때는 `null` 이다 |
| `candidates` | 규칙으로 추린 후보 업장. 업장마다 고를 수 있는 주문(`options`)이 들어 있다 |
| `allow_none` | "이용하지 않음"을 고를 수 있는가. 늘 `true` |
| `vocab` | 이유로 쓸 수 있는 라벨: `reasons_chosen`, `pain_points` |

- 주문(`options`)의 수량과 금액은 엔진이 3절의 수량 규칙과 프로모션으로 미리 계산한다.
- 성인 가격과 어린이 가격처럼 함께 사야 하는 상품은 주문 하나의 `lines` 에 여러 줄로 넣는다.
- `qty_rule` 이 `choice` 인 상품은 후보의 `addons` 에 넣고, LLM 이 수량을 고른다.
  `addons` 의 한 줄은 `product_id`, `name`, `unit`, `unit_price`, `qty_max` 다. 고른 추가 상품의 금액은 주문의 `total` 에 들어 있지 않고, 엔진이 원장에 따로 적는다.
- 후보의 `promotions` 는 그 업장에서 이번 조건에 해당하는 프로모션이다. 한 줄은 `promo_id`, `name`, `benefit`, `applied` 다.
  `applied` 가 `true` 면 그 할인이 이미 `discount` 에 들어 있다는 뜻이다.
- **예산으로 거르기**: 1인 기준이면 주문의 `total` ÷ (성인 수 + 어린이 수), 일행 기준이면 `total` 을 예산의 `max` 와 견준다. `max` 를 넘는 주문은 후보에서 뺀다.
  주문이 하나도 남지 않은 업장은 후보에서 빠진다. `max` 아래에서 비싼지 싼지는 LLM 이 `typical` 을 보고 판단한다.

```json
{
  "prompt_version": "p1",
  "scenario_id": "baseline",
  "persona": {"persona_id": "family-elders", "name": "어르신을 모신 행사 가족"},
  "condition": {
    "condition_id": "meal-dinner-weekend",
    "occasion": "meal",
    "meal": "dinner",
    "day_type": "weekend",
    "stay": null,
    "month": null,
    "adults": 4,
    "children": 0,
    "budget": {"basis": "per_person", "typical": 150000, "max": 220000},
    "purpose": null,
    "party": null
  },
  "candidates": [
    {
      "venue_id": "geumryong",
      "name": "금룡",
      "hotel": "워커힐",
      "is_competitor": false,
      "cuisine": "중식",
      "options": [
        {
          "option_id": "geumryong-o1",
          "lines": [{"product_id": "course-a", "name": "코스 A", "unit": "1인", "quantity": 4, "unit_price": 150000, "discount": 0, "line_total": 600000}],
          "total": 600000
        },
        {
          "option_id": "geumryong-o2",
          "lines": [{"product_id": "course-b", "name": "코스 B", "unit": "1인", "quantity": 4, "unit_price": 200000, "discount": 0, "line_total": 800000}],
          "total": 800000
        }
      ],
      "addons": [],
      "promotions": []
    },
    {
      "venue_id": "examplehotel-chinese",
      "name": "예시호텔 중식당",
      "hotel": "예시호텔",
      "is_competitor": true,
      "cuisine": "중식",
      "options": [
        {
          "option_id": "examplehotel-chinese-o1",
          "lines": [{"product_id": "course", "name": "디너 코스", "unit": "1인", "quantity": 4, "unit_price": 140000, "discount": 0, "line_total": 560000}],
          "total": 560000
        }
      ],
      "addons": [],
      "promotions": []
    }
  ],
  "allow_none": true,
  "vocab": {
    "reasons_chosen": ["맛", "분위기·전망", "별실", "서비스", "주차·접근", "가격 대비 만족", "아이 편의", "시즌 메뉴", "혜택·할인"],
    "pain_points": ["가격", "예약이 어려움", "대기", "소음", "양", "서비스", "주차·접근"]
  }
}
```

위 예시의 `persona` 는 줄여 적었다. 실제 요청에는 5절의 모든 키가 들어간다.

**응답** — LLM 이 이 모양으로 답한다. 금액은 답에 넣지 않는다.

| 키 | 뜻 |
|---|---|
| `choice` | 고른 것: `venue_id`, `option_id`, `addons` (`product_id` 와 `quantity` 의 목록). "이용하지 않음"이면 `venue_id` 와 `option_id` 가 `null` |
| `reason_labels` | 고른 이유. `vocab.reasons_chosen` 에서 하나 이상. "이용하지 않음"이면 `vocab.pain_points` 에서 고른다 |
| `reason_text` | 이유를 한 문장으로 |
| `used_attributes` | 판단에 쓴 페르소나의 속성. `budget`, `preferences.needs` 처럼 점으로 이어 적는다 |
| `rejected` | 고르지 않은 후보마다: `venue_id`, `pain_labels` (`vocab.pain_points` 에서), `text` 한 문장 |

```json
{
  "choice": {"venue_id": "geumryong", "option_id": "geumryong-o1", "addons": []},
  "reason_labels": ["별실", "주차·접근"],
  "reason_text": "어르신을 모시는 자리라 별실이 있고 차로 오기 편한 곳을 골랐다.",
  "used_attributes": ["visit.purposes", "preferences.needs"],
  "rejected": [
    {"venue_id": "examplehotel-chinese", "pain_labels": ["주차·접근"], "text": "값은 조금 싸지만 어르신과 움직이기에 불편하다."}
  ]
}
```

**엔진이 답을 다시 검사하는 것** — 하나라도 어긋나면 그 실행을 실패로 기록한다.

- `choice.venue_id` 가 후보에 있거나 `null` 이다.
- `choice.option_id` 가 그 업장의 주문에 있다.
- `addons` 의 상품이 그 업장의 `addons` 에 있고 수량이 0 ~ `qty_max` 다.
- 라벨이 모두 `vocab` 에 있다.
- `used_attributes` 가 페르소나에 실제로 있는 속성이다.
- 원장에 적을 금액을 업장 정의의 가격과 프로모션 규칙으로 다시 계산했을 때, 고른 주문의 `total` 과 같다. 추가 상품은 따로 계산해 더한다.

## 10. 실행 결과

상황 하나를 돌린 것이 실행 하나다. `run_id` 는 `<날짜>-<시각>-<scenario_id>` 다 (예: `20261117-101500-baseline`).

**어떤 자료로 돌리느냐에 따라 읽는 곳과 쓰는 곳이 다르다.** 섞이지 않게 엔진이 지킨다.

| `data_mode` | 읽는 것 | 결과를 쓰는 곳 |
|---|---|---|
| `private` | 기본 데이터 집계 파일, 페르소나의 두 층, 받은 참고 소스의 후기 | `private/runs/<run_id>/` |
| `sample` | 가상 예시 값과 페르소나의 공개 층만. `private/` 는 읽지 않는다 | `engine/samples/runs/<run_id>/` |

- `sample` 로 돌린 결과만 저장소에 올릴 수 있다. `private` 로 돌린 결과에는 요청에 든 비공개 층과 기본 데이터의 값이 그대로 남는다.
- 저장된 응답은 요청이 한 글자라도 다르면 재생되지 않는다. 그래서 `private` 결과를 다른 PC 에서 재생하려면 실행 결과와 함께 비공개 층과 집계 파일도 저장소 밖의 경로로 주고받는다.
  시연에 쓸 저장 응답은 한 PC 에서 만들어 그대로 쓴다.

| 파일 | 내용 |
|---|---|
| `run.json` | 실행 기록 |
| `ledger.csv` | 소비 원장 |
| `llm/<request_hash>.json` | 저장된 LLM 응답. 요청 하나가 파일 하나 |
| `calibration.json` | 보정의 대조 결과 (기준 상황만) |
| `validation.json`, `validation_reviews.csv` | 떼어 둔 후기로 잰 검증 결과와, 후기 한 건마다의 결과 |

### 10.1 실행 기록 `run.json`

| 키 | 뜻 |
|---|---|
| `run_id`, `created_at`, `engine_commit` | 실행 번호, 만든 때, 엔진 코드의 커밋 |
| `data_mode` | `private` 기본 데이터로 돌림, `sample` 가상 예시 값으로 돌림 |
| `scenario_id`, `persona_ids`, `condition_ids` | 무엇을 돌렸나 |
| `llm` | `provider`, `model`, `prompt_version`, `calls_new` (새로 부른 수), `calls_replayed` (저장된 응답을 재생한 수), `call_limit`, `stopped_by_limit` |
| `base_profile_mode` | 기본 데이터에서 나온 값을 LLM 에 어떻게 보냈나: `none` 보내지 않음, `bucketed` 범주로 바꿔 보냄, `raw` 그대로 보냄 |
| `inputs` | 입력 파일들의 해시. 같은 입력인지 견줄 때 쓴다 |
| `weights` | `group_multiplier` 고객군 배수, `persona_weight` 페르소나의 가중치, `condition_ratio` 고객군마다 묶음의 비율, `grades` 각 값의 근거 등급. 묶음의 비율은 조건마다 등급을 적는다. `assumed_splits` 로 나눈 조건은 `assumption` 이다 |
| `skipped_products` | 가격을 채우지 못해 후보에서 뺀 상품의 목록 |
| `weights_from` | 가중치를 정한 기준 상황의 `run_id`. 기준 상황 자신이면 `null` |
| `counts` | `visits` 돌린 수, `failed` 실패한 수 |
| `status` | `ok`, `stopped_by_limit`, `failed` |

```json
{
  "format_version": 1,
  "run_id": "20261117-101500-baseline",
  "created_at": "2026-11-17T10:15:00+09:00",
  "engine_commit": "0000000",
  "data_mode": "sample",
  "scenario_id": "baseline",
  "persona_ids": ["family-elders"],
  "condition_ids": ["meal-dinner-weekend"],
  "llm": {
    "provider": "anthropic",
    "model": "정한 모델 이름",
    "prompt_version": "p1",
    "calls_new": 1,
    "calls_replayed": 0,
    "call_limit": 200,
    "stopped_by_limit": false
  },
  "base_profile_mode": "none",
  "inputs": {"venues": "해시", "personas": "해시", "conditions": "해시", "scenario": "해시", "summary": "해시"},
  "weights": {
    "group_multiplier": {"가족·친족": 240.0},
    "persona_weight": {"family-elders": 120.0},
    "condition_ratio": {"가족·친족": {"meal-dinner-weekend": 1.0}},
    "grades": {
      "group_multiplier": "internal",
      "persona_weight": "assumption",
      "condition_ratio": {"가족·친족": {"meal-dinner-weekend": "assumption"}}
    }
  },
  "skipped_products": [],
  "weights_from": null,
  "counts": {"visits": 1, "failed": 0},
  "status": "ok"
}
```

### 10.2 소비 원장 `ledger.csv`

주문한 상품 한 줄이 원장의 한 줄이다. 방문 한 번에 상품이 여럿이면 `visit_id` 가 같은 줄이 여럿 생긴다.

| 열 | 뜻 |
|---|---|
| `run_id`, `scenario_id` | 실행, 상황 |
| `visit_id` | 방문 번호. `<persona_id>__<condition_id>`. 화면에서 조건을 직접 넣어 돌릴 때는 `condition_id` 를 `manual-<번호>` 로 붙여 겹치지 않게 한다 |
| `persona_id`, `customer_group`, `condition_id` | 누가, 어느 조건에서 |
| `choice_kind` | 고른 곳의 종류 (코드 값) |
| `venue_id`, `product_id` | 고른 업장과 상품. "이용하지 않음"이면 빈 칸 |
| `quantity`, `unit` | 수량과 단위 |
| `list_price`, `discount` | 단위당 표시가, 이 줄에서 깎인 금액 |
| `paid` | 고객이 낸 금액 (세금 포함). 경쟁 업장이면 그곳에 낸 금액이다 |
| `revenue_net` | **워커힐의** 세금을 뺀 매출. 경쟁 업장과 "이용하지 않음"은 0 |
| `represented` | 이 방문이 대표하는 크기 = 페르소나의 가중치 × 묶음의 비율 |
| `counted_share` | 그 업장·상품의 것으로 세는 몫. 일 년 내내 팔면 1, 일부 달만 팔면 파는 달 수 ÷ 12 |
| `weighted_revenue` | `revenue_net` × `represented` × `counted_share` |
| `reason_labels`, `reason_text`, `used_attributes` | 응답에서 온 이유. 라벨과 속성이 여럿이면 `;` |
| `llm_call` | `new` 새로 부름, `replay` 저장된 응답을 재생 |
| `request_hash` | 저장된 응답의 파일 이름 |
| `status`, `fail_reason` | `ok` 또는 `failed`, 실패한 이유 |

- 일부 달에만 파는 업장·상품을 고르면 줄을 하나 더 만든다: `choice_kind` 는 `none`, `counted_share` 는 1 에서 위의 몫을 뺀 값,
  `reason_text` 는 "파는 달이 아님". 나머지 몫을 "이용하지 않음"으로 세기 위해서다 (PRD 7.2절).
- 모든 합계는 이 원장에서 낸다. 업장별 가상 매출은 `weighted_revenue` 를 업장별로 더한 값이다.
- 아래 예시의 두 줄은 서로 다른 실행의 원장에서 한 줄씩 가져온 것이다. 원장 파일 하나에는 실행 하나의 줄만 들어간다.

```csv
run_id,scenario_id,visit_id,persona_id,customer_group,condition_id,choice_kind,venue_id,product_id,quantity,unit,list_price,discount,paid,revenue_net,represented,counted_share,weighted_revenue,reason_labels,reason_text,used_attributes,llm_call,request_hash,status,fail_reason
20261117-101500-baseline,baseline,family-elders__meal-dinner-weekend,family-elders,가족·친족,meal-dinner-weekend,walkerhill,geumryong,course-a,4,1인,150000,0,600000,545455,120.0,1.0,65454600,별실;주차·접근,어르신을 모시는 자리라 별실이 있고 차로 오기 편한 곳을 골랐다.,visit.purposes;preferences.needs,new,a1b2c3d4,ok,
20261117-103000-competitor-chinese-discount,competitor-chinese-discount,family-elders__meal-dinner-weekend,family-elders,가족·친족,meal-dinner-weekend,competitor,examplehotel-chinese,course,4,1인,140000,56000,504000,0,120.0,1.0,0,혜택·할인,할인 폭이 커서 이번에는 다른 호텔로 갔다.,buying.price_sensitivity,new,e5f6a7b8,ok,
```

### 10.3 저장된 LLM 응답 `llm/<request_hash>.json`

| 키 | 뜻 |
|---|---|
| `request_hash` | 공급자, 모델, 9절의 요청 전체를 한데 묶어 낸 해시. 하나라도 다르면 다른 파일이다 |
| `provider`, `model`, `created_at` | 누가 언제 답했나 |
| `request`, `response` | 9절의 요청과 응답 그대로 |
| `raw_text` | LLM 이 돌려준 글 그대로 |
| `usage` | `input_tokens`, `output_tokens` |

- 같은 `request_hash` 의 파일이 있으면 LLM 을 부르지 않고 그 응답을 쓴다. 그러면 원장이 똑같이 나온다 (PRD 7.3절).
- 팀원끼리 이 폴더를 저장소 밖의 경로로 주고받으면 키가 없는 사람도 같은 결과를 재생할 수 있다.

### 10.4 보정의 대조 결과 `calibration.json`

```json
{
  "format_version": 1,
  "run_id": "20261117-101500-baseline",
  "criteria": {"top_venue_must_match": true, "max_diff_pp": 15},
  "groups": {
    "가족·친족": {
      "venues": {
        "geumryong": {"sim_share": 0.3, "base_share": 0.25, "diff_pp": 5.0},
        "thebuffet": {"sim_share": 0.7, "base_share": 0.75, "diff_pp": -5.0}
      },
      "top_sim": "thebuffet",
      "top_base": "thebuffet",
      "pass": true
    }
  },
  "uncovered_groups": [],
  "pass": true
}
```

`uncovered_groups` 에는 페르소나가 없어 다루지 않은 고객군을 적는다. 화면이 이것을 "다루지 않은 고객군"으로 보여 준다.

### 10.5 검증 결과 `validation.json`

```json
{
  "format_version": 1,
  "created_at": "2026-11-19T15:00:00+09:00",
  "min_reviews": 5,
  "venues": {
    "geumryong": {
      "n": 12,
      "enough": true,
      "venue_match": 8,
      "venue_match_baseline": 7,
      "reason_match": 9,
      "reason_match_baseline": 6
    },
    "pavilion": {"n": 3, "enough": false, "venue_match": null, "venue_match_baseline": null, "reason_match": null, "reason_match_baseline": null}
  }
}
```

값은 비율이 아니라 건수다 (`n` 건 가운데 몇 건). `enough` 가 `false` 인 업장은 화면에 "검증 건수 부족"으로 보여 준다.

**후기 한 건마다의 결과** `validation_reviews.csv`

| 열 | 뜻 |
|---|---|
| `review_id`, `venue_id`, `customer_group` | 떼어 둔 후기 |
| `persona_id` | 돌린 페르소나. 그 고객군에 페르소나가 둘이면 후기의 `purpose`, `party` 가 더 많이 겹치는 쪽, 같으면 몫이 큰 쪽 (PRD 6.6절) |
| `occasion`, `meal`, `day_type` | 돌린 조건. 후기에 끼니나 요일이 비어 있으면 그 페르소나의 `visit.meals`, `visit.day_types` 의 첫 값을 쓴다 |
| `chosen_venue_id` | 페르소나가 고른 곳. "이용하지 않음"이면 빈 칸 |
| `venue_match`, `reason_match` | 업장이 같은가, 이유 라벨이 하나 이상 겹치는가 (`Y`, `N`) |
| `baseline_venue_id`, `baseline_venue_match`, `baseline_reason_match` | 단순 기준이 고른 곳과 그 결과 |
| `skipped` | 돌리지 못한 이유. 고객군이 비어 있거나 그 고객군에 페르소나가 없으면 적는다. 이런 후기는 `n` 에서 뺀다 |

## 11. 형식이 맞는지 볼 것

공통 틀을 만들 때 아래를 검사하는 도구를 넣는다. 그 전에는 파일을 올리기 전에 각자 본다.

- JSON 파일이 읽히고 `format_version` 이 있다.
- 코드 값이 2절의 표에 있는 값이다.
- 다른 파일을 가리키는 식별자가 실제로 있다: 경쟁 업장의 `competes_with`, 페르소나의 `compares_with`, 상황의 `venue_id`·`product_id`, 후기의 `venue_id`.
- 상품의 `occasion` 이 업장의 `occasions` 안에 있다. 워커힐 업장마다 경쟁 업장이 하나 이상 있다.
- 업장 정의의 모든 `source_id` 가 `sources` 에 있고 `checked_on` 이 있다.
- 라벨(방문 목적, 동행, 고른 이유, 걸린 점, 고객군)이 값 목록에 있다.
- 페르소나의 `evidence` 에 묶음 일곱 개가 모두 있고, 한 고객군의 `share_in_group.value` 를 더하면 1 이다.
- 저장소 안의 어느 파일에도 `P-` 나 `H-` 로 시작하는 후기 번호가 없다. `engine/samples/runs/` 의 저장 응답과 원장도 본다.
- `engine/samples/runs/` 의 실행 기록은 모두 `data_mode` 가 `sample` 이다.
- 상황의 `our_price`·`our_promo` 는 워커힐 업장만, `competitor` 는 경쟁 업장만 바꾼다.
- 저장소 안의 CSV 와 JSON 에 주소 목록, 떼어 둔 후기, `private/` 에 둘 실행 결과가 없다.

## 12. 언제까지 필요한가, 아직 정하지 않은 것

**최소 버전(11-16)에 필요한 것은 일부다.** 나머지는 형식은 정해 두되 P1 을 시작할 때(11-17) 다시 보고 고칠 수 있다.

| 최소 버전에 필요하다 | P1 에서 쓴다 |
|---|---|
| 2절 공통 규칙, 3절 업장 정의 (프로모션은 빈 목록) | 3절의 프로모션 규칙 |
| 4.1절 후기 라벨, 4.2절 값 목록 | 4.3절 주소 목록과 떼어 둘 후기, 돕는 사람의 파일, 번호대 |
| 5절 페르소나 정의의 공개 층 | 비공개 층과 합치는 규칙 |
| 6절의 조건 하나 | 조건 여덟 개, `assumed_splits`, `month` |
| 7절의 기준 상황 | `set_price` 를 뺀 나머지 바꾸는 종류 |
| 8절 가상 예시 값 | 기본 데이터 집계 파일, 가격이 `null` 인 상품을 채우는 규칙 |
| 9절 선택 요청과 응답 | `addons`, 후보의 `promotions` |
| 10.1절 실행 기록, 10.2절 소비 원장, 10.3절 저장된 응답 | `counted_share`, 10.4절 보정, 10.5절 검증 |

**아직 정하지 않은 것**

- [ ] 평일과 주말을 나눌 때 공휴일을 어느 달력으로 정할지 (업장 데이터 담당. PRD 5.2절의 달력 출처)
- [ ] 폴더 이름의 확정 (공통 틀을 만들 때, 엔진 담당)
- [ ] 방문 조건 묶음에 조식과 투숙 여부를 넣을지 (엔진 담당)
- [ ] `assumed_splits` 의 값 (엔진 담당)
- [ ] 기본 데이터에서 나온 값을 LLM 에 어떻게 보낼지, 곧 `base_profile_mode` 의 기본값 (PRD 17절, 엔진 담당)
- [ ] 라벨 값 목록의 첫 판 (11-13, 페르소나 담당)
- [ ] 경쟁 업장의 `venue_id` (업장 데이터 담당)
- [ ] 형식을 검사하는 도구 (공통 틀을 만들 때, 엔진 담당)
