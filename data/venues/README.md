# data/venues — 업장 정의

- 주인: hojitea-ui (업장 데이터)
- 담는 것: 워커힐 8개 업장과 경쟁 업장의 정의. 업장 하나가 파일 하나다 (`<venue_id>.json`).
- 형식: [docs/FORMATS.md](../../docs/FORMATS.md) 3절
- 예시: [tests/fixtures/example/data/venues/](../../tests/fixtures/example/data/venues/) 의 파일을 베껴서 시작한다. 예시의 값은 지어낸 것이니 모두 바꾼다.

지킬 것

- 공식 메뉴판이나 공식 발표에 있는 이름과 가격만 적는다. 기본 데이터에 적힌 이름과 단가를 옮겨 적지 않는다.
- 값마다 출처와 확인일을 적는다.
- 숫자와 참·거짓은 따옴표 없이 적는다 (`150000`, `true`). 따옴표로 감싸면 검사가 오류를 낸다.
- 이 폴더에는 업장 정의와 이 안내 파일만 둔다. 작업 중인 엑셀이나 메모, 하위 폴더를 두면 검사가 오류를 낸다. 그런 것은 `private/` 에 둔다.
- 올리기 전에 검사한다: `uv run python -m tools.check_formats`
