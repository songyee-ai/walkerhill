"""화면에 쓰는 픽토그램 (T21). 이모지 대신 직접 그린 SVG 다.

- 업장: 선으로 그린 아이콘 (24×24, 색은 `currentColor` 를 따른다).
- 페르소나: 사람 모양을 채워 그린 픽토그램. 일행의 모양(혼자, 커플, 3대 가족 …)이 보이게 한다.
어느 아이콘을 쓸지는 음식 종류·페르소나 이름의 낱말로 고른다 (`venue_icon`, `persona_icon`).
"""

LINE = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'


def _svg(body: str, size: int, filled: bool = False) -> str:
    style = 'fill="currentColor"' if filled else LINE
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{size}" height="{size}" {style} aria-hidden="true">{body}</svg>'


# ── 업장 ──
VENUE_PATHS = {
    # 그릇과 젓가락
    "chinese": '<path d="M3.5 12h17a8.5 7.5 0 0 1-17 0z"/><path d="M9 21h6"/><path d="M13 3.5 9.5 10"/><path d="M18 4l-4.5 6"/>',
    # 초밥 (밥 위에 생선, 김 띠)
    "japanese": '<rect x="3.5" y="11" width="17" height="7.5" rx="3.75"/><path d="M4.5 11.5c2.5-3.5 12.5-3.5 15 0"/>'
    '<rect x="10" y="8.6" width="4" height="10" rx="1"/>',
    # 김이 나는 뚝배기
    "korean": '<path d="M4 12h16v1.5a6.5 6.5 0 0 1-6.5 6.5h-3A6.5 6.5 0 0 1 4 13.5z"/><path d="M2 13h2M20 13h2"/>'
    '<path d="M9 3.5c-1.2 1.5 1.2 2.5 0 4.5M15 3.5c-1.2 1.5 1.2 2.5 0 4.5"/>',
    # 숯불 그릴
    "grill": '<circle cx="12" cy="10.5" r="7"/><path d="M7.5 7.5h9M5.5 10.5h13M7.5 13.5h9"/><path d="M8.5 17l-2 4.5M15.5 17l2 4.5"/>',
    # 피자 조각
    "pizza": '<path d="M12 21 3.2 6.5a15 15 0 0 1 17.6 0z"/><path d="M4.8 9a12 12 0 0 1 14.4 0"/>'
    '<circle cx="10" cy="11.5" r="1"/><circle cx="14.2" cy="12.3" r="1"/><circle cx="12" cy="15.6" r="1"/>',
    # 뷔페 (덮개를 씌운 접시)
    "buffet": '<path d="M4 17a8 8 0 0 1 16 0"/><path d="M2 17h20"/><circle cx="12" cy="7" r="1.2"/><path d="M5 20.5h14"/>',
    # 디저트 (초를 꽂은 케이크)
    "dessert": '<rect x="4" y="11" width="16" height="9.5" rx="1.5"/><path d="M4 15.2c2 1.4 4 1.4 6 0s4-1.4 6 0 3 1 4 0"/>'
    '<path d="M12 11V7.5"/><path d="M12 3.6c1 1 1 2.2 0 3.2-1-1-1-2.2 0-3.2z"/>',
    # 델리·베이커리 (빵 한 덩이)
    "bakery": '<path d="M4 13.5a8 6.5 0 0 1 16 0V19a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19z"/><path d="M9 9.5l1.6 3M13.5 8.8l1.6 3"/>',
    # 고메 스토어 (장바구니)
    "store": '<path d="M5 8h14l-1.3 11.2a1.5 1.5 0 0 1-1.5 1.3H7.8a1.5 1.5 0 0 1-1.5-1.3z"/><path d="M9 8V6.5a3 3 0 0 1 6 0V8"/>',
    # 그 밖의 식당 (포크와 나이프)
    "dining": '<path d="M6.5 3v7a2.5 2.5 0 0 0 5 0V3"/><path d="M9 12.5V21M9 3v5"/><path d="M17.5 3c-2.2 2.2-2.2 7 0 9v9"/>',
    # 외식 안 함 (집)
    "home": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v10.5h13V10"/><path d="M10 20.5v-5.5h4v5.5"/>',
}

# 음식 종류의 낱말 → 아이콘. 앞에 있는 것이 먼저 맞는다.
CUISINE_WORDS = [
    ("중식", "chinese"),
    ("일식", "japanese"),
    ("스테이크", "grill"),
    ("숯불", "grill"),
    ("구이", "grill"),
    ("한식", "korean"),
    # 고메 스토어·델리는 파는 것에 "피자"가 섞여 있어 피자보다 먼저 본다 (르파사쥬가 피자 아이콘이 되지 않게).
    ("고메", "store"),
    ("델리", "bakery"),
    ("베이커리", "bakery"),
    ("피자", "pizza"),
    ("뷔페", "buffet"),
    ("디저트", "dessert"),
    ("라운지", "dessert"),
]


def venue_kind(cuisine: str) -> str:
    return next((kind for word, kind in CUISINE_WORDS if word in cuisine), "dining")


def venue_icon(cuisine: str, size: int = 28, home: bool = False) -> str:
    return _svg(VENUE_PATHS["home" if home else venue_kind(cuisine)], size)


# ── 페르소나 ──


def _figure(cx: float, top: float, h: float) -> str:
    """사람 하나: 머리(원)와 몸(둥근 사각형). `top` 은 머리 꼭대기, `h` 는 키다."""
    r = h * 0.15
    w = h * 0.38
    return (
        f'<circle cx="{cx:.2f}" cy="{top + r:.2f}" r="{r:.2f}"/>'
        f'<rect x="{cx - w / 2:.2f}" y="{top + r * 2 + h * 0.06:.2f}" width="{w:.2f}" height="{h * 0.6:.2f}" rx="{w * 0.45:.2f}"/>'
    )


HEART = '<path d="M12 6.2c-.9-1.6-3.6-1.4-3.6.7 0 1.4 1.8 2.6 3.6 3.9 1.8-1.3 3.6-2.5 3.6-3.9 0-2.1-2.7-2.3-3.6-.7z"/>'

PERSONA_SHAPES = {
    "solo": _figure(12, 2.5, 19.5),
    "couple": _figure(7, 5, 17) + _figure(17, 5, 17) + HEART,
    "parents": _figure(4.5, 6, 14) + _figure(12, 3, 17) + _figure(19.5, 6, 14),
    # 3대 가족: 어른, 아이, 지팡이를 짚은 어르신
    "elders": _figure(10.5, 3, 18) + _figure(3.8, 10, 12) + _figure(17.5, 5.5, 16)
    + '<rect x="21.2" y="12" width="1.4" height="10" rx=".7"/><rect x="20" y="11.2" width="2.6" height="1.4" rx=".7"/>',
    "kids": _figure(9, 2.5, 19) + _figure(18, 10.5, 11.5),
    "business": _figure(9.5, 2.5, 19)
    + '<rect x="14.5" y="13.5" width="8" height="6.5" rx="1.2"/><rect x="17" y="11.8" width="3" height="2.4" rx=".8" fill="none" '
    'stroke="currentColor" stroke-width="1.2"/>',
    "friends": _figure(4.5, 5, 15) + _figure(12, 3.5, 17) + _figure(19.5, 5, 15),
    "traveler": _figure(8.5, 2.5, 19)
    + '<rect x="15" y="11" width="6.5" height="9.5" rx="1.4"/><path d="M16.8 11V9.4h2.9V11" fill="none" stroke="currentColor" stroke-width="1.3"/>',
}

# 페르소나 이름의 낱말 → 모양. 앞에 있는 것이 먼저 맞는다.
PERSONA_WORDS = [
    ("어르신", "elders"),
    ("3대", "elders"),
    ("부모님", "parents"),
    ("아이", "kids"),
    ("자녀", "kids"),
    ("커플", "couple"),
    ("연인", "couple"),
    ("부부", "couple"),
    ("비즈니스", "business"),
    ("출장", "business"),
    ("직장", "business"),
    ("친구", "friends"),
    ("모임", "friends"),
    ("투숙", "traveler"),
    ("여행", "traveler"),
    ("외국", "traveler"),
]


def persona_kind(name: str) -> str:
    return next((kind for word, kind in PERSONA_WORDS if word in name), "solo")


def persona_icon(name: str, size: int = 28) -> str:
    return _svg(PERSONA_SHAPES[persona_kind(name)], size, filled=True)


def as_img(svg: str, color: str, size: int) -> str:
    """`st.html` 은 SVG 태그를 걸러 내므로, 색을 박은 그림 파일(data URI)의 <img> 로 바꿔 넣는다."""
    import base64

    data = base64.b64encode(svg.replace("currentColor", color).encode("utf-8")).decode("ascii")
    return f'<img src="data:image/svg+xml;base64,{data}" width="{size}" height="{size}" alt="">'
