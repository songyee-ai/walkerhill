# 워커힐 페르소나 시뮬레이션

4명이 함께 만드는 프로젝트다. 2026-11-23 최종 완료, 11-25 발표.

## 처음 받는 사람

```powershell
git clone https://github.com/songyee-ai/walkerhill.git
cd walkerhill
```

코드를 쓰기 전에 아래 순서로 읽는다.

1. [CLAUDE.md](CLAUDE.md) — 협업 규칙 원본
2. [docs/PROGRESS.md](docs/PROGRESS.md) — 일정, 역할 분담, 진행 표, 내 작업 유닛
3. [docs/STRUCTURE.md](docs/STRUCTURE.md) — 폴더 주인, 공통 틀
4. [docs/PRD.md](docs/PRD.md) — 무엇을 만드는가
5. [docs/FORMATS.md](docs/FORMATS.md) — 영역끼리 주고받는 파일의 모양

## 작업 흐름

```powershell
git switch develop
git pull
git switch -c develop-<이름>-<기능>
# 작업하고 커밋한 뒤
git push -u origin develop-<이름>-<기능>
gh pr create --base develop
```

`develop` 에는 PR 로만 합친다. `main` 에는 팀장이 `develop` 과 같은 커밋을 올린다.

## 실행 방법

Python 3.13 과 패키지는 [uv](https://docs.astral.sh/uv/) 가 맞춰 준다. Python 을 따로 깔 필요가 없다.

**처음 한 번** — uv 를 깔고(이미 있으면 건너뛴다) 패키지를 설치한다. 설치한 뒤에는 PowerShell 창을 새로 연다.

```powershell
winget install --id=astral-sh.uv -e
```

```powershell
uv sync
```

**돌아가는지 확인한다** — 셋 다 오류 없이 끝나야 한다.

```powershell
uv run ruff check .
```

```powershell
uv run python -m tools.check_formats
```

```powershell
uv run python -m pytest
```

**화면을 띄운다** — 브라우저에서 `http://localhost:8501` 이 열린다. 끝낼 때는 창에서 `Ctrl+C` 를 누른다.

```powershell
uv run python -m streamlit run app/main.py
```

화면에서 조건을 골라 엔진을 돌리고, 페르소나와 방문 조건별 결과를 본다. 키가 없으면 저장된 답을 재생한다.
쓰는 법은 화면 담당의 안내(`docs/PROGRESS.md` 의 T09, T202)를 본다.
화면이 만든 상황 파일(`scenarios/ui-*.json`)은 깃이 무시한다. 시연에 쓸 상황은 사람이 확정해 `ui-` 없이 올린다.
가상 예시 값으로 돌린 실행 폴더(`engine/samples/runs/<run_id>/`)도 깃이 무시한다 (T107). 각자 연습으로 받은 답이 올라가지 않게 한다.

**시뮬레이션을 돌린다** — 상황 하나를 돌려 실행 폴더(실행 기록, 소비 원장, 저장된 응답)를 쓴다.
`--data sample` 은 가상 예시 값으로 돌려 `engine/samples/runs/` 에, `--data private` 은 기본 데이터로 돌려 `private/runs/` 에 쓴다.

```powershell
uv run python -m engine --data sample
```

- 방문마다 앞선 실행의 저장된 응답을 먼저 찾아 재생하고, 없는 것만 LLM 을 부른다. 그래서 같은 것을 다시 돌리면 LLM 을 부르지 않는다.
- LLM 을 부르려면 `.env.example` 을 `.env` 로 복사하고 자기 OpenAI 키(`LLM_API_KEY`)와 팀이 정한 모델(`LLM_MODEL`)을 넣는다.
  공급자와 주소는 `.env.example` 에 팀 설정으로 이미 적혀 있다. 호출 상한도 `.env` 에서 바꾼다.
- **로컬에서 시험할 때는 자기 Claude 구독으로 먼저 돌린다** (공급자 `claude-code`, T104·T106). OpenAI 키는 보정·시연 답을 받을 때 쓴다.
  `.env` 에서 아래 세 줄만 바꾸고, 터미널에서 `claude auth login` 을 한 번 한다 (브라우저가 열리면 자기 Claude 계정으로 로그인).

```text
LLM_PROVIDER=claude-code
LLM_MODEL=claude-sonnet-5-5
CLAUDE_CODE_PATH=
```

  - `claude` 명령이 PATH 에 있으면 `CLAUDE_CODE_PATH` 는 비워 둔다. 있는지는 `Get-Command claude` 로 본다.
    데스크톱 앱에 든 Claude Code 만 있으면 그 `claude.exe` 의 전체 경로를 적는다. 아래 명령이 찾아 준다 (앱이 업데이트되면 경로가 바뀌니 다시 찾는다):

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Claude-Data" -Recurse -Filter claude.exe -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty FullName
```

  - 데스크톱 앱의 로그인은 앱 안에서만 쓰인다. 앱에 로그인돼 있어도 `claude auth login` 은 따로 한 번 해야 한다. 경로를 적었으면 `& "<그 경로>" auth login` 이다.
  - 가상 예시 값(`--data sample`)으로만 돌린다. 기본 데이터(`--data private`)는 팀이 정한 공급자로만 돌린다 (요약이 어느 회사로 가는지 팀이 정한다. `docs/MEETING_1117.md` ③).
  - 이 답은 시연과 보정에 쓰지 않는다. 실행 폴더(`engine/samples/runs/<run_id>/`)는 깃이 무시하므로 올라가지 않는다 (T107).
  - 구독의 사용 한도는 자기 Claude Code 작업과 함께 쓴다. 호출 하나가 2만 토큰을 넘으니(T104 실측) `--personas`, `--conditions` 로 작게 돌린다.
    한도에 닿으면 엔진이 멈추고, 한도가 풀린 뒤 다시 돌리면 받은 답은 재생한다.
- 키가 없으면 `--replay-only` 를 붙인다. 저장된 응답만 재생하고, 저장된 응답이 없는 방문은 실패로 남는다.
- 일부만 돌릴 때: `--personas`, `--conditions`, `--venues` 뒤에 식별자를 적는다.
- 프롬프트의 판은 `--prompt` 로 고른다. 적지 않으면 팀이 쓰는 판 `p2` 를 읽는다 (`personas/prompts/p2.md`, T108).
  그 판의 파일이 없는 폴더에서 LLM 을 부르려 하면 다른 판으로 돌리지 않고 이유를 알리고 멈춘다.
  `--replay-only` 는 프롬프트 파일을 읽지 않는다. 그래서 기준 상황은 멈추지 않고, 그 판으로 받은 저장된 답이 없으면 방문이 실패로 남는다 (예시 사본에 `--prompt p1` 을 빼먹었을 때가 그렇다).
  기준이 아닌 상황은 기준 실행과 프롬프트의 판이 다르면 `--replay-only` 여도 돌리지 않고 이유를 알린다 (아래의 "기준이 아닌 상황은").
- 집계 파일이 있어야 돈다: `--data sample` 은 `data/samples/base_summary.csv`, `--data private` 은 `private/base/summary.csv` (업장 데이터 담당이 만든다).
  기준 상황의 가중치(묶음의 비율, 고객군 배수)와 가격이 빈 상품의 단가를 이 파일에서 낸다 (`docs/FORMATS.md` 3절, 10.1절의 "가중치를 내는 법").
  명령이 끝날 때 채운 상품과 채우지 못한 상품의 수를 알리고, 배수를 정하지 못한 고객군이 있으면 알린다.
- `--data private` 은 기본 데이터의 요약을 범주로 바꿔 LLM 에 보낸다 (`--base-profile bucketed`, 기본값). 보내지 않으려면 `--base-profile none` 이다.
  `--data sample` 은 늘 보내지 않는다 (`docs/FORMATS.md` 5절의 "기본 데이터의 요약").
- 기준이 아닌 상황은 `--scenario <scenario_id>` 로 돌린다 (`scenarios/<scenario_id>.json`). **기준 상황을 먼저 끝까지 돌려 둔다.**
  상황은 끝까지 돈 가장 새 기준 실행의 페르소나, 방문 조건, 가중치로 돌아간다 (다른 기준 실행을 쓰려면 `--baseline <run_id>`).
  그래서 `--personas`, `--conditions` 는 적지 않는다. `--venues` 로 업장을 골라 기준을 돌렸으면 상황에도 같은 업장을 적는다.
  기준 실행 뒤에 업장 정의, 페르소나, 방문 조건 묶음, 값 목록, 집계 파일, 프롬프트, 모델이 바뀌었으면 돌리지 않고 이유를 알린다. 기준 상황을 다시 돌린다.
  상황은 업장 정의 파일을 고치지 않는다. 엔진이 읽어 둔 사본에만 적용한다.
- 호출 상한(`LLM_CALL_LIMIT`, 이번만 바꾸려면 `--limit`)에 닿으면 거기서 멈추고 그 사실을 알린다. 다시 돌리면 받은 답은 재생하고 남은 방문만 부른다.
- 키나 모델 이름이 틀렸거나 호출이 연달아 3번 실패하면 멈추고 이유를 알린다.
- 검사에서 어긋난 응답은 실행 폴더의 `llm_rejected/` 에 남는다. 이유는 원장의 `fail_reason` 에 있다.
- 명령이 끝날 때의 값(`$LASTEXITCODE`): `0` 끝까지 돌았다 (실패한 방문이 있어도 0 이다. 화면에 알린다), `1` 돌리지 못했거나 LLM 을 부를 수 없어 멈췄다, `2` 호출 상한에 닿아 멈췄다.
- `.env` 는 명령을 돌리는 폴더의 것만 읽는다. 저장소의 맨 위 폴더에서 돌린다.
- 키 없이 연습할 때는 예시 파일 한 벌의 사본을 돌린다 (사본은 깃이 무시하는 `private/` 에 둔다).
  예시의 저장된 답은 Anthropic(`claude-opus-5-5`)으로 받은 것이다. 팀 `.env`(OpenAI)와 공급자가 달라 그대로는 재생되지 않으므로,
  **그 창에서만** 공급자를 예시의 값으로 바꾸고 `--replay-only` 를 붙인다 (`.env` 는 이미 있는 환경 변수를 덮어쓰지 않는다. 화면은 이것을 스스로 한다).
  예시에는 프롬프트가 `p1` 하나뿐이고 저장된 답도 `p1` 로 받은 것이라 `--prompt p1` 도 적는다:

```powershell
Copy-Item -Recurse tests/fixtures/example private/try-example
```

```powershell
$env:LLM_PROVIDER = 'anthropic'; $env:LLM_MODEL = 'claude-opus-5-5'
```

```powershell
uv run python -m engine --data sample --root private/try-example --prompt p1 --personas family-elders --conditions meal-dinner-weekend --venues geumryong examplehotel-chinese --replay-only
```

  다 돌렸으면 창을 닫거나 `Remove-Item Env:LLM_PROVIDER, Env:LLM_MODEL` 로 되돌린다. 되돌리지 않으면 그 창의 다음 실행도 예시 공급자로 돈다.

  상황은 위의 명령으로 기준 상황을 한 번 돌린 뒤에, 그 실행을 `--baseline` 으로 가리켜 돌린다.
  사본에 처음부터 든 기준 실행(`20261117-101500-baseline`)은 번호의 날짜가 늦어 "가장 새 기준 실행"으로 먼저 골라지기 때문이다:

```powershell
uv run python -m engine --data sample --root private/try-example --prompt p1 --scenario competitor-chinese-discount --venues geumryong examplehotel-chinese --replay-only --baseline <위에서 나온 run_id>
```

  기준 상황을 업장 두 곳만 읽어 돌렸으므로 상황에도 같은 업장을 적는다 (`--venues`).

**알아둘 것**

- 명령은 `uv run python -m <도구>` 꼴로 쓴다. `uv run pytest` 나 `uv run streamlit` 처럼 쓰면 윈도우의 스마트 앱 컨트롤이
  실행 파일을 막는 PC 가 있다 (11-13, 스마트 앱 컨트롤이 켜진 윈도우 11 PC 에서 확인).
- 화면은 이 PC 에서만 열린다 (`.streamlit/config.toml`). 화면에 내부 자료에서 계산한 값이 나올 수 있어서다.
- LLM 을 실제로 부르려면 `.env.example` 을 `.env` 로 복사하고 자기 OpenAI 키와 팀이 정한 모델을 넣는다. 키가 없어도 위의 확인과 화면은 돌아간다.
  `.env` 는 깃에 올라가지 않는다. 키는 서로 주고받지 않는다.
- 패키지를 더하거나 버전을 바꾸는 것은 엔진 담당만 한다. 필요하면 진행 문서의 "알릴 것"에 적는다.
- 내부 자료와 실행 결과는 `private/` 에만 둔다 ([CLAUDE.md](CLAUDE.md) 의 "비밀값과 공개 저장소").
