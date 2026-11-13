# personas — 페르소나 정의 (공개 층)

- 주인: borigunbbang (외부 데이터·페르소나)
- 담는 것: 페르소나 한 명이 파일 하나다 (`<persona_id>.json`). LLM 프롬프트의 문장은 `prompts/` 폴더에 둔다.
  이 폴더에는 이 둘과 안내 파일만 둘 수 있다. 다른 파일이나 폴더를 두면 검사가 오류를 낸다.
- 형식: [docs/FORMATS.md](../docs/FORMATS.md) 5절
- 예시: [tests/fixtures/example/personas/](../tests/fixtures/example/personas/)

지킬 것

- 공개 후기와 공식 정보에서 온 것만 적는다.
- 받은 참고 소스의 후기에서 온 근거는 비공개 층 `private/personas/<persona_id>.json` 에 적는다.
- 기본 데이터에서 계산하는 값(업장별 매출 비중 같은 것)은 적지 않는다. 엔진이 실행할 때 붙인다.
- 프롬프트에는 응답의 `rejected` 에 고르지 않은 후보를 빠짐없이 한 번씩 적으라고 쓴다. 빠지면 엔진이 그 방문을 실패로 기록한다 (형식 문서 9절).
- 올리기 전에 검사한다: `uv run python -m tools.check_formats`
