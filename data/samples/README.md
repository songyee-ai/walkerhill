# data/samples — 가상 예시 값

- 주인: hojitea-ui (업장 데이터)
- 담는 것: `base_summary.csv`. 기본 데이터 집계 파일과 같은 열을 가진 **지어낸 값**이다.
- 형식: [docs/FORMATS.md](../../docs/FORMATS.md) 8절
- 예시: [tests/fixtures/example/data/samples/base_summary.csv](../../tests/fixtures/example/data/samples/base_summary.csv)

지킬 것

- 기본 데이터의 수치를 따오지 않는다. 비슷하게 맞추지도 않는다. 임의로 정한다.
- 진짜 집계 파일은 `private/base/summary.csv` 에만 둔다. 이 폴더에 넣지 않는다.
- 이 폴더에는 `base_summary.csv` 와 이 안내 파일만 둔다. 같은 열을 가진 파일을 다른 이름이나 다른 폴더에 두면 검사가 오류를 낸다.
- 키나 기본 데이터가 없는 PC 는 이 파일로 화면을 돌린다. 그래서 `data/venues/` 의 업장과 상품이 모두 들어 있어야 한다.
