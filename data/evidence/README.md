# data/evidence — 후기 라벨과 라벨 값 목록

- 주인: borigunbbang (외부 데이터·페르소나). 단, `extra/` 는 hojitea-ui 의 폴더다.
- 담는 것
  - `vocab.json`: 라벨 값 목록
  - `reviews/<venue_id>.csv`: 만드는 데 쓰는 공개 후기의 라벨 (번호 0001 ~ 4999)
    - 0001 ~ 1999: 지도 서비스 방문자 리뷰 (금룡은 80% 전부, 피자힐·더뷔페·더파빌리온은 80% 에서 무작위로 뽑은 200건)
    - 2001 ~ 2999: 블로그 80% 전부
    - 3001 ~ 3999: 표본 밖의 방문자·구글·예약 서비스 후기 가운데 고른 이유를 밝힌 문장이 있는 것만 골라 붙인 후기.
      일부러 고른 후기라 **고객군 안의 몫처럼 비율을 내는 데는 쓰지 않는다.** 고른 이유·걸린 점의 근거로만 쓴다 (11-17, T16)
  - `extra/<venue_id>.csv`: 돕는 사람이 붙인 라벨 (번호 5000 ~ 9999)
- 형식: [docs/FORMATS.md](../../docs/FORMATS.md) 4절
- 예시: [tests/fixtures/example/data/evidence/](../../tests/fixtures/example/data/evidence/)

**이 폴더에 올리지 않는 것** — 아래는 각자 PC 의 `private/evidence/` 에만 둔다.

- 후기의 원문, 작성자 아이디, 주소
- 후기 주소 목록 (`review_urls.csv`, `holdout_urls.csv`, `build_urls.csv`)
- 떼어 둔 후기 (번호가 `H-` 로 시작)
- 받은 참고 소스의 후기 (번호가 `P-` 로 시작)

검사 도구가 위의 것이 섞였는지 본다: `uv run python -m tools.check_formats`

이 폴더에는 위 "담는 것"의 파일과 안내 파일만 둔다. 다른 파일이나 하위 폴더를 두면 검사가 오류를 낸다.
요약(`summary`)을 비롯한 어느 칸에도 후기의 주소를 적지 않는다.
