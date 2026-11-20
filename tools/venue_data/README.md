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

들어 있는 것 (11-17, hojitea-ui)

- `build_summary.py` 기본 데이터에서 집계 파일을 만든다. `uv run python -m tools.venue_data.build_summary` (`--out <폴더>` 로 다른 곳에 쓸 수 있다)
  - 읽는 것: `private/base/source.json` (기본 데이터 파일의 위치, 열 이름, 다이닝 줄을 고르는 값), 그 기본 데이터, `private/base/map.json` (상품 대응표와 상품마다 한 개당 인원 `people_per_unit`), `data/venues/`
  - 쓰는 것: `private/base/summary.csv`, `private/base/meta.json`
- `make_sample.py` 가상 예시 값을 만든다. 기본 데이터를 읽지 않는다. `uv run python -m tools.venue_data.make_sample` 는 검사만 하고, `--write` 를 붙이면 `data/samples/base_summary.csv` 를 덮어쓴다.
  `--add-people` 은 지금 예시 파일의 값은 그대로 두고 인원(`people`) 열만 채운다 (형식에 `people` 이 들어온 뒤에만 돈다, T402)
  `--constants` 는 옆의 상수 파일 `data/samples/base_summary_constants.json` 을 쓴다 (T404)
- `constants.py` 집계 옆 상수 파일(`FORMATS.md` 6.1절)을 만드는 도움 함수. `build_summary` 는 `private/base/summary_constants.json` 을 함께 쓴다 (한 개당 인원, 근거는 `private/base/map.json` 의 `people_basis`)
- 테스트: `tests/venue_data/test_venue_data_scripts.py`
