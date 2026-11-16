# 구글 리뷰 수집 부탁 (T301)

borigunbbang 이 wilstein91, songyee-ai 에게 부탁하는 일이다. 11-16 에 썼다.
지킬 규칙의 원본은 [PRD.md](PRD.md) 5.2절과 [REVIEW_RULES.md](REVIEW_RULES.md) 6절이다. 여기에는 순서만 적는다.

## 왜 부탁하나

- 지금 후기는 지도 서비스 한 곳의 것이 대부분이다. 구글 리뷰를 더하면 업장마다 근거가 늘고, 떼어 둘 20%도 5건을 넘기기 쉬워진다.
- 11-16 에 borigunbbang 이 여덟 업장을 최신순으로 시험 저장해 봤는데, 리뷰가 접힌 채(본문과 식사 유형이 잘림) 저장됐고
  리뷰가 많은 세 곳(피자힐, 더뷔페, 명월관)은 끝까지 스크롤되지 않았다. 르파사쥬는 펼쳐서 다시 저장했고, 나머지 일곱 업장을 다시 모아야 한다.
- 구글 리뷰는 대부분 1년 넘은 글이다 (최신순으로 저장한 화면에서도 1년 안의 글이 업장마다 수십 건 이하였다). 기준 기간(2026년)의 근거는 적다.
- 나누는 사람(borigunbbang)은 나누기 전에 파일을 열면 안 된다 (REVIEW_RULES 6절). 그래서 다른 사람이 모아 넘겨주는 것이 맞다.

## 시작하기 전에 (팀장)

- [x] 구글 지도의 이용약관과 robots.txt 를 확인하고, PRD 5.2절의 "후기를 모으는 방식" 조건으로 모아도 되는지 정한다.
  지도 서비스는 11-13 에 확인했지만 구글은 아직이다. 정하기 전에는 모으지 않는다.
  (11-16, 팀장이 확인했다. 약관은 대량 다운로드와 복사를 막지만, PRD 5.2절의 조건을 지키고 넘긴 뒤 지우는 조건으로 모은다)

## 맡을 업장

리뷰 수는 11-16 에 구글 화면에 표시된 전체 수다. 리뷰가 많은 세 곳을 둘로 나눴다. 바꾸고 싶으면 서로 이야기해 이 표를 고친다.

| 맡는 사람 | 업장 (`venue_id`) | 구글 리뷰 수 |
|---|---|---|
| wilstein91 | 피자힐 (`pizzahill`), 금룡 (`geumryong`), 온달 (`ondal`) | 3,007 + 248 + 231 |
| songyee-ai | 더뷔페 (`thebuffet`), 명월관 (`myongwolgwan`), 모에기 (`moegi`), 더파빌리온 (`pavilion`) | 1,650 + 1,253 + 302 + 397 |

르파사쥬(`lepassage`)는 끝났다. 구글 지도 주소 (구글의 업장 이름이 공식 이름과 다른 곳이 있어 주소로 연다):

- 피자힐: https://www.google.com/maps/place/%ED%94%BC%EC%9E%90%ED%9E%90+%EA%B7%B8%EB%9E%9C%EB%93%9C%EC%9B%8C%EC%BB%A4%ED%9E%90%EC%84%9C%EC%9A%B8/data=!4m6!3m5!1s0x357cbab730f3d191:0x68fa9c507f3bc52f
- 금룡: https://www.google.com/maps/place/%EA%B8%88%EB%A3%A1/data=!4m6!3m5!1s0x357ca31f74ec21a1:0xb48af638c71c37df
- 온달: https://www.google.com/maps/place/%EC%98%A8%EB%8B%AC/data=!4m6!3m5!1s0x357cbab0a7a19977:0xba5711fc16e657e5
- 더뷔페: https://www.google.com/maps/place/%EB%8D%94+%EB%B7%94%ED%8E%98/data=!4m6!3m5!1s0x357ca2ed7e74759b:0x486db21b088f532e
- 명월관: https://www.google.com/maps/place/%EB%B9%84%EC%8A%A4%ED%83%80+%EC%9B%8C%EC%BB%A4%ED%9E%90+%EC%84%9C%EC%9A%B8+%EB%AA%85%EC%9B%94%EA%B4%80/data=!4m6!3m5!1s0x357ca31f74ec21a1:0x2a038c19db078e1c
- 모에기: https://www.google.com/maps/place/%EB%AA%A8%EC%97%90%EA%B8%B0+%7C+MOEGI/data=!4m6!3m5!1s0x357cbab0a1e37da7:0xe3d1f6d647ed1da8
- 더파빌리온: https://www.google.com/maps/place/%EB%8D%94+%ED%8C%8C%EB%B9%8C%EB%A6%AC%EC%98%A8/data=!4m6!3m5!1s0x357cbaba6cad051f:0x6611e8374da283a0

기한: 11-17 (화) 저녁. T16 라벨(기한 11-18)에 쓴다.

## 모으는 순서 (업장마다, 크롬)

사람이 자기 브라우저에서 화면을 열고 저장한다. AI 도구로 모으지 않는다 (PRD 5.2절).

1. 위 주소를 크롬으로 열고 **리뷰** 탭을 누른다.
2. 리뷰 목록 위의 정렬 버튼에서 **최신순**을 고른다.
3. `F12` → **Console** 탭에 아래 명령을 붙여 넣고 `Enter`. 처음 붙여 넣으면 크롬이 막고 경고를 띄운다.
   그때는 `allow pasting` 을 직접 입력해 `Enter` 를 누른 뒤 명령을 다시 붙여 넣는다.
   명령은 목록을 끝까지 내리고, 모든 리뷰의 "자세히 보기"를 펼친다. 리뷰가 많은 곳은 몇 분 걸린다.
   ```js
   (async () => {
     let pane = document.querySelector('.jftiEf');
     while (pane && !(pane.scrollHeight > pane.clientHeight && getComputedStyle(pane).overflowY !== 'visible')) pane = pane.parentElement;
     if (!pane) { console.log('리뷰 목록을 못 찾음. 리뷰 탭을 열었는지 확인'); return; }
     let last = -1, same = 0;
     while (same < 5) {
       pane.scrollTop = pane.scrollHeight;
       await new Promise(r => setTimeout(r, 1500));
       const n = document.querySelectorAll('.jftiEf').length;
       same = (n === last) ? same + 1 : 0; last = n;
       console.log('불러온 리뷰', n);
     }
     document.querySelectorAll('button.w8nwRe').forEach(b => b.click());
     await new Promise(r => setTimeout(r, 1000));
     console.log('끝. 리뷰', last, '건, 아직 접힌 리뷰', document.querySelectorAll('button.w8nwRe').length, '건');
   })();
   ```
4. 콘솔에 `끝. … 아직 접힌 리뷰 0 건` 이 나오는지 본다. 0 이 아니면 아래 한 줄을 한 번 더 넣는다.
   ```js
   document.querySelectorAll('button.w8nwRe').forEach(b => b.click())
   ```
5. `Ctrl+S` → 형식은 **웹페이지, 전체** (웹페이지, HTML만 으로 저장하면 불러온 리뷰가 빠진다).
   저장소의 `private\google\` 폴더에 `<venue_id>_google_<날짜>.html` 이름으로 저장한다. 예: `pizzahill_google_2026-11-17.html`
   (`private\` 은 깃이 무시하는 폴더다. 함께 생기는 `_files` 폴더는 넘기지 않아도 된다)

스크롤 명령은 11-16 에 저장 화면의 구조를 보고 만들었고, 실제 구글 화면에서는 아직 돌려 보지 않았다. 리뷰가 적은 곳(금룡, 온달, 모에기)부터 해 본다.
리뷰 수가 멈춘 채 끝나지 않거나 "못 찾음"이 나오면 화면 그대로 borigunbbang 에게 알려 준다.

## 넘기기

1. 아래 "확인 프롬프트"로 저장한 파일을 확인한다.
2. `.html` 파일만 묶어 borigunbbang 에게 **저장소 밖**(메신저 등)으로 보낸다. 커밋이나 PR 에 넣지 않는다.
   ```powershell
   Compress-Archive -Path private\google\*.html -DestinationPath private\google_<내 아이디>.zip
   ```
3. borigunbbang 이 받았다고 알려 주면 내 PC 에서 지운다 (파일에 떼어 둘 20% 도 들어 있다).
   ```powershell
   Remove-Item -Recurse -Force private\google, private\google_<내 아이디>.zip
   ```
4. [PROGRESS.md](PROGRESS.md) 의 "알릴 것"에서 내 이름 줄에 넘긴 날짜와 업장을 적고 체크한다.

받은 파일은 borigunbbang 이 열지 않고 프로그램으로 나눈다 (같은 씨앗, 출처 이름 `google`). 나눈 20% 는 hojitea-ui 에게 간다.

## 확인 프롬프트

Claude Code 에 그대로 붙여 넣는다. 저장소 맨 위 폴더에서 연다.

```text
docs/GOOGLE_REVIEWS.md 를 읽어. 나는 이 문서의 "모으는 순서"대로 구글 리뷰 화면을 private/google/ 에 저장했어.
저장한 파일이 넘겨도 되는 상태인지 확인해 줘.

지킬 것
- 파일의 리뷰 본문, 작성자 이름, 프로필, 사진 주소를 화면에 띄우지 마. 건수와 날짜 표시("3개월 전" 같은 것)만 띄워.
  (이 파일은 다른 사람이 열지 않고 나눌 파일이고, 저장소가 공개라 내용이 대화나 커밋에 섞이면 안 된다)
- 브라우저를 열거나 구글에 접속해서 리뷰를 모으지 마. 확인만 해.
- 파일을 고치거나 옮기지 말고, 저장소에 커밋하지 마.

할 것
1. 아래 파이썬 코드를 private/google/check_google.py 로 저장하고 `uv run python private/google/check_google.py` 로 돌려.
2. 결과를 업장마다 표로 보여 줘. 넘기면 안 되는 것이 있으면 이유와 다시 저장할 방법(문서의 몇 번 단계)을 알려 줘.
   - 리뷰 수가 화면 전체 수보다 많이 적다 → 끝까지 스크롤되지 않았다 (3번)
   - 접힌 리뷰가 0 이 아니다 → 펼치지 않고 저장했다 (4번)
   - "최신순으로 보임"이 False 다 (날짜가 최근 → 과거 순서가 아니다) → 최신순이 아니다 (2번)
   - 리뷰 수가 0 이다 → "웹페이지, HTML만" 으로 저장했거나 리뷰 탭이 아니다 (5번)
3. 문제가 없으면 문서 "넘기기"의 명령을 PowerShell 문법 그대로 알려 줘. 명령은 내가 직접 돌린다.

import glob, re

UNIT = {"분": 0, "시간": 0, "일": 1, "주": 7, "개월": 30, "년": 365}
for p in sorted(glob.glob("private/google/*.html")):
    s = open(p, encoding="utf-8", errors="replace").read()
    cut = s.find('class="jftiEf')
    stars = [int(x.replace(",", "")) for x in re.findall(r"리뷰 ([\d,]+)개", s[:cut] if cut > 0 else s)][:5]
    blocks = re.split(r'<div class="jftiEf', s)[1:]
    when = [re.search(r'class="rsqaWe">([^<]*)<', b) for b in blocks]
    when = [w.group(1) for w in when if w]
    days = []
    for w in when:
        m = re.search(r"(\d+)?\s*(분|시간|일|주|개월|년) 전", w)
        if m:
            days.append(int(m.group(1) or 1) * UNIT[m.group(2)])
    print(p.replace("\\", "/").split("/")[-1],
          "| 리뷰", len(blocks),
          "| 화면 전체", sum(stars) if len(stars) == 5 else "?",
          "| 접힌 리뷰", sum('class="w8nwRe' in b for b in blocks),
          "| 첫 리뷰", when[0] if when else "-",
          "| 마지막 리뷰", when[-1] if when else "-",
          "| 1년 안", sum(d < 365 for d in days),
          "| 최신순으로 보임", days == sorted(days))
```
