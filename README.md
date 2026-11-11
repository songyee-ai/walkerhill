# 워커힐 페르소나 시뮬레이션

4명이 함께 만드는 프로젝트다. 2026-11-23 최종 완료, 11-25 발표.

## 처음 받는 사람

```powershell
git clone https://github.com/songyee-ai/walkerhill.git
cd walkerhill
```

코드를 쓰기 전에 아래 순서로 읽는다.

1. [CLAUDE.md](CLAUDE.md) — 협업 규칙 원본
2. [docs/PROGRESS.md](docs/PROGRESS.md) — 일정, 역할 분담, 진행 표
3. [docs/STRUCTURE.md](docs/STRUCTURE.md) — 폴더 주인, 공통 틀

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

기술 스택 확정 후 채운다.
