"""식당가 그림 (T21, app/street.py): 무엇을 그리는지와 그린 HTML 을 본다."""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.compare import baseline_dir_of, compare  # noqa: E402
from app.icons import PERSONA_SHAPES, VENUE_PATHS, as_img, persona_icon, persona_kind, venue_icon, venue_kind  # noqa: E402
from app.results import load_run  # noqa: E402
from app.street import NONE_KEY, Scene, Store, Token, money, render_scene, scene_from_comparison  # noqa: E402

EXAMPLE = REPO_ROOT / "tests" / "fixtures" / "example"
SCEN = EXAMPLE / "engine" / "samples" / "runs" / "20261117-103000-competitor-chinese-discount"


def _example_scene() -> Scene:
    comparison = compare(load_run(baseline_dir_of(SCEN)), load_run(SCEN))
    return scene_from_comparison(
        comparison,
        {"examplehotel-chinese": "예시호텔 중식당"},
        {"geumryong": "중식 (광동식)", "examplehotel-chinese": "중식"},
        ["geumryong"],
        ["examplehotel-chinese"],
        "경쟁 중식당의 주말 할인",
    )


def test_example_family_walks_from_geumryong_to_the_rival():
    scene = _example_scene()
    [token] = scene.tokens
    assert (token.before, token.after, token.move) == ("walkerhill:geumryong", "competitor:examplehotel-chinese", "out")
    assert token.reason
    stores = {s.key: s for s in scene.stores}
    # 워커힐 업장은 가상 매출, 경쟁 업장은 손님 수. 외식 안 함은 아무도 없어도 가게를 둔다.
    assert stores["walkerhill:geumryong"].unit == "won" and stores["walkerhill:geumryong"].after == 0
    assert stores["competitor:examplehotel-chinese"].unit == "guests" and stores["competitor:examplehotel-chinese"].after > 0
    assert NONE_KEY in stores
    # 아이콘은 직접 그린 픽토그램(SVG)이다: 중식은 그릇과 젓가락, 외식 안 함은 집.
    assert stores["walkerhill:geumryong"].icon == venue_icon("중식") and stores[NONE_KEY].icon == venue_icon("", home=True)
    assert scene.total_before > 0 and scene.total_after == 0


def test_moved_token_has_different_spots_before_and_after():
    html, height = render_scene(_example_scene())
    [style] = re.findall(r'class="tok out"[^>]*style="([^"]+)"', html)
    spots = dict(part.split(":") for part in style.split(";"))
    assert (spots["--bx"], spots["--by"]) != (spots["--ax"], spots["--ay"])
    assert height > 400


def test_screen_calls_runs_base_scenario_and_after_variables():
    html, _ = render_scene(_example_scene())
    assert "기본 시나리오" in html and "변수 적용 후" in html
    assert "평소" not in html and "바뀐 뒤" not in html


def test_pictograms_are_chosen_by_words():
    assert venue_kind("중식 (광동식 모던 컨템포러리)") == "chinese"
    assert venue_kind("한우 숯불구이") == "grill" and venue_kind("한식 코스") == "korean"
    assert venue_kind("로비 라운지 디저트") == "dessert" and venue_kind("알 수 없음") == "dining"
    assert venue_kind("고메 스토어 (델리·와인·치즈·피자·육가공품)") == "store"
    assert venue_kind("올데이 캐주얼 (화덕 피자·파스타)") == "pizza"
    assert persona_kind("어르신을 모신 행사 가족") == "elders"
    assert persona_kind("부모님을 모시는 성인 자녀 가족") == "parents"
    assert persona_kind("아이를 데려온 외식 가족") == "kids" and persona_kind("누군가") == "solo"
    # 그림은 모두 이모지가 아닌 SVG 다.
    for kind in VENUE_PATHS:
        assert "<path" in VENUE_PATHS[kind] or "<circle" in VENUE_PATHS[kind]
    for kind in PERSONA_SHAPES:
        assert persona_icon("x").startswith("<svg") and "<circle" in PERSONA_SHAPES[kind]
    img = as_img(persona_icon("커플"), "#6366f1", 30)
    assert img.startswith('<img src="data:image/svg+xml;base64,') and "<svg" not in img


def test_every_amount_says_virtual():
    html, _ = render_scene(_example_scene())
    values = re.findall(r'class="(?:before|after)-v">([^<]+)<', html)
    assert values and all(v.endswith("(가상)") for v in values)
    assert re.search(r"워커힐 가상 매출.*?\(가상 · 일 년 규모\)</small>", html)  # 맨 위의 워커힐 가상 매출


def test_headline_is_the_change_and_amounts_are_year_scale():
    """머리 숫자는 변화율이고, 금액은 "일 년 규모"라고 적는다 (11-17 팀장 요청: 기간을 골라도 그 기간의 매출이 아니다)."""
    scene = _example_scene()
    scene.scope = "고른 페르소나 1명만"
    html, _ = render_scene(scene)
    head = re.search(r'<div class="kpi">(.*?)</div></div>', html).group(1)
    assert "고른 페르소나 1명만" in head
    assert re.search(r'<span class="chg (up|down|flat)">([+-]\d+%|변화 없음|새로 생김)</span>', head)
    assert "일 년 규모" in head


def test_names_and_reasons_are_escaped():
    stores = [
        Store("walkerhill:a", "<b>가게</b>", "walkerhill", "🍴", "", 1000, 0, "won"),
        Store(NONE_KEY, "외식 안 함", NONE_KEY, "🏠", "", 0, 1, "guests"),
    ]
    tokens = [Token("<script>x</script>", "🙂", "저녁", "walkerhill:a", NONE_KEY, "out", '"이유"')]
    html, _ = render_scene(Scene("<i>t</i>", stores, tokens, 1000, 0))
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert "<b>가게</b>" not in html and "<i>t</i>" not in html


def test_money_reads_easily():
    assert money(65_454_600) == "6,545만원"
    assert money(210_000_000) == "2.1억원"
    assert money(9_000) == "9,000원"
