# 워커힐 페르소나 시뮬레이션

4명이 함께 만드는 프로젝트다. 2026-11-24 최종 완료, 11-26 발표.

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

화면에서 조건을 골라 엔진을 돌리고, 페르소나와 방문 조건별 결과를 본다. LLM 을 부를 준비가 안 됐으면 저장된 답을 재생한다.
쓰는 법은 화면 담당의 안내(`docs/PROGRESS.md` 의 T09, T202)를 본다.
화면이 만든 상황 파일(`scenarios/ui-*.json`)은 깃이 무시한다. 시연에 쓸 상황은 사람이 확정해 `ui-` 없이 올린다.
가상 예시 값으로 돌린 실행 폴더(`engine/samples/runs/<run_id>/`)도 깃이 무시한다 (T107). 각자 연습으로 받은 답이 올라가지 않게 한다.

**시뮬레이션을 돌린다** — 상황 하나를 돌려 실행 폴더(실행 기록, 소비 원장, 저장된 응답)를 쓴다.
`--data sample` 은 가상 예시 값으로 돌려 `engine/samples/runs/` 에, `--data private` 은 기본 데이터로 돌려 `private/runs/` 에 쓴다.

```powershell
uv run python -m engine --data sample
```

- 방문마다 앞선 실행의 저장된 응답을 먼저 찾아 재생하고, 없는 것만 LLM 을 부른다. 그래서 같은 것을 다시 돌리면 LLM 을 부르지 않는다.
  기준이 아닌 상황은 기준 실행의 답을 가장 먼저 찾는다. 요청에 상황의 이름이 없어, 상황의 변경과 상관없는 방문은 기준의 답을 그대로 재생한다 (T121).
  11-18 전에 받은 답은 한 번 변환해야 재생된다: `uv run python -m tools.rehash_answers` (요청에서 `scenario_id` 를 지우고 해시를 다시 낸다. 답의 내용은 그대로다).
- LLM 을 부르려면 `.env.example` 을 `.env` 로 복사하고, 터미널에서 `claude auth login` 을 한 번 한다 (브라우저가 열리면 자기 Claude 계정으로 로그인).
  **팀은 각자의 Claude 구독으로 부른다** (공급자 `claude-code`, 11-17 에 정함. T114). API 키는 쓰지 않는다.
  공급자와 모델은 `.env.example` 에 팀 설정으로 이미 적혀 있으니 아래 세 줄을 그대로 둔다. 호출 상한도 `.env` 에서 바꾼다.

```text
LLM_PROVIDER=claude-code
LLM_MODEL=claude-opus-5-5
CLAUDE_CODE_PATH=
```

  - `claude` 명령이 PATH 에 있으면 `CLAUDE_CODE_PATH` 는 비워 둔다. 있는지는 `Get-Command claude` 로 본다.
    데스크톱 앱에 든 Claude Code 만 있으면 그 `claude.exe` 의 전체 경로를 적는다. 아래 명령이 찾아 준다 (앱이 업데이트되면 경로가 바뀌니 다시 찾는다):

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Claude-Data" -Recurse -Filter claude.exe -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty FullName
```

  - 데스크톱 앱의 로그인은 앱 안에서만 쓰인다. 앱에 로그인돼 있어도 `claude auth login` 은 따로 한 번 해야 한다. 경로를 적었으면 `& "<그 경로>" auth login` 이다.
  - **보정·시연에 쓸 답은 엔진 담당의 PC 한 곳에서 받는다** (11-19 부터. 그 전에는 팀장 PC 가 받았다, T209). 나머지는 그 답을 받아 재생한다 (`docs/MEETING_1117.md` ②).
    각자 시험할 때는 가상 예시 값(`--data sample`)을 `--personas`, `--conditions` 로 작게 돌린다.
  - 구독의 사용 한도는 자기 Claude Code 작업과 함께 쓴다. 호출 하나가 입력 1만 5천 ~ 3만 토큰이다 (T104·T114 실측).
    한도에 닿으면 엔진이 멈추고, 한도가 풀린 뒤 다시 돌리면 받은 답은 재생한다.
  - 기본 데이터(`--data private`)로 부르기 전에, 답을 받는 계정이 보낸 것을 모델 학습에 쓰지 않게 돼 있는지 확인한다.
    요금제는 `& "<그 경로>" auth status` 의 `subscriptionType` 으로 본다. 팀 요금제(`team`)는 학습 스위치가 없고 조직 관리자에게 개발 파트너 프로그램 가입 여부만 묻는다.
    개인 구독은 Claude 개인정보 설정에서 "모델 학습에 사용"을 끈다.
    확인하기 전에는 `--base-profile none` 으로 돌린다 (`CLAUDE.md` 의 "스택", `docs/MEETING_1117.md` ③).
    확인이 끝나면 답을 받는 PC 의 `.env` 에 `BASE_PROFILE_CONFIRMED_FOR=claude-code` 를 적는다. 적혀 있지 않으면 엔진은 기본 데이터의 요약을 보내는 실행을 멈추고 이유를 알린다 (T115).
    요약을 보내지 않거나(`--base-profile none`) 재생만 하면(`--replay-only`) 적혀 있지 않아도 돈다.
    저장된 답이 모두 있어 실제로는 부르지 않게 될 실행도 `--replay-only` 를 붙이지 않으면 멈춘다 (돌려 보기 전에는 부를지 알 수 없다).
  - 가상 예시 값으로 돌린 실행 폴더(`engine/samples/runs/<run_id>/`)는 깃이 무시하므로 올라가지 않는다 (T107).
  - 다른 공급자(OpenAI 등)로 따로 돌려 볼 수는 있다. 그 답은 보정과 시연에 쓰지 않는다. 공급자나 모델이 다르면 팀이 받은 답과 서로 재생되지 않는다.
- 로그인하지 않았거나 LLM 을 부르지 않으려면 `--replay-only` 를 붙인다. 저장된 응답만 재생하고, 저장된 응답이 없는 방문은 실패로 남는다.
- 일부만 돌릴 때: `--personas`, `--conditions`, `--venues` 뒤에 식별자를 적는다.
- 한 달의 방문으로 돌릴 때: `--month <1 ~ 12>` 를 적는다 (계절을 볼 때. T112). 그 달에 팔지 않는 업장과 상품이 후보에서 빠지고, 요청에 달이 실린다.
  적지 않으면 일 년 전체로 본다. 달이 다르면 요청이 달라 저장된 답도 따로 받는다. 예: `uv run python -m engine --data sample --month 12`
  가중치는 그 달의 인원으로 낸다 (T210). **보정은 달을 적지 않은 기준 실행으로 한다** (`docs/FORMATS.md` 10.1절의 "실행의 달").
- 프롬프트의 판은 `--prompt` 로 고른다. 적지 않으면 팀이 쓰는 판 `p3` 을 읽는다 (`personas/prompts/p3.md`, T113. 달을 읽는 법이 든 판이다).
  판이 다르면 요청이 달라 저장된 답이 재생되지 않는다. p2 로 받아 둔 답을 재생하려면 `--prompt p2` 를 적는다.
  그 판의 파일이 없는 폴더에서 LLM 을 부르려 하면 다른 판으로 돌리지 않고 이유를 알리고 멈춘다.
  `--replay-only` 는 프롬프트 파일을 읽지 않는다. 그래서 기준 상황은 멈추지 않고, 그 판으로 받은 저장된 답이 없으면 방문이 실패로 남는다 (예시 사본에 `--prompt p1` 을 빼먹었을 때가 그렇다).
  기준이 아닌 상황은 기준 실행과 프롬프트의 판이 다르면 `--replay-only` 여도 돌리지 않고 이유를 알린다 (아래의 "기준이 아닌 상황은").
- 집계 파일이 있어야 돈다: `--data sample` 은 `data/samples/base_summary.csv`, `--data private` 은 `private/base/summary.csv` (업장 데이터 담당이 만든다).
  기준 상황의 가중치(묶음의 비율, 고객군 배수)를 방문을 돌기 전에 이 파일의 인원(`people`)으로 내고, 가격이 빈 상품의 단가도 이 파일에서 낸다 (`docs/FORMATS.md` 3절, 10.1절의 "가중치를 내는 법").
  명령이 끝날 때 채운 상품과 채우지 못한 상품의 수, 페르소나가 있는 고객군이 인원에서 차지하는 몫을 알리고, 인원을 찾지 못한 고객군이 있으면 알린다.
- `--data private` 은 기본 데이터의 요약을 범주로 바꿔 LLM 에 보낸다 (`--base-profile bucketed`, 기본값). 보내지 않으려면 `--base-profile none` 이다.
  요약을 보내는 실행은 `.env` 의 `BASE_PROFILE_CONFIRMED_FOR` 에 지금 받는 곳의 이름(팀 설정이면 `claude-code`)이 적혀 있어야 돈다 (위의 "기본 데이터로 부르기 전에").
  `--data sample` 은 늘 보내지 않는다 (`docs/FORMATS.md` 5절의 "기본 데이터의 요약").
- 기준이 아닌 상황은 `--scenario <scenario_id>` 로 돌린다 (`scenarios/<scenario_id>.json`). **기준 상황을 먼저 끝까지 돌려 둔다.**
  상황은 끝까지 돈 가장 새 기준 실행의 페르소나, 방문 조건, 가중치로 돌아간다 (다른 기준 실행을 쓰려면 `--baseline <run_id>`).
  그래서 `--personas`, `--conditions` 는 적지 않는다. `--venues` 로 업장을 골라 기준을 돌렸으면 상황에도 같은 업장을 적는다.
  달도 기준 실행과 같아야 한다. 상황은 달이 같은 가장 새 기준 실행을 고른다 (`--month` 를 적으면 그 달로 돌린 것, 적지 않으면 일 년 전체로 돌린 것).
  그런 실행이 없으면 멈춘다. `--baseline` 으로 실행을 가리키면 `--month` 를 적지 않아도 그 실행의 달로 돈다.
  기준 실행 뒤에 업장 정의, 페르소나, 방문 조건 묶음, 값 목록, 집계 파일, 프롬프트, 모델이 바뀌었으면 돌리지 않고 이유를 알린다. 기준 상황을 다시 돌린다.
  상황은 업장 정의 파일을 고치지 않는다. 엔진이 읽어 둔 사본에만 적용한다.
- 호출 상한(`LLM_CALL_LIMIT`, 이번만 바꾸려면 `--limit`)에 닿으면 거기서 멈추고 그 사실을 알린다. 다시 돌리면 받은 답은 재생하고 남은 방문만 부른다.
- 키나 모델 이름이 틀렸거나 호출이 연달아 3번 실패하면 멈추고 이유를 알린다.
- 검사에서 어긋난 응답은 실행 폴더의 `llm_rejected/` 에 남는다. 이유는 원장의 `fail_reason` 에 있다.
- 명령이 끝날 때의 값(`$LASTEXITCODE`): `0` 끝까지 돌았다 (실패한 방문이 있어도 0 이다. 화면에 알린다), `1` 돌리지 못했거나 LLM 을 부를 수 없어 멈췄다, `2` 호출 상한에 닿아 멈췄다.
- `.env` 는 명령을 돌리는 폴더의 것만 읽는다. 저장소의 맨 위 폴더에서 돌린다.
- LLM 을 부르지 않고 연습할 때는 예시 파일 한 벌의 사본을 돌린다 (사본은 깃이 무시하는 `private/` 에 둔다).
  예시의 저장된 답은 공급자 `anthropic`(`claude-opus-5-5`)으로 받은 것이다. 팀 `.env`(공급자 `claude-code`)와 공급자가 달라 그대로는 재생되지 않으므로,
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

**보정의 대조를 한다** — 기준 실행을 기본 데이터와 견줘 그 실행 폴더에 `calibration.json` 을 쓴다 (T116, `docs/PRD.md` 6.5절). LLM 을 부르지 않는다.

```powershell
uv run python -m engine.calibration --data sample
```

- 적지 않으면 일 년 전체로 끝까지 돈 가장 새 기준 실행을 견준다. 다른 실행은 `--run <run_id>` 로 가리킨다.
- 페르소나가 있는 고객군마다 워커힐 업장별 매출 비중을 견준다. 통과 기준은 가장 큰 업장이 같고 업장별 차이가 모두 15%p 이내인 것이다. 명령으로는 바꿀 수 없다.
- 기준 실행은 **달을 적지 않고, 업장을 고르지 않고(`--venues` 없이)** 돌린 것이어야 한다. 실패한 방문이 있거나 실행 뒤에 입력(페르소나, 업장 정의, 방문 조건 묶음, 기준 상황, 값 목록, 집계 파일)을 고쳤으면 멈추고 이유를 알린다.
- **페르소나를 모두 돌린 실행이어야 통과로 본다.** `--personas` 로 일부만 돌린 실행도 대조는 하지만, 페르소나가 빠진 고객군은 비중이 맞아도 미달로 적고 빠진 페르소나를 알린다.
  실패한 방문은 기준 상황을 `--replay-only` 없이 다시 돌리면 그 방문만 새로 부른다.
- 명령이 끝날 때의 값: `0` 대조했다 (통과인지 미달인지는 화면과 파일에 있다), `1` 대조하지 못했다.
- `--data private` 의 결과에는 기본 데이터에서 계산한 값이 있다. 파일은 `private/runs/` 에만 쓰이고, 화면에 나온 수치는 저장소의 파일에 옮겨 적지 않는다.

**업장 상수를 추정한다** — 점수를 받은 기준 실행으로 업장 상수를 기본 데이터의 업장 몫(사람 수)에 맞춰 추정한 상수 파일을 쓴다 (T212, `docs/FORMATS.md` 6.1절의 "추정한 상수 파일"). LLM 을 부르지 않는다.

```powershell
uv run python -m engine.estimate --data private
```

- 점수를 묻는 판(`p4` 처럼 `p1` ~ `p3` 이 아닌 판)으로 돌린 기준 실행이어야 한다 (일 년 전체, 실패 없음). 적지 않으면 일 년 전체로 끝까지 돈 가장 새 기준 실행을 쓴다 (`--run <run_id>`).
- 기본 데이터로 점수를 묻는 판을 돌리는데 추정한 상수 파일이 없으면 엔진이 멈춘다. 상수 추정에 쓸 첫 기준 실행만 `--before-estimate` 를 붙여 업장 상수를 모두 1 로 돌린다.
- 결과는 `private/base/estimated_constants.json` 에 쓰인다. 기본 데이터에서 계산한 값이라 저장소·커밋·연락판에 옮겨 적지 않는다. 다른 PC 는 답 폴더처럼 저장소 밖으로 받아 같은 자리에 둔다.
- 파일이 생기거나 바뀌면 기준 상황을 다시 돌린다 (저장된 답을 재생한다). 화면에 보이는 "추정 전 / 추정 뒤"의 차이는 맞춘 정도이지 검증이 아니다 (PRD 12절).

**알아둘 것**

- 명령은 `uv run python -m <도구>` 꼴로 쓴다. `uv run pytest` 나 `uv run streamlit` 처럼 쓰면 윈도우의 스마트 앱 컨트롤이
  실행 파일을 막는 PC 가 있다 (11-13, 스마트 앱 컨트롤이 켜진 윈도우 11 PC 에서 확인).
- 화면은 이 PC 에서만 열린다 (`.streamlit/config.toml`). 화면에 내부 자료에서 계산한 값이 나올 수 있어서다.
- LLM 을 실제로 부르려면 `.env.example` 을 `.env` 로 복사하고 `claude auth login` 을 한 번 한다 (팀은 각자의 Claude 구독으로 부른다). 로그인하지 않아도 위의 확인과 화면은 돌아간다.
  `.env` 는 깃에 올라가지 않는다. 로그인 정보와 키는 서로 주고받지 않는다.
- 패키지를 더하거나 버전을 바꾸는 것은 엔진 담당만 한다. 필요하면 진행 문서의 "알릴 것"에 적는다.
- 내부 자료와 실행 결과는 `private/` 에만 둔다 ([CLAUDE.md](CLAUDE.md) 의 "비밀값과 공개 저장소").
