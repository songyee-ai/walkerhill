// 결과 페이지 스크립트 (T130). 시안 final-v14 의 report.js 와 지도 스크립트를 옮겨, Streamlit 컴포넌트(st.components.v2)로 띄운다.
// 파이썬(app/result_page.py)이 시나리오 결과 하나를 데이터 묶음(app/result_model.py 의 build)으로 넘기고, 이 스크립트가 모든 구역을 그린다.
// 화면은 그림자 영역(shadow root) 안에 있어, 원래 스크립트가 쓰던 document 를 그림자 영역을 가리키는 대리 객체로 바꿔 끼운다.
// 다른 페이지로 가는 것(다른 결과 열기, 시나리오 만들기)은 setTriggerValue("action", …) 로 파이썬에 보낸다.
export default function (component) {
  const { parentElement: R, setTriggerValue } = component;
  const DATA = component.data;
  const W = R && R.querySelector(".wh-page");
  // Streamlit 이 다시 그릴 때마다 이 함수를 부른다. 같은 화면 조각이면 한 번만 꾸린다 (결과가 바뀌면 파이썬이 새 조각을 띄운다)
  if (!DATA || !W || W.__whReady) return;
  W.__whReady = true;
  const D = globalThis.document;
  const ICONS = "/app/static/icons/";
  const document = {
    getElementById: id => R.getElementById(id),
    querySelector: s => R.querySelector(s),
    querySelectorAll: s => R.querySelectorAll(s),
    createElement: tag => D.createElement(tag),
    createElementNS: (ns, tag) => D.createElementNS(ns, tag),
    // 누르기는 그림자 영역에서 받는다. 문서에서 받으면 누른 대상이 그림자 바깥 상자로 바뀌어 보여 판이 열리자마자 닫힌다
    addEventListener: (type, fn, opts) => (type === "visibilitychange" ? D : R).addEventListener(type, fn, opts),
    get hidden() { return D.hidden; },
    get documentElement() { return W; },
  };
  const act = (type, extra) => setTriggerValue("action", Object.assign({ type, at: Date.now() }, extra || {}));
  const mlab = m => (m == null ? "일 년 전체" : m + "월");
  const VISIT_NO = new Map(DATA.months.flatMap(m => m.visits.map(v => [v.visit_id, v.visit_no])));
  const plainWon = n => Math.round(n).toLocaleString("ko-KR") + "원";
  const signedWon = n => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(Math.round(n)).toLocaleString("ko-KR") + "원";
  const manWon = n => {
    const a = Math.abs(n), s = n > 0 ? "+" : n < 0 ? "−" : "";
    return a >= 10000 ? s + Math.round(a / 10000).toLocaleString("ko-KR") + "만 원" : s + Math.round(a).toLocaleString("ko-KR") + "원";
  };
  const rateOf = (after, before) => (before ? ((after - before) / before) * 100 : null);
  const rateText = r => (r == null ? "—" : (r > 0 ? "+" : r < 0 ? "−" : "") + Math.abs(r).toFixed(1) + "%");
  const shortTime = iso => (iso || "").slice(5, 16).replace("T", " ");
  const WEAK_GRADES = new Set(["assumption", "unknown", "가정", "미확인"]);
  function el(tag, cls, text) {
    const node = D.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function quote(text) {
    const box = el("blockquote");
    box.append(el("q", "", text));
    return box;
  }
  function aiFigure(text, small) {
    const figure = el("figure", "wh-ai" + (small ? " wh-ai--small" : ""));
    figure.append(el("figcaption", "wh-ai-label", "AI가 생성한 선택 이유"), quote(text));
    return figure;
  }
  const gradeTag = (label, key) => el("span", "wh-g" + (WEAK_GRADES.has(key || label) ? " wh-g--weak" : ""), label);
  const proofTag = personaId => {
    const info = DATA.persona_info[personaId];
    return info && info.evidence && info.evidence.limited
      ? el("span", "wh-tag wh-tag--warn", "근거 제한적")
      : el("span", "wh-tag wh-tag--proof", "참고 근거 · 후기");
  };

  // ── 달과 상관없는 구역: 배너, 창, 근거 표 (한 번만 채운다) ──
  (function fillStatic() {
    const S = DATA.scenario;
    R.querySelector(".cover-image").style.backgroundImage = 'url("' + DATA.assets.banner + '")';
    R.getElementById("report-name").textContent = S.name;
    R.querySelector(".assumptions").replaceChildren(...S.changes_text.map(text => el("li", "", text)));
    R.querySelector("[data-basis-compare]").textContent = "기본 시나리오와, ‘" + S.name + "’의 바꿀 것을 적용한 결과를 비교했습니다.";
    R.querySelector(".export-what").textContent = "‘" + S.name + "’의 시나리오 파일과 실행 결과를 파일 하나로 내려받습니다.";
    // 결과 내보내기·가져오기, 고쳐서 새로 만들기, 비교, 지우기는 다음 작업에서 넣는다. 그때까지 단추를 보이지 않는다
    for (const node of R.querySelectorAll('.cover-tools [data-dialog="export"], .export-band, #compare .sv-foot')) {
      (node.closest(".pagewrap[aria-labelledby=export-band-title]") || node).hidden = true;
    }
    R.querySelector("#compare .sectionline p").textContent = "시나리오를 누르면 결과를 엽니다. \"조건 다름\"은 지금 열린 결과와 조건이 다르다는 뜻입니다.";

    const venueRows = R.querySelector("[data-ev-venues]");
    for (const row of DATA.evidence.venues) {
      const tr = el("tr");
      tr.append(el("th", "", row.venue), el("td", "", row.what), el("td", "", row.value + (row.flag ? " · " + row.flag : "")));
      const grade = el("td");
      grade.append(gradeTag(row.grade, row.grade_key));
      tr.append(grade, el("td", "", row.source), el("td", "", (row.checked_on || "—").slice(5) || "—"));
      venueRows.append(tr);
    }
    if (!DATA.evidence.venues.length) {
      const tr = el("tr");
      const td = el("td", "", "바꾼 업장과 방문이 옮겨 간 업장이 없습니다.");
      td.colSpan = 6;
      tr.append(td);
      venueRows.append(tr);
    }
    const personaRows = R.querySelector("[data-ev-personas]");
    const keys = ["share_in_group", "visit", "budget", "preferences", "buying", "revisit", "compares_with"];
    for (const [id, name] of Object.entries(DATA.personas)) {
      const info = DATA.persona_info[id] || {};
      const tr = el("tr");
      tr.append(el("th", "", name));
      for (const key of keys) {
        const td = el("td");
        const label = info.evidence ? info.evidence.grades[key] : "";
        if (label) td.append(gradeTag(label));
        tr.append(td);
      }
      const last = el("td", "", info.evidence ? info.evidence.reviews + "건 " : "—");
      if (info.evidence && info.evidence.limited) last.append(el("span", "wh-tag wh-tag--warn", "근거 제한적"));
      tr.append(last);
      personaRows.append(tr);
    }

    const list = R.querySelector(".sv-list");
    for (const saved of DATA.saved) {
      const row = el("div", "sv-row" + (saved.current ? " current" : ""));
      const open = el("a", "sv-open");
      open.href = "#";
      open.dataset.result = saved.id;
      open.append(el("span", "sv-state has", "결과 있음"), el("b", "", saved.name), el("time", "", shortTime(saved.ran_at) + " 실행"));
      if (saved.current) open.append(el("small", "sv-now", "지금 열린 결과"));
      const condition = el("span", "sv-cond", saved.condition_line + " ");
      if (saved.differs) condition.append(el("i", "sv-diff", "조건 다름"));
      open.append(condition);
      row.append(el("span", "sv-pick"), open, el("span", "sv-tools"));
      list.append(row);
    }
  })();

// v14 보고서 화면 스크립트. 지도 스크립트가 고른 기간(합계 또는 달 하나)의 모델을 넘기면 위아래 구역을 그 기간으로 채운다.
// 합계일 때 방문 아이디는 "페르소나__조건__달" 꼴이라 같은 방문이 두 달에 있어도 겹치지 않는다.
const report = (() => {
  const byId = id => document.getElementById(id);
  const get = selector => document.querySelector(selector);
  const guestNames = Object.fromEntries(Object.entries(DATA.persona_info).map(([id, p]) => [id, p.name_lines]));
  const guestIcon = id => DATA.assets.personas[id] || ICONS + "personas/" + id + ".svg";
  const plateFiles = { incoming:"plate-in", newVisit:"plate-new", outgoing:"plate-leave", inside:"plate-move", order:"plate-order" };
  let selectedGuest = null;
  let model;
  function element(tag, cls, value) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (value !== undefined) el.textContent = value;
    return el;
  }
  function icon(src, cls) {
    const img = element("img",cls);
    img.src = src;
    img.alt = "";
    return img;
  }
  const signed = n => n > 0 ? "+" + n : n < 0 ? "−" + Math.abs(n) : "0";
  function tally(list) {
    return {
      changed: list.filter(v => model.altered(v.type)).length,
      order: list.filter(v => v.type === "order").length,
      price: list.filter(v => v.type === "price").length,
      places: list.filter(v => model.moves(v.type)).length
    };
  }
  // 고른 기간에 달이 둘 이상인가 (전체 기간이거나 3월~5월 같은 일부 기간). 그러면 달별 값을 작게 함께 보인다
  const isAll = () => model.perMonth.length > 1;
  let periodPending = null;
  const split = pick => isAll() ? model.perMonth.map(p => mlab(p.month)+" " + pick(p)).join(" · ") : "";

  function showGuest() {
    const drawer = byId("guest-detail");
    for (const b of byId("guest-grid").children) b.setAttribute("aria-expanded",String(b.dataset.guest === selectedGuest));
    drawer.hidden = !selectedGuest;
    if (!selectedGuest) return;
    const { data, rows, altered, name, types } = model;
    const changes = rows.filter(v => v.visit_id.split("__")[0] === selectedGuest && altered(v.type));
    byId("guest-label").textContent = data.personas[selectedGuest];
    const routes = byId("guest-routes");
    routes.replaceChildren();
    const december = data.months.find(item => item.month === 12);
    for (const v of changes) {
      const condition = data.conditions[v.visit_id.split("__")[1]];
      const route = v.type === "order" ? name(v.from) + " · " + v.before.order + " → " + v.after.order : name(v.from) + " → " + name(v.to);
      const line = element("p");
      if (plateFiles[v.type]) line.append(icon(ICONS+"plates/" + plateFiles[v.type] + ".svg","route-plate"));
      line.append(element("small","",(isAll() ? mlab(v.month)+" · " : "") + condition),element("b","",route),element("span","",types[v.type].name));
      routes.append(line);
      if (v.after.reason) {
        const excerpt = element("div","guest-reason");
        excerpt.append(element("small","","AI가 생성한 선택 이유"),quote(v.after.reason));
        routes.append(excerpt);
      }
    }
    if (!changes.length) routes.append(element("p","",model.label + " 동안 비교한 방문은 업장과 주문을 그대로 유지했습니다."));
  }
  function renderGuests() {
    const { data, rows, altered } = model;
    const grid = byId("guest-grid");
    grid.replaceChildren();
    for (const [id, fullName] of Object.entries(data.personas)) {
      const visits = rows.filter(v => v.visit_id.split("__")[0] === id);
      const changes = visits.filter(v => altered(v.type));
      const changed = changes.length;
      const excluded = model.excluded.filter(v => v.split("__")[0] === id).length;
      const b = element("button","guest-card");
      b.type = "button";
      b.dataset.guest = id;
      b.setAttribute("aria-controls","guest-detail");
      b.setAttribute("aria-label",fullName + ", " + model.label + " 비교 " + visits.length + "건 중 선택 변화 " + changed + "건" + (excluded ? ", 미응답 " + excluded + "건" : ""));
      const nameEl = element("strong","guest-name");
      for (const part of guestNames[id] || [fullName]) nameEl.append(element("span","",part));
      const count = element("span","guest-count");
      const first = changes[0];
      let summary = "선택 변화 " + changed + "건";
      if (changed === 1) summary = first.type === "order" ? model.name(first.to) + " · 주문 변경" : model.name(first.from) + " → " + model.name(first.to);
      count.append(element("i"),summary);
      b.append(icon(guestIcon(id),"guest-icon"),nameEl,count);
      b.addEventListener("click",() => { selectedGuest = selectedGuest === id ? null : id; showGuest(); });
      grid.append(b);
    }
    showGuest();
  }
  byId("guest-records").addEventListener("click",() => {
    const panel = get('[data-panel="visits"]');
    panel.closest("details").open = true;
    const form = panel.querySelector("form");
    form.reset();
    form.elements.persona.value = selectedGuest;
    form.elements.persona.dispatchEvent(new Event("change",{bubbles:true}));
    panel.closest("details").querySelector("summary").focus();
    panel.closest("details").scrollIntoView({block:"start"});
  });
  function renderVenues() {
    const { data, balance, name, placeSort } = model;
    const ul = get(".wh-venues-list");
    ul.replaceChildren();
    for (const venue of data.venues.filter(p => p.kind === "walkerhill").sort((a,b) => placeSort(a.id,b.id))) {
      const id = venue.id;
      const b = balance.get(id), delta = b.after-b.before;
      const card = element("li","venue-card");
      const head = element("div","venue-card-head");
      head.append(icon(ICONS+"buildings/" + venue.icon + ".svg","venue-icon"),element("b","",name(id)));
      head.append(element("small",delta>0?"gain":delta<0?"loss":"flat",delta ? signed(delta)+"건" : "동일"));
      card.append(head,element("p","venue-count",b.before + "건 → " + b.after + "건"));
      if (isAll()) card.append(element("p","venue-split",split(p => { const pb = p.balance.get(id); return signed(pb.after - pb.before); })));
      for (const [flows,direction] of [[b.ins,"유입"],[b.outs,"유출"]]) {
        if (flows.size) card.append(element("p","venue-flow",[...flows].map(([place,count]) => name(place) + " " + count + "건").join(", ") + " " + direction));
      }
      ul.append(card);
    }
    get(".wh-venues .wh-scope").textContent = model.label + " · 워커힐 " + data.venues.filter(p => p.kind === "walkerhill").length + "곳";
  }
  // 배너의 기간 선택 H: 단추 하나와 시나리오 범위. 판에서 전체 기간, 한 달, 두 달 사이 기간을 고른다
  function renderPeriod() {
    const host = byId("report-period");
    const ms = model.data.months.map(m => m.month), n = ms.length;
    if (!host.dataset.ready) {
      host.dataset.ready = "1";
      host.innerHTML = '<span class="period-anchor"><button type="button" class="period-trigger" aria-haspopup="dialog" aria-expanded="false"><span data-cur></span><span class="caret" aria-hidden="true">▼</span></button>'
        + '<div class="period-pop" role="dialog" aria-label="결과를 볼 기간" hidden><button type="button" class="period-all" data-all>전체 기간 <small>' + mlab(ms[0])+'~' + mlab(ms[n-1])+'</small></button><hr>'
        + '<div class="period-months">' + ms.map((m,i) => '<button type="button" data-i="' + i + '">' + mlab(m)+'</button>').join("") + '</div><p class="period-hint"></p></div></span>'
        + '<span class="period-range">' + mlab(ms[0])+'~' + mlab(ms[n-1])+' · ' + n + '개월</span>';
      const trigger = host.querySelector(".period-trigger"), pop = host.querySelector(".period-pop");
      const setOpen = open => { pop.hidden = !open; trigger.setAttribute("aria-expanded",String(open)); periodPending = null; paintPeriod(); };
      trigger.addEventListener("click",() => setOpen(pop.hidden));
      document.addEventListener("click",e => { if (!pop.hidden && !e.target.closest(".period-anchor")) setOpen(false); });
      document.addEventListener("keydown",e => { if (e.key === "Escape" && !pop.hidden) { setOpen(false); trigger.focus(); } });
      host.querySelector("[data-all]").addEventListener("click",() => { setOpen(false); if (model.view !== "all") model.setView("all"); });
      host.querySelector(".period-months").addEventListener("click",e => {
        const b = e.target.closest("[data-i]"); if (!b) return;
        const i = Number(b.dataset.i);
        if (periodPending === null) { periodPending = i; model.setView({from:i,to:i}); }
        else { const from = Math.min(periodPending,i), to = Math.max(periodPending,i); setOpen(false); model.setView({from,to}); }
      });
    }
    paintPeriod();
  }
  function paintPeriod() {
    const host = byId("report-period"), v = model.view;
    host.querySelector("[data-cur]").textContent = model.label;
    host.querySelector("[data-all]").setAttribute("aria-pressed",String(v === "all"));
    for (const b of host.querySelectorAll("[data-i]")) {
      const i = Number(b.dataset.i), inside = v !== "all" && i >= v.from && i <= v.to;
      b.classList.toggle("in",inside);
      b.classList.toggle("start",inside && i === v.from);
      b.classList.toggle("end",inside && i === v.to);
      b.classList.toggle("pending",periodPending === i);
      b.setAttribute("aria-pressed",String(inside));
    }
    host.querySelector(".period-hint").textContent = periodPending === null ? "달 하나를 누르면 그 달만, 두 달을 누르면 그 사이 기간을 봅니다." : "끝 달을 누르면 기간으로 봅니다.";
  }
  // ── 방문별 선택과 이유: 고른 기간에 업장이나 주문이 달라진 방문마다 한 줄 (시안은 12월 예시 줄이 HTML 에 박혀 있었다) ──
  // 꼬리표 말은 결정 74: 경쟁 업장에서 / 경쟁 업장으로 / 워커힐 다른 업장에서 / 워커힐 다른 업장으로
  const TAGS = {
    incoming: ["in", "in", "옮겨 온 매출 (경쟁 업장에서)"],
    newVisit: ["new", "in", "새로 들어온 매출"],
    inside: ["move", "in", "옮겨 온 매출 (워커힐 다른 업장에서)"],
    outgoing: ["leave", "out", "잃은 매출 (경쟁 업장으로)"],
    giveup: ["leave", "out", "잃은 매출 (외식 안 함으로)"],
    external: ["move", "", "워커힐 밖에서 옮김"],
    order: ["order", "", "주문 변경"],
  };
  const PART_TEXT = {
    new: (to) => "새로 들어온 매출 · 외식 안 함에서 " + to,
    from_competitor: (to) => "옮겨 온 매출 · 경쟁 업장에서 " + to,
    from_walkerhill: (to) => "옮겨 온 매출 · 워커힐 다른 업장에서 " + to,
    to_competitor: (at) => "잃은 매출 · " + at + "에서 경쟁 업장으로",
    to_walkerhill: (at) => "잃은 매출 · " + at + "에서 워커힐 다른 업장으로",
    to_none: (at) => "잃은 매출 · " + at + "에서 외식 안 함으로",
    price: (at) => "단가 효과 · " + at + " 가격만 바뀜",
    order: (at) => "단가 효과 · " + at + " 주문 변경",
  };
  const tagEl = (cls, text) => element("span", "wh-tag" + (cls ? " wh-tag--" + cls : ""), text);
  function routeEl(cls, v) {
    const p = element("p", cls);
    const arrow = element("span", "wh-arrow", "→");
    arrow.setAttribute("aria-label", "에서");
    if (v.type === "order") p.append(model.name(v.to) + " · " + (v.before.order || "—") + " ", arrow, " " + (v.after.order || "—"));
    else p.append(model.name(v.from) + " ", arrow, " " + model.name(v.to));
    return p;
  }
  function fields(side) {
    const dl = element("dl", "wh-detail-fields");
    const money = element("span", "wh-money", plainWon(side.paid || 0));
    const place = side.kind === "none" ? "외식 안 함" : side.venue_name || model.name(side.venue_id);
    for (const [term, value] of [["고른 곳", place], ["주문", side.order || "—"], ["낸 금액", money]]) {
      const dd = element("dd");
      dd.append(value);
      dl.append(element("dt", "", term), dd);
    }
    return dl;
  }
  function detailOf(v, title, tag) {
    const frame = element("div", "wh-detail-frame");
    const article = element("article", "wh-detail-visit");
    article.dataset.visit = v.visit_no;
    article.setAttribute("aria-label", v.visit_no + " " + title + " 상세");
    const head = element("div", "wh-detail-row");
    const person = element("div", "wh-detail-person");
    const meta = element("p", "wh-detail-meta");
    meta.append(element("span", "wh-num", v.visit_no), " " + (isAll() ? mlab(v.month) + " · " : "") + (DATA.conditions[v.condition_id] || ""));
    person.append(element("p", "wh-detail-open", "누른 방문"), element("h3", "", title), meta);
    const move = element("div", "wh-detail-move");
    const moveTags = element("div", "wh-tags");
    moveTags.append(tag.cloneNode(true));
    move.append(routeEl("wh-detail-route", v), moveTags);
    const reason = element("div", "wh-detail-reason");
    if (v.after.reason) reason.append(aiFigure(v.after.reason, false));
    const factors = element("div", "wh-tags");
    for (const label of v.after.reason_labels || []) factors.append(tagEl("factor", label));
    factors.append(proofTag(v.persona_id));
    reason.append(factors);
    head.append(person, move, reason);

    const panels = element("div", "wh-detail-panels");
    const base = element("section", "wh-detail-panel wh-detail-panel--base");
    base.append(element("h4", "", "기본 시나리오"), fields(v.before));
    if (v.before.reason) base.append(aiFigure(v.before.reason, true));
    const after = element("section", "wh-detail-panel wh-detail-panel--after");
    after.append(element("h4", "", "조건 적용 후"), fields(v.after));
    after.append(element("p", "wh-detail-same", v.from === v.to ? "기본 시나리오와 같은 업장입니다." : ""));
    const other = element("section", "wh-detail-panel wh-detail-panel--other");
    other.append(element("h4", "", "고르지 않은 업장과 이유"));
    const rejected = (v.after.rejected || []).filter(r => r.text);
    if (rejected.length) {
      const ul = element("ul", "wh-detail-other");
      for (const item of rejected) {
        const li = element("li");
        li.append(element("strong", "", item.name), aiFigure(item.text, true));
        ul.append(li);
      }
      other.append(ul);
    } else other.append(element("p", "", "다른 후보가 없었습니다."));
    panels.append(base, after, other);

    const branches = element("div", "wh-detail-branches");
    branches.append(element("h4", "", "이 방문이 가상 매출에 미친 영향"));
    const parts = (v.parts || []).filter(p => p.amount !== 0);
    if (parts.length) {
      const ul = element("ul");
      for (const part of parts) {
        const li = element("li");
        li.dataset.kind = part.amount >= 0 ? "in" : "out";
        const value = element("span", "wh-detail-branch-val");
        value.append(element("span", "wh-money", signedWon(part.amount)));
        li.append(element("span", "", (PART_TEXT[part.part] || (x => x))(model.name(part.venue_id))), value);
        ul.append(li);
      }
      branches.append(ul, element("p", "wh-detail-branch-note", "해당 방문이 대표하는 팀 수를 반영한 가상 금액입니다."));
    } else branches.append(element("p", "wh-detail-branch-note", "이 방문은 워커힐 가상 매출을 바꾸지 않았습니다."));
    article.append(head, panels, branches);
    frame.append(article);
    return frame;
  }
  function visitRow(v) {
    const title = DATA.personas[v.persona_id] || v.persona_id;
    const [kind, tagCls, tagText] = TAGS[v.type] || ["move", "", model.types[v.type].name];
    const li = element("li", "wh-list-row");
    li.dataset.kind = kind;
    li.dataset.row = v.visit_no;
    const person = element("p", "wh-list-person");
    const meta = element("span", "wh-list-meta");
    meta.append(element("span", "wh-num", v.visit_no), " " + (DATA.condition_short[v.condition_id] || ""));
    person.append(icon(guestIcon(v.persona_id), "list-icon"), element("b", "", title), " ", meta);
    const tags = element("div", "wh-tags wh-list-tags");
    const tag = tagEl(tagCls, tagText);
    if (isAll()) tags.append(tagEl("month", mlab(v.month)));
    tags.append(tag, proofTag(v.persona_id));
    if (v.kept_baseline) tags.append(tagEl("", "기본 시나리오 답 그대로"));
    const id = "wh-d-" + v.visit_no + (v.month == null ? "" : "-" + v.month);
    const open = element("button", "wh-button wh-list-open", "자세히");
    open.type = "button";
    open.dataset.openVisit = v.visit_no;
    open.setAttribute("aria-expanded", "false");
    open.setAttribute("aria-controls", id);
    open.setAttribute("aria-label", v.visit_no + " " + title + " 자세히");
    const detail = element("div", "wh-list-detail");
    detail.id = id;
    detail.hidden = true;
    detail.append(detailOf(v, title, tag));
    li.append(person, routeEl("wh-list-route", v), tags, open, detail);
    return li;
  }
  function renderList(total) {
    const { rows } = model;
    const changed = rows
      .filter(v => model.altered(v.type))
      .sort((a, b) => (a.visit_no || "").localeCompare(b.visit_no || "") || (a.month ?? 0) - (b.month ?? 0));
    const ul = get(".wh-list-rows");
    ul.replaceChildren(...changed.map(visitRow));
    ul.hidden = !changed.length;
    get(".wh-list .wh-scope").textContent = model.label + " · 선택 변화 " + total.changed + "건";
    byId("list-other-month").hidden = true;
    const kept = rows.length - total.changed;
    const keptBase = rows.filter(v => v.kept_baseline).length;
    get(".wh-list-stay").textContent =
      "업장과 주문을 유지한 방문은 " + kept + "건이며, 이 중 " + total.price + "건은 가격만 달라졌습니다." +
      (model.excluded.length ? " 미응답 " + model.excluded.length + "건은 비교에서 제외했습니다." : "") +
      (keptBase ? " 바꾼 조건과 상관없어 기본 시나리오의 답을 그대로 쓴 방문이 " + keptBase + "건 있습니다." : "");
    get(".wh-list .wh-full summary span").textContent = rows.length + model.excluded.length + "건 전체 방문 기록";
    get(".wh-list .wh-full").open = !changed.length;
  }

  // ── 가상 매출 변화: 고른 기간의 달마다 값을 더한다. 집계가 없는 달은 빼고 더하고, 변화율은 더한 금액으로 다시 낸다 ──
  const PARTS = ["new", "from_competitor", "from_walkerhill", "to_competitor", "to_walkerhill", "to_none", "price", "order"];
  const LINES = [
    { label: "새로 들어온 매출", parts: ["new"], bar: "new" },
    { label: "옮겨 온 매출", parts: ["from_competitor", "from_walkerhill"], bar: "in" },
    { label: "└ 경쟁 업장에서", parts: ["from_competitor"], bar: "in", sub: true },
    { label: "└ 워커힐 다른 업장에서", parts: ["from_walkerhill"], bar: "inside", sub: true },
    { label: "잃은 매출", parts: ["to_competitor", "to_walkerhill", "to_none"], bar: "out" },
    { label: "└ 경쟁 업장으로", parts: ["to_competitor"], bar: "out", sub: true },
    { label: "└ 워커힐 다른 업장으로", parts: ["to_walkerhill"], bar: "out-inside", sub: true },
    { label: "└ 외식 안 함으로", parts: ["to_none"], bar: "out", sub: true },
    { label: "단가 효과", parts: ["price", "order"], bar: "price" },
    { label: "└ 가격만 바뀜", parts: ["price"], bar: "price", sub: true, count: true },
    { label: "└ 주문 변경", parts: ["order"], bar: "order", sub: true },
  ];
  const monthsShown = () => model.perMonth.map(p => DATA.months.find(m => m.month === p.month));
  function visitNumbers(months, parts) {
    const found = new Set();
    for (const m of months) for (const part of parts) for (const id of m.sales.part_visits[part] || []) found.add(VISIT_NO.get(id));
    return [...found].filter(Boolean).sort();
  }
  function drawRevenue(sum, net, months) {
    const plot = get(".wh-revenue-plot");
    [...plot.children].slice(3).forEach(node => node.remove());
    const value = parts => parts.reduce((s, p) => s + sum[p], 0);
    const max = Math.max(1, Math.abs(net), ...LINES.map(line => Math.abs(value(line.parts))));
    const addRow = (label, amount, bar, kind) => {
      const sub = kind ? " wh-revenue-cat--" + kind : "";
      const shape = bar === "order" && amount < 0 ? "order-neg" : bar;
      const flips = amount < 0 && !["out", "out-inside", "order-neg"].includes(shape);
      const track = element("div", "wh-revenue-track" + (kind ? " wh-revenue-track--" + kind : ""));
      const span = element("span", "wh-revenue-bar wh-revenue-bar--" + (amount === 0 ? "zero" : shape) + (flips ? " wh-revenue-bar--neg" : ""));
      if (amount !== 0) span.style.setProperty("--wh-length", ((Math.abs(amount) / max) * 48).toFixed(1) + "%");
      track.append(span);
      const val = element("span", "wh-revenue-val" + sub);
      val.append(element("span", "wh-money", signedWon(amount)));
      plot.append(element("span", "wh-revenue-cat" + sub, label), track, val);
    };
    for (const line of LINES) {
      const amount = value(line.parts);
      if (line.sub && amount === 0) continue;
      const numbers = visitNumbers(months, line.parts);
      let label = line.label;
      if (line.count) label += " " + numbers.length + "건";
      else if (line.sub && numbers.length) label += " " + numbers.slice(0, 4).join(", ") + (numbers.length > 4 ? " 외 " + (numbers.length - 4) + "건" : "");
      addRow(label, amount, line.bar, line.sub ? "sub" : "");
    }
    addRow("순변화", net, "net", "net");
    const inside = visitNumbers(months, ["from_walkerhill", "to_walkerhill"]);
    const note = get(".wh-revenue-inside");
    note.hidden = !inside.length;
    note.replaceChildren(element("b", "", "워커힐 안에서 옮긴 매출"),
      " " + inside.slice(0, 4).join(", ") + (inside.length > 4 ? " 외 " + (inside.length - 4) + "건" : "") +
      "은 도착한 업장에는 옮겨 온 매출로, 떠난 업장에는 잃은 매출로 함께 셉니다. 워커힐 전체로는 그 차이만 남습니다.");
  }
  function drawMonthsTable(list) {
    const table = get(".wh-months-table");
    const rows = [
      ["새로 들어온 매출", ["new"]], ["옮겨 온 매출", ["from_competitor", "from_walkerhill"]],
      ["잃은 매출", ["to_competitor", "to_walkerhill", "to_none"]], ["단가 효과", ["price", "order"]],
      ["└ 가격만 바뀜", ["price"]], ["└ 주문 변경", ["order"]], ["순변화", PARTS],
    ];
    const head = element("tr");
    head.append(element("th", "", "항목"), ...list.map(m => element("th", "", m.label)), element("th", "", model.label + " 합계"));
    const body = element("tbody");
    for (const [label, parts] of rows) {
      const tr = element("tr", label === "순변화" ? "wh-sum" : "");
      tr.append(element("th", "", label));
      let total = 0;
      for (const m of list) {
        if (!m.sales) { tr.append(element("td", "wh-na", "집계 없음")); continue; }
        const amount = parts.reduce((s, p) => s + m.sales.parts[p], 0);
        total += amount;
        tr.append(element("td", "", signedWon(amount)));
      }
      tr.append(element("td", "", signedWon(total)));
      body.append(tr);
    }
    const thead = element("thead");
    thead.append(head);
    table.replaceChildren(thead, body);
  }
  function renderSales() {
    const list = monthsShown();
    const withSales = list.filter(m => m.sales), without = list.filter(m => !m.sales);
    const has = withSales.length > 0;
    const sum = Object.fromEntries(PARTS.map(p => [p, withSales.reduce((s, m) => s + m.sales.parts[p], 0)]));
    const before = withSales.reduce((s, m) => s + m.sales.before, 0);
    const after = withSales.reduce((s, m) => s + m.sales.after, 0);
    const net = after - before;
    byId("sales-kpi").replaceChildren(...(has
      ? [element("strong", net > 0 ? "positive" : net < 0 ? "negative" : "", rateText(rateOf(after, before))), element("small", "wh-money", manWon(net))]
      : [element("span", "unavailable", "집계 자료 없음")]));
    byId("sales-split").textContent = has && without.length ? without.map(m => m.label).join("·") + " 집계 없음 · " + withSales.map(m => m.label).join("·") + "만 더함" : "";
    byId("sales-detail").hidden = !has;
    byId("sales-empty").hidden = has;
    byId("sales-empty").textContent = model.label + "에는 가상 매출 집계가 없습니다.";
    const notes = [];
    if (has && without.length) notes.push(without.map(m => m.label).join("·") + "은 가상 매출 집계가 없어 " + withSales.map(m => m.label).join("·") + " 값만 더했습니다. 변화율은 더한 금액으로 다시 계산합니다.");
    const zero = [...new Set(list.flatMap(m => m.zero_groups.map(g => m.label + " " + g)))];
    if (zero.length) notes.push("그 달의 집계에 인원이 없어 가상 매출이 0 으로 들어간 고객군: " + zero.join(", ") + ".");
    if (DATA.notes.split_assumption) notes.push("몫으로 나뉜 방문은 몫만큼 옮겼다고 보고 매출을 나눴습니다.");
    const partial = byId("sales-partial");
    partial.hidden = !notes.length;
    partial.textContent = notes.join(" ");
    if (has) {
      drawRevenue(sum, net, withSales);
      const total = get(".wh-revenue-total");
      const rate = element("span", "wh-total-rate");
      rate.append("기본 시나리오 대비 ", element("span", "wh-num", rateText(rateOf(after, before))));
      total.replaceChildren("가상 매출 순변화 ", element("span", "wh-money", signedWon(net) + " (가상)"), rate);
    }
    byId("sales-months").hidden = !isAll();
    if (isAll()) drawMonthsTable(list);
    get(".wh-revenue .wh-scope").textContent = model.label + " · 기본 시나리오 대비";
  }

  // ── 근거 보기(가중치·검증): 가중치는 달마다 달라 고른 기간의 달마다 열 하나 ──
  const GRADE_NAMES = DATA.grade_names || {};
  const WEIGHT_SOURCE = {
    group_multiplier: DATA.scenario.data_mode === "private" ? "기본 데이터 집계 (그 달 줄)" : "가상 예시 집계 (그 달 줄)",
    condition_ratio: "집계와 팀 결정",
    persona_weight: "후기 건수 비율, 일부 설계 가정",
  };
  function renderEvidence() {
    const list = monthsShown();
    const table = get("[data-ev-weights]");
    const head = element("tr");
    head.append(element("th", "", "가상 매출의 재료"), ...list.map(m => element("th", "", m.label + " 등급")), element("th", "", "출처"));
    const body = element("tbody");
    for (const [i, base] of list[0].evidence.weights.entries()) {
      const tr = element("tr");
      tr.append(element("th", "", base.label));
      for (const m of list) {
        const key = m.evidence.weights[i].grade;
        const td = element("td");
        td.append(gradeTag(GRADE_NAMES[key] || key || "—", key));
        tr.append(td);
      }
      tr.append(element("td", "", WEIGHT_SOURCE[base.key] || ""));
      body.append(tr);
    }
    if (list.some(m => m.evidence.people_coverage != null)) {
      const tr = element("tr");
      tr.append(element("th", "", "페르소나가 대표하는 고객 인원"));
      for (const m of list) tr.append(element("td", "", m.evidence.people_coverage == null ? "—" : Math.round(m.evidence.people_coverage * 100) + "%"));
      tr.append(element("td", "", "실행 기록 (weights.people_coverage)"));
      body.append(tr);
    }
    const thead = element("thead");
    thead.append(head);
    table.replaceChildren(thead, body);

    const checks = get("[data-ev-checks]");
    const rows = [];
    const cal = DATA.evidence.calibration;
    rows.push(["보정", cal ? (cal.passed === cal.groups ? "통과" : "일부 미달") : "결과 없음",
      cal ? "고객군 " + cal.groups + "개 가운데 " + cal.passed + "개 통과 · 달을 주지 않은 기준 실행으로 확인" : "대조 명령을 돌린 기준 실행이 없습니다"]);
    const val = DATA.evidence.validation;
    if (val) {
      const expected = val.venue_expected == null ? "" : " · 기대 일치 " + (Math.round(val.venue_expected * 100) / 100) + "건";
      rows.push(["떼어 둔 후기로 검증", val.enough ? "검증함" : "검증 건수 부족",
        val.n + "건 가운데 고른 업장이 같음 " + val.venue_match + "건" + expected + " · 단순 기준 " + val.baseline + "건"]);
    } else rows.push(["떼어 둔 후기로 검증", "결과 없음", "기본 데이터로 돌린 기준 실행에만 있습니다"]);
    const applied = list.flatMap(m => m.evidence.constants_applied);
    if (applied.length) {
      const names = [...new Set(applied.map(c => c.name + " (" + c.grade + ")"))];
      rows.push(["쓴 결정 상수", names.length + "개", names.join(", ")]);
    }
    rows.push(["날씨", "넣지 않음", DATA.evidence.weather_note]);
    const cbody = element("tbody");
    for (const [what, result, note] of rows) {
      const tr = element("tr");
      const td = element("td");
      td.append(result === "통과" || result === "검증함" ? gradeTag(result) : element("span", "wh-tag" + (result === "넣지 않음" ? "" : " wh-tag--warn"), result));
      tr.append(element("th", "", what), td, element("td", "wh-ev-wrap", note));
      cbody.append(tr);
    }
    const chead = element("thead");
    const htr = element("tr");
    htr.append(element("th", "", "확인"), element("th", "", "결과"), element("th", "", "설명"));
    chead.append(htr);
    checks.replaceChildren(chead, cbody);
    const scope = byId("ev-weights-scope");
    if (scope) scope.textContent = isAll() ? "달마다의 가중치를 나란히 봅니다 (합친 근거 값은 만들지 않습니다)" : model.label + " 실행 기준";
  }
  function render(next) {
    model = next;
    const { rows } = model;
    const total = tally(rows);
    renderPeriod();
    byId("finding").replaceChildren((isAll() ? model.label + " 동안 " : model.label + "에 ") + "비교한 방문 " + rows.length + "건 중 ",element("strong","",total.changed+"건"),"에서 업장이나 주문이 달라졌습니다.");
    byId("place-count").textContent = total.places;
    byId("order-count").textContent = total.order;
    byId("place-split").textContent = split(p => tally(p.rows).places + "건");
    byId("order-split").textContent = split(p => tally(p.rows).order + "건");
    byId("guest-scope").textContent = model.label + " · " + Object.keys(model.data.personas).length + "개 유형";
    renderSales();
    renderList(total);
    renderEvidence();
    renderGuests();
    renderVenues();
  }
  function setupDialogs() {
    document.querySelectorAll("[data-dialog]").forEach(b => b.addEventListener("click",() => byId(b.dataset.dialog).showModal()));
  }
  setupDialogs();
  // 머리의 해·달 세그먼트. 처음에는 기기 설정을 따르고, 누르면 그 밝기로 고정한다
  const prefersDark = matchMedia("(prefers-color-scheme: dark)");
  function markTheme() {
    const current = document.documentElement.dataset.theme || (prefersDark.matches ? "dark" : "light");
    document.querySelectorAll("[data-theme-set]").forEach(b => b.setAttribute("aria-pressed",String(b.dataset.themeSet === current)));
  }
  function setTheme(value) { document.documentElement.dataset.theme = value; try { localStorage.setItem("wh-theme", value); } catch {} markTheme(); }
  document.querySelectorAll("[data-theme-set]").forEach(b => b.addEventListener("click",() => setTheme(b.dataset.themeSet)));
  prefersDark.addEventListener("change",markTheme);
  let saved = null; try { saved = localStorage.getItem("wh-theme"); } catch {}
  if (saved) setTheme(saved); else markTheme();
  return {render};
})();


 (()=>{
  "use strict";
  const root=document.querySelector(".wh-move:not(.wh-move-borrow)");
  const q=selector=>root.querySelector(selector)||document.querySelector(".wh-move-borrow "+selector);
  const data=component.data;
  const svg=q(".atlas"), slider=q(".track input"), play=q(".play");
  const ns="http://www.w3.org/2000/svg";
  const NONE="none";
  const places=new Map(data.venues.map(v=>[v.id,v]));
  places.set(NONE,{id:NONE,name:"외식 안 함",kind:"none",hotel:"",icon:"home"});
  const category={walkerhill:0,competitor:1,none:2};
  const types={
    incoming:{name:"워커힐로 들어옴",ref:"경쟁 → 워커힐",color:"in",glyph:"↘",dash:""},
    newVisit:{name:"새로 옴",ref:"외식 안 함 → 워커힐",color:"new",glyph:"+",dash:"11 3 2 3"},
    outgoing:{name:"워커힐 밖으로 나감",ref:"워커힐 → 경쟁",color:"out",glyph:"↗",dash:"9 4"},
    giveup:{name:"외식 취소",ref:"워커힐 → 외식 안 함",color:"giveup",glyph:"×",dash:"2 5"},
    inside:{name:"워커힐 안에서 옮김",ref:"워커힐 → 워커힐",color:"inside",glyph:"↔",dash:"5 3"},
    external:{name:"워커힐 밖에서 옮김",ref:"경쟁 간 이동, 경쟁 ↔ 외식 안 함",color:"outside",glyph:"⇄",dash:"8 3 2 3"},
    order:{name:"주문 변경",ref:"같은 업장, 주문 변경",color:"order",glyph:"◎",dash:""},
    price:{name:"가격만 바뀜",ref:"같은 업장, 같은 주문",color:"price",glyph:"=",dash:""},
    stay:{name:"선택 유지",color:"point",glyph:"○"}
  };
  const ui={view:"all",month:data.months[0].month,progress:0,playing:false};
  // 고른 기간의 달들: 전체 기간이면 모든 달, 아니면 data.months 의 from~to 자리 (시나리오 순서라 해를 넘어도 맞다)
  const chosen=()=>ui.view==="all"?data.months:data.months.slice(ui.view.from,ui.view.to+1);
  let rrows=[],rbal=new Map(),perMonth=[],rexcluded=[];
  let rows=[],balance=new Map(),actors=[],lanes=new Map(),locations=new Map(),tickId=0,lastTick=null;
  const figureSlots=new Map(), travel=new Map();
  let lastWidth=0, wasAtEnd=false;
  const name=id=>places.get(id).name;
  const byName=(a,b)=>a.localeCompare(b,"ko");
  const loc=place=>place.kind==="none"?NONE:place.venue_id;
  const color=key=>"var(--"+types[key].color+")";
  const altered=t=>t!=="stay"&&t!=="price";
  const moves=t=>!["stay","order","price"].includes(t);
  const fmt=n=>n>0?"+"+n:String(n);
  const clamp=n=>Math.min(1,Math.max(0,n));
  const current=()=>data.months.find(m=>m.month===ui.month);
  const withRole=id=>places.get(id).kind;
  const labels={walkerhill:"워커힐",competitor:"경쟁",none:"외식 안 함"};
  function elem(tag,cls,txt){
    const node=document.createElement(tag);if(cls)node.className=cls;if(txt!==undefined)node.textContent=txt;return node;
  }
  function draw(tag,attributes,parent){
    const node=document.createElementNS(ns,tag);
    for(const [k,v] of Object.entries(attributes))node.setAttribute(k,v);
    parent.append(node);return node;
  }
  function path(parent,d,stroke,fill="none",width=1){
    return draw("path",{d,stroke,fill,"stroke-width":width,"stroke-linejoin":"round","stroke-linecap":"round"},parent);
  }
  function svgText(parent,x,y,txt,cls,anchor="start"){
    const el=draw("text",{x,y,class:cls,"text-anchor":anchor},parent);el.textContent=txt;return el;
  }
  function typeOf(v){
    const b=v.before.kind,a=v.after.kind;
    if(b===a&&loc(v.before)===loc(v.after)){
      if(v.before.order_key!==v.after.order_key)return "order";
      return v.price_changed?"price":"stay";
    }
    if(a==="walkerhill")return b==="none"?"newVisit":b==="competitor"?"incoming":"inside";
    if(b==="walkerhill")return a==="none"?"giveup":"outgoing";
    return "external";
  }
  function rowsFor(month,tagged){
    const excluded=new Set(month.excluded_visits);
    return month.visits.filter(v=>!excluded.has(v.visit_id)).map(v=>({...v,baseId:v.visit_id,visit_id:tagged?v.visit_id+"__"+month.month:v.visit_id,month:month.month,from:loc(v.before),to:loc(v.after),type:typeOf(v)}));
  }
  function balanceFor(list){
    const map=new Map([...places.keys()].map(id=>[id,{before:0,after:0,ins:new Map(),outs:new Map()}]));
    for(const v of list){
      const a=map.get(v.from),b=map.get(v.to);a.before++;b.after++;
      if(v.from!==v.to){a.outs.set(v.to,(a.outs.get(v.to)||0)+1);b.ins.set(v.from,(b.ins.get(v.from)||0)+1)}
      v.group=[v.type,v.from,v.to].join("|");
    }
    return map;
  }
  // 지도는 늘 달 하나(ui.month)를 그린다
  function prepare(){rows=rowsFor(current(),false);balance=balanceFor(rows)}
  // 위아래 구역은 고른 기간(ui.view)을 본다. 합계면 두 달의 방문을 "방문__달" 로 합친다 (T216: 합, 방문은 달마다 따로 센다)
  function prepareReport(){
    const list=chosen(),tagged=list.length>1;
    perMonth=list.map(m=>{const r=rowsFor(m,tagged);return {month:m.month,rows:r,balance:balanceFor(r),excluded:m.excluded_visits.map(id=>tagged?id+"__"+m.month:id)}});
    rrows=perMonth.flatMap(p=>p.rows);rbal=balanceFor(rrows);rexcluded=perMonth.flatMap(p=>p.excluded);
  }
  const viewLabel=()=>{if(ui.view==="all")return "전체 기간";const l=chosen();return l.length===1?mlab(l[0].month)+"":mlab(l[0].month)+"~"+mlab(l[l.length-1].month)+""};
  function mapBadge(){
    const l=chosen(),i=l.findIndex(m=>m.month===ui.month);
    q("[data-map-month]").textContent=l.length<2?mlab(ui.month)+"":viewLabel()+" · "+(ui.playing?mlab(ui.month)+" 재생 중 ("+(i+1)+"/"+l.length+")":(i===0&&ui.progress===0)?mlab(l[0].month)+"부터 달 순서로 재생":mlab(ui.month)+" ("+(i+1)+"/"+l.length+")");
  }
  const nextMapMonth=()=>{const l=chosen(),i=l.findIndex(m=>m.month===ui.month);return l[i+1]?l[i+1].month:null};
  function showMapMonth(month){ui.month=month;prepare();makeMap();mapBadge()}
  const delta=id=>balance.get(id).after-balance.get(id).before;
  const direction=n=>n>0?0:n<0?1:2;
  function placeSort(a,b){
    return category[withRole(a)]-category[withRole(b)]||direction(delta(a))-direction(delta(b))||byName(name(a),name(b));
  }
  function particle(word,withEnd,noEnd,skipL=false){
    const tail=word.charCodeAt(word.length-1)-44032;
    const jong=tail>=0&&tail<=11171?tail%28:word.endsWith("1")?8:0;
    return word+(jong&&(!skipL||jong!==8)?withEnd:noEnd);
  }
  function drawInsights(){
    const box=q(".insights"),ul=box.querySelector("ul");ul.replaceChildren();
    const ids=[...places.keys()].filter(k=>delta(k)!==0).sort((a,b)=>direction(delta(a))-direction(delta(b))||placeSort(a,b));
    for(const id of ids){
      const bal=balance.get(id),n=delta(id),li=elem("li");
      li.dataset.venue=id;li.dataset.net=n;
      const subject=id===NONE?"외식 안 함을 선택한":particle(name(id),"을","를")+" 고른";
      const sentence=subject+" 방문이 "+Math.abs(n)+"건 "+(n>0?"늘었습니다.":"줄었습니다.");
      const flows=(map,inbound)=>[...map].sort((a,b)=>placeSort(a[0],b[0])).map(([k,count])=>(inbound?name(k)+"에서":particle(name(k),"으로","로",true))+" "+count+"건").join(", ");
      const notes=[];if(bal.ins.size)notes.push(flows(bal.ins,true)+" 유입");if(bal.outs.size)notes.push(flows(bal.outs,false)+" 유출");
      li.append(elem("span",n>0?"net":"net loss",fmt(n)+"건"),elem("b","",sentence),elem("span","flow-note",notes.join(", ")));ul.append(li);
    }
    box.hidden=ui.progress<1||!ids.length;
  }
  function renderCopy(){
    const m=current(),failed=rexcluded.length;
    q("[data-title]").textContent=data.title;q(".inputs").textContent=data.description;
    q("[data-failed]").textContent=failed ? "미응답 "+failed+"건 제외" : "";
    q("[data-test-month]").textContent=m.month===1?"":"";
    q("[data-motion-note]").textContent=rows.some(v=>moves(v.type))?"":rows.some(v=>v.type==="price"||v.type==="order")?"이달의 주문·가격 변화는 제자리에 표시":"이달에는 이동하는 점이 없음";
    const balances=q("[data-balances]");balances.replaceChildren();
    for(const id of [...places.keys()].sort(placeSort)){
      const p=places.get(id),b=rbal.get(id),dd=b.after-b.before,tr=elem("tr"),venue=elem("td","",p.name);
      tr.dataset.kind=p.kind;tr.dataset.delta=dd>0?"up":dd<0?"down":"same";
      tr.dataset.search=[p.name,p.hotel].join(" ");
      if(p.kind==="competitor")venue.append(elem("span","secondary",p.hotel+", "+name(p.pair)+"의 짝"));
      tr.append(elem("td","",labels[p.kind]),venue,elem("td","",b.before+"건"),elem("td","",b.after+"건"),elem("td","",fmt(dd)+"건"));balances.append(tr);
    }
    const table=q("[data-register]");table.replaceChildren();
    const vno=id=>VISIT_NO.get(id.split("__").slice(0,2).join("__"))||"";
    const who=(id,month)=>{const [persona,condition]=id.split("__");const td=elem("td","",data.personas[persona]); const avatar=elem("img","table-icon");avatar.src=DATA.assets.personas[persona]||ICONS+"personas/"+persona+".svg";avatar.alt="";td.prepend(avatar);td.append(elem("span","secondary",(perMonth.length>1&&month?mlab(month)+" · ":"")+(vno(id)?vno(id)+" · ":"")+data.conditions[condition]));return td};
    const choice=c=>{const td=elem("td","",name(loc(c)));if(c.order)td.append(elem("span","secondary",c.order));return td};
    for(const v of [...rrows].sort((a,b)=>placeSort(a.to,b.to)||Number(altered(b.type))-Number(altered(a.type))||byName(a.visit_id,b.visit_id))){
      const tr=elem("tr");tr.dataset.visitId=v.visit_id;tr.dataset.type=v.type;tr.dataset.month=v.month;tr.dataset.search=[vno(v.visit_id),name(v.from),name(v.to)].join(" ");
      tr.append(who(v.visit_id,v.month),choice(v.before),choice(v.after),elem("td","",types[v.type].name));table.append(tr);
    }
    for(const id of rexcluded){const tr=elem("tr");tr.dataset.visitId=id;tr.dataset.month=id.split("__")[2]||ui.month;tr.dataset.type="failed";tr.dataset.search=vno(id);tr.append(who(id,id.split("__")[2]),elem("td","","—"),elem("td","","—"),elem("td","","미응답 (비교 제외)"));table.append(tr)}
    report.render({data, m, rows:rrows, balance:rbal, perMonth, excluded:rexcluded, view:ui.view, label:viewLabel(), types, name, altered, moves, placeSort, setView});
    drawInsights();
  }
  function buildLegend(){
    const list=q(".keys");
    for(const [key,t] of Object.entries(types)){
      if(key==="stay")continue;
      const item=elem("li","key");item.dataset.type=key;item.style.setProperty("--type",color(key));
      const icon=draw("svg",{viewBox:"0 0 42 22","aria-hidden":"true"},item);
      if(moves(key)){
        const sample=path(icon,"M2 15 Q12 6 36 10","currentColor","none",2);if(t.dash)sample.setAttribute("stroke-dasharray",t.dash);
        path(icon,"M31 6 L37 10 L31 13","currentColor","none",2);
      }else if(key==="order"){
        for(const r of [4,8])draw("circle",{cx:20,cy:11,r,fill:"none",stroke:"currentColor","stroke-width":1.6},icon);
      }else{path(icon,"M9 8h23 M9 14h23","currentColor","none",2)}
      const text=elem("span");
      text.append(elem("b","",t.name),elem("span","key-count"),elem("small","",t.ref));
      item.append(text);list.append(item);
    }
  }
  function updateLegend(){
    const counts=new Map();
    for(const visit of rrows)if(visit.type!=="stay")counts.set(visit.type,(counts.get(visit.type)||0)+1);
    const items=root.querySelectorAll(".keys [data-type]");
    for(const item of items){
      const count=counts.get(item.dataset.type)||0;
      item.dataset.present=String(count>0);
      item.querySelector(".key-count").textContent=count+"건";
    }
    q(".legend-month").textContent=viewLabel()+" · "+counts.size+"개 유형";
  }
  function setupIndex(){
    const buttons=[...root.querySelectorAll("[data-open]")];
    const prefix=root.classList[1]+"-index";
    for(const [index,b] of buttons.entries()){
      const key=b.dataset.open,panel=q('[data-panel="'+key+'"]');
      b.id=prefix+"-"+key;panel.id=b.id+"-panel";
      b.setAttribute("aria-controls",panel.id);panel.setAttribute("aria-labelledby",b.id);
      b.addEventListener("click",()=>{
        const open=b.getAttribute("aria-expanded")!=="true";
        for(const trigger of buttons){
          const show=open&&trigger===b;
          trigger.setAttribute("aria-expanded",String(show));
          q('[data-panel="'+trigger.dataset.open+'"]').hidden=!show;
        }
      });
      b.addEventListener("keydown",event=>{
        let dest;
        if(event.key==="ArrowRight")dest=(index+1)%buttons.length;
        if(event.key==="ArrowLeft")dest=(index+buttons.length-1)%buttons.length;
        if(event.key==="Home")dest=0;if(event.key==="End")dest=buttons.length-1;
        if(dest!==undefined){event.preventDefault();buttons[dest].focus();}
      });
      const form=panel.querySelector("form");
      form.addEventListener("input",()=>filterRecords(panel));
      form.addEventListener("change",()=>filterRecords(panel));
      form.addEventListener("submit",event=>event.preventDefault());
      form.addEventListener("reset",event=>{event.preventDefault();for(const control of form.querySelectorAll("input,select"))control.value="";filterRecords(panel)});
    }
    const people=q('select[name="persona"]');
    for(const [id,label] of Object.entries(data.personas))people.add(new Option(label,id));
  }
  function updateFilters(){
    const typeSelect=q('select[name="type"]'),previous=typeSelect.value;
    const present=new Set(rrows.map(v=>v.type));
    typeSelect.replaceChildren(new Option("전체",""));
    for(const [key,type] of Object.entries(types))if(present.has(key))typeSelect.add(new Option(type.name,key));
    if(rexcluded.length)typeSelect.add(new Option("미응답","failed"));
    const monthField=document.querySelector('[data-panel="visits"] select[name="month"]');
    if(monthField){const ms=perMonth.map(p=>p.month);monthField.replaceChildren(new Option("전체",""),...ms.map(x=>new Option(mlab(x)+"",String(x))));monthField.closest("label").hidden=ms.length<2;}
    typeSelect.value=[...typeSelect.options].some(o=>o.value===previous)?previous:"";
    for(const panel of document.querySelectorAll("[data-panel]"))filterRecords(panel);
  }
  const normalize=s=>s.normalize("NFC").toLocaleLowerCase("ko").replace(/\s+/g,"");
  function filterRecords(panel){
    const form=panel.querySelector("form"),filters=Object.fromEntries(new FormData(form));
    const search=normalize(filters.search),records=panel.querySelectorAll("tbody tr");
    const venues=panel.dataset.panel==="venues";let count=0;
    for(const tr of records){
      const r=tr.dataset;
      const match=venues?(!filters.kind||filters.kind===r.kind)&&(!filters.delta||filters.delta===r.delta)
                        :(!filters.type||filters.type===r.type)&&(!filters.month||filters.month===r.month)&&(!filters.persona||r.visitId.split("__")[0]===filters.persona);
      tr.hidden=!(match&&normalize(r.search).includes(search));if(!tr.hidden)count++;
    }
    panel.querySelector(".shown").textContent=viewLabel()+", "+(venues?"선택지 ":"가상 방문 ")+records.length+(venues?"곳 중 ":"건 중 ")+count+(venues?"곳 표시":"건 표시");
    panel.querySelector(".no-match").hidden=count>0;
  }
  // 지도 제목의 업장 수 (시안은 8곳으로 고정했다)
  const nIn=data.venues.filter(v=>v.kind==="walkerhill").length, nOut=data.venues.filter(v=>v.kind==="competitor").length;
  const estateOrder=["geumryong","myongwolgwan","ondal","lepassage","pavilion","pizzahill","moegi","thebuffet"];
  const buildingFrames = {
    atrium: {x: -33, y: -31, width: 70, height: 46, doorX: 20.5, doorY: -3.5},
    awning: {x: -33, y: -31, width: 70, height: 46, doorX: 20.5, doorY: -3.5},
    gable: {x: -33, y: -30, width: 70, height: 45, doorX: 20.5, doorY: -3.5},
    glass: {x: -39, y: -31, width: 82, height: 46, doorX: 26.5, doorY: -3.5},
    hall: {x: -33, y: -35, width: 70, height: 50, doorX: 20.5, doorY: -3.5},
    home: {x: -25, y: -28, width: 54, height: 43, doorX: 12.5, doorY: -3.5},
    terrace: {x: -39, y: -41, width: 82, height: 56, doorX: 26.5, doorY: -3.5},
    tower: {x: -29, y: -49, width: 62, height: 64, doorX: 16.5, doorY: -3.5},
    villa: {x: -33, y: -38, width: 70, height: 53, doorX: 20.5, doorY: -3.5}
  };
  // The SVG viewBox and door coordinates keep each route anchored to the same artwork as the cards.
  function building(parent, x, y, scale, model) {
    const frame = buildingFrames[model.split("-")[0]];
    const group = draw("g", {transform: "translate("+x+" "+y+") scale("+scale+")", "aria-hidden":"true"}, parent);
    draw("image", {href: ICONS+"buildings/"+model+".svg", x:frame.x, y:frame.y, width:frame.width, height:frame.height}, group);
    return {
      left:  {x:x-frame.doorX*scale, y:y+frame.doorY*scale, side:-1},
      right: {x:x+frame.doorX*scale, y:y+frame.doorY*scale, side:1}
    };
  }
  function forest(g,x,y,scale){
    const grove=draw("g",{transform:"translate("+x+" "+y+") scale("+scale+")","aria-hidden":"true"},g);
    for(const [dx,dy,h] of [[-8,1,18],[0,-4,23],[8,2,16]]){
      path(grove,"M"+dx+" "+dy+"v-8","var(--window)","none",1);
      path(grove,"M"+dx+" "+(dy-h)+" q-10 17 -3 17 q10 3 3 -17Z","var(--contour)","var(--roof)",.7);
    }
  }
  function positions(width){
    const mobile=width<570;
    const paired=width<420;
    const height=paired?776:mobile?650:Math.round(Math.max(525,Math.min(625,width*.67)));
    const cx=width/2,cy=height*.50+3;
    const ry=height*.394,rx=Math.min(width/2-(mobile?37:55),ry*(mobile?1:1.78));
    const competitor=new Map(data.venues.filter(v=>v.kind==="competitor").map(v=>[v.pair,v.id]));
    locations=new Map();
    // 자료에 있는 워커힐 업장만 자리에 놓는다 (가상 예시 자료는 업장이 몇 곳뿐이다, T130). 짝이 없는 업장은 남은 자리에 놓는다
    const estate=[...estateOrder.filter(id=>places.has(id)),...data.venues.filter(v=>v.kind==="walkerhill"&&!estateOrder.includes(v.id)).map(v=>v.id)];
    const place=(key,i,radius,inner)=>{
      const angle=-Math.PI/2+i*Math.PI/4;
      locations.set(key,paired ? {x:width*(inner ? .265 : .75),y:78+i*82} : {x:cx+Math.cos(angle)*rx*radius,y:cy+Math.sin(angle)*ry*radius});
    };
    estate.forEach((id,i)=>{
      place(id,i,.505,true);
      const rival=competitor.get(id);
      if(rival&&places.has(rival))place(rival,i,1,false);
    });
    [...places.keys()].filter(k=>k!==NONE&&!locations.has(k)).forEach((id,j)=>place(id,estate.length+j,withRole(id)==="walkerhill"?.505:1,withRole(id)==="walkerhill"));
    locations.set(NONE,{x:width*(paired ? .75 : mobile ? .842 : .914),y:height-(mobile?38:43)});
    return {mobile,paired,width,height,cx,cy,rx,ry};
  }
  function landscape(layout){
    const {width:w,height:h,cx,cy,rx,ry,mobile,paired}=layout;
    const land=draw("g",{"aria-hidden":"true"},svg);
    draw("rect",{width:w,height:h,fill:"var(--city)"},land);
    const caption=q(".map-foot span:nth-child(2)");
    if(paired){
      caption.textContent="왼쪽은 워커힐, 오른쪽은 같은 줄의 경쟁 업장";
      svg.setAttribute("aria-label","왼쪽 워커힐 "+nIn+"곳과 오른쪽 경쟁 업장 "+nOut+"곳의 방문 이동 지도");
      draw("rect",{width:w*.50,height:h,fill:"var(--estate)"},land);
      path(land,"M"+w*.5+" 0V"+h,"var(--contour)","none",1);
      const headings=draw("g",{"data-hub":""},land);
      svgText(headings,w*.265,27,"워커힐 "+nIn+"곳","map-title","middle");
      svgText(headings,w*.75,27,"경쟁 업장 "+nOut+"곳","map-title","middle");
      return headings;
    }
    caption.textContent="안쪽은 워커힐, 바깥쪽은 같은 방향의 경쟁 업장";
    svg.setAttribute("aria-label","중앙 워커힐 "+nIn+"곳과 외곽 경쟁 업장 "+nOut+"곳의 방문 이동 지도");
    function oval(radius,fill,stroke,width=1){
      return draw("ellipse",{cx,cy,rx:rx*radius,ry:ry*radius,fill,stroke,"stroke-width":width},land);
    }
    oval(1.10,"none","var(--contour)");
    oval(.755,"var(--estate)","var(--contour)");
    oval(.728,"none","var(--paving)",3);
    oval(.704,"none","var(--contour)",.75);
    // Landscaping stays visually separate from the transient visit paths.
    const edge=draw("g",{transform:"scale("+w/1000+" "+h/600+")"},land);
    for(let i=0;i<0;i++){
      path(edge,"M-55 "+(430+i*8)+" Q14 "+(414+i*9)+" 29 "+(457+i*6)+" T106 "+(569+i*8)+" T230 "+(615+i*6),"var(--contour)","none",.8);
      path(edge,"M"+(849+i*10)+" -21 Q900 "+(47+i*6)+" 965 "+(24+i*7)+" T1050 "+(74+i*6),"var(--contour)","none",.8);
    }
    for(const [x,y,size] of [])forest(land,w*x,h*y,mobile?size*.65:size);
    const title=svgText(land,15,23,"외곽: 경쟁 업장 "+nOut+"곳","map-title");
    title.style.fontSize=mobile?"12px":"14px";
    const centre=draw("g",{"data-hub":""},land);
    draw("ellipse",{cx,cy,rx:mobile?22:43,ry:mobile?30:37,fill:"var(--garden)",stroke:"var(--contour)","stroke-width":.85},centre);
    
    const label=svgText(centre,cx,cy+3,"워커힐","map-title","middle");
    label.style.fontSize=mobile?"12px":"16px";
    const count=svgText(centre,cx,cy+19,nIn+"곳","map-title","middle");
    count.style.fontSize="11px";
    return centre;
  }
  function slotPoint(id,index,small){
    const loc=locations.get(id);
    // Between the upper inner-ring neighbours, wrap the dots below their own label.
    const columns=small?(id==="geumryong"?3:8):10,spacing=small?9.5:11;
    const col=index%columns;
    const offset=col?Math.ceil(col/2)*spacing*(col%2?1:-1):0;
    return {x:loc.x+offset,y:loc.y+23+Math.floor(index/columns)*spacing};
  }
  function assignSlots(small){
    figureSlots.clear();travel.clear();
    const counts=new Map([...places.keys()].map(k=>[k,0]));
    /* A visitor staying at a place owns the very same slot at both endpoints. */
    for(const v of rows.filter(v=>v.from===v.to).sort((a,b)=>Number(a.type==="order")-Number(b.type==="order"))){
      const i=counts.get(v.from);counts.set(v.from,i+1);
      const at=slotPoint(v.from,i,small);figureSlots.set(v.visit_id,{start:at,end:at});
    }
    const before=new Map(counts),after=new Map(counts);
    for(const v of rows.filter(v=>v.from!==v.to)){
      const i=before.get(v.from),j=after.get(v.to);before.set(v.from,i+1);after.set(v.to,j+1);
      figureSlots.set(v.visit_id,{start:slotPoint(v.from,i,small),end:slotPoint(v.to,j,small)});
    }
  }
  function cubicPoint(a,b,c,d,t){
    const s=1-t;
    return {x:s*s*s*a.x+3*s*s*t*b.x+3*s*t*t*c.x+t*t*t*d.x,
            y:s*s*s*a.y+3*s*s*t*b.y+3*s*t*t*c.y+t*t*t*d.y};
  }
  const xy=p=>p.x+" "+p.y;
  const between=(a,b,t)=>({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});
  function clearCurve(a,b,c,d,mesh){
    const length=Math.hypot(b.x-a.x,b.y-a.y)+Math.hypot(c.x-b.x,c.y-b.y)+Math.hypot(d.x-c.x,d.y-c.y);
    const steps=Math.max(8,Math.ceil(length/7));let prev=a;
    for(let i=1;i<=steps;i++){
      const point=cubicPoint(a,b,c,d,i/steps);
      if(!mesh.clear(prev,point))return false;
      prev=point;
    }
    return true;
  }
  function curvedWaypoints(points,mesh){
    let pathData="M"+xy(points[0]);
    for(let i=1;i<points.length-1;i++){
      const p=points[i],a=points[i-1],b=points[i+1];
      const before=Math.hypot(a.x-p.x,a.y-p.y),after=Math.hypot(b.x-p.x,b.y-p.y);
      if(!before||!after)continue;
      let radius=Math.min(70,before*.49,after*.49);
      while(radius>1){
        const entry=between(p,a,radius/before),exit=between(p,b,radius/after);
        // The handles align with both approaches, so a dot never makes a sharp turn.
        const h1=between(entry,p,.63),h2=between(exit,p,.63);
        if(clearCurve(entry,h1,h2,exit,mesh)){
          pathData+=" L"+xy(entry)+" C"+xy(h1)+" "+xy(h2)+" "+xy(exit);
          break;
        }
        radius*=.65;
      }
      if(radius<=1)pathData+=" L"+xy(p);
    }
    return pathData+" L"+xy(points.at(-1));
  }
  // Route around the illustrated buildings and hub. Each direction shares one full-length path.
  function navigationMesh(rectangles){
    const bounds=svg.viewBox.baseVal;
    const inMap=p=>p.x>=2&&p.x<=bounds.width-2&&p.y>=2&&p.y<=bounds.height-2;
    const boxes=rectangles.map(b=>{
      const space=3;
      return {left:b.x-space,right:b.x+b.width+space,top:b.y-space,bottom:b.y+b.height+space};
    });
    function crosses(a,b,r){
      let enter=0,exit=1;
      for(const [p,q,lo,hi] of [[a.x,b.x,r.left+.15,r.right-.15],[a.y,b.y,r.top+.15,r.bottom-.15]]){
        const d=q-p;
        if(Math.abs(d)<.001){if(p<=lo||p>=hi)return false;continue}
        const x=(lo-p)/d,y=(hi-p)/d;
        enter=Math.max(enter,Math.min(x,y));exit=Math.min(exit,Math.max(x,y));
        if(enter>=exit)return false;
      }
      return true;
    }
    const clear=(a,b)=>inMap(a)&&inMap(b)&&!boxes.some(box=>crosses(a,b,box));
    const padding=bounds.width<570?8:16;
    const corners=boxes.flatMap(r=>[
      [r.left-padding,r.top-padding],[r.right+padding,r.top-padding],
      [r.right+padding,r.bottom+padding],[r.left-padding,r.bottom+padding]
    ]).map(([x,y])=>({x,y})).filter(p=>inMap(p)&&!boxes.some(r=>p.x>r.left&&p.x<r.right&&p.y>r.top&&p.y<r.bottom));
    return {corners,clear};
  }
  function routeGeometry(start,end,mesh){
    const dx=end.x-start.x,dy=end.y-start.y,length=Math.hypot(dx,dy);
    // Leave and enter the side of the facade facing the journey, with a gentle bow.
    const handle=Math.min(90,length*.29),lift=Math.min(26,length*.12);
    for(const reach of [1,.62,1.55]){
      for(const bow of [-1,1]){
        const hx=handle*reach;
        const h1={x:start.x+start.side*hx,y:start.y+dy*.18+bow*lift};
        const h2={x:end.x+end.side*hx,y:end.y-dy*.18+bow*lift};
        if(clearCurve(start,h1,h2,end,mesh))return "M"+xy(start)+" C"+xy(h1)+" "+xy(h2)+" "+xy(end);
      }
    }
    // Keep the approaches tangent to the facade even when a longer route must turn.
    const lip=Math.min(13,length*.1);
    const exit={x:start.x+start.side*lip,y:start.y},entry={x:end.x+end.side*lip,y:end.y};
    const nodes=[exit,entry,...mesh.corners],dist=nodes.map(()=>Infinity),previous=[],closed=new Set();
    dist[0]=0;
    while(closed.size<nodes.length){
      let here=-1,best=Infinity;
      dist.forEach((d,i)=>{if(!closed.has(i)&&d<best){best=d;here=i}});
      if(here===-1||here===1)break;
      closed.add(here);const a=nodes[here];
      nodes.forEach((b,i)=>{
        const cost=best+Math.hypot(b.x-a.x,b.y-a.y);
        if(!closed.has(i)&&cost<dist[i]&&mesh.clear(a,b)){dist[i]=cost;previous[i]=here}
      });
    }
    const points=[];for(let i=1;i!==undefined;i=previous[i])points.unshift(nodes[i]);
    if(points.length===1)points.unshift(exit);
    return curvedWaypoints([start,...points,end],mesh);
  }
  const duration=7900;
  const travelSpan=.68;
  const fadeMilliseconds=900;
  const handoffSpan=180/duration;
  const maskPrefix="wh-route-"+Math.random().toString(36).slice(2);
  function arrivalMask(defs,geometry,group,index,blurId){
    const id=maskPrefix+"-"+index;
    const box=group.getBBox(),pad=24;
    const bounds={x:box.x-pad,y:box.y-pad,width:box.width+2*pad,height:box.height+2*pad};
    const mask=draw("mask",{id,maskUnits:"userSpaceOnUse",maskContentUnits:"userSpaceOnUse","mask-type":"luminance",...bounds},defs);
    draw("rect",{...bounds,fill:"white"},mask);
    const wipe=draw("path",{d:geometry,fill:"none",stroke:"black","stroke-width":30,"stroke-linecap":"round",
      pathLength:1000,"stroke-dasharray":"1000 1100","stroke-dashoffset":1000,filter:"url(#"+blurId+")"},mask);
    return {id,wipe};
  }
  function buildLanes(layer,hub){
    lanes=new Map();
    const moving=rows.filter(v=>moves(v.type));
    if(!moving.length)return;
    const queuedByPlace=new Map();
    for(const visit of rows){
      const slots=figureSlots.get(visit.visit_id);
      for(const [id,p] of [[visit.from,slots.start],[visit.to,slots.end]]){
        if(!queuedByPlace.has(id))queuedByPlace.set(id,[]);
        queuedByPlace.get(id).push(p);
      }
    }
    const fixedObstacles=[hub.getBBox()];
    for(const [id,l] of locations){
      fixedObstacles.push(l.labelBox);
      const spots=queuedByPlace.get(id);
      if(!spots)continue;
      const xs=spots.map(p=>p.x),ys=spots.map(p=>p.y);
      const x=Math.min(...xs)-4,y=Math.min(...ys)-4;
      fixedObstacles.push({x,y,width:Math.max(...xs)+4-x,height:Math.max(...ys)+4-y});
    }
    const defs=draw("defs",{},layer);
    const blurId=maskPrefix+"-feather",bounds=svg.viewBox.baseVal;
    const blur=draw("filter",{id:blurId,filterUnits:"userSpaceOnUse",x:0,y:0,width:bounds.width,height:bounds.height},defs);
    draw("feGaussianBlur",{stdDeviation:3.5},blur);
    const schedules=new Map();
    moving.forEach((visit,index)=>{
      const track={slots:figureSlots.get(visit.visit_id),depart:.045+.22*index/Math.max(1,moving.length-1)};
      if(!schedules.has(visit.group))schedules.set(visit.group,[]);
      schedules.get(visit.group).push({visit,track});
    });
    for(const [key,members] of schedules){
      const first=members[0],last=members.at(-1),type=first.visit.type;
      const from=locations.get(first.visit.from),to=locations.get(first.visit.to);
      const dx=to.x-from.x,dy=to.y-from.y,vertical=Math.abs(dx)<=Math.abs(dy)*.22;
      const commonSide=(from.x+to.x)/2<bounds.width*.49?"right":"left";
      const origin=from.doors[vertical?commonSide:dx>0?"right":"left"];
      const target=to.doors[vertical?commonSide:dx>0?"left":"right"];
      const obstacles=fixedObstacles.concat([...locations.values()].filter(l=>l!==from&&l!==to).map(l=>l.buildingBox));
      const mesh=navigationMesh(obstacles);
      const group=draw("g",{"data-lane":key},layer);
      const geometry=routeGeometry(origin,target,mesh);
      path(group,geometry,"var(--paper)","none",4.2);
      const stroke=path(group,geometry,color(type),"none",2.35);
      if(types[type].dash)stroke.setAttribute("stroke-dasharray",types[type].dash);
      const length=stroke.getTotalLength(),steps=Math.max(2,Math.ceil(length/3));
      const points=Array.from({length:steps+1},(_,j)=>stroke.getPointAtLength(length*j/steps));
      const mid=stroke.getPointAtLength(length*.54),next=stroke.getPointAtLength(Math.min(length,length*.54+2));
      const angle=Math.atan2(next.y-mid.y,next.x-mid.x)*180/Math.PI;
      const arrow=draw("g",{transform:"translate("+mid.x+" "+mid.y+") rotate("+angle+")"},group);
      path(arrow,"M-4 -3.3 L.7 0 L-4 3.3",color(type),"var(--paper)",1.8);
      const lane={group,points,arrival:last.track.depart+travelSpan,
        mask:arrivalMask(defs,geometry,group,lanes.size,blurId)};

      lanes.set(key,lane);
      for(const {visit,track} of members){track.lane=lane;travel.set(visit.visit_id,track)}
    }
  }
  const smooth=t=>t*t*(3-2*t);
  function routePoint(lane,t){
    const f=t*(lane.points.length-1),j=Math.floor(f);
    return between(lane.points[j],lane.points[Math.min(j+1,lane.points.length-1)],f-j);
  }
  // Each visit uses one symbol. Its parking slot is only for the before/after count.
  function visitorPose(track){
    const elapsed=ui.progress-track.depart,remaining=track.depart+travelSpan-ui.progress;
    if(elapsed<0)return {point:track.slots.start,alpha:smooth(clamp(-elapsed/handoffSpan))};
    if(remaining<=0)return {point:track.slots.end,alpha:smooth(clamp(-remaining/handoffSpan))};
    const phase=smooth(clamp(elapsed/travelSpan));
    const alpha=smooth(clamp(Math.min(elapsed,remaining)/handoffSpan));
    return {point:routePoint(track.lane,phase),alpha};
  }
  function updateRouteVisibility(){
    for(const lane of lanes.values()){
      const remaining=(lane.arrival-ui.progress)*duration;
      if(remaining<=0){lane.group.setAttribute("visibility","hidden");continue}
      lane.group.setAttribute("visibility","visible");
      if(remaining>=fadeMilliseconds){
        lane.group.removeAttribute("mask");
        lane.group.removeAttribute("opacity");
        continue;
      }
      // The final traveller controls the wipe. Its soft edge follows the actual curve.
      const fade=clamp(1-remaining/fadeMilliseconds);
      lane.group.setAttribute("mask","url(#"+lane.mask.id+")");
      lane.mask.wipe.setAttribute("opacity",smooth(clamp(fade/.15)));
      lane.mask.wipe.setAttribute("stroke-dashoffset",1000*(1-smooth(fade)));
      lane.group.setAttribute("opacity",1-smooth(clamp((fade-.76)/.24)));
    }
  }
  function makeMap(){
    const w=Math.round(svg.getBoundingClientRect().width);if(!w)return;
    lastWidth=w;const layout=positions(w),{height:h,mobile}=layout;
    svg.setAttribute("viewBox","0 0 "+w+" "+h);svg.setAttribute("width",w);svg.setAttribute("height",h);
    svg.replaceChildren();const desc=draw("desc",{},svg);
    desc.textContent=mlab(ui.month)+" 가상 방문 "+rows.length+"건. 업장별 건수와 각 방문의 전후 선택은 아래 표에서 확인할 수 있습니다.";
    const hub=landscape(layout);assignSlots(mobile);
    const active=new Set(rows.filter(v=>v.type!=="stay").flatMap(v=>[v.from,v.to]));
    const routesLayer=draw("g",{},svg), buildingsLayer=draw("g",{},svg), people=draw("g",{},svg);
    const scale=mobile?.56:Math.min(.95,w/890);
    for(const [id,l] of locations){
      const ext=withRole(id)!=="walkerhill";
      const g=draw("g",{"data-place":id},buildingsLayer);
      g.style.setProperty("--land",ext?"var(--city)":"var(--estate)");
      const b=draw("g",{opacity:active.has(id)?1:.78},g);
      l.doors=building(b,l.x,l.y-10,scale,places.get(id).icon);
      l.buildingBox=b.getBBox();
      const caption=svgText(g,l.x,l.y+11,name(id),"map-name"+(active.has(id)?" active":""),"middle");
      if(mobile)caption.style.fontSize="12px";
      l.labelBox=caption.getBBox();
      const tip=draw("title",{},g),p=places.get(id);
      tip.textContent=p.name+(p.hotel?", "+p.hotel:"")+", 기본 "+balance.get(id).before+"건 → 적용 후 "+balance.get(id).after+"건";
    }
    actors=[];buildLanes(routesLayer,hub);
    for(const v of [...rows].sort((a,b)=>Number(moves(a.type))-Number(moves(b.type)))){
      const g=draw("g",{"data-person":v.visit_id,"data-type":v.type},people);
      const hollow=v.type==="stay"||v.type==="order"||v.type==="price";
      let ring=null,special=null;
      if(v.type==="order")ring=draw("circle",{r:7,fill:"none",stroke:color("order"),"stroke-width":1.6},g);
      const dot=draw("circle",{class:"visit-dot",r:4,fill:hollow?"var(--point-center)":color(v.type),stroke:color(v.type),"stroke-width":1.45},g);
      if(v.type==="price")special=path(g,"M-2 -1h4 M-2 1h4",color("price"),"none",1.1);
      if(v.type==="order")special=draw("circle",{r:1.6,fill:color("order")},g);
      const tip=draw("title",{},g);tip.textContent=data.personas[v.visit_id.split("__")[0]]+", "+name(v.from)+" → "+name(v.to)+", "+types[v.type].name;
      actors.push({v,g,dot,ring,special,at:figureSlots.get(v.visit_id).start});
    }
    drawFrame();
  }
  function drawFrame(){
    for(const a of actors){
      let pos=a.at;const track=travel.get(a.v.visit_id);
      if(track){
        const pose=visitorPose(track);
        pos=pose.point;a.g.setAttribute("opacity",pose.alpha);
      }
      a.g.setAttribute("transform","translate("+pos.x+" "+pos.y+")");
      if(a.ring){
        const t=clamp((ui.progress-.22)/.55);
        a.ring.setAttribute("r",6.5+7*Math.sin(Math.PI*t));a.ring.setAttribute("visibility",t===0?"hidden":"visible");
      }
      if(a.special)a.special.setAttribute("visibility",ui.progress>.45?"visible":"hidden");
    }
    updateRouteVisibility();
    slider.value=String(Math.round(ui.progress*1000));slider.style.setProperty("--position",ui.progress*100+"%");
    slider.setAttribute("aria-valuetext",ui.progress===1?"조건 적용 후":ui.progress===0?"기본 시나리오":"재생 위치 "+slider.value/10+"%");
    const end=ui.progress===1;
    if(wasAtEnd!==end){wasAtEnd=end;q(".insights").hidden=!end||!q(".insights li");}
  }
  function controls(){play.textContent=ui.playing?"Ⅱ 일시정지":ui.progress===1?"↻ 다시 재생":"▶ 이동 재생";play.setAttribute("aria-label",ui.playing?"재생 멈춤":ui.progress===1?"처음부터 다시 재생":"방문 이동 재생")}
  function stop(){ui.playing=false;cancelAnimationFrame(tickId);lastTick=null;controls();mapBadge()}
  function finish(){
    stop();{const l=chosen(),last=l[l.length-1].month;if(ui.month!==last)showMapMonth(last)}ui.progress=1;drawFrame();controls();
    q("[data-status]").textContent=mlab(ui.month)+" 최종 위치를 표시했습니다.";
  }
  function tick(now){
    if(!ui.playing)return;if(lastTick!==null)ui.progress=clamp(ui.progress+(now-lastTick)/duration);lastTick=now;
    if(ui.progress>=1){const next=nextMapMonth();if(next===null){finish();return}showMapMonth(next);ui.progress=0;q("[data-status]").textContent=mlab(next)+" 재생";}drawFrame();tickId=requestAnimationFrame(tick);
  }
  function start(){
    if(ui.progress===1){ui.progress=0;{const f=chosen()[0].month;if(ui.month!==f)showMapMonth(f)}}ui.playing=true;lastTick=null;drawFrame();controls();mapBadge();tickId=requestAnimationFrame(tick);
  }
  function setView(view){
    stop();ui.view=view;ui.month=chosen()[0].month;ui.progress=0;wasAtEnd=false;
    prepare();prepareReport();renderCopy();updateLegend();updateFilters();makeMap();mapBadge();controls();slider.value="0";
    q("[data-status]").textContent=viewLabel()+" 기본 시나리오";
  }
  const pref=matchMedia("(prefers-color-scheme: dark)");
  function themeLabel(){
    const dark=root.dataset.theme?root.dataset.theme==="dark":pref.matches;
    q(".theme").textContent=dark?"☀ 밝게":"◐ 어둡게";
  }
  q(".theme").addEventListener("click",()=>{const dark=root.dataset.theme?root.dataset.theme==="dark":pref.matches;root.dataset.theme=dark?"light":"dark";themeLabel()});
  pref.addEventListener("change",themeLabel);
  play.addEventListener("click",()=>{if(ui.playing)stop();else if(matchMedia("(prefers-reduced-motion: reduce)").matches)finish();else start()});
  slider.addEventListener("input",()=>{stop();ui.progress=Number(slider.value)/1000;drawFrame();controls()});
  q(".end").addEventListener("click",finish);
  document.addEventListener("visibilitychange",()=>{if(document.hidden)stop()});
  themeLabel();setupIndex();buildLegend();setView(ui.view);
  new ResizeObserver(()=>{if(lastWidth!==Math.round(svg.getBoundingClientRect().width))makeMap()}).observe(svg);
 })();
 
  // ── 누르기: 방문 줄 펼치기, 페이지 안 이동, 다른 페이지로 가기 (줄은 다시 그려지므로 그림자 영역에 한 번 단다) ──
  R.addEventListener("click", event => {
    const toggle = event.target.closest("[data-open-visit]");
    if (toggle) {
      const open = toggle.getAttribute("aria-expanded") === "false";
      toggle.setAttribute("aria-expanded", String(open));
      R.getElementById(toggle.getAttribute("aria-controls")).hidden = !open;
      toggle.textContent = open ? "접기" : "자세히";
      toggle.closest(".wh-list-row").classList.toggle("is-open", open);
      return;
    }
    const scroll = event.target.closest("[data-scroll]");
    if (scroll) {
      event.preventDefault();
      R.getElementById(scroll.dataset.scroll)?.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      return;
    }
    const saved = event.target.closest("[data-result]");
    if (saved) {
      event.preventDefault();
      if (saved.dataset.result !== DATA.result_id) act("open_result", { result_id: saved.dataset.result });
      else R.getElementById("compare").close();
      return;
    }
    const action = event.target.closest("[data-action]");
    if (action) {
      event.preventDefault();
      act(action.dataset.action, { scenario_id: DATA.scenario.id });
      return;
    }
    // 폰에서 페르소나 카드를 누르면 상세로 이동 (결정 86)
    const card = event.target.closest(".guest-card");
    if (card && matchMedia("(max-width:640px)").matches) {
      setTimeout(() => {
        const drawer = R.getElementById("guest-detail");
        if (!drawer || drawer.hidden) return;
        const box = drawer.getBoundingClientRect();
        if (box.top > innerHeight * 0.55 || box.bottom < 0) {
          drawer.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
        }
      }, 60);
    }
  });
}
