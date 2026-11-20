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
| 6.1 | 결정 상수 | `engine/constants.json` | 엔진 (페르소나 전체에 걸린 값은 페르소나가 정한다) | 엔진, 화면 | 저장소 |
| 6.1 | 집계 파일 옆의 상수 파일 (없어도 된다) | `private/base/summary_constants.json` | 업장 데이터 | 엔진 | `private/`. 가상 예시는 `data/samples/base_summary_constants.json` |
| 6.1 | 추정한 상수 파일 (업장 상수. 없어도 된다) | `private/base/estimated_constants.json` | 엔진 (`python -m engine.estimate`) | 엔진, 화면 | `private/`. 가상 예시는 `data/samples/base_estimated_constants.json` |
| 7 | 상황 정의 | `scenarios/<scenario_id>.json` | 화면 | 엔진 | 저장소 |
| 8 | 기본 데이터 집계 파일 | `private/base/summary.csv` | 업장 데이터 | 엔진, 페르소나 | `private/`. 가상 예시는 `data/samples/base_summary.csv` |
| 9 | 선택 요청과 응답 | 파일이 아니다. 엔진이 LLM 을 부를 때의 형식이다 | 엔진(요청), 페르소나(프롬프트) | 엔진 | — |
| 10 | 실행 결과 | `private/runs/<run_id>/` | 엔진 | 화면, 페르소나 | `private/`. 가상 예시로 만든 것은 `engine/samples/runs/` (깃이 무시한다. 올리는 예시는 `tests/fixtures/<이름>/engine/samples/runs/`) |
| 10.6 | 매출 변화 나누기 | `private/runs/<run_id>/changes.json` (상황 실행만) | 엔진 | 화면 | 실행 결과와 같다 (10절) |

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
| 근거 등급 | `grade` | `internal` 내부 매출 자료, `official` 공식 사실, `literature` 학술 자료, `statistic` 공공 통계, `review` 후기에서 관찰, `industry` 업계 보고서, `article` 기사, `assumption` 설계 가정, `unknown` 미확인 |
| 상황의 종류 | `kind` | `baseline` 기준, `our_price` 우리 가격·구성 변경, `our_promo` 우리 프로모션, `competitor` 경쟁 호텔의 변경 |
| 고른 곳 | `choice_kind` | `walkerhill` 워커힐 업장, `competitor` 경쟁 업장, `none` 이용하지 않음 |
| 수량 규칙 | `qty_rule` | `per_person` 사람 수만큼, `per_serves` 한 단위가 여러 명분, `choice` 고객이 수량을 정함 (3절) |
| 대상 | `audience` | `adult` 성인, `child` 어린이, `all` 구분 없음 |
| 출처 종류 | `source_kind` | `blog` 블로그, `map` 지도 서비스, `booking` 예약 서비스, `reference` 받은 참고 소스 |
| 낮음·보통·높음 | `price_sensitivity`, `wait_tolerance` | `low`, `mid`, `high` |

**근거 등급의 세기** (11-19 wilstein91 결정, T210. `engine/weights.py` 의 `GRADE_STRENGTH`) — 값 여럿을 합쳐 낸 값의 등급은 가장 약한 것이다.

- 세기: `internal`·`official` (3) > `literature`·`statistic`·`review` (2) > `industry`·`article` (1.5) > `assumption` (1) > `unknown` (0).
  우리 업장을 직접 확인한 것 > 공개된 관찰 > 수치나 방법이 약한 공개 자료 > 설계 가정 > 미확인 순이다. 세기가 같으면 앞에 둔 값의 등급을 쓴다.
- 새 등급(`literature`, `statistic`, `industry`, `article`)은 **그 대상을 직접 다룬 자료**에서 온 값에 쓴다. 예: 더뷔페의 예약 마감을 전한 기사.
- 다른 곳에서 잰 범위를 빌려 와 우리 값으로 쓰는 것(가격 탄력성의 범위, 가격 민감도의 문턱, 예산의 퍼짐 같은 것)은 `assumption` 으로 적고 `sources` 에 빌려 온 자료를 하나씩 종류와 함께 적는다 (6.1절).
  PRD 5.3절·12절대로 4단계의 반응 크기는 설계 가정이다. 미국 외식 전반의 범위가 워커힐 다이닝에 그대로 맞는다는 근거가 없어, 등급만 보고 직접 잰 값으로 읽히지 않게 한다
  (11-19 songyee-ai 지적으로 고침. 처음에는 "가져온 값은 `assumption` 으로 적지 않는다"였다).

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
  가상 예시로 돌릴 때는 가상 예시 값에서 같은 방법으로 채운다 (등급은 `assumption`). 어느 쪽에도 없으면 그 상품을 후보에서 빼고 실행 기록에 남긴다.
  - 그 상품의 모든 줄(고객군, 달, 조건)의 `paid` 합 ÷ `quantity` 합을 **백 원 단위로 반올림**한다 (11-15 팀장이 정함).
    채운 단가는 후보의 가격으로 LLM 에 가므로(9절), 기본 데이터의 평균 단가가 원 단위 그대로 LLM 과 저장된 응답에 남지 않게 한다.
    반올림해 0 원이 되면 채우지 않는다.
  - 그 상품의 줄에 업장 정의와 다른 단위(`unit`)가 있으면 엔진이 멈춘다. 단위가 다른 수량을 더하면 단가가 틀린다 (8절: 집계 파일의 `unit` 은 업장 정의의 단위로 적는다).
  - `paid` 는 할인이 빠진 금액이라, 채운 단가에 프로모션 할인이 걸리면 할인이 한 번 더 들어간다. 가격이 빈 상품에는 프로모션을 걸지 않는다.
  - 채운 상품의 가격 표기는 `included` 다 (`paid` 가 세금이 든 금액이다). 업장 정의 파일은 바뀌지 않는다. 엔진이 읽은 사본에만 채운다.
  - 상황(7절)을 먼저 적용하고 그 뒤에 채운다. 그래서 `change_price_pct` 는 채운 단가를 바꾸지 않는다. 가격이 빈 상품의 값을 정하려면 `set_price` 를 쓴다.
  - 채운 상품과 채우지 못한 상품은 실행 기록의 `filled_products`, `skipped_products` 에 남는다 (10.1절).

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

- 할인은 엔진이 주문(9절의 `options`)의 줄에 넣는다 (`engine/promotions.py`). 주문 하나마다 따로 정한다.
- `discount_pct`: 적용되는 상품의 줄마다 수량 × 단가 × 퍼센트를 깎는다. 단가는 고객이 낼 금액(세금 포함)이고, 깎는 금액은 줄마다 원 단위로 반올림한다.
- `discount_amount`: 주문 한 번에 한 번만 깎는다. 적용되는 상품의 첫 줄에서 뺀다. 그 줄의 금액(수량 × 단가)보다 많이 깎지 않는다.
- `gift`: 금액은 바뀌지 않는다. LLM 에게 무엇을 주는지만 알려 준다.
- 할인이 둘 이상 해당하면 깎이는 금액이 가장 큰 것 하나만 적용한다. 깎이는 금액이 같으면 `promotions` 에 먼저 적힌 것이다.
  증정은 해당하는 것을 모두 알려 준다.
- 조건에 `stay` 가 적혀 있는데 방문 조건의 `stay` 가 `null` 이면 적용하지 않는다. 다른 조건 키도 같다.
  `party_min` 은 일행의 수(성인 + 어린이)와 견준다.
- `period` 는 방문 조건에 `month` 가 있을 때만 견준다. `month` 가 `null` 이면 기간을 보지 않고 적용한다.
  방문 조건의 달에는 연도가 없어 달만 본다: 기간이 그 달에 하루라도 걸치면 적용한다 (11-14 에 정함).
  예: `2026-12-20` ~ `2027-02-03` 은 12월, 1월, 2월의 방문에 적용한다.
- **추가 상품(9절의 `addons`)에는 할인을 적용하지 않는다** (11-16 회의에서 정함). 할인은 주문의 줄에만 넣는다.
  추가 상품에만 걸리는 프로모션은 업장 정의에 적어도 금액을 바꾸지 않는다 (9절의 `applied` 가 `false`).
  그래서 상품이 모두 추가 상품인 업장(포장·구매. 9절의 "주문이 없는 후보")에는 할인 프로모션이 효과가 없다. 그런 업장에 할인을 더하는 상황은 만들지 않는다.
  할인으로 나타내려던 프로모션이 기간 한정 메뉴처럼 정해진 가격의 상품이면, 할인 대신 상품으로 적는다 (7절의 `add_product`).

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
| `compared_with` | 견준 곳 | 경쟁 업장의 `venue_id`. 경쟁 업장의 후기에는 워커힐 업장의 `venue_id` 도 적는다 (11-19, T305). 후기의 업장 자신은 적지 않는다. 정의에 없는 곳이면 `이름:` 뒤에 한국어로 적는다 |
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

**파일로 받은 후기는 이 세 파일을 만들지 않는다** (11-16 정함). 수집 도구로 받은 표 파일에는 본문이 들어 있고 주소가 없다.
그런 후기는 주소 목록 대신 `private/evidence/` 의 나눈 기록(`split_log.csv`)과 정돈 표의 `raw_key` 로 어느 쪽인지 가리킨다 (`REVIEW_RULES.md` 5절·6절·12절).
이 절의 세 파일은 주소를 먼저 모으고 본문을 나중에 읽는 경우에만 쓴다. 열과 형식 검사는 바꾸지 않았다.

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
  엔진이 실행할 때 집계 파일(8절)에서 계산해 `base_profile` 로 붙인다 (아래 "기본 데이터의 요약").

**기본 데이터의 요약 `base_profile`** (11-15 에 정함. `engine/weights.py` 의 `base_profiles`)

기본 데이터로 돌릴 때 엔진이 요청(9절)의 `persona` 에 붙이는 그 고객군의 요약이다. 페르소나 파일에는 적지 않는다.
가상 예시로 돌릴 때는 붙이지 않는다. 어떻게 보낼지는 실행 기록의 `base_profile_mode` 다 (10.1절).

| 키 | 뜻 |
|---|---|
| `venue_share` | 워커힐 업장마다 그 고객군의 매출 비중 |
| `occasion_share` | 이용 상황(`meal`, `dessert`, `takeout`)마다 그 고객군의 매출 비중 |
| `day_type_share` | 평일·주말(`weekday`, `weekend`)마다 그 고객군의 매출 비중 |
| `top_products` | `venue_share` 에 있는 업장마다 그 고객군의 매출이 큰 상품의 `product_id` 를 큰 순서로 셋까지. 순위만 보낸다 |

- `bucketed` (기본): 비중을 `high`·`mid`·`low` 로 바꿔 보낸다. 고르게 나눴을 때의 몫(업장은 8곳이라 1/8, 이용 상황 1/3, 평일·주말 1/2)과 견줘
  1.5배 이상이면 `high`, 0.5배 이상이면 `mid`, 그보다 작으면 `low` 다. 이 기준은 설계 가정이다 (11-15 엔진 담당이 정함).
  예를 들어 한 고객군의 업장별 비중이 금룡 0.6, 더뷔페 0.3, 온달 0.1 이면 (지어낸 값이다) `{"geumryong": "high", "thebuffet": "high", "ondal": "mid"}` 다.
- `raw`: 비중을 소수 셋째 자리까지 그대로 보낸다. 내부 수치가 외부 LLM 과 저장된 응답에 남으므로 기본으로 쓰지 않는다.
- 매출이 없는 갈래는 적지 않는다. 집계 파일에 매출이 없는 고객군은 네 키가 모두 빈 묶음이다.
- 조식 매출은 넣지 않는다. 묶음에 조식이 없어(6절) 조식 매출이 다른 끼니의 선택을 끌어당기지 않게 한다.
- 집계 파일의 모든 업장과 조건을 본다. 돌리는 업장이나 조건을 골라도 요약이 같아야 요청이 같아 저장된 응답이 재생된다.
- 유형과 성별·연령 구성은 집계 파일에 없어 넣지 않는다.
- 프롬프트에 이 요약의 뜻을 적는다 (예시는 `tests/fixtures/example/personas/prompts/p1.md`). 응답의 `used_attributes` 에 `base_profile.venue_share` 처럼 적을 수 있다.

| 키 | 뜻 | 비고 |
|---|---|---|
| `persona_id`, `name` | 식별자, 짧은 이름 | |
| `customer_group` | 속한 고객군 | |
| `share_in_group` | 고객군 안의 몫: `value` (0 ~ 1), `grade`, `basis` | 한 고객군의 페르소나 몫을 더하면 1 이어야 한다. 사람 수가 아니라 방문(팀)의 비율이다: 후기 한 건을 방문 한 번으로 센다 (11-19, borigunbbang 확인. 엔진은 팀의 비율로 읽는다, T210) |
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
  계산하는 법은 10.1절의 "가중치를 내는 법"이다. 끼니가 빈 식사 줄은, 업장 정의의 파는 때로 끼니를 알 수 없을 때만
  `split_id` 가 `meal-lunch-dinner` 인 비율로 나눈다 (엔진이 이 이름으로 찾는다).
- **조식은 묶음에 넣지 않는다** (11-13 결정). 조식은 고를 업장이 하나뿐이라 페르소나의 선택을 볼 것이 없다. 집계 파일의 조식 매출은 보정의 대조에서 뺀다.
- **투숙 여부는 묶음에 넣지 않는다** (11-13 결정). 묶음의 조건은 `stay` 를 `null` 로 둔다. 기본 데이터에 투숙 여부가 없어 투숙객과 비투숙 방문객의 비율을 낼 수 없기 때문이다.
  투숙 여부는 화면에서 조건을 직접 넣어 한 번 돌릴 때와, 투숙객 전용 프로모션을 시험할 때만 쓴다.
- **달**: 묶음의 조건은 `month` 를 `null` 로 둔다. 일 년 전체로 본다는 뜻이고, 일부 달에만 파는 업장과 상품은 후보에 넣되 몫으로 센다 (10.2절의 `counted_share`).
  화면에서 한 번만 돌리거나 검증 사례를 넣을 때는 `month` 를 적을 수 있다. 그러면 엔진이 파는 달이 아닌 업장과 상품을 후보에서 뺀다.
  묶음을 한 달의 방문으로 돌리려면 묶음 파일을 고치지 않고 명령에 `--month` 를 적는다. 엔진이 조건마다 그 달을 붙인다 (10.1절의 "실행의 달").
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
      "parts": {"lunch": 0.5, "dinner": 0.5},
      "grade": "assumption",
      "decided_on": "2026-11-13",
      "note": "근거가 되는 자료가 없어 반반으로 둔다 (11-13 팀장이 정함). 금룡 후기 라벨 80건은 점심 41건, 저녁 39건이었다"
    }
  ]
}
```

### 6.1 결정 상수 `engine/constants.json`

(11-19 wilstein91 결정, T210. 읽는 코드는 `engine/constants.py`, 모델은 `engine/formats/constants.py`)
시뮬레이션 결과에 영향을 주는 엔진의 숫자를 값과 근거와 함께 이 파일 하나에 적는다. 엔진은 코드에 숫자를 두지 않고 이 파일의 값을 쓴다.

| 키 | 뜻 |
|---|---|
| `constant_id` | 상수의 식별자. 영어 소문자, 숫자, 하이픈. 파일 안에서 겹치지 않는다 |
| `name` | 사람이 읽는 이름 |
| `value` | 값. 숫자, 참·거짓, 범위(`{"min": .., "max": ..}`) 가운데 하나다 |
| `unit` | 값의 단위 (원, 개, 배, %p, 팀, 명). 참·거짓이면 `null` |
| `used_in` | 이 값을 쓰는 곳 (코드의 함수와 이 문서의 절) |
| `grade` | 근거 등급 (2절의 코드 값) |
| `sources` | 근거의 출처 자료 목록. 하나마다 `title`(자료 이름. 논문은 저자·연도·학술지, 기사·보고서는 매체와 날짜), `kind`(자료의 종류, 아래), `url`(원문 주소. 정확한 주소가 없으면 `null` 이고 아는 만큼은 `title` 에 적는다). 센 자료부터 적는다. 팀이 정한 값이면 빈 목록 (11-20, T214. 그 전에는 글 한 줄 `source` 였다) |
| `checked_on` | 출처를 확인한 날. 출처가 없으면 정한 날 |
| `note` | 왜 이 값인지, 누가 언제 정했는지 |
| `owner` | 이 값을 고치는 사람 (값을 정하는 사람) |
| `in_use` | 엔진이 지금 이 값을 쓰는가. 빠지면 `true`. 정해 두었지만 아직 쓰지 않는 값(다음 단계에서 쓸 값)은 `false` 이고 실행 기록에 남지 않는다 (10.1절) |

- **넣는 것**: 결과(고르는 후보, 가중치, 보정의 통과)를 바꾸는 숫자. 엔진이 쓰는 것(`in_use` 가 `true`)은 채운 단가의 반올림 단위, 기본 데이터의 요약에 적는 상품 수와 비중의 범주를 가르는 선,
  인원이 빈 포장·추가 상품 한 개의 팀 수·사람 수, 보정의 통과 기준 셋, 방문의 몫을 내는 날카로움 k (`share-sharpness-k`, 9절의 "점수와 몫". 11-20, T212)다.
- **업장 상수**(`share-venue-constant-<venue_id>`, T212)는 업장마다 하나씩 이 파일에 둔다. 값은 상수 추정으로 정하고 근거와 함께 적는다.
  적히지 않은 업장과 `in_use` 가 `false` 인 업장 상수는 1 로 본다 (쓰지 않는 값은 실행 기록에도 남지 않아, 형식 검사가 기록으로 몫을 다시 낼 때도 1 이다).
  k 와 업장 상수는 값이 바뀌면 해시가 바뀌어 기준 상황을 다시 돌려야 한다 (저장된 답을 재생하므로 LLM 은 부르지 않는다).
- **페르소나 전체에 걸린 상수**도 이 파일에 둔다. `personas/` 에 두지 않는다 (11-19 wilstein91 결정, T213). 지금은 진행 문서 T306 의 값이다:
  가격 민감도 등급마다의 문턱, 한 페르소나 안의 예산 퍼짐과 문턱 퍼짐, 가격 탄력성이 들어야 할 범위 둘. 모두 `in_use` 가 `false` 이고 `owner` 는 `borigunbbang` 이다.
  값은 페르소나 담당(borigunbbang)이 정하고, 바꿀 때는 "알릴 것"에 적어 엔진 담당에게 고쳐 달라고 한다 (11-19 wilstein91 결정, T213).
- **2단계(T212)**: 엔진이 페르소나의 가격 민감도 등급에 맞는 문턱을 이 파일에서 꺼내 요청에 넣는다. 프롬프트에는 그 숫자를 적지 않는다 (값은 이 파일 한 곳에만 둔다. 11-19 wilstein91 결정, T213).
- **범위 값**: 다른 곳에서 잰 범위를 빌려 온 값은 범위로 적는다 (예: 가격 민감도 낮음 15 ~ 20%, 가격 탄력성 −1.0 ~ −0.7). `min` 이 `max` 보다 크면 오류다.
  4단계(상수 추정)에서 범위 안의 값을 바꿔 가며 돌린다 (11-19 wilstein91 결정, T213).
- **넣지 않는 것**: 프로그램이 도는 데만 쓰는 숫자(호출 시간 제한, 호출 상한, 연달아 실패한 호출 수 같은 것)는 코드에 둔다.
  끼니를 알 수 없는 식사 매출을 나누는 비율은 6절의 `assumed_splits` 에 그대로 둔다 (실행 기록에는 결정 상수와 함께 남는다, 10.1절).
- **등급**: 2절의 코드 값을 쓴다. 그 대상을 직접 다룬 학술 자료, 공공 통계, 업계 보고서, 기사, 공식 발표에서 온 값은 그 등급으로 적고 `sources` 에 그 종류의 자료를 하나 이상 적는다 (형식 검사가 본다, 11절).
  팀이 정한 값은 `assumption` 이다. 다른 곳에서 잰 범위를 빌려 와 정한 값도 `assumption` 이고, 이때는 `sources` 에 빌려 온 자료를 적는다. 빌려 온 자료가 없으면 `sources` 는 빈 목록이다.
- **출처 자료의 종류**(`kind`, 11-20 wilstein91 결정, T214): `official`(공식), `literature`(학술 자료), `statistic`(공공 통계), `industry`(업계 보고서), `article`(기사), `measurement`(공개 도구로 직접 잰 값. 예: 지도 경로 서버로 잰 거리).
  앞의 다섯은 2절의 등급과 같은 뜻이다. 목록은 센 것부터 적는다: `official` > `literature` = `statistic` > `industry` = `article` > `measurement` (어기면 형식 오류다).
  화면은 `assumption` 이면서 출처가 있는 값을 "설계 가정 · 학술 자료, 기사"처럼 등급과 종류를 함께 보인다 (T130 ⑥).
- **고치는 사람**: 이 파일은 엔진 담당(wilstein91)의 것이고 공통 틀이다 (`STRUCTURE.md`). 값을 바꾸자는 제안은 "알릴 것"에 적는다.
  보정의 통과 기준 셋은 첫 대조(11-17) 뒤 한 번만 고칠 수 있다 (10.4절).
- **값을 바꾸면 기준 상황부터 다시 돌린다.** 엔진은 이 파일의 해시를 실행 기록의 `inputs.constants` 에 남기고, 기준 실행 뒤에 바뀌었으면 상황도 보정의 대조도 돌리지 않는다 (10.1절, 10.4절).
  해시는 결과를 바꾸는 부분(`constant_id`, `value`, `unit`, `in_use`)으로만 낸다. `sources`, `note`, `checked_on` 같은 근거와 설명만 고치면 해시가 그대로라 다시 돌리지 않아도 된다 (`engine/constants.py` 의 `values_hash`, 11-20 wilstein91 결정, T214).
- **읽는 곳**: 엔진 코드가 있는 저장소의 것을 읽는다. `--root` 로 다른 폴더의 자료를 돌려도 이 파일은 바뀌지 않는다 (엔진 코드와 같다).
  입력이라 `engine_commit` 의 `+dirty` 를 가를 때는 보지 않는다 (10.1절).

**집계 파일 옆의 상수 파일** (11-19 wilstein91 결정, T213) — 집계 파일(8절)을 만들 때 쓴 값(상품 한 개당 인원 같은 것)과 근거를 집계 파일 옆에 같은 모양(`ConstantsFile`)으로 적는다. 없어도 된다.

- 자리: 기본 데이터는 `private/base/summary_constants.json`, 가상 예시는 `data/samples/base_summary_constants.json` 이다. 기본 데이터의 값은 `private/` 에만 두고, 가상 예시에는 지어낸 값만 적는다.
- 주인은 업장 데이터 담당(hojitea-ui)이다. 집계 파일을 만드는 도구가 집계 파일과 함께 쓴다.
- 엔진은 돌린 데이터의 이 파일이 있으면 그 상수(`in_use` 가 `true` 인 것)를 모두 실행 기록의 `constants` 에 남긴다. `file` 은 저장소 맨 위에서 본 그 파일의 자리다 (10.1절).
  해시는 `inputs` 에 남기지 않는다.
- 가상 예시의 것은 형식 검사가 엔진의 것과 같은 규칙(출처)으로 본다 (11절).

**추정한 상수 파일** (11-20 wilstein91 결정, T212) — 업장 상수(`share-venue-constant-<venue_id>`, 9절의 "점수와 몫")를 기본 데이터의 업장 몫에 맞춰 추정한 값이다. 모양은 같다(`ConstantsFile`).

- 자리: 기본 데이터는 `private/base/estimated_constants.json`, 가상 예시는 `data/samples/base_estimated_constants.json` 이다. **기본 데이터로 추정한 값은 기본 데이터에서 계산한 값이라 `private/` 에만 둔다**
  (저장소의 `engine/constants.json` 에 옮겨 적지 않는다. `CLAUDE.md` 의 "비밀값과 공개 저장소").
- 만드는 것: `python -m engine.estimate --data private` (`engine/estimate.py`). 답을 받는 PC(엔진 담당)에서 추정하고, 다른 PC 는 답 폴더처럼 저장소 밖으로 받아 같은 자리에 둔다.
  받아 둔 답과 이 파일이 같으면 어느 PC 에서 돌려도 결과가 같다.
- 추정하는 법:
  - 점수를 받은 기준 실행(일 년 전체, 실패 없음, 모든 방문이 점수를 받음) 하나의 원장에서 방문마다 곳마다의 점수와 파는 달의 몫을 읽는다.
  - 잣대는 고객군마다 워커힐 업장의 **사람 수 몫, 모든 이용 상황**이다 (가중치와 같은 줄을 같은 몫으로 센다. `engine.weights.group_venue_people`).
    업장 상수는 "어디로 가나"를 고치는 값이라 사람 수로 맞춘다. "얼마를 시키나"는 보정의 대조(매출 비중, 10.4절)가 따로 본다.
  - 업장 상수는 **고객군과 상관없이 워커힐 업장마다 하나**다. 페르소나가 있는 고객군을 사람 수로 더한 몫에 맞춘다
    (상수 ← 상수 × 실제 몫 ÷ 시뮬레이션 몫을 몫이 같아질 때까지 되풀이. 선택 모형의 대안별 상수를 맞추는 흔한 방법). 고객군마다 남는 차이는 검증에 쓴다.
  - 경쟁 업장과 "이용하지 않음"은 상수를 정하지 않는다 (1). 기본 데이터에는 워커힐의 판매만 있어 밖으로 간 몫을 알 수 없다.
    그래서 워커힐 업장 상수 전체의 크기는 맞춘 몫으로 가중한 기하 평균이 1 이 되게 둔다 (워커힐과 밖 사이의 나뉨은 AI 의 판단 그대로).
  - 점수를 받은 기준 실행은 **저장소의 페르소나와 방문 조건을 모두 돌린 것**이어야 한다 (`--personas`, `--conditions` 로 일부만 돌린 시험 실행은 거절한다).
  - 실제 몫이 0 인데 AI 가 고르는 업장은 상수를 0.001 에 두고 맞추기에서 뺀다. 실제 몫은 있는데 점수를 받은 방문이 없는 업장은 맞추지 못하고 1 로 남는다 (명령이 알린다).
    대표하는 사람 수나 파는 달의 몫이 0 인 방문의 점수는 쓰지 않는다.
  - **맞추지 못하면(5000번 되풀이해도 몫이 같아지지 않으면) 파일을 쓰지 않고 멈춘다.** AI 가 거의 고르지 않는 업장의 실제 몫이 클 때 생긴다.
  - 날카로움 k 는 정하지 않는다. 업장 몫만으로는 k 가 정해지지 않는다 (11-20 실험). k 는 가격을 바꿨을 때 얼마나 옮기는지라 4단계의 가격 탄력성 범위로 맞춘다.
- 등급: 기본 데이터로 낸 값은 `internal`, 가상 예시로 낸 값은 `assumption` 이다. `note` 에 추정한 기준 실행과 k 를 적는다.
- 추정에 쓴 자료(같은 기준 실행, 같은 집계 파일)로 다시 맞았다고 하지 않는다 (PRD 12절). 명령이 보이는 "추정 전 / 추정 뒤" 차이는 맞춘 정도이지 검증이 아니다.
- 엔진은 돌린 데이터의 이 파일이 있으면 그 업장 상수를 몫에 쓰고, 실행 기록의 `constants` 에 남기며(`file` 은 그 파일의 자리), 해시를 `inputs.estimated` 에 남긴다 (파일이 있을 때만).
  기준 실행 뒤에 이 파일이 생기거나 바뀌면 상황도 보정의 대조도 돌지 않는다. 기준 상황을 다시 돌린다 (저장된 답을 재생한다).
- 이 파일에는 업장 상수만 둔다. `engine/constants.json` 에 같은 업장 상수가 있으면 엔진이 멈춘다.
- **기본 데이터로 점수를 묻는 판을 돌리는데 이 파일이 없으면 엔진이 멈춘다** (PC 마다 조용히 다른 상수로 돌지 않게). 상수 추정에 쓸 첫 기준 실행만 `--before-estimate` 로 업장 상수를 모두 1 로 돌린다.
  `--before-estimate` 는 파일이 아직 없을 때 기준 상황에만 쓴다 (파일이 있거나 기준이 아닌 상황이면 멈춘다). 다시 추정할 때는 있던 파일을 읽지 않고 점수에서 처음부터 맞춘다.
  점수를 묻지 않던 판(`p1` ~ `p3`)의 실행은 업장 상수를 쓰지 않아 멈추지 않는다.
- 가상 예시의 것은 형식 검사가 본다: 업장 상수만, 그 업장이 워커힐 업장 정의에 있고, 등급이 `internal` 이 아니다 (11절).

예시 — `engine/constants.json` 의 열일곱 개(엔진이 쓰는 아홉 개와 아직 쓰지 않는 여덟 개) 가운데 셋이다. 셋째는 아직 쓰지 않는 값이고, 빌려 온 자료가 학술 자료와 기사 둘이다.

```json
{
  "format_version": 1,
  "constants": [
    {
      "constant_id": "filled-price-unit",
      "name": "집계 파일로 채운 단가의 반올림 단위",
      "value": 100,
      "unit": "원",
      "used_in": "engine/weights.py 의 fill_prices (FORMATS 3절)",
      "grade": "assumption",
      "sources": [],
      "checked_on": "2026-11-15",
      "note": "채운 단가는 후보의 가격으로 LLM 에 가므로, 기본 데이터의 평균 단가가 원 단위 그대로 남지 않게 한다 (11-15 팀장이 정함)",
      "owner": "wilstein91"
    },
    {
      "constant_id": "calibration-max-diff-pp",
      "name": "보정 통과: 업장별 비중 차이의 한도",
      "value": 15,
      "unit": "%p",
      "used_in": "engine/calibration.py 의 compare (PRD 6.5절)",
      "grade": "assumption",
      "sources": [],
      "checked_on": "2026-11-17",
      "note": "첫 대조(11-17) 뒤 한 번만 고칠 수 있고, 고치면 이유를 진행 문서의 T18 절에 적는다. 돌릴 때마다 바꿔 가며 통과시키지 못하게 한다",
      "owner": "wilstein91"
    },
    {
      "constant_id": "price-sensitivity-threshold-high",
      "name": "가격 민감도 높음: 망설이기 시작하는 인상 폭",
      "value": 5,
      "unit": "%",
      "used_in": "아직 쓰지 않음. 2단계에서 엔진이 페르소나의 등급을 보고 요청에 넣는다 (T212)",
      "grade": "assumption",
      "sources": [
        {
          "title": "Raab 외 2009, Journal of Hospitality & Tourism Research 33(1):93-105",
          "kind": "literature",
          "url": "https://vtechworks.lib.vt.edu/handle/10919/97044"
        },
        {
          "title": "Toast 설문 (abc17news.com, 2026-11-16 게재)",
          "kind": "article",
          "url": null
        }
      ],
      "checked_on": "2026-11-19",
      "note": "평소 금액(budget.typical)보다 이만큼 넘게 비싸지면 망설이고, 같은 이용 상황의 더 싼 대안이 있으면 그쪽을 고른다 (T306 ①). 다른 곳에서 잰 범위를 빌려 와 정한 값이다",
      "owner": "borigunbbang",
      "in_use": false
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
- `set_price` 의 `price` 와 `change_price_pct` 가 바꾸는 값은 업장 정의의 `price` (출처에 표시된 가격)다. 가격 표기(`price_basis`)는 바꾸지 않는다.
- `change_price_pct` 의 `product_id` 가 `null` 이면 가격이 있는 모든 상품을 바꾼다. 가격이 비어 있는 상품 하나를 가리켜 퍼센트로 바꿀 수는 없다 (`set_price` 로 값을 정한다).

**엔진이 상황을 적용하는 법** (11-14 에 정함. `engine/scenarios.py`)

- 바꾸려는 업장, 상품, 프로모션이 없거나 더하려는 것이 이미 있으면 실행을 멈춘다. 적용하지 못한 채 돌리면 기준과 같은 결과가 조용히 나오기 때문이다.
  `change_price_pct` 로 업장의 모든 상품을 바꾸라고 했는데 가격이 있는 상품이 하나도 없을 때도 멈춘다.
  읽을 업장을 골라 돌릴 때(`--venues`)는 상황이 바꾸는 업장도 넣고, 기준 상황도 같은 업장으로 돌려 둔다
  (업장을 다르게 고르면 읽은 업장 정의가 기준 실행과 달라 10.1절의 검사가 `venues` 가 달라졌다며 막는다).
- 다 적용한 업장 정의도 3절의 규칙을 지켜야 한다 (예: 뺀 상품을 가리키는 프로모션이 남아 있으면 안 된다). 형식 검사도 엔진과 같은 코드로 적용해 본다.
- 기준이 아닌 상황은 기준 실행의 페르소나, 방문 조건, 가중치로 돌린다 (10.1절의 "기준이 아닌 상황을 돌리는 법").

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
| `people` | 그 수량으로 먹은 사람 수의 합 | 가중치의 기준이다 (10.1절의 "가중치를 내는 법"). 집계 파일을 만드는 쪽이 상품마다 정한 "단위당 인원"으로 낸다 (업장 데이터 담당). 업장 정의의 `serves` 로 내지 않는다. 사람 수로 셀 수 없는 상품만 빈 칸이다: 포장(피자 포장, 르파사주 바구니)과 추가 상품(예: 에이드 변경). 엔진은 빈 칸인 포장을 한 개 한 팀으로 보고, 빈 칸인 그 밖의 상품은 0 명으로 센다 (11-19, T210) |
| `paid` | 고객이 낸 금액의 합 (세금 포함) | 가격이 `null` 인 상품의 단가를 `paid` ÷ `quantity` 로 채운다 (3절) |
| `revenue_net` | 세금을 뺀 매출의 합 | `paid` ÷ 1.1 이다. 줄마다 반올림한 값을 더한 것이라 조금 어긋날 수 있다 |
| `price_unconfirmed` | 기본 데이터가 가격을 확인하지 못했다고 표시한 줄이면 `Y`, 아니면 `N` | 이 열은 빈 칸을 쓰지 않는다. `Y` 면 화면에서 `unknown` 등급으로 보여 준다 |

- 기본 데이터의 업장 이름·상품 번호를 `venue_id`·`product_id` 로 바꾸는 표는 `private/base/map.json` 에 둔다. 기본 데이터의 이름이 들어 있으므로 저장소에 올리지 않는다.
- 함께 두는 `private/base/meta.json` 에 기준 기간, 만든 날, 줄 수, 식별자로 바꾸지 못한 줄 수를 적는다.
- 집계를 만들 때 쓴 값(상품 한 개당 인원 같은 것)은 옆의 `private/base/summary_constants.json` 에 근거와 함께 적는다. 모양과 규칙은 6.1절의 "집계 파일 옆의 상수 파일" (11-19 wilstein91 결정, T213).
- **가상 예시**: `data/samples/base_summary.csv` 는 같은 열을 가진 지어낸 값이다. 기본 데이터의 수치를 따오지 않는다. 키나 기본 데이터가 없는 PC 는 이 파일로 돌린다.
- 업장 정의의 파는 달 밖에서 팔린 줄(예: 더파빌리온 빙수)도 그대로 둔다. 엔진은 그 줄도 고객군의 매출과 업장별 비중에 넣는다 (11-15 팀장이 정함.
  보정은 일 년 합계만 쓰므로 그 매출이 어느 달에 팔렸는지는 상관없다. 11-19(T210)부터 달을 준 실행의 가중치는 그 달의 줄만 쓴다). 형식 검사는 가상 예시 값에서만 이것을 오류로 본다.

엔진은 이 파일에서 아래를 계산한다.

| 계산하는 값 | 쓰는 곳 |
|---|---|
| 고객군마다 업장별 매출 비중 | 보정의 대조 (PRD 6.5절), 페르소나의 `base_profile` (5절) |
| 고객군마다, 조건마다의 인원 | 묶음의 비율과 고객군 배수 (PRD 7.2절, 10.1절의 "가중치를 내는 법"). 다이닝의 범위는 기본 데이터에서 사업부문이 호텔 다이닝인 8개 업장이다. 조식은 넣지 않는다 (6절) |
| 고객군의 다이닝 매출 합 | 가상 매출과 견줄 기본 데이터 쪽 합계. 11-19(T210)부터 가중치로 맞추지 않아 차이가 남는다. 그 차이를 어떻게 볼지는 다음 단계에서 정한다 |
| 상품마다 `paid` 합 ÷ `quantity` 합 | 가격이 빈 상품의 단가 (3절) |
| 고객군과 이용 상황마다 매출이 가장 큰 업장 | 검증의 단순 기준 (PRD 6.6절) |

예시 (지어낸 값이다. `revenue_net` 은 하나씩 팔린 줄마다 반올림한 값을 더한 것으로 지었다)

```csv
customer_group,venue_id,product_id,occasion,meal,day_type,month,unit,quantity,people,paid,revenue_net,price_unconfirmed
가족·친족,geumryong,course-a,meal,,weekday,5,1인,300,300,45000000,40909200,N
가족·친족,geumryong,course-a,meal,,weekend,5,1인,480,480,72000000,65454720,N
가족·친족,geumryong,course-b,meal,dinner,weekend,5,1인,180,180,36000000,32727240,N
```

이 예시로 10.1절의 예시 실행(가족·친족의 페르소나 하나 × 조건 `meal-dinner-weekend`)을 돌리면 이렇게 된다.
조건 `meal-dinner-weekend` 의 인원은 끼니가 빈 주말 줄의 반(점심·저녁 0.5·0.5. 480 × 0.5 = 240)과 주말 저녁 줄(180)을 더한 420 명이다 (평일 줄은 돌리지 않는 조건이다).
돌리는 조건이 하나라 묶음의 비율은 1 이다. 페르소나의 일행이 4명이고 고객군 안의 몫이 0.5 이므로,
고객군 배수는 420 ÷ (0.5 × 4) = 210, 페르소나의 가중치는 210 × 0.5 = 105 다. 이 방문은 105 팀, 420 명을 대표한다.
페르소나가 금룡 코스 A 를 4인분 골라 세금을 뺀 매출이 545,455 이면 가중 매출은 545,455 × 105 = 57,272,775 다.
같은 줄의 기본 데이터 매출(65,454,600)과 같지 않다. 이 차이는 맞추지 않고 남긴다 (11-19, T210).

## 9. 선택 요청과 응답

엔진은 이 한 가지 형식으로만 LLM 을 부른다 (PRD 7.3절). 공급자마다 다른 부분은 엔진 안쪽에서 감춘다.
프롬프트의 문장은 페르소나 담당이 쓰고(`personas/prompts/` 에 둔다), 요청과 응답의 모양은 여기서 정한다.

**요청** — 엔진이 만든다.

| 키 | 뜻 |
|---|---|
| `prompt_version` | 프롬프트의 판 이름. 프롬프트를 고치면 바꾼다 |
| `persona` | 두 층을 합친 페르소나. 기본 데이터로 돌릴 때는 엔진이 붙인 `base_profile` 과, 비공개 층의 흔적 `overridden_by_private` (5절)가 들어 있다. 가상 예시로 돌릴 때는 둘 다 없거나 비어 있다 |
| `condition` | 이번 방문 조건. 6절의 조건에 `adults`, `children`, `budget`, `purpose`, `party` 를 더한 것. `purpose` 와 `party` 는 검증할 때 후기의 라벨을 넣고 (후기에 비어 있으면 `null`), 다른 때는 `null` 이다 |
| `candidates` | 규칙으로 추린 후보 업장. 업장마다 고를 수 있는 주문(`options`)이 들어 있다. 주문 없이 추가 상품(`addons`)만 있는 후보도 있다 (아래 "주문이 없는 후보") |
| `allow_none` | "이용하지 않음"을 고를 수 있는가. 늘 `true` |
| `vocab` | 이유로 쓸 수 있는 라벨: `reasons_chosen`, `pain_points` |

- **요청에 상황의 이름(`scenario_id`)은 없다** (11-18, T121. 그 전에는 있었다). 상황은 후보의 가격·상품·프로모션으로만 요청에 드러난다.
  후보가 기준과 같은 방문은 어느 상황에서 돌려도 요청이 같아 기준의 답이 재생되고, LLM 이 상황의 이름에서 무엇이 바뀌었는지 짐작하지 못한다.
  어느 상황의 방문인지는 실행 기록과 원장의 `scenario_id` 에 남는다.
- 주문(`options`)의 수량과 금액은 엔진이 3절의 수량 규칙과 프로모션으로 미리 계산한다.
- 성인 가격과 어린이 가격처럼 함께 사야 하는 상품은 주문 하나의 `lines` 에 여러 줄로 넣는다.
- `qty_rule` 이 `choice` 인 상품은 후보의 `addons` 에 넣고, LLM 이 수량을 고른다.
  `addons` 의 한 줄은 `product_id`, `name`, `unit`, `unit_price`, `qty_max` 다. 고른 추가 상품의 금액은 주문의 `total` 에 들어 있지 않고, 엔진이 원장에 따로 적는다.
  추가 상품에는 프로모션 할인을 적용하지 않는다 (11-16 회의. 3절). 그래서 `addons` 에는 할인 칸이 없고, 원장의 추가 상품 줄의 할인은 0 이다.
- **주문이 없는 후보** (11-13 에 더함): 이번 조건에 살 수 있는 상품이 모두 `choice` 인 업장은 `options` 가 빈 목록이고 `addons` 만 있다.
  포장·구매 업장이 그렇다 (상품마다 고객이 수량을 정한다). 이런 업장을 고를 때는 `option_id` 를 `null` 로 두고 추가 상품을 하나 이상 산다.
  주문이 있는 업장에서는 주문을 꼭 하나 고른다. 추가 상품만 고를 수 없다. 후보에는 주문이나 추가 상품이 하나 이상 있어야 한다.
- 후보의 `promotions` 는 그 업장에서 이번 조건에 해당하는 프로모션이다. 한 줄은 `promo_id`, `name`, `benefit`, `applied` 다.
  `applied` 가 `true` 면 그 할인이 이미 `discount` 에 들어 있다는 뜻이다.
  - 넣는 것 (11-14 에 정함): 3절의 조건과 기간에 해당하고, 이 후보에서 살 수 있는 상품(주문의 줄이나 추가 상품)에 걸리는 프로모션이다.
    이번 조건에 팔지 않는 상품에만 걸리는 프로모션은 넣지 않는다.
  - `applied` 가 `true`: 그 할인이 이 후보의 주문 가운데 하나 이상에 들어 있다. 어느 주문인지는 줄의 `discount` 로 안다 (할인은 주문마다 따로 고른다).
  - `applied` 가 `false`: 금액에 들어 있지 않다. 증정(금액을 바꾸지 않는다. 목록에 있으면 받는 것이다), 더 큰 할인에 밀려 어느 주문에도 들어가지 않은 할인,
    추가 상품에만 걸리는 할인(3절. 추가 상품에는 할인을 적용하지 않는다)이 그렇다.
  - 깎인 줄이 있는 후보에는 `applied` 가 `true` 인 할인이 있고, 깎인 줄이 없는 후보에는 없다. 어긋나면 형식에 어긋난 요청이다.
- **예산으로 거르기**: 1인 기준이면 주문의 `total` ÷ (성인 수 + 어린이 수), 일행 기준이면 `total` 을 예산의 `max` 와 견준다. `max` 를 넘는 주문은 후보에서 뺀다.
  `total` 은 할인을 뺀 금액이다. 할인을 받아 `max` 안으로 들어온 주문은 후보에 남는다.
  주문이 하나도 남지 않은 업장은 후보에서 빠진다. `max` 아래에서 비싼지 싼지는 LLM 이 `typical` 을 보고 판단한다.
  그래서 `max` 를 넘는 주문이 든 요청은 형식에 어긋난 요청이다.
  수량 규칙이 있는 상품을 파는 업장은 주문이 남지 않으면 추가 상품이 있어도 후보에서 빠진다 (음료만 사러 가는 곳이 아니다).
- **예산의 `max` 는 산 것 전부와 견준다** (11-13 에 정함): 고른 주문의 `total` 에 고른 추가 상품의 금액을 더한 값이 `max` 를 넘는 답은 실패로 기록한다.
  그래서 가장 싼 주문에 하나만 더해도 `max` 를 넘는 추가 상품은 후보에 넣지 않는다. 주문이 없는 후보는 추가 상품의 값만 보고, 남는 추가 상품이 없으면 후보에서 뺀다.
  (주문의 `total` 만 견주면 주문에 추가 상품을 더해 `max` 를 넘겨도 통과한다. 독립 검토에서 나온 것이다.)

**후보와 주문을 만드는 규칙** — 엔진(`engine/candidates.py`)이 이렇게 만든다.

- **업장**: 이번 조건의 이용 상황이 있는 워커힐 업장과, 그 업장들과 견주는(`competes_with`) 경쟁 업장을 본다.
  영업 시간에 그 끼니·요일의 줄이 없는 업장, 일행의 수가 예약 조건의 인원 범위(`party_min` ~ `party_max`) 밖인 업장은 뺀다.
  `hours` 나 `reservation` 이 `null` 인 업장은 그 검사를 건너뛴다. 조건에 `month` 가 있으면 그 달에 영업하지 않는 업장과 팔지 않는 상품도 뺀다.
- **상품**: 이용 상황이 같고 그 끼니·요일에 파는(`slots`) 상품만 쓴다. 가격이 비어 있는 상품은 빼고 실행 기록의 `skipped_products` 에 남긴다.
- **주문**: 구분 없는 가격(`audience` 가 `all`)의 상품은 그 상품 하나가 주문 하나다. 성인 가격과 어린이 가격이 따로면 한 주문에 두 줄로 넣는다.
  어린이가 없으면 성인 줄만 넣는다. 어린이가 있는데 어린이 가격이 없는 성인 상품은 주문이 되지 못한다.
  조건에 `month` 가 없으면 파는 달이 같은 것끼리만 짝짓는다 (방문의 몫은 하나다. 10.2절). `month` 가 있으면 그 달에 파는 것끼리 짝짓는다.
  어린이 가격이 둘 이상이면 가격마다 주문이 따로 생긴다 (어린이 모두가 그 가격인 주문이다. 지금 업장 정의에는 이런 곳이 없다).
- **추가 상품과 파는 달**: 조건에 `month` 가 없을 때, 후보의 주문을 파는 달 가운데 팔지 않는 달이 있는 추가 상품은 넣지 않는다.
  추가 상품은 주문마다가 아니라 후보에 하나의 목록으로 들어가므로, 그 후보의 어느 주문과도 함께 낼 수 있는 것만 넣는다
  (일 년 내내 파는 주문이 하나라도 있으면 일부 달에만 파는 추가 상품은 빠진다).
  추가 상품의 줄에는 고른 주문의 몫을 적으므로(10.2절), 넣으면 일부 달에만 파는 추가 상품이 주문만큼 팔린 것으로 부풀려진다.
- **순서와 번호**: 후보는 워커힐 업장 먼저, 그 안에서는 `venue_id` 순이다. `option_id` 는 이번 조건에 만들 수 있는 주문을 업장 정의의 상품 순서대로 세어
  `<venue_id>-o1`, `-o2` … 로 붙인다. 번호는 예산으로 거르기 전에 매기므로, 예산을 넘어 빠진 주문의 번호는 비어 있을 수 있다.
- **상황과 할인**: 업장 정의는 상황을 적용한 사본을 쓴다 (7절). 주문마다 3절의 규칙으로 할인을 넣은 뒤에 예산으로 거른다.

```json
{
  "prompt_version": "p1",
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
| `choice` | 고른 것: `venue_id`, `option_id`, `addons` (`product_id` 와 `quantity` 의 목록). "이용하지 않음"이면 `venue_id` 와 `option_id` 가 `null`. 주문이 없는 후보를 골랐으면 `option_id` 만 `null` |
| `reason_labels` | 고른 이유. `vocab.reasons_chosen` 에서 하나 이상. "이용하지 않음"이면 `vocab.pain_points` 에서 고른다 |
| `reason_text` | 이유를 한 문장으로 |
| `used_attributes` | 판단에 쓴 페르소나의 속성. `budget`, `preferences.needs` 처럼 점으로 이어 적는다 |
| `rejected` | 고르지 않은 후보마다: `venue_id`, `pain_labels` (`vocab.pain_points` 에서), `text` 한 문장 |
| `scores` | 후보마다와 "이용하지 않음"의 점수와, 그곳에 간다면 고를 주문 (11-20 wilstein91 결정, T212). 항목마다 `venue_id` ("이용하지 않음"은 `null`), `percent` (정수, "이 손님이 같은 상황을 백 번 맞는다면 몇 번", 모두 더하면 100), `option_id`, `addons` (`choice` 와 같은 모양). 점수를 묻지 않던 판(`p1`, `p2`, `p3`)의 답에는 없다. 아래 "점수와 몫" |

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
- `choice.option_id` 가 그 업장의 주문에 있다. 주문이 없는 후보를 골랐으면 `option_id` 가 `null` 이고, 산 추가 상품이 하나 이상이다.
- 고른 주문의 `total` 에 고른 추가 상품의 금액을 더한 값이 예산의 `max` 를 넘지 않는다.
- `addons` 의 상품이 그 업장의 `addons` 에 있고 수량이 0 ~ `qty_max` 다. 같은 상품을 두 번 적지 않는다.
- 라벨이 모두 `vocab` 에 있다.
- `rejected` 에 고르지 않은 후보가 빠짐없이 한 번씩 있다. 고른 업장과 후보에 없는 업장은 `rejected` 에 없다.
  "이용하지 않음"을 골랐으면 후보 모두가 `rejected` 에 있다.
- `used_attributes` 가 페르소나에 실제로 있는 속성이다.
- 원장에 적을 금액을 업장 정의의 가격과 프로모션 규칙으로 다시 계산했을 때, 고른 주문의 `total` 과 같다. 추가 상품은 따로 계산해 더한다.

- 점수(`scores`)는 아래 "점수와 몫"의 규칙을 지킨다.

마지막 항목과 점수의 금액을 뺀 나머지는 `engine.formats.problems_in_response` 가 본다. 금액은 업장 정의가 있어야 해서 엔진이 따로 본다 (`engine.ledger.amount_problems`).
저장된 응답을 재생할 때도 같은 검사를 다시 한다.

**점수와 몫** (11-20 wilstein91 결정, T212 의 2단계 방식) — 방문 하나가 한 곳만 고르지 않고 몫으로 나뉘어 여러 곳에 간다.

- 점수를 묻는 판의 답에는 `scores` 가 꼭 있다. 후보마다 하나와 "이용하지 않음"(`venue_id` 가 `null`) 하나가 빠짐없이 한 번씩 있고, `percent` 를 더하면 100 이다.
- 점수가 0 보다 큰 곳의 주문(`option_id`, `addons`)은 `choice` 와 같은 규칙으로 검사한다 (그 업장의 주문인지, 추가 상품과 수량, 예산, 업장 정의로 다시 낸 금액).
  점수가 0 인 곳은 주문을 적지 않아도 된다 (`option_id` 가 `null`, `addons` 가 빈 목록). "이용하지 않음"에는 주문이 없다.
- `choice` 에 적은 곳은 점수가 0 보다 크고, 그곳의 주문이 `choice` 와 같다. `choice` 와 이유(`reason_labels` 등)는 지금처럼 이번 한 번의 선택과 그 이유다.
- 엔진은 점수를 몫으로 바꾼다 (`engine.shares`): 그곳의 몫 = (점수 ^ k) × 그곳의 상수를 모든 곳의 합이 1 이 되게 나눈 것.
  k 와 업장 상수는 결정 상수다 (6.1절의 `share-sharpness-k`, `share-venue-constant-<venue_id>`). 업장 상수가 적히지 않은 곳과 "이용하지 않음"은 1 이다.
  둘은 받은 자료로 추정한다 ("상수 추정", 선택 모형의 대안별 상수와 같은 방법). 추정에 쓴 자료로 다시 맞았다고 하지 않는다 (PRD 12절).
- 점수를 묻지 않던 판(`p1`, `p2`, `p3`, `engine.formats.choice.SINGLE_ANSWER_PROMPTS`)의 답은 `scores` 가 없어도 되고, 엔진은 `choice` 에 적은 곳의 몫을 1 로 읽는다 (1단계 방식, 답 하나).
  임시 호환이다: 팀이 쓰는 답과 예시 묶음을 점수를 묻는 판으로 다시 받은 뒤 없앤다 (진행 문서 T212 의 완료 조건).
- 응답 스키마(아래 "응답의 모양을 묶는다")는 점수를 묻는 판의 요청에만 `scores` 를 더한다.

```json
{
  "scores": [
    {"venue_id": "geumryong", "percent": 70, "option_id": "geumryong-o1", "addons": []},
    {"venue_id": "examplehotel-chinese", "percent": 25, "option_id": "examplehotel-chinese-o1", "addons": []},
    {"venue_id": null, "percent": 5, "option_id": null, "addons": []}
  ]
}
```

위는 위의 요청에 점수를 묻는 판으로 답했다면 더해졌을 `scores` 의 예다 (지어낸 값). k 와 업장 상수가 모두 1 이면 몫은 금룡 0.70, 예시호텔 중식당 0.25, 이용하지 않음 0.05 다.

**LLM 을 부르는 법** (11-14 에 정함) — 공급자가 달라도 보내는 것은 같다 (`engine/llm.py`).

- **시스템 프롬프트**: `personas/prompts/<prompt_version>.md` 의 글 그대로다. 엔진은 글을 덧붙이지 않는다.
  그래서 판 이름 하나가 프롬프트의 글 하나다. 글을 고치면 `prompt_version` 을 바꾼다 (요청의 해시가 달라져 저장된 응답이 재생되지 않는다).
  판 이름은 파일 이름이라 영어 소문자, 숫자, `.`, `_`, `-` 로 적는다. 예시는 `tests/fixtures/example/personas/prompts/p1.md` 다.
- **사용자 메시지**: 위의 요청을 JSON 으로 적은 글이다.
- **돌려받는 글**: 위의 응답을 JSON 으로 적은 글이다. 앞뒤에 다른 말이나 코드 울타리가 붙어 있으면 맨 바깥의 `{ … }` 만 읽는다.
  그 안은 파일과 같이 엄격하게 본다 (약속에 없는 키, 따옴표로 감싼 숫자는 어긋난 답이다).
- 공급자는 환경 변수 `LLM_PROVIDER` 로 고른다 (`.env.example`). 팀은 `claude-code` 로 각자의 Claude 구독을 부른다 (11-17, T114. 11-16 에는 `openai-compatible` 로 정했었다).
- **응답의 모양을 묶는다** (11-16 에 고침): 엔진은 요청마다 그 요청에서 고를 수 있는 값만 받는 응답 스키마를 만들어 공급자에 보낸다
  (`engine.llm.response_schema`). 업장은 후보의 `venue_id`, 주문과 추가 상품은 후보에 있는 식별자, 이유 라벨은 `vocab` 의 두 목록,
  걸린 점 라벨은 `vocab.pain_points`, `used_attributes` 는 페르소나의 속성을 점으로 이은 경로 가운데서만 고른다.
  스키마로 묶지 못하는 규칙(고른 업장의 주문인지, 고르지 않은 후보가 빠짐없는지, 예산, 고른 경우와 "이용하지 않음"의 라벨 목록)은 엔진이 답을 받은 뒤에 검사한다.
  - `anthropic` 은 구조화된 출력으로 보낸다. `openai-compatible` 은 `response_format` 의 엄격한 `json_schema` 로 보낸다.
  - `claude-code` (11-16, T104. 11-17 부터 팀이 쓰는 공급자, T114)는 자기 Claude 구독으로 로그인한 Claude Code 명령(`claude -p`)을 부르고 스키마를 `--json-schema` 로 보낸다.
    시스템 프롬프트는 프롬프트 파일의 글로 통째로 바꾸고, 도구·MCP·설정 파일을 끄고, 저장소 밖의 빈 폴더에서 띄운다.
    공급자 이름과 모델이 요청의 해시에 들어가므로, 다른 공급자나 다른 모델로 받은 답은 팀의 실행에서 재생되지 않는다. 그런 답은 시연과 보정에 쓰지 않는다.
  - 스키마를 받지 않는 주소면 `LLM_RESPONSE_FORMAT=json_object` 로 적는다. 그때는 JSON 으로 답하라고만 요청하므로 응답의 모양은 프롬프트가 알려 줘야 한다.
  - 스키마는 요청의 해시에 들어가지 않는다. 스키마를 바꿔도 저장된 응답은 그대로 재생된다. 어느 쪽이든 엔진이 답을 다시 검사한다.
  - 고친 까닭: 11-16 에 처음 실제로 부른 답(OpenAI, `json_object`)이 값 목록에 없는 라벨과 점으로 잇지 않은 속성 이름으로 어긋났다.
  `openai-compatible` 의 주소(`LLM_BASE_URL`)는 `https://` 여야 한다. `http://` 는 이 PC 의 주소(localhost, 127.0.0.1, ::1)일 때만 받고, 그때는 프록시를 거치지 않는다.
  주소가 다른 곳으로 넘기는 답(3xx)은 따라가지 않는다. 키와 요청이 암호화되지 않은 채로, 또는 적지 않은 곳으로 나가지 않게 하려는 것이다.
- 어긋난 답은 다시 묻지 않고 그 방문을 실패로 기록한다. 어긋난 답은 10.3절의 "어긋난 응답"으로 남는다.

## 10. 실행 결과

상황 하나를 돌린 것이 실행 하나다. `run_id` 는 `<날짜>-<시각>-<scenario_id>` 다 (예: `20261117-101500-baseline`).

**어떤 자료로 돌리느냐에 따라 읽는 곳과 쓰는 곳이 다르다.** 섞이지 않게 엔진이 지킨다.

| `data_mode` | 읽는 것 | 결과를 쓰는 곳 |
|---|---|---|
| `private` | 기본 데이터 집계 파일, 페르소나의 두 층, 받은 참고 소스의 후기 | `private/runs/<run_id>/` |
| `sample` | 가상 예시 값과 페르소나의 공개 층만. `private/` 는 읽지 않는다 | `engine/samples/runs/<run_id>/` |

- `sample` 로 돌린 결과만 저장소에 올릴 수 있다. `private` 로 돌린 결과에는 요청에 든 비공개 층과 기본 데이터의 값이 그대로 남는다.
- 맨 위의 `engine/samples/runs/` 는 깃이 무시한다 (11-16, T107). 각자 연습으로 받은 답이 올라가지 않게 한다.
  올릴 실행은 테스트의 예시 묶음(`tests/fixtures/<이름>/engine/samples/runs/`)에 둔다. 형식 검사는 깃 저장소가 아닌 곳(예시 묶음과 그 사본)의 실행 폴더만 본다.
- 저장된 응답은 요청이 한 글자라도 다르면 재생되지 않는다. 그래서 `private` 결과를 다른 PC 에서 재생하려면 실행 결과와 함께 비공개 층과 집계 파일도 저장소 밖의 경로로 주고받는다.
  시연에 쓸 저장 응답은 한 PC 에서 만들어 그대로 쓴다.

| 파일 | 내용 |
|---|---|
| `run.json` | 실행 기록 |
| `ledger.csv` | 소비 원장 |
| `llm/<request_hash>.json` | 저장된 LLM 응답. 요청 하나가 파일 하나. 검사를 통과한 것만 둔다 |
| `llm_rejected/<request_hash>.json` | 검사에서 어긋난 LLM 응답. 재생에는 쓰지 않는다 (10.3절) |
| `calibration.json` | 보정의 대조 결과 (기준 상황만) |
| `changes.json` | 기준과 견준 매출 변화 나누기 (상황 실행만, 10.6절) |
| `validation.json`, `validation_reviews.csv` | 떼어 둔 후기로 잰 검증 결과와, 후기 한 건마다의 결과 |

- 실행 하나의 폴더에는 위의 파일만 둔다. 검증 결과는 떼어 둔 후기로 잰 것이라 `private/runs/` 의 실행에만 있고, `engine/samples/runs/` 에는 두지 않는다.
- 이 파일들은 이름을 바꾸거나 다른 폴더로 옮겨도 실행 결과다. 형식 검사는 내용으로 알아보고, 위 표의 자리 밖에 있으면 오류로 본다 (11절).

### 10.1 실행 기록 `run.json`

| 키 | 뜻 |
|---|---|
| `run_id`, `created_at`, `engine_commit` | 실행 번호, 만든 때, 엔진 코드의 커밋. 엔진 코드(`engine/` 에서 `samples/`, `conditions.json`, `constants.json` 을 뺀 것)에 커밋하지 않은 변경이 있으면 끝에 `+dirty` 가 붙는다 |
| `data_mode` | `private` 기본 데이터로 돌림, `sample` 가상 예시 값으로 돌림 |
| `scenario_id`, `persona_ids`, `condition_ids` | 무엇을 돌렸나 |
| `month` | 실행의 달 (1 ~ 12). 묶음의 조건을 모두 그 달의 방문으로 돌렸다. 일 년 전체로 돌렸으면 `null` 이다. 명령의 `--month` 로 준다. 기준이 아닌 상황은 기준 실행의 값을 따른다 (아래 "실행의 달") |
| `llm` | `provider`, `model`, `prompt_version`, `calls_new` (새로 부른 수), `calls_replayed` (저장된 응답을 재생한 수), `call_limit`, `stopped_by_limit` |
| `base_profile_mode` | 기본 데이터의 요약(5절의 `base_profile`)을 LLM 에 어떻게 보냈나: `none` 보내지 않음, `bucketed` 범주로 바꿔 보냄, `raw` 그대로 보냄. 기본 데이터로 돌릴 때의 기본값은 `bucketed` 다 (11-13 결정). 가상 예시로 돌릴 때는 늘 `none` 이다. 명령의 `--base-profile` 로 바꾼다. 기준이 아닌 상황은 기준 실행의 값을 따른다 요약을 보내는 실행(`bucketed`, `raw`)은 그 공급자로 보내도 된다고 확인한 PC 에서만 돈다 (아래 "요약을 보내기 전의 확인") |
| `inputs` | 입력 파일들의 해시. 같은 입력인지 견줄 때 쓴다. 읽은 것만 적는다: `venues`, `personas`, `conditions`, `scenario`, `vocab`, 집계 파일 `summary` (늘 읽는다), 결정 상수 `constants` (6.1절. 늘 읽는다. 11-19 부터), 추정한 상수 파일이 있으면 `estimated` (6.1절. 11-20 부터, T212), LLM 을 부를 수 있게 돌렸으면 프롬프트 파일의 `prompt` (재생만 하는 실행은 프롬프트를 읽지 않는다) |
| `weights` | `group_multiplier` 고객군 배수, `persona_weight` 페르소나의 가중치, `condition_ratio` 고객군마다 묶음의 비율, `grades` 각 값의 근거 등급, `people_coverage` 집계 파일의 인원 가운데 페르소나가 있는 고객군의 몫 (0 ~ 1. 집계 파일에 인원이 없으면 `null`). 등급은 값마다 적는다 (고객군 배수는 고객군마다, 가중치는 페르소나마다, 묶음의 비율은 고객군과 조건마다). 내는 법은 아래 "가중치를 내는 법" |
| `filled_products` | 가격이 비어 있어 집계 파일로 단가를 채운 상품의 목록 (3절). `<venue_id>:<product_id>` 로 적는다. 채운 단가는 적지 않는다 |
| `skipped_products` | 가격을 채우지 못해 후보에서 뺀 상품의 목록. `<venue_id>:<product_id>` 로 적는다 |
| `weights_from` | 가중치를 정한 기준 상황의 `run_id`. 기준 상황 자신이면 `null` |
| `counts` | `visits` 돌린 수, `failed` 실패한 수 |
| `status` | `ok`, `stopped_by_limit`, `failed` |
| `constants` | 이 실행이 쓴 결정 상수와 그 값·근거의 목록. 엔진이 쓰는 것(`in_use`)만 남고, 집계 파일 옆의 상수 파일이 있으면 그것도 들어간다 (6.1절). 하나마다 `constant_id`, `name`, `value`, `unit`, `grade`, `sources` (6.1절과 같은 모양), `checked_on`, `file` (적힌 파일). 아래 "쓴 결정 상수" |
| `baseline_answers` | 기준이 아닌 상황에서, 바꾼 업장이 기준과 상황 어느 선택에도 끼지 않아 원장을 기준의 답으로 적은 방문의 `visit_id` 목록. 기준 상황은 `null`. 11-19(T210) 전의 실행 기록에는 없다. 아래 "상관없는 방문의 답" |
| `share_method` | 방문의 몫을 낸 방식 (11-20, T212. 9절의 "점수와 몫"): `single` 모든 방문의 답에 점수가 없어 고른 곳의 몫이 1 이다 (1단계 방식, 답 하나), `scores` 모든 방문의 답에 점수가 있어 몫으로 나눴다 (2단계 방식), `mixed` 둘이 섞였다. 답이 하나도 없는 실행(후보 없음·실패뿐)은 `single` 이다. 화면은 이 값으로 "1단계 방식 (답 하나)"과 "2단계 방식 (몫)"을 가른다. 11-20 전의 실행 기록에는 없고, 그 실행은 모두 1단계 방식이다 |

- 묶음의 조건으로 돌린 실행은 `weights` 에 페르소나마다의 가중치와, 고객군과 조건마다의 비율이 빠짐없이 있어야 한다. 없으면 원장의 `represented` 를 확인할 수 없다.
  화면에서 조건을 직접 넣어 돌린 방문(`manual-`)에는 가중치가 없다.
- 기준이 아닌 상황의 `weights` 는 `weights_from` 에 적은 기준 상황의 값과 같다. 가중치는 기준 상황에서 한 번 정하고 그대로 쓴다 (PRD 7.2절).
- T11(11-15) 전에 돌린 실행 기록은 등급의 모양과 `filled_products` 가 달라 읽히지 않는다. 기준 상황부터 다시 돌린다.
- 11-20(T214) 전에 돌린 실행 기록은 출처를 글 한 줄(`source`)로 적었고 모두 `null` 이었다. 엔진과 화면은 그 기록을 `sources` 가 빈 목록인 것으로 읽는다 (임시 호환. 없애는 조건은 진행 문서 T212).
  또 그 전의 `inputs.constants` 는 파일 전체의 해시라 새 해시와 달라, 그 기준 실행으로는 상황도 보정의 대조도 돌지 않는다. 기준 상황을 한 번 다시 돌린다 (저장된 답을 재생한다).
- `month` 가 생기기 전(T112, 11-17)에 돌린 실행 기록에는 이 칸이 없다. 달을 주지 않고 돌린 것이라 `null` 로 읽는다. 다시 돌리지 않아도 된다.
- T210(11-19) 전에 돌린 실행 기록은 가중치를 매출로 맞춘 것이고 `people_coverage` 가 없다. 읽히지만 가중치의 뜻이 다르다.
  집계 파일에 `people` 이 더해져 해시가 달라졌으므로 그 기준 실행으로는 상황이 돌지 않는다. 기준 상황부터 다시 돌린다.

**쓴 결정 상수** (11-19 wilstein91 결정, T210) — 실행마다 엔진이 쓴 상수를 값까지 `constants` 에 남긴다 (11-19 팀 결정: 값까지 모두 남기기).

- 들어가는 것: `engine/constants.json` 의 상수 가운데 엔진이 쓰는 것(`in_use` 가 `true`. 6.1절. `file` 은 `engine/constants.json`)과, 방문 조건 묶음의 `assumed_splits` 모두(6절. `file` 은 `engine/conditions.json`),
  그리고 집계 파일 옆의 상수 파일이 있으면 그 상수(6.1절. `file` 은 `data/samples/base_summary_constants.json` 이나 `private/base/summary_constants.json`).
  `in_use` 가 `false` 인 상수는 남지 않는다 (11-19 wilstein91 결정, T213).
  나누는 비율은 `constant_id` 가 `split_id`, `name` 이 `applies_when`, `value` 가 갈래마다의 비율(`parts`), `checked_on` 이 `decided_on` 이고 `unit` 은 `null`, `sources` 는 빈 목록이다.
- `value` 는 숫자, 참·거짓, 범위(`{"min": .., "max": ..}`)다. 나누는 비율만 갈래 이름을 키로 둔 묶음이다.
- 11-19(T210) 전에 돌린 실행 기록에는 이 칸과 `inputs.constants` 가 없다. 읽히지만, `inputs.constants` 가 없어 그 기준 실행으로는 상황도 보정의 대조도 돌지 않는다. 기준 상황부터 다시 돌린다.
- 화면이 이 목록을 보여 준다 (어떻게 보일지는 화면 담당이 정한다). 기본 데이터로 돌린 실행은 화면의 기존 가림 규칙을 따른다.

**요약을 보내기 전의 확인** (11-17 에 넣음, T115) — 기본 데이터의 요약이 밖의 LLM 으로 나가는 실행을 엔진이 가려 막는다.

- 기본 데이터로 돌리면서(`data_mode` 가 `private`) 요약을 보내고(`base_profile_mode` 가 `bucketed` 나 `raw`) LLM 을 부를 수 있게 돌리면,
  엔진은 `.env` 의 `BASE_PROFILE_CONFIRMED_FOR` 가 지금 받는 곳의 이름과 같은지 본다. 다르거나 비어 있으면 실행 폴더를 만들지 않고 멈추며 이유와 적을 값을 알린다.
- **받는 곳의 이름** (`engine.llm.receiver_of`): `anthropic` 과 `claude-code` 는 받는 회사가 하나라 공급자의 이름 그대로다.
  `openai-compatible` 은 주소(`LLM_BASE_URL`)에 따라 받는 곳이 달라 `openai-compatible:<주소의 호스트>` 다 (예: `openai-compatible:api.openai.com`). 포트와 경로는 보지 않는다.
- 보지 않는 때: 요약을 보내지 않는 실행(`none`), 재생만 하는 실행(`--replay-only`. 아무것도 나가지 않는다), 가상 예시로 돌리는 실행(요약이 없다).
- LLM 을 부를 수 있게 돌리면, 저장된 답이 모두 있어 실제로는 부르지 않게 될 실행도 본다. 돌려 보기 전에는 부를지 알 수 없기 때문이다. 그때는 `--replay-only` 로 돌린다.
- 기준이 아닌 상황은 기준 실행의 `base_profile_mode` 를 따르므로, 기준 실행이 요약을 보냈으면 상황도 같은 확인이 있어야 돈다.
- 값이 받는 곳의 이름인 까닭: 확인은 받는 회사마다 따로다. 공급자나 주소를 바꾸면 적어 둔 값이 맞지 않아 다시 확인하게 된다.
  모델만 바꾼 것은 가리지 않는다 (같은 회사의 같은 계정으로 간다).
- 이 값은 실행 기록에 남지 않는다. 그 PC 에서 확인했다는 표시일 뿐이고, 무엇을 확인하는지는 `CLAUDE.md` 의 "스택"과 `MEETING_1117.md` ③ 에 있다.
- 형식 검사는 이 값을 보지 않는다. 기본 데이터로 돌린 실행은 `private/` 에만 있어 형식 검사의 범위 밖이다.

**실행의 달** (11-17 에 넣음, T112. 계절을 넣기로 한 것은 11-16, `MEETING_1117.md` ④) — 계절을 보려고 실행 하나를 한 달의 방문으로 돌린다.

- 명령에 `--month <1 ~ 12>` 를 적으면 엔진이 묶음의 조건마다 그 달을 붙여 돌린다. 묶음 파일의 `month` 는 그대로 `null` 이다 (6절).
  적지 않으면 지금까지처럼 일 년 전체로 본다. 이때의 요청은 `month` 가 생기기 전과 글자까지 같아 저장된 응답이 그대로 재생된다.
- 달을 주면 달라지는 것은 셋이다.
  - **후보**: 그 달에 영업하지 않는 업장과 팔지 않는 상품이 빠진다 (9절). 기간이 있는 프로모션은 그 달에 걸칠 때만 적용한다 (3절).
  - **요청**: `condition.month` 에 그 달이 실린다. 달의 뜻(연말, 성수기 등)을 어떻게 읽을지는 프롬프트가 정한다. 요청이 달라지므로 저장된 응답도 달마다 따로다.
  - **몫**: 그 달의 방문이라 `counted_share` 가 늘 1 이고 "파는 달이 아님" 줄이 생기지 않는다 (10.2절).
- **가중치는 그 달의 인원으로 낸다** (11-19 엔진 담당이 정함, T210. 아래 "가중치를 내는 법"에서 집계 파일의 그 달 줄만 쓴다).
  - 묶음의 비율과 고객군 배수 모두 그 달의 인원이다. 그래서 달을 준 실행의 가상 매출은 그 달의 방문 크기를 따른다.
  - 그 달에 인원이 없는 고객군은 배수가 0 이고 등급이 `unknown` 이다. 명령이 그 고객군을 알린다. 그 실행과 그것을 기준으로 한 상황에서 그 고객군의 가상 매출은 0 이다.
  - 같은 달의 기준 실행과 상황은 가중치가 같아 견줄 수 있다.
  - 11-17 ~ 11-19 에는 달을 줘도 일 년 합계에 맞췄다 (고객군의 가상 매출 합이 어느 달로 돌려도 같았다). T210 에서 바꿨다.
  - **보정(T18)은 달을 주지 않은 기준 실행으로 한다.** 형식 검사는 달을 준 실행에 `calibration.json` 이 있으면 오류로 본다.
  - 기본 데이터의 요약(5절의 `base_profile`)과 집계 파일로 채우는 단가(3절)도 일 년 합계 그대로다.
- 가격은 달에 따라 바뀌지 않는다. 업장 정의의 가격은 하나이고, 달마다 다른 요금은 상황으로 얹는다 (11-16 에 정함. 달별 가격을 적는 형식은 동결 뒤 과제).
- 기준이 아닌 상황은 기준 실행의 달로 돈다. 다른 달을 따로 주면 돌리지 않는다 (아래 "기준이 아닌 상황을 돌리는 법").
- 형식 검사는 묶음의 조건으로 돌린 방문마다 저장된 응답과 어긋난 응답의 요청의 달이 실행 기록의 `month` 와 같은지 본다. 화면에서 직접 넣은 조건(`manual-`)은 달을 사람이 넣어 견주지 않는다.
  달을 준 실행에서 고른 줄의 `counted_share` 가 1 이 아니거나, 상황의 `month` 가 `weights_from` 의 실행과 다르면 오류다.
- 날씨는 받지 않는다 (11-16 에 정함. 근거가 없어 `assumption` 이 되고 형식·엔진·프롬프트를 함께 바꿔야 해 동결 뒤 과제로 남겼다).

**가중치를 내는 법** (11-15 에 정함. 11-19 에 매출에서 인원으로 바꿈, T210. `engine/weights.py`) — 기준 상황을 돌릴 때 엔진이 방문을 돌기 전에 집계 파일(8절)에서 낸다 (PRD 7.2절).

- 집계 파일: 기본 데이터로 돌리면 `private/base/summary.csv`, 가상 예시로 돌리면 `data/samples/base_summary.csv` 다. 없으면 돌리지 않는다.
- **쓰는 인원** (`group_people`): 읽은 워커힐 업장의 줄만 쓴다 (`--venues` 로 고르면 그 업장의 줄). 달을 준 실행은 그 달의 줄만 쓴다. 줄마다 인원(`people`)을 돌리는 조건에 넣는다.
  - `people` 이 빈 포장 줄은 수량 × 그 고객군의 평균 일행 수다 (한 개를 한 팀으로 본다). 평균 일행 수 = Σ(고객군 안의 몫 × 일행 수) ÷ Σ(몫), 돌리는 페르소나로 낸다 (`average_parties`).
    페르소나가 없는 고객군은 아는 고객군들의 평균을 쓴다 (설계 가정). 그 밖의 빈 칸(추가 상품)은 0 명이다 (8절).
  - 식사가 아닌 줄은 이용 상황과 평일·주말이 같은 조건에, 끼니가 있는 식사 줄은 끼니까지 같은 조건에 넣는다.
  - 끼니가 빈 식사 줄은, 업장 정의에서 그 요일에 그 상품을 점심과 저녁 가운데 한 끼니에만 팔면(3절의 `slots`) 그 끼니의 조건에 넣는다.
    예: "주말 점심과 모든 요일 저녁"에 파는 상품의 평일 줄은 저녁이다 (8절: 상품으로 알 수 없을 때만 나눈다. 11-15 독립 검토에서 나와 정함).
    둘 다 팔면(또는 업장 정의에 그 상품이 없으면) 6절의 비율(`meal-lunch-dinner`)로 나눠 점심과 저녁 조건에 넣는다.
  - 조식 줄과 돌리지 않는 조건의 줄은 넣지 않는다. 파는 달 밖에서 팔린 줄도 넣는다 (8절).
- **한 방문이 대표하는 팀 수** = 그 고객군의 그 조건의 인원 × 페르소나의 몫 ÷ Σ(그 고객군에서 돌리는 페르소나마다 몫 × 일행 수).
  몫(5절의 `share_in_group.value`)은 팀(방문)의 비율이고, 일행 수는 `visit.party` 의 `adults` + `children` 이다.
  그래서 고객군마다 "대표하는 팀 수 × 일행 수"를 더하면 그 고객군의 인원과 같다. 이것을 실행 기록의 모양으로 나눠 적는다 (`decide_weights`):
- **묶음의 비율** = 그 고객군의 그 조건의 인원 ÷ 그 고객군의 돌리는 조건 모두의 인원. 고객군마다 더하면 1 이다.
  조건의 일부만 돌리면(`--conditions`) 돌린 조건 안에서 나눈다. 그 고객군의 인원이 없으면 모두 0 이다.
- **고객군 배수** = 그 고객군의 돌리는 조건 모두의 인원 ÷ Σ(몫 × 일행 수).
  집계 파일에 그 고객군의 인원이 없으면 0 이다. 명령이 알린다. 페르소나의 `customer_group` 이 집계 파일의 고객군 이름과 다른 때가 가장 흔하다.
- **페르소나의 가중치** = 고객군 배수 × 고객군 안의 몫. 원장의 `represented` (= 가중치 × 묶음의 비율)가 위의 대표하는 팀 수다.
- 방문을 돌기 전에 정하므로 AI 가 무엇을 고르든 가중치는 바뀌지 않는다. 엔진은 방문마다 `represented` 와 `weighted_revenue` 를 바로 적는다.
  기준이 아닌 상황은 기준 실행의 가중치를 그대로 쓴다.
- **가상 매출과 기본 데이터 매출의 차이는 맞추지 않고 남긴다.** 그 차이를 점수로 보는 것은 다음 단계다 (PRD 8절).
  11-15 ~ 11-19 에는 방문을 다 돈 뒤 고객군 배수를 원장으로 맞춰 고객군의 가상 매출 합이 기본 데이터 매출과 늘 같았다 (차이가 보이지 않았다). T210 에서 바꿨다.
- **`people_coverage`** = 페르소나가 있는 고객군의 인원 ÷ 집계 파일의 모든 고객군의 인원 (쓰는 인원의 범위 안에서). 페르소나가 없는 고객군은 시뮬레이션에 나오지 않는다.
  얼마나 빠졌는지를 적어 두기만 하고, 다루는 것은 뒤의 단계다. 명령이 이 값을 알린다.
- **등급**
  - 묶음의 비율: 기본 데이터면 `internal`. 팀이 정한 비율(6절의 `assumed_splits`)로 나눈 인원이 든 조건은 그 비율의 `grade` (지금은 `assumption`)와 견줘 약한 것이다.
  - 고객군 배수: 기본 데이터면 `internal`. 인원이 없으면 `unknown` 이다.
  - 나눈 인원의 일부만 돌리는 조건에 든 고객군(예: `--conditions` 로 저녁만 돌림)은 그 고객군의 합계가 나누는 비율에 기대므로,
    그 고객군의 비율과 배수가 모두 나누는 비율의 등급을 따른다. 묶음의 조건을 모두 돌리면 생기지 않는다.
  - 페르소나의 가중치: 고객군 배수의 등급과 `share_in_group.grade` 가운데 약한 것. 세기는 2절의 "근거 등급의 세기"다.
    세기가 같으면(예: `internal` 과 `official`, `review` 와 `literature`) 고객군 배수의 등급을 쓴다.
  - 가상 예시로 돌리면 `internal` 대신 `assumption` 이다. 인원이 없어 낼 수 없는 값은 `unknown` 이다.
- 업장별 가상 매출과 비중은 원장에서 낸다: `engine.ledger.venue_shares` (PRD 7.2절의 4·5. 경쟁 업장과 "이용하지 않음"은 분모에 넣지 않고 방문의 크기로 따로 낸다).
- **기준이 아닌 상황을 돌리는 법** (11-14 에 정함): 끝까지 돈 기준 실행(`status` 가 `ok`)이 먼저 있어야 한다.
  엔진은 그 실행의 `persona_ids`, `condition_ids`, `weights` 를 그대로 쓰고 `weights_from` 에 그 `run_id` 를 적는다.
  실행하는 명령은 같은 `data_mode` 의 끝까지 돈 가장 새 기준 실행을 고른다 (`--baseline` 으로 다른 실행을 가리킬 수 있다).
  기준 실행 뒤에 입력(`inputs` 의 `venues`, `personas`, `conditions`, `vocab`, `summary`, `constants`. 두 실행 모두 프롬프트를 읽었으면 `prompt`)이나
  `llm` 의 `provider`·`model`·`prompt_version` 이 달라졌으면 돌리지 않는다. 기준 상황을 다시 돌린 뒤에 돌린다.
  `base_profile_mode` 와 `month` 는 기준 실행의 값을 쓴다. 다른 값을 따로 주면 돌리지 않는다.
  명령은 달이 같은 기준 실행 가운데 가장 새것을 고른다: `--month` 를 적으면 그 달로 돌린 것, 적지 않으면 일 년 전체로 돌린 것이다.
  그런 실행이 없으면 다른 달의 실행으로 넘어가지 않고 멈춘다 (적지 않은 달이 조용히 따라오지 않게 한다). `--baseline` 으로 실행을 가리키고 `--month` 를 적지 않으면 그 실행의 달을 따른다.
  상황 사이의 차이에 상황의 변경만 남게 하려는 것이다.
  - 이 검사가 보지 못하는 것: 엔진 코드가 바뀐 것(`engine_commit`), 기준 실행이 재생만 해서 프롬프트를 읽지 않았을 때 그 뒤에 바뀐 프롬프트의 글.
    코드나 프롬프트를 고쳤으면 기준 상황부터 다시 돌린다.
  - **기준 실행에 실패한 방문이 있으면(`counts.failed`) 상황을 돌리지 않는다** (11-16 회의에서 정함). 그 방문은 기준에서 금액이 0 인 줄이라,
    상황에서 성공하면 차이에 상황의 변경이 아닌 것이 섞인다. 엔진은 실행 폴더를 만들지 않고 실패한 건수와 다시 돌리는 법을 알린다.
    - 원장의 `llm_call` 이 `new` 이거나 빈 실패(부르다 실패, 답이 어긋남, 재생만 해서 응답이 없음)는 기준 상황을 `--replay-only` 없이 다시 돌리면
      저장된 응답은 재생하고 그 방문만 LLM 을 새로 부른다.
    - `llm_call` 이 `replay` 인 실패(저장된 응답을 읽지 못했거나 다시 검사하다 어긋남. 엔진 코드가 바뀐 뒤에 생길 수 있다)는 다시 돌려도 같은 응답이
      재생돼 그대로 남는다. `fail_reason` 의 원인을 먼저 고친다.
    - 실행하는 명령이 고르는 "가장 새 기준 실행"에 실패한 방문이 있어도 그보다 옛 실행으로 넘어가지 않고 멈춘다.
      실패가 있는 것을 모른 채 옛 실행과 견주는 일을 막으려는 것이다. 옛 실행을 쓰려면 `--baseline` 으로 가리킨다.
    실패를 어떻게 줄이고 화면에서 어떻게 보일지는 쓰면서 보완한다 (T10 의 경위).
  - 묶음의 조건은 `stay` 가 `null` 이라(6절), 조건에 `stay` 가 적힌 프로모션을 더한 상황은 묶음으로 돌리면 기준과 같은 결과가 나온다 (3절).
- 가상 예시로 돌린 실행(`data_mode` 가 `sample`)의 `grades` 에는 `internal` 을 쓰지 않는다. 지어낸 값에서 낸 가중치의 등급은 `assumption` 이다.
- `counts` 는 원장과 맞아야 한다: `visits` 는 원장의 방문 수, `failed` 는 그중 실패한 방문 수다.
  끝까지 돌린 실행(`status` 가 `ok`)의 원장에는 `persona_ids` × `condition_ids` 마다 방문이 하나씩 있다.
- **`llm` 의 수와 `status`** (11-14 에 정함)
  - `calls_new` 는 이 실행에서 LLM 을 부른 수다. 실패한 호출과 답이 어긋난 호출도 센다 (상한은 비용을 막으려는 것이다).
    `call_limit` 을 넘지 않는다. LLM 없이 재생만 한 실행은 둘 다 0 이다.
    세는 것은 엔진이 공급자를 부른 수다. 공급자의 SDK 가 안에서 다시 보내 보는 요청은 세지 않는다.
  - 새로 부르려는데 `calls_new` 가 `call_limit` 에 닿아 있으면 거기서 멈춘다. `status` 는 `stopped_by_limit`, `llm.stopped_by_limit` 은 `true` 다 (둘은 늘 함께다).
  - 설정이 틀려 부를 수 없으면 그 방문을 실패로 남기고 멈춘다. `status` 는 `failed` 다.
    키가 없거나 틀린 것, 없는 모델 이름, 공급자가 요청 자체를 받지 않는 것(HTTP 400·401·403·404), 주소가 다른 곳으로 넘기는 것(3xx)이 그렇다.
    다시 불러도 같은 실패가 나는 것들이다.
  - 한 번의 호출이 실패한 것(연결 오류, 요청 한도, 서버 오류, 답을 거절함, 답이 길이 한도에서 끊김)은 그 방문만 실패로 남기고 다음 방문으로 간다.
    다만 **이렇게 실패한 호출이 연달아 3번이면 멈춘다** (`status` 는 `failed`). 닿지 않는 주소나 멈춘 공급자를 상한까지 계속 부르지 않으려는 것이다.
    거절과 길이 한도에서 끊긴 답도 실패한 호출로 센다. 읽을 글을 받으면(검사에서 어긋난 답이어도) 다시 0 부터 센다.
  - 멈춘 실행의 원장에는 멈추기 전까지 돌린 방문만 있다. 받은 답은 `llm/` 에 남아 있어, 다시 돌리면 재생하고 남은 방문만 새로 부른다.
  - 예상하지 못한 오류로 끊긴 실행도 그때까지의 실행 기록과 원장을 쓴다 (`status` 는 `failed`). 실행 기록이 없는 실행 폴더는 형식 검사가 오류로 본다.

예시 — 예시 묶음(`tests/fixtures/example/`)으로 엔진이 쓴 실행 기록이다. `engine_commit` 만 자리를 채운 값이다.
입력의 해시는 예시 묶음의 파일로 낸 값이라, 예시 묶음의 입력 파일을 고치면 이 예시와 예시 묶음의 실행을 함께 다시 만든다 (테스트가 어긋나면 알려 준다).

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
  "month": null,
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
    "venues": "048b79beafe886d2",
    "personas": "687c20fc4eaa5b6f",
    "conditions": "81ec9570eef55a09",
    "scenario": "7f0c40802f158f2c",
    "vocab": "8198206734bb16a5",
    "summary": "b2e533d5aec19534",
    "constants": "a45c688652baa74c",
    "prompt": "9fee7d4f42a62d8b"
  },
  "weights": {
    "group_multiplier": {"가족·친족": 210.0},
    "persona_weight": {"family-elders": 105.0},
    "condition_ratio": {"가족·친족": {"meal-dinner-weekend": 1.0}},
    "grades": {
      "group_multiplier": {"가족·친족": "assumption"},
      "persona_weight": {"family-elders": "assumption"},
      "condition_ratio": {"가족·친족": {"meal-dinner-weekend": "assumption"}}
    },
    "people_coverage": 1.0
  },
  "filled_products": [],
  "skipped_products": [],
  "weights_from": null,
  "counts": {"visits": 1, "failed": 0},
  "status": "ok",
  "constants": [
    {"constant_id": "filled-price-unit", "name": "집계 파일로 채운 단가의 반올림 단위", "value": 100, "unit": "원", "grade": "assumption", "sources": [], "checked_on": "2026-11-15", "file": "engine/constants.json"},
    {"constant_id": "base-profile-top-products", "name": "기본 데이터의 요약에 업장마다 적는 상품 수", "value": 3, "unit": "개", "grade": "assumption", "sources": [], "checked_on": "2026-11-15", "file": "engine/constants.json"},
    {"constant_id": "base-profile-bucket-high", "name": "비중을 높음(high)으로 보는 선", "value": 1.5, "unit": "배", "grade": "assumption", "sources": [], "checked_on": "2026-11-15", "file": "engine/constants.json"},
    {"constant_id": "base-profile-bucket-mid", "name": "비중을 보통(mid)으로 보는 선", "value": 0.5, "unit": "배", "grade": "assumption", "sources": [], "checked_on": "2026-11-15", "file": "engine/constants.json"},
    {"constant_id": "takeout-teams-per-item", "name": "인원이 빈 칸인 포장 한 개가 나타내는 팀 수", "value": 1, "unit": "팀", "grade": "assumption", "sources": [], "checked_on": "2026-11-19", "file": "engine/constants.json"},
    {"constant_id": "add-on-people-per-item", "name": "인원이 빈 칸인 추가 상품 한 개가 나타내는 사람 수", "value": 0, "unit": "명", "grade": "assumption", "sources": [], "checked_on": "2026-11-19", "file": "engine/constants.json"},
    {"constant_id": "calibration-top-venue-must-match", "name": "보정 통과: 가장 큰 업장이 같아야 하는가", "value": true, "unit": null, "grade": "assumption", "sources": [], "checked_on": "2026-11-17", "file": "engine/constants.json"},
    {"constant_id": "calibration-max-diff-pp", "name": "보정 통과: 업장별 비중 차이의 한도", "value": 15, "unit": "%p", "grade": "assumption", "sources": [], "checked_on": "2026-11-17", "file": "engine/constants.json"},
    {"constant_id": "calibration-diff-min-personas", "name": "보정 통과: 업장별 차이를 따지는 최소 페르소나 수", "value": 2, "unit": "명", "grade": "assumption", "sources": [], "checked_on": "2026-11-17", "file": "engine/constants.json"},
    {"constant_id": "share-sharpness-k", "name": "방문의 몫을 낼 때 AI 점수에 거는 지수 (날카로움 k)", "value": 1, "unit": null, "grade": "assumption", "sources": [], "checked_on": "2026-11-20", "file": "engine/constants.json"},
    {"constant_id": "meal-lunch-dinner", "name": "집계 파일에서 끼니가 비어 있는 식사 매출", "value": {"lunch": 0.5, "dinner": 0.5}, "unit": null, "grade": "assumption", "sources": [], "checked_on": "2026-11-13", "file": "engine/conditions.json"}
  ],
  "baseline_answers": null,
  "share_method": "single"
}
```

**상관없는 방문의 답** (11-19 wilstein91 결정, T210. 임시 규칙)

- 기준이 아닌 상황에서 방문 하나를 돈 뒤, 기준에서 고른 곳과 상황에서 고른 곳 둘 다 상황이 바꾼 업장(상황 정의의 `changes` 의 `venue_id`)이 아니면,
  그 방문의 원장은 기준 실행의 원장 줄로 적는다 (`run_id`·`scenario_id` 는 이 실행의 것, `llm_call` 은 `replay`). 기준의 저장된 답을 이 실행의 `llm/` 에도 베껴 둔다.
  그런 방문은 `baseline_answers` 에 적는다. 한쪽이라도 실패했거나 요청이 같아 이미 기준의 답을 재생한 방문은 해당하지 않는다.
- 까닭: 방문마다 답이 하나라, 바꾼 업장과 상관없는 방문의 답이 LLM 의 흔들림으로 달라지면 상황의 효과처럼 보인다 (매출 변화 나누기의 "주문 변화", 10.6절).
  답이 하나로는 흔들림과 진짜 변화(고르지 않는 업장이 바뀌어 남은 업장 사이의 판단이 바뀌는 것)를 가를 수 없어 상관없는 변화는 두지 않는다.
- LLM 은 그대로 부른다 (어디를 고를지는 물어야 안다). 이 상황에서 받은 답은 지우지 않고 `llm/` 에 남는다.
- 없애는 조건: 개선 2단계에서 비율로 고르게 되면 이 규칙을 없애고, 흔들림 폭보다 큰 변화만 효과로 본다 (진행 문서의 T212).

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
| `list_price`, `discount` | 단위당 표시가, 이 줄에서 깎인 금액. 추가 상품 줄의 `discount` 는 늘 0 이다 (11-16 회의. 3절). 형식 검사가 저장된 응답과 견줘 본다 |
| `paid` | 고객이 낸 금액 (세금 포함). 경쟁 업장이면 그곳에 낸 금액이다 |
| `revenue_net` | **워커힐의** 세금을 뺀 매출. 경쟁 업장과 "이용하지 않음"은 0 |
| `represented` | 이 방문이 대표하는 크기 = 페르소나의 가중치 × 묶음의 비율 |
| `counted_share` | 그 업장·상품의 것으로 세는 파는 달의 몫. 일 년 내내 팔면 1, 일부 달만 팔면 파는 달 수 ÷ 12. 조건에 `month` 가 있으면 그 달의 방문이라 1 이다 |
| `choice_share` | 방문이 이 곳으로 간 몫 (0 ~ 1. 11-20, T212. 9절의 "점수와 몫"). 답 하나로 고른 방문(1단계 방식)은 1 이다. 11-20 전의 원장에는 이 열이 없어 1 로 읽는다 |
| `score` | 이 곳에 AI 가 적은 점수 (0 ~ 100). 1단계 방식의 답과 응답 없이 엔진이 정한 줄은 빈 칸이다. 11-20 전의 원장에는 이 열이 없다 |
| `season_gap_of` | 일부 달에만 파는 곳의 나머지 몫을 센 "이용하지 않음" 줄이면 그 곳의 `venue_id`. 그 밖에는 빈 칸이다. 11-20 전의 원장에는 이 열이 없다 (그 원장의 그런 줄은 `reason_text` 로 가른다) |
| `weighted_revenue` | `revenue_net` × `represented` × `counted_share` × `choice_share`. 원 단위로 반올림해 적는다 |
| `reason_labels`, `reason_text`, `used_attributes` | 응답에서 온 이유. 라벨과 속성이 여럿이면 `;` |
| `llm_call` | `new` 새로 부름, `replay` 저장된 응답을 재생 |
| `request_hash` | 저장된 응답의 파일 이름 |
| `status`, `fail_reason` | `ok` 또는 `failed`, 실패한 이유 |

- **방문은 몫으로 나뉘어 여러 곳에 간다** (11-20, T212). 몫이 0 보다 큰 곳마다 그곳의 주문을 줄로 적고, 그 줄들의 `choice_share` 에 그곳의 몫을 적는다.
  "이용하지 않음"의 몫은 `choice_kind` 가 `none` 인 줄 하나다 (`season_gap_of` 는 빈 칸). 몫이 0 인 곳은 줄이 없다.
  고른 이유(`reason_labels`, `reason_text`, `used_attributes`)는 응답의 `choice` 에 적은 곳의 줄에만 적고, 다른 곳의 줄은 비어 있다.
  곳마다의 주문은 "그곳에 간다면"의 주문이라, 예산·인원·수량 같은 조건은 곳마다 따로 본다 (곳의 금액을 더해 예산과 견주지 않는다).
  곳마다의 `choice_share` 를 더하면 1 이다. 답 하나로 고른 방문(1단계 방식)은 고른 곳 하나의 `choice_share` 가 1 이라 11-20 전과 같은 줄이 된다.
- 일부 달에만 파는 업장·상품을 고르면 그 곳의 줄을 하나 더 만든다: `choice_kind` 는 `none`, `counted_share` 는 1 에서 위의 몫을 뺀 값,
  `choice_share` 는 그 곳의 몫, `season_gap_of` 는 그 곳의 `venue_id`, `reason_text` 는 "파는 달이 아님". 나머지 몫을 "이용하지 않음"으로 세기 위해서다 (PRD 7.2절).
- **한 곳의 파는 달의 몫은 더해서 1 이다.** 한 곳에서 고른 줄들은 `counted_share` 가 같다. 그 값이 1 이면 그 곳의 "파는 달이 아님" 줄이 없고,
  1 보다 작으면 그 줄이 꼭 하나 있다. "이용하지 않음"의 줄은 `counted_share` 가 1 이다.
  몫은 방문이 어디로 갔는지를 세는 값이라 방문에 하나다. 그래서 엔진은 주문 하나에 파는 달이 서로 다른 상품을 함께 넣지 않고,
  추가 상품의 줄에도 고른 주문과 같은 몫을 적는다.
  주문 없이 추가 상품만 고른 방문(9절)의 몫은 고른 상품을 모두 함께 파는 달 수 ÷ 12 다. 함께 파는 달이 없으면 그 답은 실패다.
  주문에 더한 추가 상품은 그 주문을 파는 달에 모두 파는 것이어야 한다. 아니면 그 답은 실패다 (9절의 "추가 상품과 파는 달").
- 모든 합계는 이 원장에서 낸다. 업장별 가상 매출은 `weighted_revenue` 를 업장별로 더한 값이다. 합계에는 `status` 가 `ok` 인 줄만 넣는다.
- **실패한 방문은 줄 하나로만 남긴다.** `status` 는 `failed`, `fail_reason` 에 이유, `choice_kind` 는 `none`, 업장·상품은 빈 칸, 수량과 금액은 모두 0 이다.
  한 방문에 `ok` 인 줄과 `failed` 인 줄을 섞지 않는다. `fail_reason` 은 실패한 줄에만 적는다.
  저장된 응답의 파일을 찾았는데 쓰지 못해 실패한 방문은 `llm_call` 과 `request_hash` 를 적고 실행 기록의 `calls_replayed` 에 센다.
  응답이 검사에서 어긋난 경우, 파일을 읽을 수 없는 경우, 파일의 요청이 해시와 맞지 않는 경우가 그렇다.
  LLM 을 새로 불렀는데 실패한 방문(호출이 실패했거나 답이 어긋남)은 `llm_call` 이 `new` 다.
  실패한 줄의 `request_hash` 가 가리키는 파일은 `llm/` 에 없다. 검사에서 어긋난 응답이면 `llm_rejected/` 에 있고 (10.3절),
  읽을 수 없는 파일이거나 답을 받지 못한 호출이면 어디에도 없다.
- **원장은 저장된 응답에서 나온 것이어야 한다.**
  - 업장을 고른 줄에는 `request_hash` 가 반드시 있다. 업장을 고르는 것은 LLM 의 응답뿐이기 때문이다.
    `llm_call` 과 `request_hash` 를 함께 비우는 줄은 두 가지뿐이다 (둘은 늘 함께 있거나 함께 비어 있다).
    후보가 하나도 없어 엔진이 응답 없이 "이용하지 않음"으로 정한 방문 (`reason_text` 는 "후보가 없음"),
    그리고 LLM 을 부르지 않고 재생만 했는데 저장된 응답이 없어 실패한 방문이다.
  - 한 방문의 줄들은 `request_hash` 가 가리키는 저장된 응답(10.3절)과 같아야 한다:
    요청의 페르소나와 조건, 응답이 고른 업장, 고른 주문의 줄(상품, 수량, 단위, 단가, 할인, 금액), 고른 추가 상품(상품, 수량, 단위, 단가), 이유.
    손으로 고친 원장을 걸러 내려는 것이다. 위의 "파는 달이 아님" 줄은 이유가 따로라 이유를 견주지 않는다.
- 아래 예시의 두 줄은 서로 다른 실행의 원장에서 한 줄씩 가져온 것이다. 원장 파일 하나에는 실행 하나의 줄만 들어간다.

```csv
run_id,scenario_id,visit_id,persona_id,customer_group,condition_id,choice_kind,venue_id,product_id,quantity,unit,list_price,discount,paid,revenue_net,represented,counted_share,choice_share,score,season_gap_of,weighted_revenue,reason_labels,reason_text,used_attributes,llm_call,request_hash,status,fail_reason
20261117-101500-baseline,baseline,family-elders__meal-dinner-weekend,family-elders,가족·친족,meal-dinner-weekend,walkerhill,geumryong,course-a,4,1인,150000,0,600000,545455,105.0,1.0,1.0,,,57272775,별실;주차·접근,어르신을 모시는 자리라 별실이 있고 차로 오기 편한 곳을 골랐다.,visit.purposes;preferences.needs,new,44f617297b40af86,ok,
20261117-103000-competitor-chinese-discount,competitor-chinese-discount,family-elders__meal-dinner-weekend,family-elders,가족·친족,meal-dinner-weekend,competitor,examplehotel-chinese,course,4,1인,140000,56000,504000,0,105.0,1.0,1.0,,,0,혜택·할인,할인 폭이 커서 이번에는 다른 호텔로 갔다.,buying.price_sensitivity,new,4f37e77301272ce3,ok,
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
  실행하는 명령(`python -m engine`)은 같은 `data_mode` 의 앞선 실행들의 `llm/` 을 찾는다. 재생한 응답은 그 실행의 `llm/` 에도 베껴 둔다.
- **찾는 순서** (11-18, T121): `--answers` 로 가리킨 폴더, 그다음 먼저 돌린 실행부터다. 기준이 아닌 상황은 그 앞에 기준 실행의 `llm/` 을 가장 먼저 찾는다.
  같은 요청의 답이 여러 실행에 있으면 가장 먼저 받은 답을 쓴다. 그래서 상황의 변경과 상관없는 방문(요청이 기준과 같다)은 기준의 답을 그대로 재생하고,
  기준 상황을 다시 재생해도 나중에 돌린 상황의 답이 끼어들지 않는다.
- **요청에 `scenario_id` 가 든 옛 모양의 답** (11-18 전에 받은 것)은 해시가 달라 재생되지 않는다. 한 번 변환한다: `uv run python -m tools.rehash_answers`
  (요청에서 `scenario_id` 를 지우고 `request_hash`·파일 이름·원장의 `request_hash` 칸을 새 해시로 바꾼다. 답의 내용은 그대로다. LLM 을 부르지 않는다).
  변환하지 않은 폴더가 있으면 엔진은 돌리기 전에 멈추고 알린다. 받아 둔 압축은 풀어서 변환한다.
- 팀원끼리 이 폴더를 저장소 밖의 경로로 주고받으면 키가 없는 사람도 같은 결과를 재생할 수 있다.
- `created_at` 은 그 응답을 받은 실행의 시각이다. `usage` 는 공급자가 알려 준 값이고, LLM 이 답한 것이 아닌 "정해 둔 답"은 0 이다.
- `llm/` 에는 검사(9절)를 통과한 응답만 둔다. 받자마자 저장하므로 실행이 도중에 멈춰도 받은 답은 남는다.

**어긋난 응답 `llm_rejected/<request_hash>.json`** (11-14 에 정함) — 검사에서 어긋난 응답은 여기에 따로 남긴다.
프롬프트를 고칠 때 LLM 이 실제로 뭐라고 답했는지 보려는 것이다. 재생에는 쓰지 않으므로 다음 실행은 그 요청을 다시 부른다.

| 키 | 뜻 |
|---|---|
| `format_version`, `request_hash`, `provider`, `model`, `created_at`, `request`, `raw_text`, `usage` | 저장된 응답과 같다 |
| `llm_call` | `new` 이번 실행에서 새로 받은 답, `replay` 저장된 응답을 재생하다 어긋난 것 |
| `problems` | 어긋난 곳을 적은 문장의 목록. 하나 이상. 원장의 `fail_reason` 은 이것을 `; ` 로 이은 글이다 |

- `response` 는 없다. 글을 응답으로 읽지 못한 것도 여기에 남기 때문이다.
- 이 파일이 있으면 원장에 같은 `request_hash` 의 실패한 줄이 있다. 한 실행에서 같은 요청이 `llm/` 과 `llm_rejected/` 에 함께 있을 수 없다.
- 읽을 수 없는 저장 파일과 답을 받지 못한 호출은 남길 글이 없어 여기에 없다. 원장의 `fail_reason` 에만 이유가 남는다.

### 10.4 보정의 대조 결과 `calibration.json`

```json
{
  "format_version": 1,
  "run_id": "20261117-101500-baseline",
  "criteria": {"top_venue_must_match": true, "max_diff_pp": 15, "diff_min_personas": 2},
  "groups": {
    "가족·친족": {
      "venues": {
        "geumryong": {"sim_share": 0.3, "base_share": 0.25, "diff_pp": 5.0},
        "thebuffet": {"sim_share": 0.7, "base_share": 0.75, "diff_pp": -5.0}
      },
      "top_sim": "thebuffet",
      "top_base": "thebuffet",
      "personas": 2,
      "pass": true
    }
  },
  "uncovered_groups": [],
  "pass": true
}
```

**대조 결과를 내는 법** (11-17 에 넣음, T116. `engine/calibration.py`) — `uv run python -m engine.calibration --data <sample|private>` 가 기준 실행 하나를 견줘 그 실행 폴더에 이 파일을 쓴다 (PRD 6.5절). LLM 을 부르지 않는다.

- **대조하는 실행**: 적지 않으면 일 년 전체로 끝까지 돈 가장 새 기준 실행이다 (`--run <run_id>` 로 가리킬 수 있다). 같은 실행을 다시 대조하면 파일을 덮어쓴다.
- **대조하지 않고 멈추는 때**: 기준 상황이 아니거나, 끝까지 돌지 않았거나, 실패한 방문이 있거나, 달을 주고 돌렸거나(10.1절의 "실행의 달"),
  실행 뒤에 입력(`inputs` 의 `venues`, `personas`, `conditions`, `scenario`, `vocab`, `summary`, `constants`)이 달라졌을 때다. 업장을 골라 돌린 실행(`--venues`)도 읽은 업장이 달라 멈춘다.
  비중의 분모가 워커힐 업장 전체여야 하기 때문이다. 화면에서 조건을 직접 넣어 돌린 실행(`manual-`)도 멈춘다. 조건의 일부만 돌린 실행은 대조한다 (돌린 조건의 매출끼리 견준다).
- **대조하는 고객군** (`groups`): 저장소에 페르소나가 있는 고객군 모두다. 그 고객군의 페르소나 가운데 실행에 빠진 것이 있으면, 비중은 돌린 페르소나만으로 적되 **통과가 아니다**.
  한 고객군을 일부 페르소나로 맞춘 결과는 보정의 근거가 아니다. 하나도 돌리지 않은 고객군은 가상 매출이 없는 것으로 적힌다. 명령이 돌리지 않은 페르소나를 알린다.
- **가상 매출 쪽** (`sim_share`): 그 고객군의 원장에서 워커힐 업장마다 `weighted_revenue` 를 더한 값의 비중이다 (`engine.ledger.venue_shares`).
- **기본 데이터 쪽** (`base_share`): 집계 파일에서 그 고객군의 워커힐 업장마다의 매출 비중이다 (`engine.weights.group_venue_revenue`).
  가중치의 인원을 셀 때와 같은 줄을 같은 몫으로 센다 (10.1절의 "쓰는 인원": 읽은 워커힐 업장의 줄만, 돌리는 조건에 드는 몫만, 조식은 뺀다).
  견주는 것은 고객군마다 매출이 업장 사이에 나뉜 모양(비중)이다. 11-19(T210)부터 가중치를 인원으로 정해 고객군의 합계는 두 쪽이 같지 않을 수 있다 (그 차이는 대조에 들지 않는다).
- `venues` 에는 읽은 워커힐 업장을 모두 적는다. 어느 쪽에도 매출이 없는 업장은 0 이다. 경쟁 업장과 "이용하지 않음"은 넣지 않는다.
- 비중은 소수 넷째 자리, `diff_pp` (가상 − 기본, %p)는 둘째 자리까지 적는다. `top_sim`, `top_base` 는 적힌 비중이 가장 큰 업장이고, 그쪽에 매출이 없으면 `null` 이다.
  적힌 비중이 같으면 업장 정의의 차례에서 앞의 것이다. 가장 큰 업장과 통과 여부는 모두 파일에 적힌 값으로 정하므로, 파일만 보고 다시 낼 수 있다.
- **통과** (`pass`): `top_sim` 과 `top_base` 가 같고, 적힌 `diff_pp` 의 크기가 모두 `max_diff_pp` 이내다. 어느 한쪽에 매출이 없는 고객군은 견줄 수 없어 통과가 아니다
  (그 고객군이 워커힐 업장을 고른 방문이 없거나, 집계 파일에 그 고객군의 매출이 없다). 맨 위의 `pass` 는 고객군이 모두 통과일 때다.
- **페르소나 수** (`personas`): 저장소에 있는 그 고객군의 페르소나 수다 (실행에서 돌린 수가 아니다). 이 수가 `criteria.diff_min_personas` 보다 작은 고객군은
  `diff_pp` 를 적기만 하고 통과를 가르는 데 쓰지 않는다. 가장 큰 업장이 같은지만 본다 (11-17 에 고침, PRD 6.5절과 `PROGRESS.md` 의 T18).
  두 칸이 없는 옛 파일(11-17 의 첫 대조)은 `diff_min_personas` 를 1 로, `personas` 를 모르는 것으로 읽어 모든 고객군의 차이를 본 것으로 둔다.
- **통과 기준** (`criteria`)은 결정 상수 파일에 적혀 있다 (6.1절의 `engine/constants.json`. 11-19 까지는 `engine/calibration.py` 의 코드에 있었다, T210). 명령의 인자로 바꿀 수 없다. 첫 대조 뒤 한 번만 고칠 수 있고, 고치면 이유를 진행 문서의 T18 절에 적는다 (PRD 6.5절).
- 기본 데이터로 돌린 실행의 대조 결과는 `private/runs/<run_id>/` 에만 있다. 명령이 화면에 적는 고객군별 결과에도 기본 데이터에서 계산한 값이 있으니 저장소의 파일에 옮겨 적지 않는다.

`uncovered_groups` 에는 페르소나가 없어 다루지 않은 고객군을 적는다. 집계 파일에 매출이 있는 고객군 가운데 저장소에 페르소나가 하나도 없는 것이다 (페르소나는 있는데 그 실행에서 돌리지 않은 고객군은 `groups` 에 미달로 든다). 화면이 이것을 "다루지 않은 고객군"으로 보여 준다.

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
      "reason_n": 6,
      "reason_enough": true,
      "reason_match": 4,
      "reason_match_baseline": 3
    },
    "pizzahill": {
      "n": 9,
      "enough": true,
      "venue_match": 5,
      "venue_match_baseline": 6,
      "reason_n": 2,
      "reason_enough": false,
      "reason_match": null,
      "reason_match_baseline": null
    },
    "thebuffet": {
      "n": 3, "enough": false, "venue_match": null, "venue_match_baseline": null,
      "reason_n": 1, "reason_enough": false, "reason_match": null, "reason_match_baseline": null
    }
  },
  "total": {
    "n": 24,
    "venue_match": 15,
    "venue_match_baseline": 14,
    "reason_n": 9,
    "reason_match": 5,
    "reason_match_baseline": 4
  }
}
```

값은 비율이 아니라 건수다. 업장 일치는 `n` 건 가운데 몇 건, 이유 일치는 `reason_n` 건 가운데 몇 건이다 (11-17, T117).

- `n`: 그 업장의 떼어 둔 후기 가운데 돌린 것 (`skipped` 가 빈 후기). `enough` 는 `n` 이 `min_reviews` 이상인가다.
  `enough` 가 `false` 면 `venue_match`, `venue_match_baseline` 은 `null` 이고 화면에 "검증 건수 부족"으로 보여 준다.
- `reason_n`: `n` 건 가운데 고른 이유 라벨(`reasons_chosen`)이 있는 후기. 이유 일치는 이 후기로만 잰다 (PRD 6.6절). `reason_enough` 는 `reason_n` 이 `min_reviews` 이상인가다.
  `reason_enough` 가 `false` 면 `reason_match`, `reason_match_baseline` 은 `null` 이다. 업장 일치는 잴 수 있어도 이유 일치는 "검증 건수 부족"일 수 있다 (위의 `pizzahill`).
- `total`: 모든 업장을 합친 건수. 검증 건수가 모자란 업장의 후기도 들어간다. 그래서 `total` 의 일치 건수는 업장에 적힌 건수의 합보다 클 수 있다.
  다만 건수가 `null` 인 업장의 분모(`n` 또는 `reason_n`)를 더한 것보다 클 수는 없다. `n`, `reason_n` 은 업장들의 합과 같다.
  업장마다 이유 일치의 건수가 모자라도 `total` 로는 견줄 수 있다. `total` 에도 5건 기준은 같다: `total` 의 `reason_n` 이 `min_reviews` 보다 작으면 합친 이유 일치도 "검증 건수 부족"으로 보인다.

**후기 한 건마다의 결과** `validation_reviews.csv`

| 열 | 뜻 |
|---|---|
| `review_id`, `venue_id`, `customer_group` | 떼어 둔 후기 |
| `persona_id` | 돌린 페르소나. 그 고객군에 페르소나가 둘이면 후기의 `purpose`, `party` 가 더 많이 겹치는 쪽, 같으면 몫이 큰 쪽 (PRD 6.6절). 후기에 비어 있는 칸은 겹치지 않는 것으로 센다 |
| `occasion`, `meal`, `day_type` | 돌린 조건. 후기에 끼니나 요일이 비어 있으면 그 페르소나의 `visit.meals`, `visit.day_types` 의 첫 값을 쓴다 |
| `chosen_venue_id` | 페르소나가 고른 곳. "이용하지 않음"이면 빈 칸 |
| `venue_match`, `reason_match` | 업장이 같은가, 이유 라벨이 하나 이상 겹치는가 (`Y`, `N`). 후기에 고른 이유 라벨이 없으면 `reason_match` 는 빈 칸이다 (11-17, T117) |
| `baseline_venue_id`, `baseline_venue_match`, `baseline_reason_match` | 단순 기준이 고른 곳과 그 결과. 후기에 고른 이유 라벨이 없으면 `baseline_reason_match` 는 빈 칸이다 |
| `skipped` | 돌리지 못한 이유. 고객군이 비어 있거나 그 고객군에 페르소나가 없으면 적는다. 이런 후기는 `n` 에서 빼고, 돌린 결과의 칸(`persona_id` 부터 `baseline_reason_match` 까지)은 모두 빈 칸이다 |

### 10.6 매출 변화 나누기 `changes.json`

상황 실행(기준이 아닌 실행)이 끝나면 엔진이 그 실행 폴더에 함께 쓴다 (`engine/changes.py`, T210). 기준 실행(`weights_from`)과 견준 워커힐의 가상 매출 변화를
워커힐 업장마다 갈래로 나눈 것이다 (PRD 8절의 1단계). LLM 을 부르지 않는다. 기준 실행에는 없다.
화면이 읽는다 (`app/breakdown.py`, T124). 화면은 이 파일의 합이 두 원장으로 낸 변화와 다르면 나누기를 보이지 않는다.
11-19 현재 방문마다의 갈래(`visits`)는 화면이 아직 쓰지 않는다.

```json
{
  "format_version": 1,
  "run_id": "20261117-103000-competitor-chinese-discount",
  "baseline_run_id": "20261117-101500-baseline",
  "excluded_visits": [],
  "walkerhill": {
    "new": 0,
    "from_competitor": 0,
    "from_walkerhill": 0,
    "to_competitor": -57272775,
    "to_walkerhill": 0,
    "to_none": 0,
    "price": 0,
    "order": 0,
    "total": -57272775
  },
  "venues": [
    {
      "venue_id": "geumryong",
      "before": 57272775,
      "after": 0,
      "parts": {
        "new": 0,
        "from_competitor": 0,
        "from_walkerhill": 0,
        "to_competitor": -57272775,
        "to_walkerhill": 0,
        "to_none": 0,
        "price": 0,
        "order": 0,
        "total": -57272775
      }
    }
  ],
  "visits": [
    {
      "visit_id": "family-elders__meal-dinner-weekend",
      "represented": 105.0,
      "before": {
        "kind": "walkerhill",
        "venue_id": "geumryong"
      },
      "after": {
        "kind": "competitor",
        "venue_id": "examplehotel-chinese"
      },
      "before_shares": [
        {
          "kind": "walkerhill",
          "venue_id": "geumryong",
          "share": 1.0
        }
      ],
      "after_shares": [
        {
          "kind": "competitor",
          "venue_id": "examplehotel-chinese",
          "share": 1.0
        }
      ],
      "parts": [
        {
          "venue_id": "geumryong",
          "part": "to_competitor",
          "amount": -57272775
        }
      ],
      "promo": "none",
      "promo_shares": {
        "would_come": 0.0,
        "drawn": 0.0
      }
    }
  ]
}
```

| 키 | 뜻 |
|---|---|
| `run_id` | 이 상황 실행 |
| `baseline_run_id` | 견준 기준 실행. 실행 기록의 `weights_from` 과 같다 |
| `excluded_visits` | 두 실행 모두에서 뺀 방문의 `visit_id` (아래 "나누는 법") |
| `walkerhill` | 워커힐 전체의 갈래별 금액(아래 갈래 표의 키 여덟 개)과 `total`. 업장들의 값을 더한 것이다 |
| `venues[].venue_id` | 워커힐 업장. 두 실행 어느 쪽에서도 그 업장을 고른 방문이 없으면 적지 않는다 |
| `venues[].before`, `venues[].after` | 그 업장의 기준과 상황의 가상 매출 (원) |
| `venues[].parts` | 그 업장의 갈래별 금액과 `total` (`after` − `before`) |
| `visits[].visit_id`, `visits[].represented` | 방문(페르소나 × 조건)과 그 방문이 대표하는 팀 수. 두 실행에서 같다 |
| `visits[].before`, `visits[].after` | 방문이 간 곳 가운데 몫이 가장 큰 곳 (같으면 워커힐, 경쟁, 이용하지 않음 순서, 그다음 `venue_id` 순서). `kind` 는 `walkerhill`, `competitor`, `none` 이고, `venue_id` 는 `none` 이면 `null` 이다. 답 하나로 고른 방문은 그 곳이다 |
| `visits[].before_shares`, `visits[].after_shares` | 방문이 간 곳마다 `kind`, `venue_id`, `share` (원장의 `choice_share`. 11-20, T212). 몫이 0 인 곳은 없다. 11-20 전의 파일에는 없다 |
| `visits[].parts` | 그 방문이 든 갈래: `venue_id`, `part`(갈래의 키), `amount`(원). 금액이 바뀌지 않은 방문도 적는다 (`parts` 가 비거나 금액이 0 이다) |
| `visits[].promo` | 상황에서 워커힐 업장의 할인을 받았는지로 본 방문의 구분 (11-20 wilstein91 결정, T215. 화면의 "혜택이 없어도 올 고객", PRD 3절): `none` 상황에서 워커힐 업장의 할인을 받지 않았다, `would_come` 기준에서도 그 업장을 고르던 방문이 할인을 받았다, `drawn` 기준에서는 그 업장을 고르지 않던 방문이 할인을 받으며 그 업장을 골랐다. 할인은 원장의 `discount` 가 0 보다 큰 줄이 있는지로 본다 (기존 프로모션의 할인도 든다). 방문이 몫으로 나뉘면 아래 `promo_shares` 의 두 몫 가운데 큰 쪽이다 (같으면 `would_come`, 둘 다 0 이면 `none`) |
| `visits[].promo_shares` | 상황에서 워커힐 업장의 할인을 받은 몫 (11-20, T212): `would_come` 기준에도 그 업장에 있던 몫(두 실행의 그 업장 몫 가운데 작은 쪽), `drawn` 상황에서 늘어난 몫. 할인을 받은 업장마다 더한다. 11-20 전의 파일에는 없다 |

**갈래** — 방문 하나가 기준에서 상황으로 어디에 갔나로 정한다. 금액은 원 단위 정수이고 세금을 뺀 가상 매출이다.
아래 표는 답 하나로 고른 방문(몫이 0 아니면 1)의 경우다. 몫으로 나뉜 방문은 아래 "몫으로 나뉜 방문"의 규칙으로 같은 갈래에 나눈다.

| 갈래 | 키 | 방문이 간 곳 (기준 → 상황) | 금액 |
|---|---|---|---|
| 새로 들어온 매출 | `new` | 이용 안 함 → 이 업장 | 상황의 매출 (0 이상) |
| 옮겨 온 매출(경쟁에서) | `from_competitor` | 경쟁 업장 → 이 업장 | 상황의 매출 (0 이상) |
| 옮겨 온 매출(워커힐 안에서) | `from_walkerhill` | 다른 워커힐 업장 → 이 업장 | 상황의 매출 (0 이상) |
| 잃은 매출(경쟁으로) | `to_competitor` | 이 업장 → 경쟁 업장 | −(기준의 매출) (0 이하) |
| 잃은 매출(워커힐 안으로) | `to_walkerhill` | 이 업장 → 다른 워커힐 업장 | −(기준의 매출) (0 이하) |
| 잃은 매출(이용 안 함으로) | `to_none` | 이 업장 → 이용 안 함 | −(기준의 매출) (0 이하) |
| 가격 효과 | `price` | 이 업장 → 이 업장. 고른 상품, 수량, `counted_share` 가 같고 가격이나 할인만 달랐다 | 상황 − 기준 (어느 쪽도 된다) |
| 주문 변화 | `order` | 이 업장 → 이 업장. 상품이나 수량이 달랐다 | 상황 − 기준 (어느 쪽도 된다) |

**나누는 법**

- 방문(`visit_id`)마다 두 실행의 원장을 견준다. 두 실행은 같은 페르소나·조건·가중치로 돌아 방문마다 대표하는 팀 수가 같다.
  그래서 갈래는 방문이 "어디에 갔나"만 견줘 정하고, 금액은 원장의 `weighted_revenue` 를 방문·업장마다 더해 원 단위로 반올림한 것이다.
- 한쪽 실행에서라도 실패했거나(`status` 가 `ok` 가 아니다) 한쪽에만 있는 방문은 두 실행 모두에서 빼고 `excluded_visits` 에 적는다 (화면의 비교와 같다).
- 워커힐 안에서 옮긴 방문은 두 업장에 한 번씩 적힌다 (떠난 곳에 `to_walkerhill`, 온 곳에 `from_walkerhill`). `walkerhill` 에서 둘을 더하면 옮기면서 달라진 금액만 남는다.
- PRD 8절의 넷으로 보일 때는 `from_competitor` 와 `from_walkerhill` 을 더해 옮겨 온 매출, `to_` 로 시작하는 셋을 더해 잃은 매출, `price` 와 `order` 를 더해 단가 효과로 묶는다.

**몫으로 나뉜 방문** (11-20 wilstein91 결정, T212. 비례 배분) — 방문 하나에서 워커힐 업장 하나의 몫이 기준 `b`, 상황 `a` 이고 그 업장의 가중 매출이 `B`, `A` 일 때:

- 남은 몫 `min(b, a)` 의 금액 차이 `A × min/a − B × min/b` 는 가격 효과(`price`)나 주문 변화(`order`)다. 고른 상품·수량·`counted_share` 가 같으면 가격 효과다.
- 몫이 늘었으면(`a > b`) 늘어난 몫의 금액 `A × (a − b)/a` 를, 이 업장을 뺀 곳들 가운데 몫이 줄어든 곳들이 줄어든 만큼에 비례해 나눈다:
  "이용하지 않음"이 준 몫은 `new`, 경쟁 업장이 준 몫은 `from_competitor`, 다른 워커힐 업장이 준 몫은 `from_walkerhill`.
- 몫이 줄었으면(`b > a`) 줄어든 몫의 금액 `−B × (b − a)/b` 를, 몫이 늘어난 곳들이 늘어난 만큼에 비례해 나눈다 (`to_none`, `to_competitor`, `to_walkerhill`).
- "비례로 옮겼다"는 것은 가정이다. AI 는 어디서 어디로 옮겼는지 따로 말하지 않는다. 결과를 보일 때 이 가정을 함께 적는다.
- 금액은 원 단위로 반올림하되, 방문·업장마다 갈래의 합이 그 업장의 `A` 와 `B` 를 반올림한 값의 차이와 같게 한다 (나머지가 큰 갈래부터 1원씩 맞춘다).
- 파는 달이 아닌 몫(원장의 `season_gap_of`)은 그 곳의 몫 안에서 금액으로만 들어간다. 그래서 몫을 견줄 때는 원장의 `choice_share` 만 본다.
- 답 하나로 고른 방문은 이 규칙이 위의 갈래 표와 같은 결과를 낸다 (남은 몫이 1 이면 가격 효과나 주문 변화, 0 이면 온 곳이나 간 곳 하나로 모두 간다).

**맞아야 하는 것** — 모델(`engine/formats/changes.py`)이 읽을 때 본다. 남는 금액이 없다.

- 업장마다 갈래를 모두 더하면 `parts.total` 이고, `parts.total` 은 `after` − `before` 다.
- 업장들의 갈래와 `total` 을 더하면 `walkerhill` 의 같은 키다.
- 방문들의 `parts` 를 업장·갈래마다 더하면 그 업장의 그 갈래 금액이다.
- 형식 검사가 두 실행의 원장으로 다시 나눠 이 파일과 같은지 본다 (11절). 손으로 고치지 않는다.

예 (지어낸 방문 다섯, `tests/test_changes.py`):

| 방문 | 기준 → 상황 | 갈래 |
|---|---|---|
| a | `thebuffet` → `thebuffet`. 같은 상품·수량에 값만 올랐다 | `thebuffet` 의 `price` |
| b | `thebuffet` → 경쟁 뷔페 | `thebuffet` 의 `to_competitor` |
| c | `thebuffet` → `pizzahill` | `thebuffet` 의 `to_walkerhill`, `pizzahill` 의 `from_walkerhill` |
| d | 이용 안 함 → `geumryong` | `geumryong` 의 `new` |
| e | `pizzahill` → `pizzahill`. 다른 상품을 골랐다 | `pizzahill` 의 `order` |

**넷이 아니라 다섯인 까닭** (11-19 wilstein91 결정, T210) — PRD 8절은 넷(새로 들어온 매출, 옮겨 온 매출, 잃은 매출, 단가 효과)으로 나눈다.
여기서는 단가 효과를 가격 효과와 주문 변화로 갈랐다. 팀이 기본 데이터로 돌린 상황 실행에서, 워커힐의 가격이 바뀌지 않은 방문도 같은 업장에서 주문을 바꾼 것이 있었다 (AI 답의 흔들림).
하나로 묶으면 이것이 가격 때문에 생긴 변화처럼 보인다. 상황과 상관없는 방문의 주문 변화는 T210 의 다음 조건(상황과 상관없는 방문은 기준의 답을 쓴다)으로 없앤다.

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
- 결정 상수(6.1절) 가운데 등급이 `official`, `literature`, `statistic`, `industry`, `article` 인 것은 `sources` 에 그 등급과 같은 종류의 자료가 있다 (11-19 T210, 11-20 T214).
  `engine/constants.json` 과 가상 예시 집계 옆의 `data/samples/base_summary_constants.json` 을 같은 규칙으로 본다. 범위 값은 `min` 이 `max` 보다 크지 않다 (11-19, T213).
- 라벨(방문 목적, 동행, 고른 이유, 걸린 점, 고객군)이 값 목록에 있다. 후기 라벨의 방문 목적과 동행은 비어 있어도 된다.
- 후기 라벨의 줄마다 근거가 되는 칸이 하나 이상 있다 (4.1절). `ordered` 와 `compared_with` 의 `이름:` 뒤에는 이름이 있다.
- 페르소나의 `evidence` 에 묶음 일곱 개가 모두 있고, 한 고객군의 `share_in_group.value` 를 더하면 1 이다.
- 묶음의 조건은 `month` 와 `stay` 가 `null` 이고 조식 조건이 없다. 상황의 `our_price`·`our_promo` 는 워커힐 업장만, `competitor` 는 경쟁 업장만 바꾼다.
  상황의 `changes` 를 엔진과 같은 코드로 적용했을 때 업장 정의가 3절의 규칙을 지킨다 (7절).
- 저장된 응답의 요청에서 깎인 줄과 후보의 `promotions` 의 `applied` 가 서로 맞는다 (9절).
- 묶음의 조건으로 돌린 방문은 저장된 응답과 어긋난 응답의 요청의 달(`condition.month`)이 실행 기록의 `month` 와 같다 (10.1절의 "실행의 달").
  달을 준 실행은 고른 줄의 `counted_share` 가 1 이고 `calibration.json` 이 없다. 상황의 `month` 는 `weights_from` 의 실행과 같다.
- 매출 변화 나누기(`changes.json`)는 상황 실행에만 있고, `run_id`·`baseline_run_id` 가 실행 기록과 맞고, 두 실행의 원장으로 다시 나눈 것과 같다 (10.6절. 11-19, T210).
- 예시 묶음의 `engine/samples/runs/` 의 실행 기록은 모두 `data_mode` 가 `sample` 이다. 가중치가 빠짐없이 있고 등급에 `internal` 이 없다.
  가중치와 등급의 키가 같고, 고객군마다 묶음의 비율을 더하면 1 (인원이 없어 낼 수 없으면 모두 0) 이고, 페르소나의 가중치가 고객군 배수 × 고객군 안의 몫이다.
  `filled_products` 의 상품은 업장 정의에서 가격이 빈 상품이다.
  원장의 방문 수가 실행 기록과 맞고, 원장이 저장된 응답과 같다 (10절).
  어긋난 응답(`llm_rejected/`)은 해시가 요청과 맞고, 공급자·모델·상황이 실행 기록과 같고, 같은 요청이 `llm/` 에 없다.
  원장에 그 요청의 실패한 줄이 있고, 그 줄의 `llm_call` 과 `fail_reason` 이 파일의 `llm_call`, `problems` 와 같다.
- 데이터 폴더에 1절의 표에 없는 파일이나 폴더가 없다. 확장자는 소문자다. (빈 폴더를 깃에 남기는 `.gitkeep` 은 둘 수 있다.)

**올리면 안 되는 것** — 깃에 올라갈 수 있는 **모든 파일**을 훑는다. 확장자, 크기, 글자 인코딩, 폴더의 깊이를 가리지 않는다.
깃이 무시하는 것(맨 위의 `private/`, `.env`, `.venv/` 같은 것)만 건너뛴다.

- 어느 파일에도 `P-` 나 `H-` 로 시작하는 후기 번호가 없다. 예시를 적어도 되는 곳은 이 문서와 테스트 코드(`tests/` 의 `.py`)뿐이다.
- 기본 데이터로 돌린 실행 기록(`data_mode` 가 `private`)이 없다. JSON 안에 든 것도, 문서에 글로 붙여 넣은 것도 본다.
  코드나 안내 문서가 이 값을 설명하는 것은 막지 않는다 (실행 기록의 다른 키가 함께 있을 때만 실행 기록으로 본다).
  글로 붙여 넣은 것을 찾는 검사는 후기 번호와 같이 이 문서와 테스트 코드를 예외로 둔다.
- JSON 어디에도 `base_profile` 과 `overridden_by_private` 에 값이 없다 (키가 없거나 비어 있다). 둘 다 기본 데이터로 돌린 결과에만 값이 있다.
- 자리가 정해진 파일이 그 자리 밖에 없다. 파일의 이름이 아니라 **내용으로** 알아본다:
  후기 라벨, 가상 예시 값과 같은 열의 파일, 소비 원장, 실행 기록, 저장된 응답과 어긋난 응답, 보정의 대조 결과.
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
| 9절 선택 요청과 응답 | `addons`, 주문이 없는 후보, 후보의 `promotions` |
| 10.1절 실행 기록, 10.2절 소비 원장, 10.3절 저장된 응답과 어긋난 응답 | `counted_share`, 10.4절 보정, 10.5절 검증 |

**아직 정하지 않은 것**

- [x] 평일과 주말을 나눌 때 공휴일을 어느 달력으로 정할지 (11-13, 한국천문연구원 특일 정보(공공데이터포털). 주말은 토·일·공휴일이고 대체공휴일도 든다. 업장 데이터 담당의 제안을 팀장이 받아들임)
- [x] 폴더 이름의 확정 (11-13, 팀장이 제안대로 확정함. `STRUCTURE.md` 의 폴더 표)
- [x] 방문 조건 묶음에 조식과 투숙 여부를 넣을지 (11-13, 둘 다 넣지 않는다. 6절)
- [x] `assumed_splits` 의 값 (11-13, 팀장이 정함. 끼니를 알 수 없는 식사 매출은 점심 0.5, 저녁 0.5 로 나눈다. 뒷받침하는 자료가 없어 반반으로 두었고 등급은 `assumption` 이다. `engine/conditions.json`)
- [x] 기본 데이터에서 나온 값을 LLM 에 어떻게 보낼지, 곧 `base_profile_mode` 의 기본값 (11-13, 팀장이 정함. 범주로 바꿔 보내는 `bucketed`. 내부 수치가 외부 LLM 과 저장된 응답에 그대로 남지 않게 한다. 10.1절. 11-15 에 T11 에서 붙였다. 요약에 넣는 것은 5절의 "기본 데이터의 요약")
- [ ] 라벨 값 목록의 첫 판 (11-13, 페르소나 담당)
- [ ] 경쟁 업장의 `venue_id` (업장 데이터 담당)
- [x] 추가 상품(`addons`)에 프로모션 할인을 적용할지 (11-16 팀 회의에서 정함. 적용하지 않는다. 3절·9절·10.2절에 적었고,
  형식 검사가 원장의 추가 상품 줄의 할인이 0 이고 낸 금액이 수량 × 표시가인지 저장된 응답과 견줘 본다.
  기본 데이터로는 추가 상품의 할인을 보정에서 맞춰 볼 수 없고, 공개된 프로모션 조건에도 음료 할인이 적혀 있지 않았다)
- [x] 형식을 검사하는 도구 (11-13, `tools/check_formats.py` 를 만들어 예시 파일 한 벌이 `--strict` 로 통과하는 것을 확인함)
