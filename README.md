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

지금 화면은 공통 틀이 돌아가는지 확인하는 뼈대이고, 지어낸 예시 파일을 보여 준다.

**알아둘 것**

- 명령은 `uv run python -m <도구>` 꼴로 쓴다. `uv run pytest` 나 `uv run streamlit` 처럼 쓰면 윈도우의 스마트 앱 컨트롤이
  실행 파일을 막는 PC 가 있다 (11-13, 스마트 앱 컨트롤이 켜진 윈도우 11 PC 에서 확인).
- 화면은 이 PC 에서만 열린다 (`.streamlit/config.toml`). 화면에 내부 자료에서 계산한 값이 나올 수 있어서다.
- LLM 을 실제로 부르려면 `.env.example` 을 `.env` 로 복사하고 자기 키를 넣는다. 키가 없어도 위의 확인과 화면은 돌아간다.
- 패키지를 더하거나 버전을 바꾸는 것은 엔진 담당만 한다. 필요하면 진행 문서의 "알릴 것"에 적는다.
- 내부 자료와 실행 결과는 `private/` 에만 둔다 ([CLAUDE.md](CLAUDE.md) 의 "비밀값과 공개 저장소").
