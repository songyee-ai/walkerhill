# 예시 파일 한 벌

[docs/FORMATS.md](../../../docs/FORMATS.md) 의 예시를 그대로 파일로 만든 것이다. 저장소 맨 위와 같은 폴더 구조를 쓴다.

- **여기 든 가격, 비율, 금액, 후기, "예시호텔"은 모두 지어낸 값이다.** 실제 가격도 기본 데이터의 값도 아니다.
  업장 이름이 워커힐의 것이어도 내용은 지어낸 것이다. 진짜 업장 정의는 `data/venues/` 에 업장 데이터 담당이 만든다.
- 자기 파일을 만들 때 여기서 같은 종류의 파일을 베껴서 시작한다.
- 테스트가 이 폴더를 쓴다. 형식 문서의 예시와 이 파일들이 다르면 테스트가 실패한다.
  형식을 바꿀 때는 문서, `engine/formats/` 의 모델, 이 폴더를 함께 고친다.

## 무엇이 들어 있나

| 파일 | 형식 문서의 절 | 비고 |
|---|---|---|
| `data/venues/geumryong.json`, `examplehotel-chinese.json` | 3절 | 문서의 예시 |
| `data/venues/thebuffet.json`, `examplehotel-buffet.json` | 3절 | 문서에 없다. 성인·어린이 가격이 따로인 업장의 예시 |
| `data/evidence/vocab.json`, `data/evidence/reviews/geumryong.csv` | 4절 | 문서의 예시 |
| `personas/family-elders.json` | 5절 | 문서의 예시 |
| `personas/family-kids.json` | 5절 | 문서에 없다. 같은 고객군의 둘째 페르소나이고, 후기 근거가 없는 경우("이유 근거 부족")의 예시 |
| `personas/prompts/p1.md` | 9절 | 문서에 없다. 프롬프트의 예시. 엔진은 이 글을 시스템 프롬프트로 그대로 보낸다 |
| `engine/conditions.json` | 6절 | 문서의 예시 |
| `scenarios/baseline.json` | 7절 | 문서에 없다. 기준 상황 |
| `scenarios/geumryong-course-price-up.json`, `competitor-chinese-discount.json` | 7절 | 문서의 예시 |
| `data/samples/base_summary.csv` | 8절 | 문서의 예시 |
| `engine/samples/runs/20261117-101500-baseline/` | 9절, 10절 | 실행 기록, 원장, 저장된 응답, 보정 결과. 문서의 예시. 보정 결과를 뺀 나머지는 엔진이 쓴 것 |
| `engine/samples/runs/20261117-103000-competitor-chinese-discount/` | 10절 | 원장은 문서의 예시 둘째 줄이다. 엔진이 쓴 것 |

문서의 예시 가운데 페르소나의 비공개 층과 검증 결과는 파일로 두지 않았다. 저장소에 올리지 않는 것이기 때문이다.

## 알아둘 것

- 두 실행의 결과(실행 기록, 원장, 저장된 응답)는 엔진이 쓴 그대로다 (11-15, T11). 가중치도 엔진이 `data/samples/base_summary.csv` 에서 낸 것이다.
  자리만 채운 값은 실행 기록의 `engine_commit`(`0000000`) 하나다. 보정의 대조 결과(`calibration.json`)는 엔진이 쓰지 않아 손으로 만든 것이다.
  LLM 대신 저장된 응답의 글을 돌려주는 가짜 공급자로 돌려 두 실행이 바이트까지 같은 것을 테스트가 본다
  (`tests/test_weights.py` 의 `test_engine_writes_both_example_runs_as_they_are`. 재생으로 같은 원장이 나오는 것은 `tests/test_engine.py`, `tests/test_scenarios.py` 가 본다).
- 그래서 이 폴더의 입력 파일(업장 정의, 페르소나, 조건 묶음, 상황, 값 목록, 집계 값, 프롬프트)을 고치면 입력의 해시가 달라져 그 테스트가 실패한다.
  그때는 두 실행을 엔진으로 다시 만들어 이 폴더와 `FORMATS.md` 10.1절의 예시를 함께 고친다 (가짜 공급자로 두 실행을 돌리는 것은 위 테스트와 같다).
- 기준 실행은 업장 두 곳(`geumryong`, `examplehotel-chinese`)만 읽어 돌렸다. 이 폴더의 사본에서 그 실행으로 상황을 돌리려면 같은 업장을 적는다 (`README.md` 의 "시뮬레이션을 돌린다").
- 검사하는 법:

```powershell
uv run python -m tools.check_formats --root tests/fixtures/example --strict
```
