# 구조 문서

폴더의 주인과 공통 틀을 적는다. 규칙의 원본은 [CLAUDE.md](../CLAUDE.md) 이고 여기에는 다시 쓰지 않는다.

## 폴더별 주인

남의 폴더 파일은 가져다 쓰기만 하고, 고칠 것은 주인에게 요청한다.

| 폴더 | 주인 | 담는 것 |
|---|---|---|
| `docs/` | 전원 (자기 작업의 절만) | 진행 문서, 구조 문서, PRD, 데이터 형식 약속 |
| `.github/` | songyee-ai | 자동 검사 |
| `private/` | 각자 (깃에 올라가지 않음) | 내부 자료와 실행 결과(저장된 LLM 응답, 소비 원장, 기본 데이터 집계 파일, 대조 결과), 페르소나 정의의 비공개 층, 후기 주소 목록. 안내 파일 `README.md` 만 저장소에 있다 |
| `engine/` | songyee-ai | 형식 약속을 코드로 옮긴 모델(`engine/formats/`), 후보 추리기와 검사 규칙, 방문 조건 묶음과 가중 합산, 소비 원장, LLM 연결, 실행기, 가상 예시 값으로 만든 저장 응답 |
| `tools/` | songyee-ai | 개발할 때 쓰는 도구. 형식 검사 도구(`tools/check_formats.py`) |
| `tests/` | songyee-ai | 테스트와 예시 파일 한 벌(`tests/fixtures/example/`). 다른 영역은 자기 테스트를 `tests/<자기 폴더 이름>/` 아래에 새 파일로 더한다 (예: `tests/app/`). 테스트에 쓸 예시 파일을 더할 때는 `tests/fixtures/<이름>/` 아래에 저장소와 같은 폴더 모양으로 둔다. 그 묶음도 저장소와 같은 형식 검사를 받는다 (`tests/fixtures/example/` 을 베껴서 고치면 된다) |
| `data/venues/`, `data/samples/`, `data/evidence/extra/` | hojitea-ui | 워커힐 8개 업장과 경쟁 업장의 정의 파일 (이용 상황, 상품과 가격, 판매 단위, 운영 정보, 출처), 가상 예시 값 |
| `data/evidence/`, `personas/` | borigunbbang | 후기를 요약하고 라벨을 붙인 결과, 라벨 값 목록, 페르소나 정의의 공개 층, LLM 프롬프트(`personas/prompts/`) |
| `app/` | wilstein91 | Streamlit 화면 |
| `scenarios/` | wilstein91 | 상황 정의 (시연 시나리오) |
| `slides/` | wilstein91 | 발표 자료 |

폴더 이름은 11-13 에 확정했다. 담당은 [PROGRESS.md](PROGRESS.md) 의 역할 분담 표와 같다.
폴더마다 주인과 담는 것, 베껴서 시작할 예시의 위치를 적은 안내 파일(`README.md`)이 있다.
무엇을 `private/` 에 두고 무엇을 저장소에 두는지는 [PRD.md](PRD.md) 10절이 기준이다.
데이터 폴더(`data/`, `personas/`, `scenarios/`, `engine/samples/`)에는 [FORMATS.md](FORMATS.md) 1절의 파일과 안내 파일만 둔다.
작업 중인 엑셀, 메모, 임시 파일은 `private/` 에 둔다.

## 공통 틀 목록

여러 영역이 함께 쓰는 파일이다. 꼭 필요할 때 팀에 알리고 한 사람이 고친다.

| 파일 | 고치는 사람 | 비고 |
|---|---|---|
| `CLAUDE.md` | songyee-ai | 규칙을 바꾸자는 제안은 누구나 "알릴 것"에 적는다 |
| `.gitignore`, `.gitattributes`, `.env.example` | songyee-ai | `.gitignore` 를 고치면 `tools/check_formats.py` 의 건너뛰는 목록(`ignored_by_git`)도 함께 고친다. 둘이 다르면 테스트가 실패한다 |
| `.github/workflows/check.yml` | songyee-ai | |
| `.github/pull_request_template.md` | songyee-ai | PR 을 열 때 뜨는 확인 양식 |
| `pyproject.toml`, `uv.lock`, `.python-version` | songyee-ai | 패키지와 Python 버전. 필요한 패키지가 생기면 "알릴 것"에 적는다 |
| `engine/formats/` | songyee-ai | 형식 약속을 코드로 옮긴 모델. 모든 영역이 가져다 쓴다 |
| `tools/check_formats.py` | songyee-ai | 형식 검사 도구 |
| `tests/conftest.py`, `tests/fixtures/example/` | songyee-ai | 테스트가 함께 쓰는 것과 예시 파일 한 벌 |
| `.streamlit/config.toml` | songyee-ai | 화면의 설정. 이 PC 에서만 열리게 하고 사용 통계를 보내지 않는다 |
| `README.md` | songyee-ai | 받는 법과 실행 방법 |
| `docs/FORMATS.md` | songyee-ai | 형식을 바꾸자는 제안은 누구나 "알릴 것"에 적는다. 쓰는 사람이 모두 체크한 뒤 바꾼다 |

형식을 바꿀 때는 `docs/FORMATS.md`, `engine/formats/`, `tests/fixtures/example/` 세 곳을 함께 고친다. 하나만 고치면 테스트가 실패한다.

## 영역 사이의 약속

영역끼리 주고받는 데이터 형식이다. 자세한 모양과 예시는 [FORMATS.md](FORMATS.md) 에 있다 (11-13 초안. 쓰는 사람이 확인하면 확정한다).
형식을 바꿀 때는 "알릴 것"에 적고 쓰는 사람 모두가 체크한 뒤 바꾼다.

| 형식 | 만드는 사람 | 쓰는 사람 | `FORMATS.md` 의 절 |
|---|---|---|---|
| 업장 정의 (경쟁 업장 포함) | hojitea-ui | songyee-ai, wilstein91, borigunbbang | 3절 |
| 후기 라벨, 라벨 값 목록, 후기 주소 목록 | borigunbbang (떼어 둔 후기는 hojitea-ui) | songyee-ai, hojitea-ui | 4절 |
| 페르소나 정의 (공개 층과 비공개 층) | borigunbbang | songyee-ai, wilstein91 | 5절 |
| 방문 조건 묶음 | songyee-ai | hojitea-ui, wilstein91 | 6절 |
| 상황 정의 | wilstein91 | songyee-ai | 7절 |
| 기본 데이터 집계 파일, 가상 예시 값 | hojitea-ui | songyee-ai, borigunbbang | 8절 |
| 선택 요청과 응답 | songyee-ai (프롬프트의 문장은 borigunbbang) | songyee-ai | 9절 |
| 실행 결과 (실행 기록, 소비 원장, 저장된 LLM 응답, 대조 결과) | songyee-ai | wilstein91, borigunbbang | 10절 |

## 알려진 함정

겪은 문제와 피하는 방법을 날짜와 함께 적는다.

- 11-11: 줄바꿈은 `.gitattributes` 로 LF 에 고정돼 있다. 편집기가 CRLF 로 저장해도 커밋할 때 LF 로 바뀐다.
- 11-11: `main` 과 `develop` 은 강제 푸시가 막혀 있다. `develop` 은 PR 로만 합칠 수 있다.
- 11-11: 저장소를 만든 직후 푸시와 PR 로 자동 검사가 저절로 시작되지 않았다. 저장소 설정에서 Actions 를
  껐다 켜니 해결됐다. 또 수동 실행(`gh workflow run`)의 결과는 PR 의 필수 검사로 인정되지 않는다.
  PR 에 검사가 안 붙으면 PR 을 닫았다 다시 열거나 새 커밋을 올린다.
- 11-11: 자동 검사는 PR 을 열거나 고칠 때, 그리고 `main`·`develop` 에 들어갈 때 돈다. PR 없이 개인 브랜치에
  푸시만 하면 돌지 않는다. 검사가 통과하지 않은 커밋은 `develop` 과 `main` 에 올라가지 않는다.
- 11-13: 윈도우의 스마트 앱 컨트롤이 켜진 PC 에서는 `uv run pytest` 가 "애플리케이션 제어 정책에서 이 파일을 차단했습니다"로
  실패한다. 설치할 때 만들어지는 실행 파일을 윈도우가 막기 때문이다. `uv run python -m pytest` 처럼 `python -m` 꼴로 돌리면 된다.
- 11-13: 같은 PC 에서 나온 지 열흘쯤 된 pandas 와 pyarrow 가 "DLL load failed"로 막혔고, 한 달쯤 앞선 판은 통과했다.
  그래서 `pyproject.toml` 의 `exclude-newer` 로 새로 나온 판을 쓰지 않게 했다. 패키지의 판을 올릴 때는 그 PC 에서 테스트를 돌려 본다.
- 11-13: Streamlit 은 기본값으로 두면 같은 네트워크의 다른 기기에서도 화면이 열리고 사용 통계를 밖으로 보낸다.
  `.streamlit/config.toml` 에서 둘 다 껐다.
- 11-13: CSV 는 `encoding="utf-8-sig"` 로 읽고 쓴다. BOM 이 없으면 엑셀에서 한글이 깨지고 형식 검사가 "주의"를 낸다.
  `engine.formats.io` 의 `read_csv`, `write_csv` 를 쓰면 맞춰진다.
- 11-13: 형식 검사의 "주의"는 아직 덜 만든 것일 수 있는 항목이라 자동 검사를 막지 않는다. 통합 검증(T23) 때는 `--strict` 로 통과해야 한다.
- 11-13: 깃이 무시하는 것은 저장소 맨 위의 `private/` 뿐이다. `data/private/` 처럼 다른 곳에 만든 폴더는 그대로 올라간다.
  형식 검사가 그런 폴더를 오류로 알려 준다. 내부 자료는 맨 위의 `private/` 로 옮긴다.
- 11-13: 형식 검사는 깃에 올라갈 수 있는 모든 파일을 훑고, 파일의 종류를 이름이 아니라 내용으로 알아본다.
  실행 결과나 후기 라벨을 이름을 바꿔 다른 폴더에 두어도, 목록 하나로 묶거나 `.jsonl` 로 바꿔도 오류가 난다. 엑셀 파일과 묶은 파일은 안을 볼 수 없어 올리지 못한다.
- 11-13: 표나 JSON 에 `순매출`, `총결제액` 이라는 열 이름이 있으면 형식 검사가 기본 데이터로 보고 막는다. 집계해서 열이 하나만 남아도 같다.
  지어낸 값으로 만든 표라면 열 이름을 형식 약속의 영어 이름(`revenue_net`, `paid`)으로 적는다.
- 11-13: 원장의 합계는 `status` 가 `ok` 인 줄로만 낸다. 실패한 방문은 금액이 0 인 줄 하나로 남는다 (`FORMATS.md` 10.2절).
- 11-13: 한국어 엑셀에서 CSV 를 그냥 저장하면 UTF-8 이 아니라서 형식 검사가 오류를 낸다. "CSV UTF-8 (쉼표로 분리)"로 저장한다.
- 11-13: JSON 의 숫자를 따옴표로 감싸면(`"150000"`) 형식 검사가 오류를 낸다. 코드에서 JSON 파일을 읽을 때는 `engine.formats.read_model` 을 쓴다.
  `model_validate` 로 느슨하게 읽으면 그런 파일이 통과해, 검사와 실행이 서로 다른 것을 본다.
- 11-13: 깃헙 액션의 판은 그 액션에 실제로 있는 태그로 적는다. `astral-sh/setup-uv` 는 `v10` 처럼 앞 번호만 적은 태그가 없어 `v10.3.3` 으로 적었다.
  올리기 전에 태그가 있는지 확인한다: `gh api repos/<주인>/<액션>/git/ref/tags/<태그>`
- 11-13: PR 이 base 브랜치와 충돌하면 자동 검사가 아예 시작되지 않는다. PR 의 검사 목록이 비어 있으면 먼저 충돌이 있는지 본다.
  내가 PR 을 여는 사이에 다른 사람의 PR 이 먼저 합쳐지면서 같은 문서를 고쳤을 때 생긴다 (진행 문서의 "알릴 것"이 가장 자주 겹친다).
  `develop` 을 내 브랜치에 합쳐 충돌을 정리하고 다시 푸시하면 검사가 시작된다. 겹친 줄은 양쪽의 변경을 모두 살린다.
