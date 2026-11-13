# scenarios — 상황 정의

- 주인: wilstein91 (화면·실험·발표)
- 담는 것: 비교하려고 돌리는 상황. 상황 하나가 파일 하나다 (`<scenario_id>.json`). 기준 상황은 `baseline.json` 이다.
- 형식: [docs/FORMATS.md](../docs/FORMATS.md) 7절
- 예시: [tests/fixtures/example/scenarios/](../tests/fixtures/example/scenarios/)

지킬 것

- 바꾸는 값이 어디서 왔는지 `note` 에 적는다 (공개된 가격에서 정했는지, 가정인지).
- 상황은 업장 정의 파일을 고치지 않는다. 엔진이 실행할 때 사본에 적용한다.
- 이 폴더에는 상황 정의와 이 안내 파일만 둔다. 다른 파일이나 하위 폴더를 두면 검사가 오류를 낸다.
- 올리기 전에 검사한다: `uv run python -m tools.check_formats`
