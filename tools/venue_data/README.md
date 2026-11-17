# tools/venue_data — 업장 데이터의 집계 스크립트

- 주인: hojitea-ui (업장 데이터)
- 담는 것: 기본 데이터에서 집계 파일(`private/base/summary.csv`)을 만드는 스크립트와, 가상 예시 값(`data/samples/`)을 만드는 스크립트 (T13).
- 형식: 집계 파일은 [docs/FORMATS.md](../../docs/FORMATS.md) 8절

지킬 것

- 코드만 둔다. 기본 데이터, 집계 결과, 바꾸는 표는 `private/` 에 둔다.
- 기본 데이터의 실제 수치, 열 이름, 코드 값, 상품과 고객의 이름을 코드와 주석에 적지 않는다. 필요한 대응은 `private/` 의 표에서 읽는다.
  (11-17, 공개 저장소라 코드에 적은 것도 그대로 공개된다. [CLAUDE.md](../../CLAUDE.md) 의 "비밀값과 공개 저장소")
- 읽는 곳과 쓰는 곳은 `private/` 아래다. 가상 예시 값만 `data/samples/` 에 쓴다.
- 돌리는 명령은 `uv run python -m tools.venue_data.<스크립트 이름>` 꼴이다. 스크립트를 넣을 때 빈 `__init__.py` 를 함께 넣는다.
- 테스트는 `tests/venue_data/` 아래에 새 파일로 더한다. 테스트에는 지어낸 값만 쓴다.
- 올리기 전에 린트와 형식 검사를 돌린다: `uv run python -m ruff check .`, `uv run python -m tools.check_formats`
