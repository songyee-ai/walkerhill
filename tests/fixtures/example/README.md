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
| `engine/conditions.json` | 6절 | 문서의 예시 |
| `scenarios/baseline.json` | 7절 | 문서에 없다. 기준 상황 |
| `scenarios/geumryong-course-price-up.json`, `competitor-chinese-discount.json` | 7절 | 문서의 예시 |
| `data/samples/base_summary.csv` | 8절 | 문서의 예시 |
| `engine/samples/runs/20261117-101500-baseline/` | 9절, 10절 | 실행 기록, 원장, 저장된 응답, 보정 결과. 문서의 예시 |
| `engine/samples/runs/20261117-103000-competitor-chinese-discount/` | 10절 | 원장은 문서의 예시 둘째 줄이고, 나머지는 그에 맞춰 만든 것 |

문서의 예시 가운데 페르소나의 비공개 층과 검증 결과는 파일로 두지 않았다. 저장소에 올리지 않는 것이기 때문이다.

## 알아둘 것

- 실행 결과는 엔진으로 돌린 것이 아니라 손으로 만든 것이다. 엔진이 생기면(T05) 엔진으로 다시 만든다.
- 검사하는 법:

```powershell
uv run python -m tools.check_formats --root tests/fixtures/example --strict
```
