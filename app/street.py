"""식당가 보기 (T21): 식당이 늘어선 거리 위에서 페르소나가 기본 시나리오 → 변수 적용 후로 옮겨 가는 모습을 그린다.

11-16 결정(지도 대신 간소화한 식당가와 페르소나로 행동 변화를 눈에 띄게)을 그림으로 만든 것이다.
새 패키지 없이 HTML·CSS 로 그리고, 화면에는 `streamlit.components.v1.html` 로 넣는다. 아이콘은 app/icons.py 의 픽토그램이다.
색과 간격은 Tailwind 의 기본 팔레트(slate, indigo, emerald, rose, amber)와 간격 단위를 따랐다. 밝은·어두운 화면 모두 맞춘다.
무엇을 그릴지는 `scene_from_comparison` 이 정하고, `render_scene` 은 그리기만 한다 (테스트하기 쉽게 나눴다).
"""

from dataclasses import dataclass
from html import escape

from app.board import pct_change, venue_cards
from app.compare import Comparison, Place
from app.icons import persona_icon, venue_icon

# 화면에서 두 실행을 부르는 이름 (11-16 화면 담당 결정: "평소/바뀐 뒤" 대신)
BASE_LABEL = "기본 시나리오"
AFTER_LABEL = "변수 적용 후"

# ── 그릴 것 ──


@dataclass
class Store:
    key: str
    name: str
    kind: str  # walkerhill / competitor / none
    icon: str  # SVG
    caption: str
    # 워커힐 업장은 가상 매출(원), 경쟁 업장과 외식 안 함은 손님 수(가상, 명)
    before: float
    after: float
    unit: str  # "won" / "guests"


@dataclass
class Token:
    persona: str
    icon: str  # SVG
    condition: str
    before: str  # Store.key
    after: str
    move: str  # app/compare.py 의 MOVE_LABEL 키
    reason: str = ""


@dataclass
class Scene:
    title: str
    stores: list[Store]
    tokens: list[Token]
    total_before: int
    total_after: int
    hidden: int = 0  # AI 답을 받지 못해 그리지 않은 방문 수


NONE_KEY = "none"


def place_key(place: Place) -> str:
    if place.kind == "none":
        return NONE_KEY
    return f"{place.kind}:{place.venue_id}"


def none_store(before: float = 0.0, after: float = 0.0) -> Store:
    return Store(NONE_KEY, "외식 안 함", NONE_KEY, venue_icon("", home=True), "이번에는 외식하지 않음", before, after, "guests")


def scene_from_comparison(
    comparison: Comparison,
    names: dict[str, str],
    cuisines: dict[str, str],
    walkerhill: list[str],
    competitors: list[str],
    title: str = "",
) -> Scene:
    """비교 결과를 거리 그림으로 바꾼다. `walkerhill`, `competitors` 의 업장은 손님이 없어도 가게를 둔다."""
    cards = {place_key(c.place): c for c in venue_cards(comparison, names, walkerhill)}
    for venue_id in competitors:
        cards.setdefault(f"competitor:{venue_id}", None)
    stores = []
    for key, card in cards.items():
        kind = key.split(":", 1)[0]
        venue_id = key.split(":", 1)[1] if ":" in key else ""
        if kind == "walkerhill":
            before, after, unit = float(card.revenue_before or 0), float(card.revenue_after or 0), "won"
        elif card:
            before, after, unit = card.guests_before, card.guests_after, "guests"
        else:
            before, after, unit = 0.0, 0.0, "guests"
        if kind == NONE_KEY:
            stores.append(none_store(before, after))
            continue
        name = card.name if card else names.get(venue_id, venue_id)
        cuisine = cuisines.get(venue_id, "")
        stores.append(Store(key, name, kind, venue_icon(cuisine), cuisine.split(" (")[0], before, after, unit))
    order = {"walkerhill": 0, "competitor": 1, NONE_KEY: 2}
    stores.sort(key=lambda s: (order[s.kind], s.name))
    if not any(s.kind == NONE_KEY for s in stores):
        stores.append(none_store())

    tokens = [
        Token(m.persona, persona_icon(m.persona), m.condition, place_key(m.before), place_key(m.after), m.move, m.reason_after or "")
        for m in comparison.moves
        if m.move != "failed"
    ]
    hidden = sum(1 for m in comparison.moves if m.move == "failed")
    return Scene(title, stores, tokens, comparison.total_before, comparison.total_after, hidden)


# ── 그리기 ──
# 가게 카드 안에 손님 줄을 두어(빈 자리를 따로 두지 않고) 한 화면에 식당가 전체가 들어오게 한다.

COLS = 4  # 한 줄에 놓는 가게 수
CARD_TOP = 58  # 카드 윗부분(아이콘·이름·값)의 높이(px)
LANE_H = 38  # 카드 아래 손님 줄 한 줄의 높이(px)
ROW_GAP = 12
ZONE_HEAD = 28
TOKEN = 30  # 페르소나 동그라미 지름(px)
TOKEN_STEP = 34  # 손님 줄에서 페르소나 사이 간격(px)
PER_LANE = 6  # 손님 줄 한 줄에 서는 페르소나 수

MOVE_TEXT = {
    "out": "워커힐 밖으로",
    "in": "워커힐로",
    "inside": "워커힐 안에서",
    "other": "밖에서 옮김",
    "same": "그대로",
}


def money(amount: float) -> str:
    """큰 금액을 읽기 쉽게 줄인다: 1억 이상은 억, 1만 이상은 만 원. "가상" 표시는 부르는 쪽이 붙인다."""
    amount = round(amount)
    if abs(amount) >= 100_000_000:
        return f"{amount / 100_000_000:,.1f}억원"
    if abs(amount) >= 10_000:
        return f"{amount / 10_000:,.0f}만원"
    return f"{amount:,}원"


def value_text(store: Store, value: float) -> str:
    return f"{money(value)} (가상)" if store.unit == "won" else f"{value:,.0f}명 (가상)"


def delta_text(store: Store) -> tuple[str, str]:
    """(글, 색의 이름). 색은 up / down / flat 이고, 늘었나 줄었나만 뜻한다 (가게 테두리의 색과 같은 뜻)."""
    diff = store.after - store.before
    if round(diff) == 0:
        return "변화 없음", "flat"
    sign = "▲" if diff > 0 else "▼"
    if store.unit == "won":
        text = f"{sign} {money(abs(diff))} ({pct_change(store.before, store.after)})"
    else:
        text = f"{sign} {abs(diff):,.0f}명"
    return text, "up" if diff > 0 else "down"


@dataclass
class _Slot:
    left: float  # %
    top: int  # px
    width: float  # %


ZONES = (("워커힐 다이닝", ("walkerhill",)), ("경쟁 호텔 · 외식 안 함", ("competitor", NONE_KEY)))


def _lanes(tokens: list[Token]) -> int:
    """손님 줄이 몇 줄 필요한가: 기본 시나리오와 변수 적용 후 가운데 한 가게에 가장 많이 선 사람 수로 정한다."""
    most = 0
    for which in ("before", "after"):
        count: dict[str, int] = {}
        for token in tokens:
            key = getattr(token, which)
            count[key] = count.get(key, 0) + 1
        most = max([most, *count.values()])
    return max(1, -(-most // PER_LANE))


def _layout(stores: list[Store], card_h: int) -> tuple[dict[str, _Slot], list[tuple[str, int]], int]:
    """가게 자리. 워커힐 구역, 그 아래 경쟁 호텔과 외식 안 함 구역. (자리, 구역 제목과 높이, 전체 높이)."""
    slots: dict[str, _Slot] = {}
    heads: list[tuple[str, int]] = []
    width = 100 / COLS
    top = 0
    for zone, kinds in ZONES:
        group = [s for s in stores if s.kind in kinds]
        if not group:
            continue
        heads.append((zone, top))
        top += ZONE_HEAD
        for i, store in enumerate(group):
            row, col = divmod(i, COLS)
            slots[store.key] = _Slot(col * width, top + row * (card_h + ROW_GAP), width)
        rows = -(-len(group) // COLS)
        top += rows * (card_h + ROW_GAP) + 6
    return slots, heads, top


def _token_spots(tokens: list[Token], slots: dict[str, _Slot], which: str) -> list[tuple[str, int]]:
    """페르소나마다 (CSS left, top px). 가게 카드 아래의 손님 줄에 왼쪽부터 선다."""
    count: dict[str, int] = {}
    spots = []
    for token in tokens:
        key = getattr(token, which)
        slot = slots.get(key) or slots[NONE_KEY]
        n = count.get(key, 0)
        count[key] = n + 1
        lane, pos = divmod(n, PER_LANE)
        left = f"calc({slot.left:.3f}% + {16 + pos * TOKEN_STEP}px)"
        spots.append((left, slot.top + CARD_TOP + 4 + lane * LANE_H))
    return spots


CSS = """
:root {
  --bg:#ffffff; --panel:#f8fafc; --line:#e5e7eb; --line2:#f1f5f9; --ink:#0f172a; --sub:#475569; --muted:#94a3b8;
  --accent:#4f46e5; --accent-soft:#eef2ff; --wh:#b45309; --wh-soft:#fef3c7; --rival:#475569; --rival-soft:#f1f5f9;
  --up:#059669; --up-soft:#d1fae5; --down:#e11d48; --down-soft:#ffe4e6; --move:#2563eb; --move-soft:#dbeafe;
  --token:#ffffff; --shadow:0 1px 2px rgba(15,23,42,.05);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#0b1220; --panel:#111a2b; --line:#1f2a3d; --line2:#172234; --ink:#e5e7eb; --sub:#a3adbf; --muted:#64748b;
    --accent:#a5b4fc; --accent-soft:#1e1b4b; --wh:#fbbf24; --wh-soft:#3b2a0a; --rival:#cbd5e1; --rival-soft:#1e293b;
    --up:#34d399; --up-soft:#06352a; --down:#fb7185; --down-soft:#3f0d1a; --move:#93c5fd; --move-soft:#172554;
    --token:#111a2b; --shadow:0 1px 2px rgba(0,0,0,.4);
  }
}
* { box-sizing:border-box; margin:0; padding:0; }
body { background:transparent; color:var(--ink); line-height:1.45; font-size:13px;
  font-family:"Pretendard","Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif; -webkit-font-smoothing:antialiased; }
.wrap { background:var(--bg); border:1px solid var(--line); border-radius:14px; padding:18px 18px 14px; }
.kpis { display:grid; grid-template-columns:1.6fr 1fr 1fr; border:1px solid var(--line); border-radius:12px; overflow:hidden; margin-bottom:14px; }
.kpi { padding:12px 16px; background:var(--panel); }
.kpi + .kpi { border-left:1px solid var(--line); }
.kpi .k { font-size:12px; color:var(--sub); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.kpi .v { font-size:22px; font-weight:700; letter-spacing:-.02em; margin-top:2px; font-variant-numeric:tabular-nums; display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
.kpi .v small { font-size:13px; font-weight:500; color:var(--muted); }
.pill { display:inline-block; font-size:11.5px; font-weight:600; padding:2px 8px; border-radius:999px; }
.pill.up { background:var(--up-soft); color:var(--up); } .pill.down { background:var(--down-soft); color:var(--down); }
.pill.flat { background:var(--rival-soft); color:var(--sub); }
.bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
.seg { display:inline-flex; background:var(--panel); border:1px solid var(--line); border-radius:9px; padding:2px; }
.seg button { font:inherit; font-size:13px; font-weight:600; border:0; background:transparent; color:var(--sub); padding:5px 12px; border-radius:7px; cursor:pointer; }
.seg button.on { background:var(--bg); color:var(--ink); box-shadow:0 1px 3px rgba(15,23,42,.12); }
.replay { font:inherit; font-size:13px; font-weight:600; border:0; background:transparent; color:var(--accent); cursor:pointer; padding:5px 4px; }
.legend { display:flex; gap:12px; flex-wrap:wrap; font-size:12px; color:var(--sub); margin-left:auto; }
.legend i { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; vertical-align:1px; }
.who { display:flex; gap:6px; flex-wrap:wrap; margin:-4px 0 12px; }
.who span { display:inline-flex; align-items:center; gap:5px; font-size:12px; color:var(--sub); background:var(--panel);
  border:1px solid var(--line); padding:2px 9px 2px 3px; border-radius:999px; }
.who span b { width:20px; height:20px; border-radius:50%; background:var(--accent-soft); color:var(--accent); display:inline-flex; align-items:center; justify-content:center; }
.scene { position:relative; }
.zone { position:absolute; left:2px; font-size:11px; font-weight:700; letter-spacing:.08em; color:var(--muted); text-transform:uppercase; }
.store { position:absolute; padding:0 5px; }
.card { background:var(--bg); border:1px solid var(--line); border-radius:11px; box-shadow:var(--shadow); overflow:hidden;
  transition:border-color .5s, box-shadow .5s; }
.top { height:__CARD_TOP__px; display:flex; align-items:center; gap:10px; padding:0 12px; }
.pic { width:34px; height:34px; flex:none; border-radius:9px; display:flex; align-items:center; justify-content:center; background:var(--wh-soft); color:var(--wh); }
.store.competitor .pic { background:var(--rival-soft); color:var(--rival); }
.store.none .pic { background:var(--line2); color:var(--muted); }
.id { min-width:0; flex:1; }
.nm { font-size:13.5px; font-weight:700; line-height:1.3; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cap { font-size:11.5px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.val { font-size:12px; font-weight:600; color:var(--sub); font-variant-numeric:tabular-nums; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.lane { border-top:1px dashed var(--line); background:var(--panel); position:relative; }
.lane .d { position:absolute; right:10px; top:9px; font-size:11px; font-weight:700; padding:1px 7px; border-radius:999px; white-space:nowrap; }
.lane .d.up { color:var(--up); background:var(--up-soft); } .lane .d.down { color:var(--down); background:var(--down-soft); }
.lane .d.flat { color:var(--muted); background:transparent; }
.store.none .card { background:var(--panel); }
.after-v, .after-d { display:none; }
.st-after .after-v, .st-after .after-d { display:inline-block; }
.st-after .before-v { display:none; }
.st-after .store.lost .card { border-color:var(--down); box-shadow:0 0 0 3px var(--down-soft); }
.st-after .store.won .card { border-color:var(--up); box-shadow:0 0 0 3px var(--up-soft); }
.tok { position:absolute; width:__TOK__px; height:__TOK__px; border-radius:50%; background:var(--token); color:var(--accent);
  display:flex; align-items:center; justify-content:center; box-shadow:0 1px 3px rgba(15,23,42,.18); border:2px solid var(--line);
  left:var(--bx); top:var(--by); z-index:3; cursor:default;
  transition:left 1.2s cubic-bezier(.6,.05,.3,1) var(--delay), top 1.2s cubic-bezier(.6,.05,.3,1) var(--delay), border-color .4s, color .4s; }
.st-after .tok { left:var(--ax); top:var(--ay); }
.st-after .tok.out { border-color:var(--down); color:var(--down); } .st-after .tok.in { border-color:var(--up); color:var(--up); }
.st-after .tok.inside, .st-after .tok.other { border-color:var(--move); color:var(--move); }
.moves { margin-top:14px; border:1px solid var(--line); border-radius:12px; overflow:hidden; }
.moves .hd { font-size:12px; font-weight:700; color:var(--sub); padding:9px 14px; background:var(--panel); border-bottom:1px solid var(--line); }
.mv { display:flex; gap:10px; align-items:flex-start; padding:10px 14px; }
.mv + .mv { border-top:1px solid var(--line2); }
.mv .e { width:28px; height:28px; flex:none; border-radius:8px; background:var(--accent-soft); color:var(--accent); display:flex; align-items:center; justify-content:center; }
.mv .t { font-size:13px; font-weight:600; } .mv .r { font-size:12px; color:var(--sub); margin-top:1px; }
.tag { font-size:10.5px; font-weight:700; padding:1px 7px; border-radius:5px; margin-right:6px; }
.tag.out { background:var(--down-soft); color:var(--down); } .tag.in { background:var(--up-soft); color:var(--up); }
.tag.inside, .tag.other { background:var(--move-soft); color:var(--move); }
.note { font-size:11.5px; color:var(--muted); margin-top:10px; }
"""

JS = """
const root = document.getElementById('root');
const btnB = document.getElementById('b-before'), btnA = document.getElementById('b-after'), btnP = document.getElementById('b-play');
function show(after){ root.classList.toggle('st-after', after); btnA.classList.toggle('on', after); btnB.classList.toggle('on', !after); }
function play(){ show(false); setTimeout(() => show(true), 900); }
btnB.onclick = () => show(false); btnA.onclick = () => show(true); btnP.onclick = play;
play();
"""


def _small(svg: str, size: int) -> str:
    return svg.replace('width="28" height="28"', f'width="{size}" height="{size}"', 1)


def render_scene(scene: Scene) -> tuple[str, int]:
    """(HTML, 높이 px). 높이는 화면에 넣을 때 쓴다."""
    lanes = _lanes(scene.tokens)
    card_h = CARD_TOP + lanes * LANE_H
    slots, heads, scene_h = _layout(scene.stores, card_h)
    before = _token_spots(scene.tokens, slots, "before")
    after = _token_spots(scene.tokens, slots, "after")
    lost = {t.before for t in scene.tokens if t.before != t.after}
    won = {t.after for t in scene.tokens if t.before != t.after}

    parts = [f'<div class="zone" style="top:{top + 4}px">{escape(name)}</div>' for name, top in heads]
    for store in scene.stores:
        slot = slots[store.key]
        d_text, d_kind = delta_text(store)
        state = " lost" if store.key in lost and store.key not in won else " won" if store.key in won and store.key not in lost else ""
        parts.append(
            f'<div class="store {store.kind}{state}" style="left:{slot.left:.3f}%;top:{slot.top}px;width:{slot.width:.3f}%">'
            f'<div class="card"><div class="top"><div class="pic">{_small(store.icon, 20)}</div>'
            f'<div class="id"><div class="nm" title="{escape(store.name)} · {escape(store.caption)}">{escape(store.name)}</div>'
            f'<div class="val"><span class="before-v">{escape(value_text(store, store.before))}</span>'
            f'<span class="after-v">{escape(value_text(store, store.after))}</span></div></div></div>'
            f'<div class="lane" style="height:{lanes * LANE_H}px"><span class="d after-d {d_kind}">{escape(d_text)}</span></div></div></div>'
        )
    for i, (token, (bx, by), (ax, ay)) in enumerate(zip(scene.tokens, before, after, strict=True)):
        moved = token.before != token.after
        tip = f"{token.persona} · {token.condition}" + (f" — {token.reason}" if token.reason else "")
        parts.append(
            f'<div class="tok {token.move}" title="{escape(tip)}" '
            f'style="--bx:{bx};--by:{by}px;--ax:{ax};--ay:{ay}px;--delay:{(i * 0.12 if moved else 0):.2f}s">'
            f"{_small(token.icon, 17)}</div>"
        )

    diff = scene.total_after - scene.total_before
    total = Store("total", "", "walkerhill", "", "", scene.total_before, scene.total_after, "won")
    t_text, t_kind = delta_text(total)
    moved = [t for t in scene.tokens if t.before != t.after]
    names = {s.key: s.name for s in scene.stores}
    people: dict[str, str] = {}
    for token in scene.tokens:
        people.setdefault(token.persona, token.icon)
    who = "".join(f"<span><b>{_small(icon, 13)}</b>{escape(name)}</span>" for name, icon in people.items())
    move_rows = "".join(
        f'<div class="mv"><div class="e">{_small(t.icon, 16)}</div><div><div class="t"><span class="tag {t.move}">{MOVE_TEXT[t.move]}</span>'
        f"{escape(t.persona)} · {escape(names.get(t.before, ''))} → {escape(names.get(t.after, ''))}</div>"
        f'<div class="r">{escape(t.condition)}{" — " + escape(t.reason) if t.reason else ""}</div></div></div>'
        for t in moved
    )
    note = []
    if not moved:
        note.append(f"{BASE_LABEL}와 선택이 같습니다. 이 변수로는 고른 페르소나의 선택이 바뀌지 않았습니다.")
    if scene.hidden:
        note.append(f"AI 답을 받지 못한 방문 {scene.hidden}건은 그림과 매출에서 뺐습니다.")
    note.append("모든 금액과 손님 수는 가상 값입니다. 페르소나에 마우스를 올리면 고른 이유가 보입니다.")
    outs = sum(t.move == "out" for t in scene.tokens)
    ins = sum(t.move == "in" for t in scene.tokens)

    body = (
        '<div class="wrap" id="root"><div class="kpis">'
        f'<div class="kpi"><div class="k">워커힐 가상 매출 · {escape(scene.title)}</div>'
        f'<div class="v"><small>{escape(money(scene.total_before))} →</small>{escape(money(scene.total_after))} (가상)'
        f'<span class="pill {t_kind if diff else "flat"}">{escape(t_text)}</span></div></div>'
        f'<div class="kpi"><div class="k">워커힐 밖으로 나간 방문</div><div class="v">{outs}건</div></div>'
        f'<div class="kpi"><div class="k">워커힐로 들어온 방문</div><div class="v">{ins}건</div></div></div>'
        '<div class="bar"><div class="seg">'
        f'<button id="b-before">{BASE_LABEL}</button><button id="b-after">{AFTER_LABEL}</button></div>'
        '<button class="replay" id="b-play">↻ 다시 보기</button>'
        '<div class="legend"><span><i style="background:var(--down)"></i>떠난 곳 · 워커힐 밖으로</span>'
        '<span><i style="background:var(--up)"></i>온 곳 · 워커힐로</span>'
        '<span><i style="background:var(--move)"></i>그 밖에 옮김</span></div></div>'
        f'<div class="who">{who}</div>'
        f'<div class="scene" style="height:{scene_h}px">{"".join(parts)}</div>'
        + (f'<div class="moves"><div class="hd">움직인 페르소나 {len(moved)}명</div>{move_rows}</div>' if moved else "")
        + f'<div class="note">{" ".join(escape(n) for n in note)}</div></div>'
    )
    css = CSS.replace("__CARD_TOP__", str(CARD_TOP)).replace("__TOK__", str(TOKEN))
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}<script>{JS}</script></body></html>"
    height = 36 + 74 + 44 + 34 + scene_h + (40 + len(moved) * 58 if moved else 0) + 40
    return html, height
