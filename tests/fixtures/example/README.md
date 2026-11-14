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
| `engine/samples/runs/20261117-101500-baseline/` | 9절, 10절 | 실행 기록, 원장, 저장된 응답, 보정 결과. 문서의 예시 |
| `engine/samples/runs/20261117-103000-competitor-chinese-discount/` | 10절 | 원장은 문서의 예시 둘째 줄이고, 나머지는 그에 맞춰 만든 것 |

문서의 예시 가운데 페르소나의 비공개 층과 검증 결과는 파일로 두지 않았다. 저장소에 올리지 않는 것이기 때문이다.

## 알아둘 것

- 실행 결과는 엔진으로 돌린 것이 아니라 손으로 만든 것이다. 그래서 실행 기록의 입력 해시(`inputs`)는 자리만 채운 값이다.
  원장과 저장된 응답은 엔진이 내는 것과 같다: 저장된 응답을 재생하면 두 실행 모두 같은 원장이 나오는 것을 테스트가 본다
  (`tests/test_engine.py` 의 기준 실행, `tests/test_scenarios.py` 의 둘째 실행. 둘째 실행은 엔진이 상황을 적용해 만든 요청의 해시가 예시와 같아야 재생된다).
- 실행 기록까지 엔진이 쓴 것으로 바꾸는 것은 가중치를 집계 파일에서 내게 된(T11) 뒤에 두 실행을 함께 한다. 지금 엔진으로 만들면 기준 실행의 가중치가 문서의 예시와 달라진다.
  엔진은 기준 실행 뒤에 입력이 바뀌었으면 상황을 돌리지 않으므로(`FORMATS.md` 10.1절), 자리만 채운 해시가 든 이 기준 실행으로는 상황을 돌릴 수 없다.
  이 폴더의 사본에서 상황을 돌려 보려면 기준 상황을 엔진으로 한 번 돌린 뒤에 한다 (`README.md` 의 "시뮬레이션을 돌린다").
- 검사하는 법:

```powershell
uv run python -m tools.check_formats --root tests/fixtures/example --strict
```
