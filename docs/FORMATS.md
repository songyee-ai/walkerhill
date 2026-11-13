# 데이터 형식 약속

- 상태: **초안** (2026-11-13). 형식을 쓰는 사람이 [PROGRESS.md](PROGRESS.md) 의 "알릴 것"에서 확인하면 확정한다.
- 무엇을 만드는지는 [PRD.md](PRD.md), 폴더 주인은 [STRUCTURE.md](STRUCTURE.md) 가 기준이다. 이 문서는 영역끼리 주고받는 파일의 모양만 정한다.
- 확정한 뒤 형식을 바꿀 때는 "알릴 것"에 적고, 그 형식을 쓰는 사람이 모두 체크한 뒤 바꾼다. 바꾸면 그 형식의 `format_version` 을 올린다.
- 이 문서의 예시에 든 가격, 비율, 금액, 업장 이름 "예시호텔"은 모두 **지어낸 값**이다. 실제 가격도 기본 데이터의 값도 아니다.
- 폴더 이름은 11-13 에 확정했다 (`STRUCTURE.md`).
- **코드와 예시 파일**: 이 문서를 코드로 옮긴 모델이 `engine/formats/` 에 있고, 이 문서의 예시를 그대로 파일로 만든 한 벌이 `tests/fixtures/example/` 에 있다.
  자기 파일을 만들 때 그 예시 파일을 베껴서 시작한다. 형식을 바꿀 때는 이 문서, 모델, 예시 파일을 함께 고친다 (셋이 어긋나면 테스트가 실패한다).
- **검사**: 파일을 올리기 전에 `uv run python -m tools.check_formats` 를 돌린다 (11절).

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

**데이터 폴더에는 이 표의 파일만 둔다.** `data/`, `personas/`, `scenarios/`, `engine/samples/` 에는 위 표의 파일과
안내 파일(`README.md`)만 둘 수 있다. 예외는 프롬프트의 문장을 두는 `personas/prompts/` 하나다.
그 밖의 파일과 폴더는 형식 검사가 오류로 본다 (11절). 검사가 읽지 않는 파일에는 틀린 데이터나 올리면 안 되는 것이 섞여도 알 수 없기 때문이다.

## 2. 공통 규칙

- **글자와 줄바꿈**: 모든 파일은 UTF-8, 줄바꿈은 LF 다. CSV 는 엑셀에서 한글이 깨지지 않도록 맨 앞에 BOM 을 붙인다.
  Python 에서는 쓸 때도 읽을 때도 `encoding="utf-8-sig"` 를 쓴다.
- **키 이름**: 영어 소문자와 밑줄을 쓴다 (`venue_id`). 사람이 읽는 이름, 설명, 라벨 값은 한국어로 쓴다.
- **식별자** (`venue_id`, `product_id`, `persona_id`, `scenario_id`, `condition_id`): 영어 소문자, 숫자, 하이픈만 쓴다.
  한번 정하면 바꾸지 않는다. 다른 파일이 이 값으로 서로를 가리키기 때문이다.
  `venue_id` 는 영어 글자로 시작하고 세 글자 이상이다. 형식 검사가 저장소에서 후기 번호(4.1절)를 찾을 때 이 모양에 기댄다.
- **금액**: 원 단위 정수다. 쉼표와 "원"을 붙이지 않는다.
- **세금**: 고객이 낸 금액은 세금을 포함한 값이다. 세금을 뺀 매출은 낸 금액 ÷ 1.1 을 반올림한 정수다 (0.5 는 올린다).
  기본 데이터의 매출도 같은 방식으로 계산돼 있다 (11-13, 기본 데이터에 딸린 안내에서 확인). 출처의 가격이 세금을 따로 붙이는 표기면 3절의 `price_basis` 로 표시한다.
- **반올림**: 금액을 계산하다 소수가 나오면 언제나 원 단위로 반올림한다 (0.5 는 올린다).
- **날짜와 시각**: 날짜는 `2026-11-13`, 연월은 `2026-11`, 시각은 `18:30` (24시간), 날짜와 시각을 함께 적을 때는 `2026-11-17T10:15:00+09:00`.
  함께 적을 때는 시간대(`+09:00`)를 빼지 않는다. 빼면 PC 마다 다른 시각으로 읽힌다.
- **JSON 의 값**: 숫자와 참·거짓은 따옴표 없이 적는다 (`150000`, `true`). 정수인 값에는 소수점을 붙이지 않는다 (`1.0` 이 아니라 `1`).
  검사 도구와 엔진은 JSON 을 적힌 그대로 엄격하게 읽는다. 코드에서 읽을 때는 `engine.formats.read_model` 을 쓴다.
- **빈 값**: JSON 은 `null`, CSV 는 빈 칸이다. "확인했는데 모른다"를 따로 적어야 하면 코드 값 `unknown` 을 쓴다.
- **여러 값**: CSV 의 한 칸에 값을 여러 개 넣을 때는 세미콜론(`;`)으로 나눈다.
- **`format_version`**: JSON 파일의 맨 위에 둔다. 지금은 모두 `1` 이다.

**코드 값** — 프로그램이 갈래를 나누는 값은 아래 영어 코드로만 적는다. 화면에는 한국어 뜻을 보여 준다.

| 뜻 | 키 | 코드 값 |
|---|---|---|
| 이용 상황 | `occasion` | `meal` 식사, `dessert` 디저트·차, `takeout` 포장·구매 |
| 끼니 | `meal` | `lunch` 점심, `dinner` 저녁, `breakfast` 조식. 식사가 아니면 `null` |
| 평일·주말 | `day_type` | `weekday` 평일, `weekend` 주말(토·일·공휴일. 대체공휴일도 든다). 업장 정의에서 둘 다 해당하면 `all` |
| 투숙 여부 | `stay` | `guest` 투숙객, `visitor` 비투숙 방문객. 구분하지 않으면 `null` |
| 달 | `month` | 1 ~ 12. 일 년 전체로 보면 `null` |
| 가격 표기 | `price_basis` | `included` 세금과 봉사료가 든 가격, `excluded_vat` 부가세만 따로 붙는 가격, `excluded_vat_service` 봉사료와 부가세가 모두 따로 붙는 가격, `unknown` 모름 |
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
| `hours` | 영업 시간. 끼니와 평일·주말마다 한 줄: `meal`, `day_type`, `open`, `last_order`, `close`, `source_id` | 식사가 아닌 업장은 `meal` 을 `null` 로 둔다. `source_id` 가 `null` 이면 `default_source_id` 를 쓴다 (영업 시간은 메뉴판과 출처가 다를 수 있다). 마지막 주문 시각이 따로 없으면 `last_order` 를 `null` 로 둔다. 경쟁 업장은 모르면 `hours` 전체를 `null` 로 두고, 그러면 운영 시간 검사를 건너뛴다 |
| `reservation` | 예약 조건: `required` 필수인지, `party_min`·`party_max` 받을 수 있는 인원, `note`, `source_id` | 모르면 `null`. `source_id` 가 `null` 이면 `default_source_id` 를 쓴다 |
| `products` | 상품 목록 (아래 표) | |
| `promotions` | 지금 진행 중인 프로모션 (아래 표) | 없으면 빈 목록 |
| `sources` | 출처 목록: `source_id`, `title`, `url`, `checked_on` | 확인일은 그 값을 마지막으로 확인한 날 |
| `default_source_id` | 항목에 `source_id` 가 없을 때 쓰는 출처 | |

**상품** (`products` 의 한 줄)

| 키 | 뜻 | 비고 |
|---|---|---|
| `product_id`, `name` | 업장 안에서 겹치지 않는 식별자, 상품 이름 | |
| `occasion` | 이 상품의 이용 상황 | 업장의 `occasions` 안에 있어야 한다 |
| `slots` | 파는 때. 끼니(`meal`)와 평일·주말(`day_type`)의 짝을 하나 이상 적는다 | 아래 "파는 때를 적는 규칙" |
| `months` | 파는 달 | 업장과 같으면 `null` |
| `audience` | 누구의 가격인가 | 성인·어린이 가격이 따로면 상품을 둘로 나눈다 |
| `unit` | 판매 단위. 한국어로 적는다 | 예: `1인`, `세트`, `판`, `개`, `잔`, `건` |
| `serves` | 한 단위가 몇 명분인가 | `1인` 이면 1, 2인 세트면 2 |
| `qty_rule` | 수량을 정하는 규칙 | 아래 참고 |
| `qty_max` | `choice` 일 때 고를 수 있는 가장 큰 수량 | 다른 규칙이면 `null` |
| `price` | 출처에 표시된 가격 | 모르면 `null` 이고 `grade` 는 `unknown` |
| `price_basis` | 그 가격의 표기 | 출처에 적힌 가격을 그대로 옮기고 표기만 고른다. 엔진이 `excluded_vat` 면 1.1, `excluded_vat_service` 면 1.21(1.1 × 1.1)을 곱해 고객이 낼 금액으로 바꾼다 (곱한 뒤 한 번 반올림). `unknown` 은 `included` 로 보고 화면에 표시한다 |
| `grade`, `source_id` | 근거 등급과 출처 | 공식 사이트나 공식 발표, 그것을 전한 기사에서 온 값이면 `official` 이다. `source_id` 가 `null` 이면 `default_source_id` 를 쓴다 |

**상품의 이름과 가격을 적는 규칙**

- 공개 파일에는 공식 메뉴판이나 공식 발표에 있는 이름과 가격만 적는다. 기본 데이터에 적힌 이름과 단가를 옮겨 적지 않는다.
- 기본 데이터에는 있는데 공식 자료에서 확인하지 못한 상품은 이름을 일반적인 말로 적고 `price` 를 `null` 로 둔다.
- **`price` 가 `null` 인 상품**: 기본 데이터로 돌릴 때는 엔진이 집계 파일(8절)의 `paid` ÷ `quantity` 로 단가를 채우고 등급을 `internal` 로 표시한다.
  `paid` 는 고객이 낸 금액(세금 포함)이라 그대로 고객이 낼 단가가 된다. 세금을 뺀 `revenue_net` 으로 나누면 단가가 세금만큼 낮아지므로 쓰지 않는다.
  가상 예시로 돌릴 때는 가상 예시 값에서 같은 방법으로 채운다. 어느 쪽에도 없으면 그 상품을 후보에서 빼고 실행 기록에 남긴다.

**파는 때를 적는 규칙** (`slots`)

- 한 줄은 `{"meal": 끼니, "day_type": 요일}` 이다. `day_type` 은 `weekday`, `weekend`, 둘 다면 `all` 이다.
- 끼니 목록과 요일 목록을 따로 적어 곱하지 않고 짝으로 적는다. 그래야 "주말 점심과 모든 요일 저녁"에 같은 값으로 파는 상품을 적을 수 있다:
  `[{"meal": "lunch", "day_type": "weekend"}, {"meal": "dinner", "day_type": "all"}]`
- 식사가 아닌 상품(디저트·차, 포장·구매)은 `meal` 을 `null` 로 둔다: `[{"meal": null, "day_type": "all"}]`
- 같은 때를 두 번 적지 않는다. `all` 은 평일과 주말을 모두 덮으므로, 점심·`all` 과 점심·`weekend` 를 함께 적으면 오류다.
- 기본 데이터의 상품 하나는 업장 정의의 상품 하나로 잇는다. 파는 때가 섞였다고 상품을 둘로 나누지 않는다.

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
    {"meal": "lunch", "day_type": "all", "open": "12:00", "last_order": "14:00", "close": "15:00", "source_id": null},
    {"meal": "dinner", "day_type": "all", "open": "18:00", "last_order": "20:30", "close": "22:00", "source_id": null}
  ],
  "reservation": {"required": false, "party_min": 1, "party_max": 12, "note": "별실은 예약 필수", "source_id": null},
  "products": [
    {
      "product_id": "course-a",
      "name": "코스 A",
      "occasion": "meal",
      "slots": [{"meal": "lunch", "day_type": "all"}, {"meal": "dinner", "day_type": "all"}],
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
      "slots": [{"meal": "dinner", "day_type": "all"}],
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
      "slots": [{"meal": "lunch", "day_type": "all"}, {"meal": "dinner", "day_type": "all"}],
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
| `purpose` | 방문 목적 | 값 목록에서 하나. 글과 화면에 없으면 빈 칸 |
| `party` | 동행 | 값 목록에서 하나. 글과 화면에 없으면 빈 칸 |
| `adults`, `children` | 성인 수, 어린이 수 | 글에 없으면 빈 칸 |
| `occasion`, `meal`, `day_type`, `stay` | 이용 상황, 끼니, 평일·주말, 투숙 여부 | 코드 값. 글에 없으면 빈 칸 |
| `ordered` | 주문한 것 | 업장 정의의 `product_id`. 여러 개면 `;` 로 나눈다. 정의에 없는 메뉴면 `이름:` 뒤에 한국어로 적는다 |
| `paid_total` | 일행이 낸 총액 | 글에 금액이 있을 때만 |
| `reasons_chosen` | 고른 이유 | 값 목록에서. 여러 개면 `;` |
| `pain_points` | 걸린 점 | 값 목록에서. 여러 개면 `;` |
| `compared_with` | 견준 곳 | 경쟁 업장의 `venue_id`. 정의에 없는 곳이면 `이름:` 뒤에 한국어로 적는다 |
| `would_return` | 다시 올 뜻 | `yes`, `no`, 글에 없으면 빈 칸 |
| `summary` | 한두 문장 요약 | 우리 말로 쓴다. 원문을 따오지 않는다. 본문이 있으면 꼭 쓰고, 본문 없이 화면 값만 있는 후기만 비운다 |
| `labeler`, `labeled_on` | 라벨을 붙인 사람(깃헙 아이디), 붙인 날 | |

**빈 칸**: 글과 화면에 없는 것은 지어내지 않고 비운다. 빈 칸이 많은 것이 정상이다. 지도 서비스의 방문 목적과 동행은 최근 후기에만 붙어 있다.

- 근거가 되는 칸(`purpose`, `party`, `ordered`, `reasons_chosen`, `pain_points`, `compared_with`, `would_return`)이
  모두 빈 줄은 올리지 않는다. 근거가 없는 후기다. 형식 검사가 오류로 본다.
- `summary` 를 비워도 형식 검사는 지나간다. 본문이 있는지는 검사가 알 수 없어서, 본문이 있는 후기에 요약을 쓰는 것은 라벨을 붙이는 사람이 지킨다.
  (11-13 에 정했다. 처음에는 `purpose`, `party`, `summary` 가 꼭 채우는 칸이었다)

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

예시 (지어낸 후기다. 셋째 줄은 방문 목적과 동행이 글에 없는 후기다)

```csv
review_id,venue_id,source_kind,posted_ym,customer_group,purpose,party,adults,children,occasion,meal,day_type,stay,ordered,paid_total,reasons_chosen,pain_points,compared_with,would_return,summary,labeler,labeled_on
R-geumryong-0003,geumryong,blog,2026-05,가족·친족,가족 행사,3대 가족,5,1,meal,dinner,weekend,visitor,course-a,,별실;주차·접근,가격,examplehotel-chinese,yes,어르신 생신이라 별실이 있는 곳을 찾았고 주차가 편해 골랐다. 가격은 부담스러웠다고 적었다.,borigunbbang,2026-11-13
R-geumryong-0011,geumryong,map,2026-08,가족·친족,가족 행사,3대 가족,,,meal,lunch,weekend,,course-a,,별실;서비스,,,yes,상견례 자리였고 응대가 좋았다고 적었다.,borigunbbang,2026-11-13
R-geumryong-0027,geumryong,map,2026-03,,,,,,meal,dinner,,,,,,대기,,no,예약하고 갔는데도 오래 기다렸다고 적었다. 누구와 왜 갔는지는 글에 없다.,borigunbbang,2026-11-13
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
  - 값이 하나인 키는 비공개 층의 값을 쓴다.
  - 값이 목록인 키는 두 목록을 합치고 겹치는 값은 하나만 남긴다. 비공개 층으로 목록의 값을 지울 수는 없다.
  - 비공개 층으로 값을 지우거나(`null`) 값의 종류를 바꿀 수는 없다 (숫자를 글자로, 목록을 값 하나로 바꾸는 것). 그런 층은 합치지 않고 오류로 본다.
  - 비공개 층에도 `format_version` 과 `persona_id` 를 적는다. `persona_id` 가 없거나 공개 층과 다르면 오류다.
  - **흔적**: 엔진은 비공개 층 때문에 달라진 키를 합친 결과의 `overridden_by_private` 목록에 모두 적는다.
    값이 바뀐 키, 새로 생긴 키, 값이 더해진 목록이 여기에 든다 (예: `budget.max`, `evidence.preferences.refs`).
    이 목록이 비어 있으면 합친 결과는 공개 층과 같다. 비공개 층이 없으면 빈 목록이다.
    기본 데이터로 돌릴 때는 요청(9절)의 `persona` 에서 이 목록을 빼지 않는다. 저장된 응답이 어느 자료로 돌린 것인지 알아보는 표시다.
  - 근거가 어느 층에서 왔는지는 후기 번호의 머리글자(`R`, `P`)로 안다.
  - 코드에서는 `engine.formats.merged_persona` 로 합친다. 합친 결과가 이 절의 형식에 맞는지도 함께 본다.
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
- **조식은 묶음에 넣지 않는다** (11-13 결정). 조식은 고를 업장이 하나뿐이라 페르소나의 선택을 볼 것이 없다. 집계 파일의 조식 매출은 보정의 대조에서 뺀다.
- **투숙 여부는 묶음에 넣지 않는다** (11-13 결정). 묶음의 조건은 `stay` 를 `null` 로 둔다. 기본 데이터에 투숙 여부가 없어 투숙객과 비투숙 방문객의 비율을 낼 수 없기 때문이다.
  투숙 여부는 화면에서 조건을 직접 넣어 한 번 돌릴 때와, 투숙객 전용 프로모션을 시험할 때만 쓴다.
- **달**: 묶음의 조건은 `month` 를 `null` 로 둔다. 일 년 전체로 본다는 뜻이고, 일부 달에만 파는 업장과 상품은 후보에 넣되 몫으로 센다 (10.2절의 `counted_share`).
  화면에서 한 번만 돌리거나 검증 사례를 넣을 때는 `month` 를 적을 수 있다. 그러면 엔진이 파는 달이 아닌 업장과 상품을 후보에서 뺀다.
- `manual-` 로 시작하는 `condition_id` 는 화면에서 직접 넣은 조건에만 쓴다 (10.2절). 묶음의 조건에는 쓰지 않는다.
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
- `change_price_pct` 의 바뀐 가격은 가격 × (100 + `pct`) ÷ 100 을 원 단위로 반올림한 값이다. 바뀐 폭을 먼저 반올림해서 더하거나 빼지 않는다.
  그렇게 하면 내릴 때 1원 어긋난다 (15원을 10% 내리면 14원이다). 코드에서는 `engine.formats.change_price` 를 쓴다.

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

한 줄은 한 달 동안 "그 고객군이 그 상품을 그 조건에서 산 것"의 합이다. 일 년 전체로 볼 때는 엔진이 달을 더한다.

| 열 | 뜻 | 비고 |
|---|---|---|
| `customer_group` | 고객군 | 기본 데이터의 값 그대로 |
| `venue_id`, `product_id` | 업장, 상품 | 업장 정의(3절)의 식별자로 바꿔 적는다 |
| `occasion` | 이용 상황 | 코드 값 |
| `meal` | 끼니 | 상품으로 알 수 없으면 빈 칸. 그러면 6절의 `assumed_splits` 로 나눈다 |
| `day_type` | 평일·주말 | 기본 데이터의 날짜로 정한다. 공휴일은 한국천문연구원 특일 정보(공공데이터포털)를 따르고, 대체공휴일도 주말로 본다 |
| `month` | 달 (1 ~ 12) | 기본 데이터의 날짜로 정한다. 일부 달에만 파는 상품과 연중에 가격이 바뀌는 상품을 가려 보려고 달마다 따로 적는다 |
| `unit` | 판매 단위 | 업장 정의(3절)에 적은 단위 이름으로 적는다. 기본 데이터의 단위 이름을 그대로 옮기지 않는다 (예: 기본 데이터의 `인` 은 업장 정의의 `1인`) |
| `quantity` | 팔린 수량의 합 | |
| `paid` | 고객이 낸 금액의 합 (세금 포함) | 가격이 `null` 인 상품의 단가를 `paid` ÷ `quantity` 로 채운다 (3절) |
| `revenue_net` | 세금을 뺀 매출의 합 | `paid` ÷ 1.1 이다. 줄마다 반올림한 값을 더한 것이라 조금 어긋날 수 있다 |
| `price_unconfirmed` | 기본 데이터가 가격을 확인하지 못했다고 표시한 줄이면 `Y`, 아니면 `N` | 이 열은 빈 칸을 쓰지 않는다. `Y` 면 화면에서 `unknown` 등급으로 보여 준다 |

- 기본 데이터의 업장 이름·상품 번호를 `venue_id`·`product_id` 로 바꾸는 표는 `private/base/map.json` 에 둔다. 기본 데이터의 이름이 들어 있으므로 저장소에 올리지 않는다.
- 함께 두는 `private/base/meta.json` 에 기준 기간, 만든 날, 줄 수, 식별자로 바꾸지 못한 줄 수를 적는다.
- **가상 예시**: `data/samples/base_summary.csv` 는 같은 열을 가진 지어낸 값이다. 기본 데이터의 수치를 따오지 않는다. 키나 기본 데이터가 없는 PC 는 이 파일로 돌린다.

엔진은 이 파일에서 아래를 계산한다.

| 계산하는 값 | 쓰는 곳 |
|---|---|
| 고객군마다 업장별 매출 비중 | 보정의 대조 (PRD 6.5절), 페르소나의 `base_profile` |
| 고객군마다 방문 조건 묶음의 비율 | 가중 합산 (PRD 7.2절) |
| 고객군의 다이닝 매출 합 | 고객군 배수 (PRD 7.2절). 다이닝의 범위는 기본 데이터에서 사업부문이 호텔 다이닝인 8개 업장이다 |
| 고객군과 이용 상황마다 매출이 가장 큰 업장 | 검증의 단순 기준 (PRD 6.6절) |

예시 (지어낸 값이다)

```csv
customer_group,venue_id,product_id,occasion,meal,day_type,month,unit,quantity,paid,revenue_net,price_unconfirmed
가족·친족,geumryong,course-a,meal,,weekday,5,1인,300,45000000,40909091,N
가족·친족,geumryong,course-a,meal,,weekend,5,1인,500,75000000,68181818,N
가족·친족,geumryong,course-b,meal,dinner,weekend,5,1인,120,24000000,21818182,N
```

## 9. 선택 요청과 응답

엔진은 이 한 가지 형식으로만 LLM 을 부른다 (PRD 7.3절). 공급자마다 다른 부분은 엔진 안쪽에서 감춘다.
프롬프트의 문장은 페르소나 담당이 쓰고(`personas/prompts/` 에 둔다), 요청과 응답의 모양은 여기서 정한다.

**요청** — 엔진이 만든다.

| 키 | 뜻 |
|---|---|
| `prompt_version` | 프롬프트의 판 이름. 프롬프트를 고치면 바꾼다 |
| `scenario_id` | 어느 상황인가 |
| `persona` | 두 층을 합친 페르소나. 기본 데이터로 돌릴 때는 엔진이 붙인 `base_profile` 과, 비공개 층의 흔적 `overridden_by_private` (5절)가 들어 있다. 가상 예시로 돌릴 때는 둘 다 없거나 비어 있다 |
| `condition` | 이번 방문 조건. 6절의 조건에 `adults`, `children`, `budget`, `purpose`, `party` 를 더한 것. `purpose` 와 `party` 는 검증할 때 후기의 라벨을 넣고 (후기에 비어 있으면 `null`), 다른 때는 `null` 이다 |
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
  그래서 `max` 를 넘는 주문이 든 요청은 형식에 어긋난 요청이다.

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
- `addons` 의 상품이 그 업장의 `addons` 에 있고 수량이 0 ~ `qty_max` 다. 같은 상품을 두 번 적지 않는다.
- 라벨이 모두 `vocab` 에 있다.
- `rejected` 에 고르지 않은 후보가 빠짐없이 한 번씩 있다. 고른 업장과 후보에 없는 업장은 `rejected` 에 없다.
  "이용하지 않음"을 골랐으면 후보 모두가 `rejected` 에 있다.
- `used_attributes` 가 페르소나에 실제로 있는 속성이다.
- 원장에 적을 금액을 업장 정의의 가격과 프로모션 규칙으로 다시 계산했을 때, 고른 주문의 `total` 과 같다. 추가 상품은 따로 계산해 더한다.

마지막 항목을 뺀 나머지는 `engine.formats.problems_in_response` 가 본다. 마지막 항목은 업장 정의가 있어야 해서 엔진이 따로 본다.

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

- 실행 하나의 폴더에는 위의 파일만 둔다. 검증 결과는 떼어 둔 후기로 잰 것이라 `private/runs/` 의 실행에만 있고, `engine/samples/runs/` 에는 두지 않는다.
- 이 파일들은 이름을 바꾸거나 다른 폴더로 옮겨도 실행 결과다. 형식 검사는 내용으로 알아보고, 위 표의 자리 밖에 있으면 오류로 본다 (11절).

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

- 묶음의 조건으로 돌린 실행은 `weights` 에 페르소나마다의 가중치와, 고객군과 조건마다의 비율이 빠짐없이 있어야 한다. 없으면 원장의 `represented` 를 확인할 수 없다.
  화면에서 조건을 직접 넣어 돌린 방문(`manual-`)에는 가중치가 없다.
- 기준이 아닌 상황의 `weights` 는 `weights_from` 에 적은 기준 상황의 값과 같다. 가중치는 기준 상황에서 한 번 정하고 그대로 쓴다 (PRD 7.2절).
- 가상 예시로 돌린 실행(`data_mode` 가 `sample`)의 `grades` 에는 `internal` 을 쓰지 않는다. 지어낸 값에서 낸 가중치의 등급은 `assumption` 이다.
- `counts` 는 원장과 맞아야 한다: `visits` 는 원장의 방문 수, `failed` 는 그중 실패한 방문 수다.
  끝까지 돌린 실행(`status` 가 `ok`)의 원장에는 `persona_ids` × `condition_ids` 마다 방문이 하나씩 있다.

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
    "model": "claude-opus-5-5",
    "prompt_version": "p1",
    "calls_new": 1,
    "calls_replayed": 0,
    "call_limit": 200,
    "stopped_by_limit": false
  },
  "base_profile_mode": "none",
  "inputs": {
    "venues": "0000000000000000",
    "personas": "0000000000000000",
    "conditions": "0000000000000000",
    "scenario": "0000000000000000",
    "summary": "0000000000000000"
  },
  "weights": {
    "group_multiplier": {"가족·친족": 240.0},
    "persona_weight": {"family-elders": 120.0},
    "condition_ratio": {"가족·친족": {"meal-dinner-weekend": 1.0}},
    "grades": {
      "group_multiplier": "assumption",
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
- **방문 하나의 몫은 더해서 1 이다.** 한 방문에서 고른 줄들은 `counted_share` 가 같다. 그 값이 1 이면 "이용하지 않음" 줄이 없고,
  1 보다 작으면 위의 줄이 꼭 하나 있다. "이용하지 않음"을 고른 방문은 `counted_share` 가 1 인 줄 하나다.
  몫은 방문이 어디로 갔는지를 세는 값이라 방문에 하나다. 그래서 엔진은 주문 하나에 파는 달이 서로 다른 상품을 함께 넣지 않고,
  추가 상품의 줄에도 고른 주문과 같은 몫을 적는다.
- 모든 합계는 이 원장에서 낸다. 업장별 가상 매출은 `weighted_revenue` 를 업장별로 더한 값이다. 합계에는 `status` 가 `ok` 인 줄만 넣는다.
- **실패한 방문은 줄 하나로만 남긴다.** `status` 는 `failed`, `fail_reason` 에 이유, `choice_kind` 는 `none`, 업장·상품은 빈 칸, 수량과 금액은 모두 0 이다.
  한 방문에 `ok` 인 줄과 `failed` 인 줄을 섞지 않는다. `fail_reason` 은 실패한 줄에만 적는다.
- **원장은 저장된 응답에서 나온 것이어야 한다.**
  - 업장을 고른 줄에는 `request_hash` 가 반드시 있다. 업장을 고르는 것은 LLM 의 응답뿐이기 때문이다.
    후보가 하나도 없어 엔진이 응답 없이 "이용하지 않음"으로 정한 방문만 `llm_call` 과 `request_hash` 를 함께 비운다 (둘은 늘 함께 있거나 함께 비어 있다).
  - 한 방문의 줄들은 `request_hash` 가 가리키는 저장된 응답(10.3절)과 같아야 한다:
    요청의 페르소나와 조건, 응답이 고른 업장, 고른 주문의 줄(상품, 수량, 단위, 단가, 할인, 금액), 고른 추가 상품(상품, 수량, 단위, 단가), 이유.
    손으로 고친 원장을 걸러 내려는 것이다. 위의 "파는 달이 아님" 줄은 이유가 따로라 이유를 견주지 않는다.
- 아래 예시의 두 줄은 서로 다른 실행의 원장에서 한 줄씩 가져온 것이다. 원장 파일 하나에는 실행 하나의 줄만 들어간다.

```csv
run_id,scenario_id,visit_id,persona_id,customer_group,condition_id,choice_kind,venue_id,product_id,quantity,unit,list_price,discount,paid,revenue_net,represented,counted_share,weighted_revenue,reason_labels,reason_text,used_attributes,llm_call,request_hash,status,fail_reason
20261117-101500-baseline,baseline,family-elders__meal-dinner-weekend,family-elders,가족·친족,meal-dinner-weekend,walkerhill,geumryong,course-a,4,1인,150000,0,600000,545455,120.0,1.0,65454600,별실;주차·접근,어르신을 모시는 자리라 별실이 있고 차로 오기 편한 곳을 골랐다.,visit.purposes;preferences.needs,new,3048cd02fff58366,ok,
20261117-103000-competitor-chinese-discount,competitor-chinese-discount,family-elders__meal-dinner-weekend,family-elders,가족·친족,meal-dinner-weekend,competitor,examplehotel-chinese,course,4,1인,140000,56000,504000,0,120.0,1.0,0,혜택·할인,할인 폭이 커서 이번에는 다른 호텔로 갔다.,buying.price_sensitivity,new,ee5893fa9739d0ca,ok,
```

### 10.3 저장된 LLM 응답 `llm/<request_hash>.json`

| 키 | 뜻 |
|---|---|
| `format_version` | 지금은 `1` |
| `request_hash` | 공급자, 모델, 9절의 요청 전체를 한데 묶어 낸 해시. 하나라도 다르면 다른 파일이다 |
| `provider`, `model`, `created_at` | 누가 언제 답했나 |
| `request`, `response` | 9절의 요청과 응답 그대로 |
| `raw_text` | LLM 이 돌려준 글 그대로 |
| `usage` | `input_tokens`, `output_tokens` |

- **해시를 내는 법**: `{"provider": …, "model": …, "request": …}` 를 키를 정렬하고 공백 없이 적은 JSON 으로 바꾼 뒤, 그 글의 SHA-256 에서 앞 16글자를 쓴다.
  직접 계산하지 말고 `engine.formats.compute_request_hash` 를 쓴다. PC 가 달라도 같은 요청이면 같은 값이 나온다.
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
    "thebuffet": {"n": 3, "enough": false, "venue_match": null, "venue_match_baseline": null, "reason_match": null, "reason_match_baseline": null}
  }
}
```

값은 비율이 아니라 건수다 (`n` 건 가운데 몇 건). `enough` 가 `false` 인 업장은 화면에 "검증 건수 부족"으로 보여 준다.

**후기 한 건마다의 결과** `validation_reviews.csv`

| 열 | 뜻 |
|---|---|
| `review_id`, `venue_id`, `customer_group` | 떼어 둔 후기 |
| `persona_id` | 돌린 페르소나. 그 고객군에 페르소나가 둘이면 후기의 `purpose`, `party` 가 더 많이 겹치는 쪽, 같으면 몫이 큰 쪽 (PRD 6.6절). 후기에 비어 있는 칸은 겹치지 않는 것으로 센다 |
| `occasion`, `meal`, `day_type` | 돌린 조건. 후기에 끼니나 요일이 비어 있으면 그 페르소나의 `visit.meals`, `visit.day_types` 의 첫 값을 쓴다 |
| `chosen_venue_id` | 페르소나가 고른 곳. "이용하지 않음"이면 빈 칸 |
| `venue_match`, `reason_match` | 업장이 같은가, 이유 라벨이 하나 이상 겹치는가 (`Y`, `N`) |
| `baseline_venue_id`, `baseline_venue_match`, `baseline_reason_match` | 단순 기준이 고른 곳과 그 결과 |
| `skipped` | 돌리지 못한 이유. 고객군이 비어 있거나 그 고객군에 페르소나가 없으면 적는다. 이런 후기는 `n` 에서 뺀다 |

## 11. 형식이 맞는지 볼 것

아래를 검사하는 도구가 `tools/check_formats.py` 에 있다. 자동 검사도 PR 마다 이 도구를 돌린다.

```powershell
uv run python -m tools.check_formats            # 저장소의 데이터 파일을 검사한다
uv run python -m tools.check_formats --strict   # 다 만든 뒤의 기준으로 검사한다
```

- 결과는 "오류"와 "주의" 두 가지다. 오류가 있으면 자동 검사가 실패한다.
- "주의"는 아직 덜 만든 것일 수 있는 항목이다. 한 고객군의 몫을 더한 값이 1 보다 작을 때, 워커힐 업장에 경쟁 업장이 아직 없을 때,
  워커힐 업장의 `hours` 가 `null` 일 때, CSV 에 BOM 이 없을 때 나온다. `--strict` 를 주면 주의도 오류로 본다. 통합 검증(T23) 때는 `--strict` 로 통과해야 한다.

**파일의 모양** — 데이터 폴더의 파일을 형식마다 본다.

- JSON 파일이 읽히고 `format_version` 이 있다. 값의 종류가 맞다 (2절의 "JSON 의 값". 따옴표로 감싼 숫자는 오류다).
- 코드 값이 2절의 표에 있는 값이다.
- 다른 파일을 가리키는 식별자가 실제로 있다: 경쟁 업장의 `competes_with`, 페르소나의 `compares_with`, 상황의 `venue_id`·`product_id`, 후기의 `venue_id`.
- 상품의 `occasion` 이 업장의 `occasions` 안에 있다. 워커힐 업장마다 경쟁 업장이 하나 이상 있다.
- 업장 정의의 모든 `source_id` 가 `sources` 에 있고 `checked_on` 이 있다.
- 라벨(방문 목적, 동행, 고른 이유, 걸린 점, 고객군)이 값 목록에 있다. 후기 라벨의 방문 목적과 동행은 비어 있어도 된다.
- 후기 라벨의 줄마다 근거가 되는 칸이 하나 이상 있다 (4.1절). `ordered` 와 `compared_with` 의 `이름:` 뒤에는 이름이 있다.
- 페르소나의 `evidence` 에 묶음 일곱 개가 모두 있고, 한 고객군의 `share_in_group.value` 를 더하면 1 이다.
- 묶음의 조건은 `month` 와 `stay` 가 `null` 이고 조식 조건이 없다. 상황의 `our_price`·`our_promo` 는 워커힐 업장만, `competitor` 는 경쟁 업장만 바꾼다.
- `engine/samples/runs/` 의 실행 기록은 모두 `data_mode` 가 `sample` 이다. 가중치가 빠짐없이 있고 등급에 `internal` 이 없다.
  원장의 방문 수가 실행 기록과 맞고, 원장이 저장된 응답과 같다 (10절).
- 데이터 폴더에 1절의 표에 없는 파일이나 폴더가 없다. 확장자는 소문자다. (빈 폴더를 깃에 남기는 `.gitkeep` 은 둘 수 있다.)

**올리면 안 되는 것** — 깃에 올라갈 수 있는 **모든 파일**을 훑는다. 확장자, 크기, 글자 인코딩, 폴더의 깊이를 가리지 않는다.
깃이 무시하는 것(맨 위의 `private/`, `.env`, `.venv/` 같은 것)만 건너뛴다.

- 어느 파일에도 `P-` 나 `H-` 로 시작하는 후기 번호가 없다. 예시를 적어도 되는 곳은 이 문서와 테스트 코드(`tests/` 의 `.py`)뿐이다.
- 기본 데이터로 돌린 실행 기록(`data_mode` 가 `private`)이 없다. JSON 안에 든 것도, 문서에 글로 붙여 넣은 것도 본다.
  코드나 안내 문서가 이 값을 설명하는 것은 막지 않는다 (실행 기록의 다른 키가 함께 있을 때만 실행 기록으로 본다).
  글로 붙여 넣은 것을 찾는 검사는 후기 번호와 같이 이 문서와 테스트 코드를 예외로 둔다.
- JSON 어디에도 `base_profile` 과 `overridden_by_private` 에 값이 없다 (키가 없거나 비어 있다). 둘 다 기본 데이터로 돌린 결과에만 값이 있다.
- 자리가 정해진 파일이 그 자리 밖에 없다. 파일의 이름이 아니라 **내용으로** 알아본다:
  후기 라벨, 가상 예시 값과 같은 열의 파일, 소비 원장, 실행 기록, 저장된 응답, 보정의 대조 결과.
  - 표는 열 이름으로 알아본다: CSV·TSV 의 첫 줄, 글 파일(`.txt`)의 첫 줄이 여러 칸으로 나뉠 때 그 칸들, 마크다운 표의 머리글.
  - JSON 은 키로 알아본다: 맨 위뿐 아니라 안쪽의 묶음을 모두 본다. 응답 여럿을 목록 하나에 모은 파일, 한 줄에 하나씩 적은 `.jsonl`, 표를 JSON 으로 바꾼 파일도 같다.
- 저장소 어디에도 둘 수 없는 것이 없다.
  - 후기 주소 목록: 주소를 담는 열(`url`, `link`, `주소`, `링크`)과 후기를 가리키는 열(`review_id`, `source_kind`, `dropped`)이 함께 있는 표나 JSON.
    4.3절의 세 파일 이름도 쓸 수 없다. 주소 열만 있는 출처 목록은 막지 않는다.
  - 검증 결과.
  - 기본 데이터와 그 일부: 금액을 담는 열 이름(`순매출`, `총결제액`) 가운데 하나라도 든 표나 JSON, 기본 데이터의 파일 이름이 든 파일.
    집계해서 열 이름 뒤에 말이 붙은 것도 본다 (마크다운 표는 문서가 그 열을 설명할 수 있어, 머리글이 그 이름과 똑같을 때만 본다).
    지어낸 값의 표라면 열 이름을 이 문서의 영어 이름(`revenue_net`)으로 적는다.
- 후기 라벨에 주소가 적혀 있지 않다. `holdout` 이라는 폴더에 데이터 파일이 없다.
- 맨 위가 아닌 곳에 `private` 라는 폴더가 없다. 깃이 무시하는 것은 맨 위의 `private/` 뿐이라, 다른 곳의 것은 그대로 올라간다. 이름은 소문자로 쓴다.
- 안을 볼 수 없는 데이터 파일(엑셀, parquet, 묶은 파일)이 없다. 5MB 를 넘는 CSV·JSON 이 없다. CSV·JSON 은 UTF-8 이다.

**이 도구가 보지 못하는 것** — 이것은 사람이 지킨다 (`CLAUDE.md` 의 "비밀값과 공개 저장소").

- 지어낸 값이라고 적은 파일의 값이 정말 지어낸 것인지. 문서에 풀어 쓴 수치. 발표 자료와 그림, 노트북의 출력.
- 본문이 있는 후기에 요약(`summary`)을 썼는지 (4.1절).
- 열 이름을 바꾼 표: 다른 이름의 열에 담은 기본 데이터의 금액, 약속과 다른 열 이름의 주소 목록.
- 번호도 주소도 없이 옮겨 적은 후기의 문장.

**테스트의 예시 묶음** — 테스트에 쓸 예시 파일을 더할 때는 `tests/fixtures/<이름>/` 아래에 저장소와 같은 폴더 모양으로 둔다.
그 안에서는 위의 자리 규칙을 그 묶음 안의 경로로 본다. 대신 그 묶음도 저장소와 같은 형식 검사를 받는다
(실행 결과에는 실행 기록이 있어야 하고, 가상 예시로 돌린 것이어야 한다). `tests/fixtures/example/` 을 베껴서 고치면 된다.

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

- [x] 평일과 주말을 나눌 때 공휴일을 어느 달력으로 정할지 (11-13, 한국천문연구원 특일 정보(공공데이터포털). 주말은 토·일·공휴일이고 대체공휴일도 든다. 업장 데이터 담당의 제안을 팀장이 받아들임)
- [x] 폴더 이름의 확정 (11-13, 팀장이 제안대로 확정함. `STRUCTURE.md` 의 폴더 표)
- [x] 방문 조건 묶음에 조식과 투숙 여부를 넣을지 (11-13, 둘 다 넣지 않는다. 6절)
- [ ] `assumed_splits` 의 값 (엔진 담당)
- [ ] 기본 데이터에서 나온 값을 LLM 에 어떻게 보낼지, 곧 `base_profile_mode` 의 기본값 (PRD 17절, 엔진 담당)
- [ ] 라벨 값 목록의 첫 판 (11-13, 페르소나 담당)
- [ ] 경쟁 업장의 `venue_id` (업장 데이터 담당)
- [ ] 추가 상품(`addons`)에 프로모션 할인을 적용할지 (엔진 담당, T04). 요청의 추가 상품에는 할인이 적혀 있지 않아,
  지금은 형식 검사가 추가 상품 줄의 할인을 저장된 응답과 견주지 못한다. 정하면 9절과 10.2절에 적고 검사에 넣는다.
- [x] 형식을 검사하는 도구 (11-13, `tools/check_formats.py` 를 만들어 예시 파일 한 벌이 `--strict` 로 통과하는 것을 확인함)
