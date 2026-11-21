// 시나리오 만들기 스크립트 (T130). 시안 scenario-builder-v4 의 model·화면·불러오기 스크립트를 옮겨, Streamlit 컴포넌트(st.components.v2)로 띄운다.
// 파이썬(app/builder_page.py)이 자료(업장·메뉴·페르소나·준비된 상황)와 결과 있는 시나리오 목록을 데이터 묶음(app/builder_model.py)으로 넘긴다.
// 입력은 모두 브라우저에 두고, "시뮬레이션 실행"을 누르면 상황 정의와 입력을 setTriggerValue("action", …) 로 파이썬에 보낸다.
// 화면은 그림자 영역 안에 있어, 원래 스크립트가 쓰던 document 를 그림자 영역을 가리키는 대리 객체로 바꿔 끼운다 (app/report/report.js 와 같다).
export default function (component) {
  const { parentElement: R, setTriggerValue } = component;
  const W = R && R.querySelector(".wh-builder");
  if (!component.data || !W) return;
  // 다시 그릴 때는 꾸린 화면과 입력을 그대로 두고, 파이썬이 넘긴 새 값(실행 오류, 목록)만 반영한다
  if (W.__whBuilder) {
    W.__whBuilder(component.data);
    return;
  }
  let DATA = component.data;
  const D = globalThis.document;
  const STATIC = "/app/static/";
  const document = {
    getElementById: id => R.getElementById(id),
    querySelector: s => R.querySelector(s),
    querySelectorAll: s => R.querySelectorAll(s),
    createElement: tag => D.createElement(tag),
    createElementNS: (ns, tag) => D.createElementNS(ns, tag),
    // 누르기는 그림자 영역에서 받는다. 문서에서 받으면 누른 대상이 그림자 바깥 상자로 바뀌어 보여 closest 가 못 찾는다
    addEventListener: (type, fn, opts) => (type === "visibilitychange" ? D : R).addEventListener(type, fn, opts),
    get activeElement() { return R.activeElement; },
    get body() { return W; },
    get documentElement() { return W; },
    get hidden() { return D.hidden; },
  };
  const act = (type, extra) => setTriggerValue("action", Object.assign({ type, at: Date.now() }, extra || {}));
  const catalogs = DATA.catalogs;

const dayLabels = {weekday:"평일", weekend:"주말"};
const visitLabels = {lunch:"점심", dinner:"저녁", dessert:"디저트·차", takeout:"포장·구매"};
const occasionLabels = {meal:"식사", dessert:"디저트·차", takeout:"포장·구매"};
const kinds = {
  price:["기존 메뉴 가격 바꾸기","지금 메뉴의 가격을 올리거나 내립니다.","price"],
  promo:["프로모션","방문 조건에 따라 할인하거나 증정합니다.","gift"],
  product:["한정 메뉴 더하기","기간을 정해 새 메뉴를 추가합니다.","dish"],
  remove:["메뉴 빼기","고객이 고를 수 있는 메뉴에서 뺍니다.","minus"]
};
const presetMeta = {
  "thebuffet-december-price":["glass-walkerhill","가격 변경","성인·어린이 메뉴 4개"],
  "geumryong-yearend-course":["hall-walkerhill","한정 메뉴","평일 점심·저녁 코스"],
  "parkview-yearend-price":["atrium-competitor","가격 변경","성인·어린이 메뉴 8개"],
  "geumryong-course-price-up":["hall-walkerhill","가격 변경","코스 A 가격 인상"],
  "competitor-chinese-discount":["hall-competitor","프로모션","주말 주문 할인"]
};
const months = Array.from({length:12},(_,i)=>i+1);
const clone = value => JSON.parse(JSON.stringify(value));
const number = value => Number(value).toLocaleString("ko-KR");
const won = value => value==null ? "공개 가격 없음" : number(value)+"원";
const signed = value => (Number(value)>0?"+":"")+number(value);
const isInt = x => x!=="" && x!=null && Number.isSafeInteger(Number(x));
const positive = x => isInt(x) && Number(x)>0;
const uid = () => "ui-"+crypto.randomUUID();
const defaultPreset = "thebuffet-december-price";
// 시안 가정: 이 PC 에 결과(실행 폴더)가 있는 준비된 시나리오
const presetRan = new Set();
function initial(source="team"){
  const data=catalogs[source];
  return {source, name:"", nameEdited:false, preset:null, side:"in", changes:[],
    // 11-21: 누가·언제는 처음에 비워 둔다. 기본값으로 채워 두면 진행 단계 ②③이 손대지 않아도 끝난 것으로 보였다 (결정 14를 바꿈)
    people:[], days:[], occasions:[],
    period:"single", start:null,end:null, extendOnNext:false, loadedKey:null, loadedHasResult:false, modified:false, answer:"replay",prompt:data.default_prompt||data.prompts[0]};
}
// 준비된 시나리오의 결과를 받을 때 쓴 조건 (시안 가정: 페르소나 모두, 방문 조건 모두, 12월)
function fullScope(source=state.source){const data=catalogs[source];return {...initial(source),people:data.people.map(p=>p.id),days:Object.keys(dayLabels),occasions:Object.keys(visitLabels),start:12,end:12};}
let state=initial();
const catalog=()=>catalogs[state.source];
const venue=id=>catalog().venues[id];
const sideLabel=()=>state.side==="in"?"워커힐 안":"워커힐 밖";
const sideVenues=()=>Object.entries(catalog().venues).filter(([,v])=>v.is_competitor===(state.side==="out")).sort(([,a],[,b])=>a.name.localeCompare(b.name,"ko"));
function fresh(type, venueId=sideVenues()[0][0]){
  const occasion=venue(venueId).occasions[0];
  return {id:uid(),type,venueId,scope:type==="remove"?"some":"all",ids:[],mode:"pct",value:10,prices:{},
    name:"",benefit:"discount_pct",gift:"",day:"",meal:"",party:"",from:"",to:"",
    occasion, slots:[],months:[],unit:"1인",serves:1,audience:"all",price:"",itemId:uid(),original:null};
}
function loadPreset(id){
  const p=catalog().presets[id];
  if(!p) return;
  fillDefinition(p,id);
}
function fillDefinition(p,id=null){
  const rows=definitionRows(p);
  state.side=p.kind==="competitor"?"out":"in";
  state.name=p.name;state.nameEdited=false;state.preset=id;state.changes=rows;
  state.originName=p.name;state.originFile="";state.libraryKey=null;state.modified=false;
}
function definitionRows(p){
  const rows=[];
  for(const c of p.changes){
    const t={set_price:"price",change_price_pct:"price",add_product:"product",add_promotion:"promo",remove_product:"remove"}[c.op];
    if(c.op==="set_price"){
      let row=rows.at(-1);
      if(!row || row.venueId!==c.venue_id || row.type!=="price" || row.mode!=="set" || row.ids.includes(c.product_id)){
        row=fresh("price",c.venue_id);row.mode="set";row.scope="some";rows.push(row);
      }
      row.ids.push(c.product_id);row.prices[c.product_id]=c.price;continue;
    }
    const row=fresh(t,c.venue_id);rows.push(row);
    if(c.op==="change_price_pct" || c.op==="remove_product"){
      row.scope=c.product_id?"some":"all";row.ids=c.product_id?[c.product_id]:[];row.value=c.pct??0;
    } else if(c.op==="add_product"){
      const a=c.product;
      Object.assign(row,{original:clone(a),itemId:a.product_id,name:a.name,price:a.price,occasion:a.occasion,
        months:a.months||[],unit:a.unit,serves:a.serves,audience:a.audience,
        slots:a.slots.flatMap(s=>(s.day_type==="all"?Object.keys(dayLabels):[s.day_type]).map(day=>day+"/"+(s.meal||"")))});
    } else if(c.op==="add_promotion"){
      const a=c.promotion,q=a.conditions;
      Object.assign(row,{original:clone(a),itemId:a.promo_id,name:a.name,benefit:a.benefit.type,
        value:a.benefit.value,gift:a.benefit.type==="gift"?a.benefit.value:"",scope:a.applies_to?"some":"all",ids:a.applies_to||[],
        day:q.day_type||"",meal:q.meal||"",party:q.party_min||"",from:a.period?.from||"",to:a.period?.to||""});
    }
  }
  return rows;
}
function markEdited(){
  const original=state.originName||catalog().presets[state.preset]?.name;
  if(original && !state.nameEdited && state.name===original) state.name+=" 수정본";
  state.modified=true;
}
function selectedMenus(row){
  const products=venue(row.venueId).products;
  return row.scope==="all"?products:row.ids.map(id=>products.find(p=>p.product_id===id)).filter(Boolean);
}
function revisedPrice(row,p){
  if(row.mode==="set") return positive(row.prices[p.product_id])?Number(row.prices[p.product_id]):null;
  if(p.price==null || !isInt(row.value)) return null;
  return row.mode==="amount"?p.price+Number(row.value):Math.round(p.price*(100+Number(row.value))/100);
}
function previewPrice(row,p){
  const price=revisedPrice(row,p);
  if(price!=null) return won(price);
  if(row.mode==="pct" && p.price==null && isInt(row.value)) return "평균 가격 "+signed(row.value)+"%";
  return "—";
}
function shortChange(row){
  const v=venue(row.venueId), items=selectedMenus(row);
  const target=row.scope==="all"?"모든 메뉴":items.length===1?items[0].name:"메뉴 "+items.length+"개";
  if(row.type==="price") return v.name+" "+target+" "+(row.mode==="pct"?signed(row.value)+"%":row.mode==="amount"?signed(row.value)+"원":"새 가격 적용");
  if(row.type==="product") return v.name+" "+row.name+" 추가";
  if(row.type==="remove") return v.name+" "+target+" 빼기";
  return v.name+" "+row.name+" · "+(row.benefit==="gift"?row.gift+" 증정":number(row.value)+(row.benefit==="discount_pct"?"%":"원")+" 할인");
}
function span(s=state){
  if(s.period==="year") return [];
  if(s.start==null || (s.period==="range" && s.end==null)) return [];
  const length=s.period==="single"?1:(s.end-s.start+12)%12+1;
  return Array.from({length},(_,i)=>(s.start-1+i)%12+1);
}
function periodText(s=state){
  if(s.period==="year") return "일 년 전체";
  if(s.start==null) return "달을 골라 주세요";
  if(s.period==="range" && s.end==null) return s.start+"월 → 끝 달 선택";
  const list=span(s);
  if(list.length===1) return list[0]+"월 · 1개월";
  return s.start+"월~"+(s.end<s.start?"다음 해 ":"")+s.end+"월 · "+list.length+"개월";
}
function visitCount(s=state){
  const n=s.days.length*s.occasions.length;
  return {conditions:n,each:s.people.length*n*(s.period==="year"?1:span(s).length)};
}
function rowErrors(r,others=state.changes.filter(c=>c.id!==r.id)){
  const errors=[], products=selectedMenus(r), v=venue(r.venueId);
  if(r.type!=="product" && !products.length) errors.push("적용할 메뉴를 하나 이상 골라 주세요.");
  if(r.type==="price"){
    if(r.mode!=="set" && !isInt(r.value)) errors.push("소수점 없이 숫자로 입력해 주세요.");
    if(r.mode==="pct" && Number(r.value)<=-100) errors.push("바꾼 뒤 가격이 0원 이하가 됩니다.");
    if(r.mode==="amount" && products.some(p=>p.price==null)) errors.push("공개 가격이 없는 메뉴는 퍼센트나 새 가격만 됩니다.");
    if(r.mode==="set" && products.some(p=>!positive(r.prices[p.product_id]))) errors.push("고른 메뉴마다 새 가격을 입력해 주세요.");
    if(products.some(p=>revisedPrice(r,p)!=null && !positive(revisedPrice(r,p)))) errors.push("바꾼 뒤 0원 이하인 메뉴가 있습니다.");
  }
  if(r.type==="promo"){
    if(!r.name.trim()) errors.push("프로모션 이름을 입력해 주세요.");
    if(r.benefit==="gift" && !r.gift.trim()) errors.push("증정품 이름을 입력해 주세요.");
    if(r.benefit==="discount_pct" && (!positive(r.value) || Number(r.value)>99)) errors.push("할인율은 1~99 사이 숫자로 입력해 주세요.");
    if(r.benefit==="discount_amount" && !positive(r.value)) errors.push("할인 금액을 1원 이상 입력해 주세요.");
    if(r.party!=="" && !positive(r.party)) errors.push("최소 일행 수를 1명 이상으로 입력해 주세요.");
    if(Boolean(r.from)!==Boolean(r.to) || r.from>r.to) errors.push("시작일과 종료일을 순서대로 모두 입력해 주세요.");
  }
  if(r.type==="product"){
    if(!r.name.trim()) errors.push("한정 메뉴 이름을 입력해 주세요.");
    if(!positive(r.price)) errors.push("한정 메뉴 가격을 1원 이상 입력해 주세요.");
    if(!r.unit.trim() || !positive(r.serves)) errors.push("판매 단위와 몇 명분인지 입력해 주세요.");
    if(!r.slots.length) errors.push("파는 때를 하나 이상 골라 주세요.");
  }
  const same=others.filter(c=>c.venueId===r.venueId);
  if(r.type==="remove"){
    const ids=new Set(r.ids);
    const refs=[...v.promotions.map(p=>p.applies_to),...same.filter(c=>c.type==="promo" && c.scope==="some").map(c=>c.ids)];
    if(refs.some(list=>list?.some(id=>ids.has(id)))) errors.push("프로모션이 걸린 메뉴라 뺄 수 없습니다.");
    if(same.some(c=>c.type==="remove" && c.ids.some(id=>ids.has(id)))) errors.push("이미 뺀 메뉴입니다.");
  }
  if(r.type==="promo" && r.scope==="some" && same.some(c=>c.type==="remove" && c.ids.some(id=>r.ids.includes(id)))) errors.push("뺀 메뉴에는 프로모션을 걸 수 없습니다.");
  return [...new Set(errors)];
}
function problems(){
  const result=[];
  if(!state.name.trim()) result.push("시나리오 이름을 입력해 주세요.");
  if(!state.changes.length) result.push("바꿀 것을 하나 이상 추가해 주세요.");
  if(!state.people.length) result.push("페르소나를 한 명 이상 골라 주세요.");
  if(!state.days.length || !state.occasions.length) result.push("요일과 이용 상황을 각각 하나 이상 골라 주세요.");
  if(state.period!=="year" && !span().length) result.push(state.start==null?"실행할 달을 골라 주세요.":"기간의 끝 달을 골라 주세요.");
  state.changes.forEach(c=>result.push(...rowErrors(c)));
  return [...new Set(result)];
}
function missingParts(){
  const m=[];
  if(!state.name.trim()) m.push("이름");
  if(!state.changes.length) m.push("바꿀 것");
  else if(state.changes.some(c=>rowErrors(c).length)) m.push("바꿀 것의 빈 값");
  if(!state.people.length) m.push("페르소나");
  if(!state.days.length) m.push("요일");
  if(!state.occasions.length) m.push("이용 상황");
  if(state.period!=="year" && !span().length) m.push(state.start==null?"기간":"끝 달");
  return m;
}
function notices(){
  const result=[], promos=state.changes.filter(c=>c.type==="promo");
  if(promos.some(c=>c.benefit!=="gift" && promos.some(x=>x!==c && x.venueId===c.venueId && x.benefit!=="gift"))) result.push("한 업장에서는 가장 큰 할인 하나만 적용됩니다.");
  if(state.period==="year" && promos.some(c=>c.from)) result.push("일 년 전체로 돌리면 프로모션 날짜는 반영되지 않습니다.");
  return result;
}
function changeOps(r){
  const base={venue_id:r.venueId}, items=selectedMenus(r);
  if(r.type==="price" && r.mode==="pct") return (r.scope==="all"?[null]:items.map(p=>p.product_id)).map(product_id=>({...base,op:"change_price_pct",product_id,pct:Number(r.value)}));
  if(r.type==="price") return items.map(p=>({...base,op:"set_price",product_id:p.product_id,price:revisedPrice(r,p)}));
  if(r.type==="remove") return items.map(p=>({...base,op:"remove_product",product_id:p.product_id}));
  if(r.type==="product"){
    const product={product_id:r.itemId,name:r.name.trim(),occasion:r.occasion,
      slots:r.slots.map(k=>{const [day_type,meal]=k.split("/");return {day_type,meal:meal||null};}),
      months:r.months.length?r.months:null,unit:r.unit.trim(),serves:Number(r.serves),audience:r.audience,
      price:Number(r.price),price_basis:"included",qty_rule:Number(r.serves)===1?"per_person":"per_serves",qty_max:null,
      grade:"assumption",source_id:null};
    if(r.original && !r.edited) return [{...base,op:"add_product",product:clone(r.original)}];
    return [{...base,op:"add_product",product}];
  }
  return [{...base,op:"add_promotion",promotion:{promo_id:r.itemId,name:r.name.trim(),benefit:{type:r.benefit,value:r.benefit==="gift"?r.gift.trim():Number(r.value)},
    applies_to:r.scope==="all"?null:r.ids,conditions:{day_type:r.day||null,meal:r.meal||null,party_min:r.party?Number(r.party):null,stay:null},period:r.from?{from:r.from,to:r.to}:null,grade:"assumption",source_id:null}}];
}
function definition(id){
  const pricesOnly=state.changes.every(c=>c.type==="price");
  return {format_version:1,scenario_id:id,name:state.name.trim(),kind:state.side==="out"?"competitor":pricesOnly?"our_price":"our_promo",
    description:state.changes.map(shortChange).join(" / "),changes:state.changes.flatMap(changeOps),note:"화면의 시나리오 만들기에서 만든 상황이다. 값은 가정이다."};
}

const $ = id => document.getElementById(id);
const esc = x => String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const paths={
 upload:'<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5m-7 10v-7m-3 3 3-3 3 3"/>',
 info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-9v.1"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',minus:'<path d="M5 12h14"/>',arrow:'<path d="M4 12h15m-6-6 6 6-6 6"/>',
 compare:'<path d="M3 7h16m-4-4 4 4-4 4M21 17H5m4-4-4 4 4 4"/>',
 sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
 moon:'<path d="M20 14a8.5 8.5 0 0 1-10-10 8.5 8.5 0 1 0 10 10Z"/>',
 check:'<path d="m5 12 4 4L19 6"/>',checked:'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
 building:'<path d="M3 20h18M5 20V8l7-4 7 4v12M9 9v2m6-2v2m-6 3v2m6-2v2m-4 4v-3h2v3"/>',
 hotel:'<path d="M3 20h18M4 20V9h8v11m0-15h7v15M7 12h2m-2 4h2m6-8h1m-1 4h1m-1 4h1"/>',
 clipboard:'<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M8.5 12h7m-7 4h5"/>',
 price:'<path d="m3 12 9-9h7l2 2v7l-9 9z"/><circle cx="16.5" cy="7.5" r="1.2"/>',
 gift:'<path d="M3 9h18v4H3zM5 13v8h14v-8m-7-4v12M12 9C9 9 5 8 6 5s5-2 6 4Zm0 0c3 0 7-1 6-4s-5-2-6 4Z"/>',
 dish:'<path d="M3 16h18M5 15a7 7 0 0 1 14 0M12 7V5m-2 0h4M3 19h18"/>',
 edit:'<path d="m4 16 11-11 4 4L8 20l-5 1zM13 7l4 4"/>',
 trash:'<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v7m4-7v7"/>',
 close:'<path d="m6 6 12 12M6 18 18 6"/>',chevron:'<path d="m5 9 7 7 7-7"/>',
 sliders:'<path d="M3 7h6m5 0h7M3 17h11m5 0h2"/><circle cx="11.5" cy="7" r="2.5"/><circle cx="16.5" cy="17" r="2.5"/>',
 stack:'<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M7 5h10M9 2.5h6"/>',
 replay:'<path d="M5 9a8 8 0 1 1 0 7m0-12v5h5"/>'};
const icon = key => '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24">'+paths[key]+'</svg>';
document.querySelectorAll("[data-icon]").forEach(n=>n.outerHTML=icon(n.dataset.icon));
const btn=(label,cls,action,extra="")=>'<button type="button" class="'+cls+'" data-action="'+action+'" '+extra+'>'+label+'</button>';
function chips(options,selected,action){
  return Object.entries(options).map(([key,label])=>btn(esc(label),"chip",action,'data-key="'+esc(key)+'" aria-pressed="'+selected.includes(key)+'"')).join("");
}
const warning = message => '<p class="warning">'+esc(message)+'</p>';
const setText=(id,value)=>$(id).textContent=value;
const rowsHTML=rows=>rows.map(([key,value])=>'<dt>'+esc(key)+'</dt><dd>'+esc(value)+'</dd>').join("");
const toggle=(list,key)=>list.includes(key)?list.filter(x=>x!==key):[...list,key];
const editorModal=$("modal");
// 이름 끝 글자의 받침으로 조사를 고른다 (예: josa("금룡 인상","을","를"))
const josa=(w,a,b)=>{const c=String(w).trim().slice(-1).charCodeAt(0);return (c>=0xAC00&&c<=0xD7A3&&(c-0xAC00)%28)?a:b;};
let draft=null, editingId=null, confirmAction=null, timer=null;
function modal(title,body,footer=""){
  setText("modal-title",title);$("dialog-body").innerHTML=body;$("dialog-foot").innerHTML=footer;
  if(!editorModal.open) editorModal.showModal();
  $("dialog-body").scrollTop=0;
}
function closeModal(){editorModal.close();}
$("close").onclick=closeModal;
editorModal.addEventListener("close",()=>{if(editorModal.open) return;draft=null;editingId=null;confirmAction=null;if(timer){clearInterval(timer);timer=null;}});
function confirmChoice(title,message,label,action){
  confirmAction=action;
  modal(title,message?'<p>'+esc(message)+'</p>':'',btn("취소","secondary","cancel")+btn(esc(label),"primary","confirm"));
}
function renderPresets(){
  renderLibraryPreview();
}
function renderSetup(){
  if($("name").value!==state.name) $("name").value=state.name;
  $("side").innerHTML=["in","out"].map(side=>{
    const on=side===state.side, count=Object.values(catalog().venues).filter(v=>v.is_competitor===(side==="out")).length;
    return btn(icon(side==="in"?"building":"hotel")+(side==="in"?"워커힐 안":"워커힐 밖")+' <small>'+(side==="in"?"":"경쟁 ")+count+'곳</small>'+(on?icon("checked"):'<i class="radio"></i>'),"side-card","side",'data-key="'+side+'" aria-pressed="'+on+'"');
  }).join("");
  setText("change-count",state.changes.length+"개");
  $("changes").innerHTML=state.changes.map(c=>{
    const label=kinds[c.type],summary=shortChange(c),p=selectedMenus(c)[0];
    let detail=label[0];
    let detailHTML=null;
    if(c.type==="price" && p){detail=p.name+" "+won(p.price)+" → "+previewPrice(c,p);detailHTML=esc(p.name)+' <span class="nw">'+esc(won(p.price)+" → "+previewPrice(c,p))+"</span>";}
    if(c.type==="product") detail=c.unit+" "+won(c.price);
    return '<div class="change-row"><span class="item-icon">'+icon(label[2])+'</span><div class="change-text"><strong>'+esc(summary)+'</strong><small>'+(detailHTML||esc(detail))+'</small></div>'+
      btn(icon("edit"),"icon-btn","edit",'aria-label="'+esc(summary)+' 고치기" title="고치기" data-key="'+c.id+'"')+
      btn(icon("trash"),"icon-btn","delete",'aria-label="'+esc(summary)+' 지우기" title="지우기" data-key="'+c.id+'"')+'</div>';
  }).join("")||'<p class="empty">아직 바꿀 것이 없습니다.</p>';
}
function renderAudience(){
  setText("people-count",state.people.length+"명");
  setText("all-people",state.people.length===catalog().people.length?"모두 해제":"모두 고르기");
  $("people").innerHTML=catalog().people.map(p=>{
    const on=state.people.includes(p.id),a=p.party;
    const path=p.icon||p.id;
    const group=p.group+" · 성인 "+a.adults+"명"+(a.children?", 어린이 "+a.children+"명":"");
    return btn('<img src="'+STATIC+'icons/personas/'+esc(path)+'.svg" alt=""><strong>'+esc(p.name)+'</strong><small>'+esc(group)+'</small>'+(on?'<span class="tick">'+icon("checked")+'</span>':""),"person","person",'data-key="'+esc(p.id)+'" aria-pressed="'+on+'"');
  }).join("");
  $("days").innerHTML=chips(dayLabels,state.days,"day");
  $("occasions").innerHTML=chips(visitLabels,state.occasions,"visit");
  $("period-mode").innerHTML=chips({year:"일 년 전체",single:"한 달",range:"이어진 여러 달"},[state.period],"period");
  const selected=span();
  $("months").innerHTML=state.period==="year"?"":months.map(m=>{
    const edge=m===state.start || m===state.end,on=selected.includes(m)||edge;
    return btn(m+"월","month"+(edge?" edge":""),"month",'data-key="'+m+'" aria-pressed="'+on+'"');
  }).join("");
  setText("period-label",periodText());
  const hints={year:"달을 나누지 않고 일 년 전체를 한 번에 계산합니다.",single:state.extendOnNext?"끝 달을 누르면 기간으로 늘어납니다.":"한 달을 누르거나, 이어서 끝 달을 눌러 기간을 고릅니다.",
    range:state.start!=null && state.end==null?"끝 달을 누릅니다. 더 이른 달이면 다음 해까지 이어집니다.":"시작 달과 끝 달을 차례로 누릅니다. 결과는 달마다의 합입니다."};
  setText("month-hint",hints[state.period]);
}
function renderSummary(){
  const counts=visitCount(),errors=problems();
  setText("sum-name",state.name.trim()||"이름 없음");
  setText("sum-side",sideLabel()+" · 바꿀 것 "+state.changes.length+"개");
  $("sum-changes").innerHTML=state.changes.map(c=>'<li>'+esc(shortChange(c))+'</li>').join("");
  $("sum-details").innerHTML=rowsHTML([["페르소나",state.people.length+"명"],["방문 조건",counts.conditions+"가지"],["기간",periodText()]]);
  setText("visits",number(counts.each));
  // 11-21 실험(ux-ui-baseline): 실행할 수 있는지를 요약 맨 위에 한 줄로. 막히면 단추를 끄고 이유와 갈 곳을 바로 옆에
  const ans=answerCount(), replay=state.answer==="replay", missing=missingParts();
  const blocked=replay && state.changes.length>0 && ans.fresh>0 && !missing.length;
  const rs=$("run-state");
  rs.className="run-state "+(missing.length?"wait":blocked?"stop":"ok");
  rs.innerHTML=missing.length?"채울 것 "+missing.length+"가지: "+missing.map(esc).join(", ")
    :blocked?"이 PC에서는 실행할 수 없습니다 · AI 응답이 없는 방문 "+number(ans.fresh)+"건"
    :(replay?"실행할 수 있습니다 · 저장된 AI 응답으로 돌립니다":"실행할 수 있습니다 · 새로 받을 AI 응답 "+number(ans.fresh)+"건");
  $("calls").hidden=true;
  const tips=[];
  if(blocked) tips.push('<div class="stop-help"><p>바꾸기 전 시나리오는 실행할 수 있습니다. 이 입력은 파일로 내려받아 담당자에게 넘길 수 있습니다.</p><div class="stop-actions">'+
    (state.loadedHasResult&&state.modified?btn("원래대로","secondary small-btn","revert"):"")+
    btn(icon("upload")+"시나리오 파일 내려받기","secondary small-btn","export-def")+'</div></div>');
  $("issues").innerHTML=tips.join("")+notices().map(warning).join("");
  $("reset").disabled=isBlank();
  $("run").disabled=$("run-mobile").disabled=errors.length>0||blocked;
  $("mobile-status").innerHTML=missing.length?"채울 것 "+missing.length+"가지":blocked?'<button type="button" class="text-button" data-action="to-summary">실행할 수 없음 · 이유 보기</button>':"예상 방문 "+number(counts.each)+"건씩";
  renderSteps();
}
// 진행 단계 (11-21): 상자마다 한 단계. 채워지면 번호 동그라미에 색, 아직인 첫 단계는 테두리만 진하게. 누르면 그 상자로 간다
// 스낵바: 화면 아래에 잠깐 뜨는 알림 + 되돌리기 (6초)
let snackTimer=null;
function snack(text,undo){
  let el=$("snack");if(!el){el=document.createElement("div");el.id="snack";el.setAttribute("role","status");W.appendChild(el);}
  el.innerHTML='<span>'+esc(text)+'</span>'+(undo?'<button type="button">되돌리기</button>':'');el.hidden=false;
  if(undo) el.querySelector("button").onclick=()=>{undo();el.hidden=true;};
  const hide=()=>{if(el.matches(":hover,:focus-within")){snackTimer=setTimeout(hide,2000);return;}el.hidden=true;};
  clearTimeout(snackTimer);snackTimer=setTimeout(hide,10000);
}
function renderSteps(){
  const done=[
    Boolean(state.name.trim()) && state.changes.length>0 && state.changes.every(c=>!rowErrors(c).length),
    state.people.length>0,
    state.days.length>0 && state.occasions.length>0 && (state.period==="year" || span().length>0),
    false];
  const names=["시나리오 설정","페르소나","방문 조건과 기간","결과"], now=done.indexOf(false);
  $("steps").innerHTML=names.map((n,i)=>(i?'<li class="rule" aria-hidden="true"></li>':'')+
    '<li class="'+(done[i]?'done':'')+(i===now?' now':'')+'"'+(i===now?' aria-current="step"':'')+'>'+
    (i<3?'<button type="button" data-step="'+i+'"':'<span')+' aria-label="'+(i+1)+'단계 '+n+(done[i]?' 완료':'')+'"><b>'+(i+1)+'</b>'+n+(i<3?'</button>':'</span>')+'</li>').join("");
}
document.addEventListener("click",e=>{if(e.target.closest('[data-action="to-summary"]')){document.querySelector(".summary").scrollIntoView({behavior:"smooth",block:"start"});return;}const b=e.target.closest("[data-step]");if(b) document.querySelectorAll(".form-column > .panel")[Number(b.dataset.step)]?.scrollIntoView({behavior:"smooth",block:"start"});});
function render(){
  const active=document.activeElement?.closest("button[data-action][data-key]");
  renderPresets();renderSetup();renderAudience();renderSummary();
  $("source").value=state.source;$("answer").value=state.answer;
  $("prompt").innerHTML=catalog().prompts.map(p=>'<option value="'+esc(p)+'">'+esc(p)+(p===catalog().default_prompt?" (팀 기본)":"")+'</option>').join("");
  $("prompt").value=state.prompt;
  setText("advanced-label",catalog().data_label+" · "+(state.answer==="replay"?"AI 새로 부르지 않음":"AI 새로 부름"));
  if(active && !active.isConnected){
    const target=[...document.querySelectorAll("button[data-action][data-key]")].find(b=>b.dataset.action===active.dataset.action && b.dataset.key===active.dataset.key);
    target?.focus({preventScroll:true});
  }
}
function chooseMonth(m){
  if(state.period==="single"){
    if(state.extendOnNext && m!==state.start){state.period="range";state.end=m;state.extendOnNext=false;}
    else{state.start=m;state.end=m;state.extendOnNext=true;}
  }
  else if(state.start==null || state.end!=null){state.start=m;state.end=null;}
  else state.end=m;
}
function setTheme(theme){
  document.documentElement.dataset.theme=theme;
  document.querySelectorAll("button[data-theme]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.theme===theme)));
  try{localStorage.setItem("wh-theme",theme);}catch{}
}
function clearDraft(){
  state=initial(state.source);render();$("name").focus();
}
const isBlank=()=>JSON.stringify({...state,source:null})===JSON.stringify({...initial(state.source),source:null});
function requestBlank(){
  if(isBlank()){clearDraft();return;}
  confirmChoice("입력한 내용을 모두 지울까요?","저장된 시나리오와 결과는 남습니다.","지우기",clearDraft);
}
$("reset").onclick=requestBlank;
$("name").oninput=e=>{state.name=e.target.value;state.nameEdited=true;state.modified=true;renderSummary();};
$("all-people").onclick=()=>{markEdited();state.people=state.people.length===catalog().people.length?[]:catalog().people.map(p=>p.id);render();};
$("answer").onchange=e=>{markEdited();state.answer=e.target.value;render();};
$("prompt").onchange=e=>{markEdited();state.prompt=e.target.value;render();};
$("source").onchange=e=>{
  const source=e.target.value;e.target.value=state.source;
  const swap=()=>{state=initial(source);render();};
  confirmChoice("사용할 자료를 바꿀까요?","지금 입력한 내용은 지워집니다.","자료 바꾸기",swap);
};
$("add").onclick=()=>modal("무엇을 바꿀까요?",'<div class="type-list">'+Object.entries(kinds).map(([type,[name,desc,ic]])=>btn('<span class="item-icon">'+icon(ic)+'</span><span><strong>'+name+'</strong><small>'+desc+'</small></span>',"","choose-type",'data-key="'+type+'"')).join("")+'</div>');
document.querySelectorAll("button[data-theme]").forEach(b=>b.onclick=()=>setTheme(b.dataset.theme));

function field(label,control,description=""){
  return '<label class="field"><span>'+esc(label)+'</span>'+control+(description?'<small>'+esc(description)+'</small>':"")+'</label>';
}
const pair=(a,b)=>'<div class="grid-two">'+a+b+'</div>';
const input=(key,type="text",attrs="")=>'<input type="'+type+'" data-edit="'+key+'" value="'+esc(draft[key])+'" '+attrs+'>';
function select(key,options){
  return '<select data-edit="'+key+'">'+Object.entries(options).map(([id,label])=>'<option value="'+esc(id)+'"'+(String(draft[key])===id?" selected":"")+'>'+esc(label)+'</option>').join("")+'</select>';
}
function choiceArea(label,options,selected,action){
  return '<div class="field" role="group" aria-label="'+esc(label)+'"><span>'+esc(label)+'</span><div class="chips">'+chips(options,selected,action)+'</div></div>';
}
function menuTable(reference=false){
  const r=draft,rows=venue(r.venueId).products, price=r.type==="price"&&!reference;
  const scope=reference||r.type==="remove"?"":choiceArea("적용 메뉴",{all:"모든 메뉴",some:"메뉴 고르기"},[r.scope],"scope");
  const lines=rows.map(p=>{
    const chosen=r.scope==="all"||r.ids.includes(p.product_id);
    const name=esc(p.name)+'<small>'+esc(p.unit)+'</small>';
    const checkbox=!reference && r.scope==="some"?'<input type="checkbox" data-menu="'+esc(p.product_id)+'" '+(chosen?"checked":"")+'>':"";
    const newInput='<input type="number" min="1" data-price="'+esc(p.product_id)+'" value="'+esc(r.prices[p.product_id])+'" aria-label="'+esc(p.name)+' 새 가격">';
    return '<tr><td>'+(checkbox?'<label>'+checkbox+'<span>'+name+'</span></label>':name)+'</td><td class="num">'+esc(won(p.price))+'</td>'+
      (price?'<td class="num" data-preview="'+esc(p.product_id)+'">'+(!chosen?"—":r.mode==="set"?newInput:esc(previewPrice(r,p)))+'</td>':"")+'</tr>';
  }).join("");
  return scope+'<div class="table-scroll"><table class="menu-table"><thead><tr><th>메뉴 · 단위</th><th class="num">지금 가격</th>'+(price?'<th class="num">바꾼 뒤 가격</th>':"")+'</tr></thead><tbody>'+lines+'</tbody></table></div>';
}
function priceFields(){
  const r=draft;
  const mode=field("바꾸는 방법",select("mode",{pct:"퍼센트",amount:"금액 더하기·빼기",set:"새 가격 적기"}));
  return (r.mode==="set"?mode:pair(mode,field(r.mode==="pct"?"바꿀 비율 (%)":"더하거나 뺄 금액 (원)",input("value","number",'step="1"'),"내릴 때는 −10처럼 적습니다.")))+menuTable();
}
function promoFields(){
  const r=draft, gifts=r.benefit==="gift";
  return field("프로모션 이름",input("name","text",'placeholder="예: 주말 어린이 반값"'))+
    pair(field("혜택",select("benefit",{discount_pct:"퍼센트 할인",discount_amount:"금액 할인",gift:"증정"})),
      gifts?field("증정품",input("gift","text",'placeholder="예: 웰컴 음료 한 잔"')):field(r.benefit==="discount_pct"?"할인율 (1~99%)":"주문 1회 할인 금액 (원)",input("value","number",'min="1" step="1"')))+
    '<p class="hint">'+(gifts?"증정은 고객이 메뉴를 고를 때 혜택이 됩니다. 증정품 비용은 가상 매출에 반영되지 않습니다.":"할인은 주된 주문에 한 번 적용합니다. 추가 음료 등은 할인에서 빠집니다.")+'</p>'+
    (venue(r.venueId).occasions.includes("meal")?pair(field("적용 요일",select("day",{"":"모두",...dayLabels})),field("끼니",select("meal",{"":"모두",lunch:"점심",dinner:"저녁"}))):field("적용 요일",select("day",{"":"모두",...dayLabels})))+
    field("최소 일행 수 (선택)",input("party","number",'min="1" placeholder="인원 제한 없음"'))+
    pair(field("시작일 (선택)",input("from","date")),field("종료일 (선택)",input("to","date")))+menuTable();
}
function productFields(){
  const r=draft,v=venue(r.venueId),slots={};
  for(const [day,dayName] of Object.entries(dayLabels)){
    const meals=r.occasion==="meal"?{lunch:"점심",dinner:"저녁",...(r.slots.some(s=>s.endsWith("/breakfast"))?{breakfast:"조식"}:{})}:{"":""};
    for(const [meal,mealName] of Object.entries(meals)) slots[day+"/"+meal]=(dayName+" "+mealName).trim();
  }
  const supported=v.months||months;
  return pair(field("메뉴 이름",input("name","text",'placeholder="예: 겨울 특선 코스"')),field("이용 상황",select("occasion",Object.fromEntries(v.occasions.map(k=>[k,occasionLabels[k]])))))+
    choiceArea("파는 때",slots,r.slots,"slot")+
    choiceArea("파는 달 (비우면 업장과 같음)",Object.fromEntries(supported.map(m=>[m,m+"월"])),r.months.map(String),"sale-month")+
    pair(field("판매 단위",input("unit","text",'placeholder="예: 2인 세트"')),field("몇 명분",input("serves","number",'min="1"')))+
    pair(field("대상",select("audience",{adult:"성인",child:"어린이",all:"구분 없음"})),field("세금 포함 가격 (원)",input("price","number",'min="1"')))+
    '<details class="menu-ref"><summary>이 업장의 기존 메뉴 '+v.products.length+'개 보기</summary>'+menuTable(true)+'</details>';
}
function editContent(reset=false){
  const pos=$("dialog-body").scrollTop;
  const venueField=field("업장",select("venueId",Object.fromEntries(sideVenues().map(([id,v])=>[id,v.name]))));
  const types={price:priceFields,promo:promoFields,product:productFields,remove:()=>'<p class="hint">뺄 메뉴를 골라 주세요.</p>'+menuTable()};
  modal(kinds[draft.type][0],'<div class="editor">'+venueField+types[draft.type]()+'<div id="edit-issues" aria-live="polite"></div></div>',
    btn("취소","secondary","cancel")+btn(editingId?"고친 내용 적용":"시나리오에 추가","primary","apply",'id="apply" aria-describedby="edit-issues"'));
  if(!reset) $("dialog-body").scrollTop=pos;
  editStatus();
}
function editStatus(){
  const errors=rowErrors(draft);
  $("edit-issues").innerHTML=errors.map(warning).join("");
  $("apply").disabled=errors.length>0;
  if(draft.type==="price" && draft.mode!=="set"){
    document.querySelectorAll("[data-preview]").forEach(cell=>{
      const p=venue(draft.venueId).products.find(x=>x.product_id===cell.dataset.preview);
      cell.textContent=draft.scope==="all"||draft.ids.includes(p.product_id)?previewPrice(draft,p):"—";
    });
  }
}
function edit(type,id){
  editingId=id||null;
  draft=id?clone(state.changes.find(x=>x.id===id)):fresh(type);
  editContent(true);
}
$("dialog-body").addEventListener("input",e=>{
  const target=e.target,key=target.dataset.edit;
  if(!draft||target.tagName==="SELECT"||target.type==="checkbox") return;
  if(target.dataset.price) draft.prices[target.dataset.price]=target.value;
  else if(key) draft[key]=target.value;
  editStatus();
});
$("dialog-body").addEventListener("change",e=>{
  if(!draft) return;
  const t=e.target,key=t.dataset.edit;
  if(t.dataset.menu){draft.ids=toggle(draft.ids,t.dataset.menu);editContent();return;}
  if(t.tagName!=="SELECT") return;
  if(key==="venueId"){
    const old=draft;draft={...fresh(old.type,t.value),id:old.id};draft.edited=true;
  }else{
    draft[key]=t.value;
    if(key==="occasion") draft.slots=[];
    if(key==="benefit") draft.value=t.value==="discount_amount"?10000:10;
    if(key==="mode") draft.value=t.value==="amount"?5000:10;
  }
  editContent();
});
function saveEdit(){
  if(!draft || rowErrors(draft).length) return;
  const index=state.changes.findIndex(c=>c.id===editingId);
  if(index<0 || JSON.stringify(state.changes[index])!==JSON.stringify(draft)){
    draft.edited=true;markEdited();
    if(index<0) state.changes.push(draft);else state.changes[index]=draft;
  }
  closeModal();render();
}
function changeSide(side){
  if(side===state.side) return;
  const swap=()=>{markEdited();state.side=side;state.changes=[];state.preset=null;render();};
  if(state.changes.length) confirmChoice((side==="out"?"워커힐 밖":"워커힐 안")+"으로 바꿀까요?","추가한 바꿀 것 "+state.changes.length+"개가 지워집니다.","바꾸기",swap);
  else swap();
}
function usePreset(key){
  const activate=()=>{loadPreset(key);render();};
  if(state.changes.length && (!state.preset || state.name!==catalog().presets[state.preset].name || state.changes.some(c=>c.edited))){
    confirmChoice("‘"+catalog().presets[key].name+"’"+josa(catalog().presets[key].name,"을","를")+" 불러올까요?","지금 입력한 내용은 지워집니다.","불러오기",activate);
  } else activate();
}
document.addEventListener("click",e=>{
  const button=e.target.closest("[data-action]");
  if(!button || button.disabled) return;
  const {action,key}=button.dataset;
  if(action==="cancel"){closeModal();return;}
  if(action==="confirm"){const callback=confirmAction;closeModal();callback?.();return;}
  if(action==="preset"){usePreset(key);return;}
  if(action==="side"){changeSide(key);return;}
  if(action==="choose-type"){edit(key);return;}
  if(action==="edit"){edit(null,key);return;}
  if(action==="apply"){saveEdit();return;}
  if(action==="delete"){
    const item=state.changes.find(c=>c.id===key);
    const at=state.changes.indexOf(item);markEdited();state.changes=state.changes.filter(c=>c.id!==key);render();$("add").focus();
    snack("‘"+shortChange(item)+"’"+josa(shortChange(item),"을","를")+" 지웠습니다",()=>{state.changes.splice(at,0,item);render();});return;
  }
  if(["scope","slot","sale-month"].includes(action)){
    if(action==="scope") draft.scope=key;
    if(action==="slot") draft.slots=toggle(draft.slots,key);
    if(action==="sale-month") draft.months=toggle(draft.months,Number(key)).sort((a,b)=>a-b);
    editContent();return;
  }
  if(["person","day","visit","month","period"].includes(action)){
    if(action==="period" && key===state.period && !state.extendOnNext) return;
    markEdited();
    if(action==="period"){state.period=key;state.start=state.end=null;state.extendOnNext=false;}
    if(action==="month") chooseMonth(Number(key));
    const fieldName={person:"people",day:"days",visit:"occasions"}[action];
    if(fieldName) state[fieldName]=toggle(state[fieldName],key);
    render();return;
  }
  if(action==="history-result"){closeModal();act("open_result",{result_id:key});return;}
  
  if(action==="compare") compare();
});

// v4: "저장된 시나리오" 목록 하나 (준비된 것 + 결과가 있는 것), 파일은 우리 내보내기 파일(.zip)만 받는다.
// 결과 있음/없음은 실제 화면에서는 이 PC 에 실행 폴더가 있는지로 가린다. 시안에서는 runs(브라우저 저장)와 presetRan 으로 흉내 낸다.
const fingerprint = x => JSON.stringify(stable(x));
function runFor(changes, source=state.source){
  return runs.find(r=>r.source===source && fingerprint(r.config.changes)===fingerprint(changes));
}
function libraryEntries(){
  const ranked=Object.keys(presetMeta);
  const presets=Object.entries(catalog().presets).sort(([a],[b])=>(ranked.includes(a)?ranked.indexOf(a):Infinity)-(ranked.includes(b)?ranked.indexOf(b):Infinity));
  const team=presets.map(([id,p])=>{
    const run=runFor(p.changes);
    return entryInfo({key:"team/"+id,id,kind:"team",scenario:p,run,hasResult:Boolean(run)||presetRan.has(id),srcLabel:"기본 제공"});
  });
  const teamPrints=new Set(presets.map(([,p])=>fingerprint(p.changes)));
  const mine=runs.filter(r=>r.source===state.source && !teamPrints.has(fingerprint(r.config.changes)))
    .map(r=>entryInfo({key:"run/"+r.id,id:r.id,kind:"run",scenario:r.config,run:r,hasResult:true,
      srcLabel:r.from==="file"?r.date+" 파일에서 가져옴":r.date+" 실행"}));
  // 결과 있는 것을 앞에, 그 안에서는 최근 것을 앞에
  return [...mine,...team].sort((a,b)=>Number(b.hasResult)-Number(a.hasResult));
}
function entryInfo(e){
  const s=e.scenario, outside=s.kind==="competitor", first=s.changes[0];
  const labels={set_price:"가격 변경",change_price_pct:"가격 변경",add_product:"한정 메뉴",remove_product:"메뉴 빼기",add_promotion:"프로모션"};
  const types=[...new Set(s.changes.map(op=>labels[op.op]))].join("·");
  const meta=e.kind==="team"?presetMeta[e.id]:null;
  const matched=Object.entries(presetMeta).find(([key])=>catalog().presets[key]?.changes[0].venue_id===first?.venue_id);
  const venueNames=[...new Set(s.changes.map(op=>venue(op.venue_id)?.name).filter(Boolean))];
  // 카드에는 바꿀 것 요약만 보인다 (처음 둘, 나머지는 "외 n개")
  const rows=definitionRows(s).map(shortChange);
  const changeLines=rows.slice(0,2).concat(rows.length>2?["외 "+(rows.length-2)+"개"]:[]);
  return {...e,title:s.name,side:outside?"워커힐 밖":"워커힐 안",types,venueNames,changeLines,
    art:meta?.[0]||matched?.[1][0]||(outside?"hall-competitor":"hall-walkerhill")};
}
// 실행한 때: 실제 화면에서는 실행 폴더가 만들어진 때. 시안의 준비된 결과(presetRan)는 가정한 때를 쓴다
const ranAt=e=>e.run?.date||(e.hasResult?"11-20 17:30":"");
const statusTag=e=>e.hasResult?'<span class="status has"><i></i>결과 있음 · '+esc(ranAt(e))+'</span>':'<span class="status none"><i></i>실행 전</span>';
const resultLink=e=>e.hasResult?btn('결과 보기 '+icon("arrow"),"result-link","open-result",'data-key="'+esc(e.key)+'" aria-label="'+esc(e.title)+' 결과 보기"'):"";
function card(e){
  const on=state.loadedKey===e.key;
  return '<div class="preset '+(e.side==="워커힐 밖"?"side-out":"side-in")+'" aria-pressed="'+on+'">'+(on?'<span class="selected">'+icon("check")+'</span>':'')+
    btn(statusTag(e)+'<strong>'+esc(e.title)+'</strong>'+e.changeLines.map(t=>'<small>'+esc(t)+'</small>').join("")+'<img src="'+STATIC+'icons/buildings/'+e.art+'.svg" alt="">',
      "preset-main","library-load",'data-key="'+esc(e.key)+'"')+resultLink(e)+'</div>';
}
function row(e){
  const on=state.loadedKey===e.key;
  return '<div class="library-row"'+(on?' aria-current="true"':'')+'>'+
    btn('<img src="'+STATIC+'icons/buildings/'+e.art+'.svg" alt=""><span class="entry-copy"><span class="row-top">'+statusTag(e)+'<strong>'+esc(e.title)+'</strong></span><small>'+esc(e.changeLines.join(" · "))+'</small></span>',
      "library-result","library-load",'data-key="'+esc(e.key)+'"')+resultLink(e)+'</div>';
}
function renderLibraryPreview(){
  const entries=libraryEntries(), chosen=entries.find(e=>e.key===state.loadedKey);
  // 고른 것이 앞 네 칸 밖에 있을 때만 맨 앞으로 가져온다 (보이는 카드가 자리를 옮기지 않게)
  const top=chosen && entries.indexOf(chosen)>3?[chosen,...entries.filter(e=>e!==chosen)]:entries;
  $("presets").innerHTML=top.slice(0,4).map(card).join("");
  setText("browse-library","");$("browse-library").insertAdjacentHTML("beforeend","전체 "+entries.length+"개 보기 "+icon("arrow"));
  const fb=$("import-feedback");
  if(state.loadedKey && state.loadedHasResult && state.modified){
    // 불러온 결과 있는 시나리오를 고쳤을 때: 되돌아갈 길을 같은 자리에
    fb.dataset.key=state.loadedKey;
    fb.innerHTML='<p class="file-notice edited">'+icon("edit")+'<span>고친 내용은 아직 결과가 없습니다.</span></p>';
  }else if(fb.dataset.key!==state.loadedKey || state.modified){fb.replaceChildren();delete fb.dataset.key;}
}
function openLibrary(){
  modal("전체 시나리오",'<p class="hint" style="margin:-6px 0 10px">누르면 아래 입력란에 채워집니다.</p><div class="library-tools"><input type="search" id="library-query" aria-label="시나리오 검색" placeholder="이름이나 업장으로 찾기"></div><p id="found-count" class="hint" aria-live="polite"></p><div id="library-results"></div>');
  function update(){
    const q=$("library-query").value.trim().toLocaleLowerCase();
    const list=libraryEntries().filter(e=>[e.title,e.side,e.types,e.srcLabel,...e.venueNames].join(" ").toLocaleLowerCase().includes(q));
    setText("found-count",list.length+"개 · 결과 있음 "+list.filter(e=>e.hasResult).length+"개");
    $("library-results").innerHTML=list.map(row).join("")||'<p class="empty">'+(q?'‘'+esc($("library-query").value.trim())+'’에 맞는 시나리오가 없습니다. 이름이나 업장 이름으로 찾아 주세요.':'아직 시나리오가 없습니다.')+'</p>';
  }
  $("library-query").oninput=update;update();$("library-query").focus();
}
function applyEntry(e,message){
  const apply=()=>{
    if(editorModal.open) closeModal();
    // 결과가 있으면 방문 조건(누가·언제·고급 설정)은 그 실행에서, 이름과 바꿀 것은 시나리오 파일에서 채운다
    if(e.run){state=clone(e.run.input);fillDefinition(e.run.config,e.kind==="team"?e.id:null);}
    else{
      // 결과가 있는 준비된 시나리오는 그 결과를 받을 때의 조건(누가·언제)도 채운다. 실행 전이면 누가·언제는 사용자가 고른다
      if(e.hasResult){const f=fullScope();Object.assign(state,{people:f.people,days:f.days,occasions:f.occasions,period:f.period,start:f.start,end:f.end});}
      fillDefinition(e.scenario,e.kind==="team"?e.id:null);
    }
    state.loadedKey=e.key;state.loadedHasResult=e.hasResult;state.modified=false;
    state.originName=state.name;state.nameEdited=false;
    render();
    const fb=$("import-feedback");fb.dataset.key=e.key;
    fb.innerHTML='<p class="file-notice">'+icon("checked")+esc(message||("‘"+e.title+"’"+josa(e.title,"을","를")+" 불러왔습니다."+(e.hasResult?" 고치지 않으면 결과를 바로 볼 수 있습니다.":"")))+'</p>';
  };
  const dirty=state.modified||(!state.loadedKey&&(state.name||state.changes.length));
  if(dirty) confirmChoice("‘"+e.title+"’"+josa(e.title,"을","를")+" 불러올까요?","지금 입력한 내용은 지워집니다.","불러오기",apply);
  else apply();
}
$("browse-library").onclick=openLibrary;
document.addEventListener("click",ev=>{
  const load=ev.target.closest('[data-action="library-load"]');
  if(load){const e=libraryEntries().find(x=>x.key===load.dataset.key);if(e) applyEntry(e);return;}
  const res=ev.target.closest('[data-action="open-result"]');
  if(res){
    const e=libraryEntries().find(x=>x.key===res.dataset.key);if(!e) return;
    if(editorModal.open) closeModal();
    if(e.run) act("open_result",{result_id:e.run.id});
  }
});

// 파일에서 불러오기: 결과 내보내기로 받은 .zip 하나. 비교 창의 "가져오기"와 같은 처리로 결과를 목록에 더하고, 이어서 입력을 채운다.
// 묶음 안의 모양(시안 가정, T130 에서 정한다): scenarios/ui-*.json (상황 정의) + runs/<실행>/run.json (방문 조건·달)
function insist(test,message){if(!test) throw new Error(message);}
function checkDefinition(p){
  insist(p && typeof p.name==="string" && p.name.trim(),"시나리오 이름이 없습니다.");
  insist(["our_price","our_promo","competitor"].includes(p.kind),"바꿀 쪽을 알 수 없습니다.");
  insist(Array.isArray(p.changes) && p.changes.length,"바꿀 것이 없습니다.");
  for(const [i,c] of p.changes.entries()){
    const v=Object.hasOwn(catalog().venues,c?.venue_id)?venue(c.venue_id):null;
    insist(v,(i+1)+"번째 바꿀 것 · 지금 자료에 없는 업장입니다.");
    insist(v.is_competitor===(p.kind==="competitor"),(i+1)+"번째 바꿀 것 · 다른 쪽 업장이 섞여 있습니다.");
  }
  const rows=definitionRows(p), errors=rows.flatMap(r=>rowErrors(r,rows.filter(o=>o!==r)));
  insist(!errors.length,errors[0]);
  return p;
}
async function readExport(file){
  insist(file.name.toLowerCase().endsWith(".zip"),"결과 내보내기로 받은 .zip 파일만 불러올 수 있습니다.");
  let zip;
  try{zip=await JSZip.loadAsync(file);}catch{throw new Error("파일을 열 수 없습니다. 내려받는 중에 손상되지 않았는지 확인해 주세요.");}
  const names=Object.keys(zip.files);
  const defName=names.find(n=>/^scenarios\/[^/]+\.json$/.test(n));
  insist(defName,"이 파일에는 시나리오가 들어 있지 않습니다. 결과 내보내기로 받은 파일인지 확인해 주세요.");
  insist(names.every(n=>!n.startsWith("/")&&!n.split("/").includes("..")),"이 파일은 안전하지 않은 내용이 있어 열지 않았습니다.");
  const config=checkDefinition(JSON.parse(await zip.file(defName).async("string")));
  const runFiles=names.filter(n=>/^runs\/[^/]+\/run\.json$/.test(n));
  if(!runFiles.length){const sc=zip.file("input.json");return {config,input:sc?JSON.parse(await sc.async("string")):null,defOnly:true};}
  const metas=await Promise.all(runFiles.map(async n=>JSON.parse(await zip.file(n).async("string"))));
  const m=metas[0];
  insist(m.source===state.source,"다른 자료("+(m.source==="team"?"팀 자료":"예시 사본")+")로 돌린 결과입니다. 고급 설정의 자료를 바꾼 뒤 불러오세요.");
  return {config,input:m.input};
}
function openFileHelp(){
  modal("파일에서 불러오기",'<div class="file-help"><p><b>결과 내보내기</b>로 받은 .zip 파일을 골라 주세요.</p>'+
    '<p class="hint">기본 데이터로 돌린 결과는 회사 안에서만 주고받으세요.</p></div>',
    btn("취소","secondary","cancel")+btn(icon("upload")+"파일 고르기","primary","pick-file"));
}
async function receiveFile(file){
  closeModal();
  const fb=$("import-feedback");
  fb.innerHTML='<p class="file-notice">'+icon("upload")+'파일을 읽는 중입니다.</p>';
  try{
    const {config,input,defOnly}=await readExport(file);
    if(defOnly){
      // 결과 없이 시나리오만 든 파일: 입력만 채운다 (담당자 PC 에서 이어서 실행)
      state=input?{...clone(input),source:state.source}:initial(state.source);fillDefinition(config);
      state.loadedKey=null;state.loadedHasResult=false;state.modified=true;render();
      fb.innerHTML='<p class="file-notice">'+icon("checked")+esc("‘"+config.name+"’"+josa(config.name,"을","를")+" 불러왔습니다. 아직 결과가 없는 시나리오입니다.")+'</p>';
      return;
    }
    const same=runs.find(r=>r.signature===signatureOf(config,input));
    const record=same||addRun(config,input,{from:"file",file:file.name});
    const e=libraryEntries().find(x=>x.run?.id===record.id) || libraryEntries().find(x=>x.kind==="team" && fingerprint(x.scenario.changes)===fingerprint(config.changes));
    applyEntry(e,(same?"이미 있는 결과는 건너뛰고 ":"결과를 저장된 시나리오에 더하고 ")+"‘"+config.name+"’"+josa(config.name,"을","를")+" 불러왔습니다.");
  }catch(err){
    fb.innerHTML=warning(file.name+" · "+err.message+" 지금 입력은 그대로 두었습니다.");
  }
}
$("open-file").onclick=openFileHelp;
document.addEventListener("click",e=>{if(e.target.closest('[data-action="pick-file"]')) $("import-file").click();});
$("import-file").onchange=e=>{const f=e.target.files[0];e.target.value="";if(f) receiveFile(f);};

  // ── 저장된 시나리오와 실행 (시안의 preview.js 를 대신한다. 시안은 실행을 브라우저에 흉내 냈다) ──
  const stable = value => Array.isArray(value) ? value.map(stable)
    : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(k => [k, stable(value[k])])) : value;
  // 결과 있는 시나리오: 파이썬이 결과 묶음(app/result_store.py)마다 하나씩 넘긴다. 모양은 시안의 runs 와 같다
  let runs = DATA.runs;
  // 새로 받을 AI 응답은 미리 셀 수 없다 (엔진에 세는 기능이 없다). 실행을 막지 않고 안내 한 줄만 둔다 (11-22 팀장 결정)
  function answerCount() {
    const each = visitCount().each;
    return { reuse: each * 2, fresh: 0 };
  }
  const baseNotices = notices;
  notices = () => {
    const found = baseNotices();
    if (state.source === "practice" && state.period !== "year") found.push("예시 사본의 저장된 답은 일 년 전체로 받은 것이라, 기간을 고르지 않고 일 년 전체로 돕니다.");
    if (state.answer === "replay") found.push("저장된 AI 응답이 없는 방문은 결과에서 빠집니다. 빠진 수는 결과 화면에 나옵니다.");
    return found;
  };
  // 머리의 "저장된 시나리오" 창: 결과 페이지와 같은 목록. 줄을 누르면 결과, 실행 전 줄은 입력을 채운다.
  // 비교·내려받기·지우기·파일에서 불러오기는 다음 작업에서 넣는다 (결과 페이지도 숨겨 둠)
  function condLine(e) { return e.run ? e.run.condition_line || "" : ""; }
  function compare() {
    const rows = libraryEntries().map(e => '<div class="sv-row"><span></span>' +
      btn('<span class="sv-top"><span class="status ' + (e.hasResult ? "has" : "none") + '"><i></i>' + (e.hasResult ? "결과 있음" : "실행 전") + "</span><strong>" + esc(e.title) + "</strong>" +
        (e.hasResult ? "<time>" + esc(ranAt(e)) + " 실행</time>" : "") + "</span><small>" + esc(e.hasResult ? condLine(e) : e.changeLines.join(" · ")) + "</small>",
        "sv-open", e.hasResult ? "open-result" : "library-load", 'data-key="' + esc(e.key) + '"') +
      (e.hasResult ? '<span class="sv-tools">' + btn(icon("edit"), "icon-btn", "library-load", 'data-key="' + esc(e.key) + '" title="고쳐서 새로 만들기" aria-label="고쳐서 새로 만들기"') + "</span>" : "<span></span>") + "</div>").join("");
    modal("저장된 시나리오", '<p class="hint" style="margin:-6px 0 10px">시나리오를 누르면 결과를 엽니다. 실행 전 시나리오는 입력란에 채워집니다.</p>' + (rows || '<p class="empty">아직 저장된 시나리오가 없습니다.</p>'));
  }
  $("compare").onclick = compare;
  // 실행: 상황 정의와 입력을 파이썬에 보낸다. 파이썬이 달마다 기본 시나리오와 바꾼 뒤를 돌리고, 끝나면 결과 페이지로 넘어간다.
  // 파이썬의 실행은 중간에 멈출 수 없어 창을 닫는 단추를 숨긴다
  function runPreview() {
    if (problems().length || editorModal.open) return;
    const passes = state.source === "practice" || state.period === "year" ? [null] : span();
    const label = passes[0] === null ? "일 년 전체" : passes.length === 1 ? passes[0] + "월" : passes[0] + "월~" + passes[passes.length - 1] + "월 (" + passes.length + "개월)";
    modal("시뮬레이션을 실행하는 중",
      '<p id="run-stage" aria-live="polite">' + esc(label) + " · 기본 시나리오와 바꾼 뒤를 차례로 돌립니다.</p>" +
      '<progress id="run-progress"></progress><p class="hint">끝나면 결과 화면으로 넘어갑니다. 이 창을 닫지 마세요.</p>');
    $("close").hidden = true;
    act("run", { definition: definition("draft"), input: clone(state) });
  }
  $("run").onclick = $("run-mobile").onclick = runPreview;
  // 고급 설정의 "사용할 데이터"와 "AI 새로 부르기"는 이 PC 의 자료와 설정을 따른다 (파이썬이 넘김)
  const baseRender = render;
  render = () => {
    baseRender();
    const data = catalog();
    const mode = $("data-mode");
    mode.replaceChildren(Object.assign(D.createElement("option"), { textContent: data.data_label }));
    setText("data-mode-note", data.data_note || "");
    const ai = $("answer").querySelector('option[value="ai"]');
    if (ai) ai.disabled = !data.can_call;
  };
  // 파이썬이 다시 그리며 넘긴 새 값: 실행 오류면 진행 창을 닫고 이유를 보인다
  let lastError = null;
  W.__whBuilder = next => {
    DATA = next;
    runs = next.runs;
    const error = next.run_error;
    if (error && error.at !== lastError) {
      lastError = error.at;
      if (editorModal.open) closeModal();
      $("close").hidden = false;
      modal("실행하지 못했습니다", "<p>" + esc(error.message) + "</p>", btn("입력으로 돌아가기", "secondary", "cancel"));
    }
    render();
  };
  // 페이지 안 이동 (건너뛰기·로고)
  R.addEventListener("click", e => {
    const target = e.target.closest("[data-scroll]");
    if (!target) return;
    e.preventDefault();
    R.getElementById(target.dataset.scroll)?.scrollIntoView({ block: "start" });
  });
  // 입력 칸에서 친 글자가 Streamlit 의 단축키(r 다시 실행, c 캐시 지우기)로 넘어가지 않게 한다
  R.addEventListener("keydown", e => {
    if (e.target.closest && e.target.closest("input,textarea,select")) e.stopPropagation();
  });
  let theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  try { theme = localStorage.getItem("wh-theme") || theme; } catch { /* 저장소를 못 쓰면 기기 설정 */ }
  setTheme(theme === "dark" ? "dark" : "light");
  render();
  // 결과 페이지의 "고쳐서 새로 만들기"로 왔으면 그 결과로 입력을 채운다
  // 그 결과를 돌린 자료(팀 자료·예시 사본)로 먼저 바꾸고, 그 결과의 입력과 바꿀 것으로 채운다
  if (DATA.preload) {
    const id = DATA.preload.replace(/^run\//, "");
    const run = runs.find(r => r.id === id);
    if (run) {
      if (run.source !== state.source) state = initial(run.source);
      applyEntry(entryInfo({ key: "run/" + id, id, kind: "run", scenario: run.config, run, hasResult: true, srcLabel: run.date + " 실행" }));
    }
  }
}
