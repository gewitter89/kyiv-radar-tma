/* Kyiv Radar 1.13. Product filters: accessible modal and the existing catalog state. */
(() => {
 "use strict";
 const Q=id=>document.getElementById(id);
 const choices=[["generator","Генератор у будинку","Заявлено, не перевірено"],["gpon","Інтернет під час відключень","Заявлено, не перевірено"],["pets","З тваринами","Уточнюйте умови"],["lowFloor","До 4-го поверху","Лише з відомим поверхом"],["favs","Лише обрані","Ваші збережені квартири"]];
 let draft=null,opener=null,previousOverflow="";
 // Preserve the user's search and advanced filters when entering favorites.
 // The shortcut is a separate browsing destination, not another hidden criterion.
 let previousBrowse=null;
 const btn=(title,id,className)=>{const b=document.createElement("button");b.type="button";b.textContent=title;if(id)b.id=id;if(className)b.className=className;return b};
 function countRoom(value){
  const data=typeof LISTINGS!=="undefined"&&Array.isArray(LISTINGS)?LISTINGS:[];
  return data.filter(a=>{const n=Number(a.rooms)||(typeof getDealRooms==="function"?getDealRooms(a):null);return a.roomConflict!==true&&Number.isInteger(n)&&(value===5?n>=5:n===value)}).length;
 }
 function hasConditions(f){return choices.some(([key])=>Boolean(f[key]))}
 function refreshChips(){
  if(typeof ACTIVE_FILTERS==="undefined")return;
  const f=ACTIVE_FILTERS;
  const rooms=Q("krRoomsTrigger"),price=Q("krPriceTrigger"),extra=Q("krConditionsTrigger");
  if(rooms){rooms.textContent=f.rooms==null?"Кімнати":f.rooms===5?"5+ кімн":f.rooms+" кімн";rooms.classList.toggle("kr-chip-on",f.rooms!=null)}
  if(price){price.textContent=f.maxPrice==null?"Ціна":"До "+Number(f.maxPrice).toLocaleString("uk-UA")+" ₴";price.classList.toggle("kr-chip-on",f.maxPrice!=null)}
  if(extra){let count=choices.filter(([key])=>Boolean(f[key])).length;extra.textContent=count?"Умови · "+count:"Умови";extra.classList.toggle("kr-chip-on",count>0)}
  const fav=Q("krFavoritesShortcut");
  if(fav){
   const count=typeof FAVORITES!=="undefined"?FAVORITES.size:0;
   const active=Boolean(f.favs);
   fav.querySelector(".kr-favorites-count").textContent=String(count);
   fav.querySelector(".kr-favorites-heart").textContent=active?"♥":"♡";
   fav.classList.toggle("kr-chip-on",active);
   fav.setAttribute("aria-pressed",String(active));
   fav.setAttribute("aria-label",active?"Повернутися до пошуку квартир":"Відкрити обрані квартири: "+count);
   fav.title=active?"Повернутися до пошуку":"Мої обрані квартири";
  }
 }
 function sync(){
  if(!draft)return;
  Q("krRoomsOptions").querySelectorAll("button").forEach(b=>{
   const value=b.dataset.room==="any"?null:Number(b.dataset.room);const selected=value===draft.rooms;
   b.classList.toggle("kr-selected",selected);b.setAttribute("aria-pressed",String(selected));
   if(value!=null)b.setAttribute("aria-label",(value===5?"5 і більше":String(value))+" кімнат: "+countRoom(value)+" оголошень");
  });
  Q("krPriceOptions").querySelectorAll("button").forEach(b=>{
   const value=b.dataset.price==="any"?null:Number(b.dataset.price);const selected=value===draft.maxPrice;
   b.classList.toggle("kr-selected",selected);b.setAttribute("aria-pressed",String(selected));
  });
  Q("krConditionOptions").querySelectorAll("input").forEach(c=>{c.checked=Boolean(draft[c.dataset.key])});
  const input=Q("krMaxPriceInput");if(document.activeElement!==input)input.value=draft.maxPrice==null?"":String(draft.maxPrice);
  const zero=[3,4,5].filter(v=>countRoom(v)===0);
  Q("krRoomNotice").textContent=zero.length?"Для "+zero.map(v=>v===5?"5+":v).join(", ")+" кімнат зараз немає оголошень. Вибір залишається доступним для нових надходжень.":"Показуємо кількість квартир у поточному каталозі.";
 }
 function toggleFavoritesShortcut(){
  if(typeof ACTIVE_FILTERS==="undefined")return;
  const favoritesAreOpen=Boolean(ACTIVE_FILTERS.favs);
  const input=Q("searchInput");
  if(!favoritesAreOpen){
   previousBrowse={
    filters:{...ACTIVE_FILTERS},
    query:typeof searchQuery==="string"?searchQuery:""
   };
   Object.assign(ACTIVE_FILTERS,{
    rooms:null,maxPrice:null,generator:false,gpon:false,
    lowFloor:false,pets:false,favs:true
   });
   // All saved cards should be visible, not silently hidden by the old query.
   if(typeof searchQuery!=="undefined")searchQuery="";
   if(input)input.value="";
   if(typeof setViewMode==="function")setViewMode("list");
  }else{
   if(previousBrowse){
    Object.assign(ACTIVE_FILTERS,previousBrowse.filters,{favs:false});
    if(typeof searchQuery!=="undefined")searchQuery=previousBrowse.query;
    if(input)input.value=previousBrowse.query;
   }else ACTIVE_FILTERS.favs=false;
   previousBrowse=null;
  }
  if(typeof currentActiveId!=="undefined")currentActiveId=null;
  if(typeof updateFilterPillsUI==="function")updateFilterPillsUI();
  if(typeof renderAll==="function")renderAll();
  const list=Q("listViewContainer");
  if(list&&!list.classList.contains("hidden"))list.scrollTop=0;
 }
 function open(section,source){
  const modal=Q("krFiltersSheet");if(!modal||!modal.hidden)return;
  draft={...ACTIVE_FILTERS};opener=source||document.activeElement;previousOverflow=document.body.style.overflow;
  document.body.style.overflow="hidden";modal.hidden=false;document.documentElement.classList.add("kr-smart-filters");
  ["krRoomsTrigger","krPriceTrigger","krConditionsTrigger"].forEach(id=>Q(id)?.setAttribute("aria-expanded","true"));
  sync();Q("krFiltersScroll").scrollTop=0;
  requestAnimationFrame(()=>{Q(section==="price"?"krPriceSection":section==="conditions"?"krConditionsSection":"krRoomsSection")?.scrollIntoView({block:"nearest"});Q("krFiltersClose")?.focus({preventScroll:true})});
 }
 function close(){
  const modal=Q("krFiltersSheet");if(!modal||modal.hidden)return;
  modal.hidden=true;document.documentElement.classList.remove("kr-smart-filters");document.body.style.overflow=previousOverflow;
  ["krRoomsTrigger","krPriceTrigger","krConditionsTrigger"].forEach(id=>Q(id)?.setAttribute("aria-expanded","false"));
  draft=null;if(opener&&opener.isConnected)opener.focus({preventScroll:true});
 }
 function apply(){
  if(!draft)return;
  for(const key of ["rooms","maxPrice","generator","gpon","pets","lowFloor","favs"]) ACTIVE_FILTERS[key]=draft[key];
  if(typeof updateFilterPillsUI==="function")updateFilterPillsUI();
  if(typeof currentActiveId!=="undefined")currentActiveId=null;
  if(typeof renderAll==="function")renderAll();
  refreshChips();close();
 }
 function createSheet(){
  const modal=document.createElement("div");modal.id="krFiltersSheet";modal.className="kr-filters-sheet";modal.hidden=true;
  modal.innerHTML="<button type=\"button\" id=\"krFiltersScrim\" class=\"kr-filters-scrim\" aria-label=\"Закрити фільтри\"></button><section class=\"kr-filters-panel\" role=\"dialog\" aria-modal=\"true\" aria-labelledby=\"krFiltersTitle\"><header class=\"kr-filters-head\"><div><h2 id=\"krFiltersTitle\">Фільтри квартир</h2><p>Обирайте лише потрібне</p></div><button type=\"button\" id=\"krFiltersClose\" aria-label=\"Закрити фільтри\">×</button></header><div class=\"kr-filters-scroll\" id=\"krFiltersScroll\"><section id=\"krRoomsSection\" class=\"kr-filters-section\"><h3>Кількість кімнат</h3><div id=\"krRoomsOptions\" class=\"kr-room-options\" role=\"group\" aria-label=\"Вибір кількості кімнат\"></div><p id=\"krRoomNotice\" class=\"kr-filter-note\"></p></section><section id=\"krPriceSection\" class=\"kr-filters-section\"><h3>Максимальна ціна</h3><label for=\"krMaxPriceInput\">Оренда за місяць, ₴</label><input id=\"krMaxPriceInput\" type=\"number\" inputmode=\"numeric\" min=\"0\" max=\"1000000\" step=\"500\" placeholder=\"Без обмежень\"><div id=\"krPriceOptions\" class=\"kr-price-options\" role=\"group\" aria-label=\"Швидкий вибір ціни\"></div></section><section id=\"krConditionsSection\" class=\"kr-filters-section\"><h3>Умови проживання</h3><div id=\"krConditionOptions\" class=\"kr-condition-options\"></div><p class=\"kr-filter-note\">Відомості заявлені в оголошеннях. Ми не підтверджували умови незалежно.</p></section><section class=\"kr-filters-section\"><button type=\"button\" id=\"krFiltersSort\" class=\"kr-filters-sort\">Сортування <span aria-hidden=\"true\">›</span></button></section></div><footer class=\"kr-filters-footer\"><button type=\"button\" id=\"krFiltersReset\">Скинути</button><button type=\"button\" id=\"krFiltersApply\">Показати квартири</button></footer></section>";
  document.body.append(modal);
  for(const [v,label] of [[null,"Усі"],[1,"1"],[2,"2"],[3,"3"],[4,"4"],[5,"5+"]]){
   const b=btn(label,null,"kr-filter-option");b.dataset.room=v==null?"any":String(v);b.setAttribute("aria-pressed","false");
   b.addEventListener("click",()=>{draft.rooms=v;sync()});Q("krRoomsOptions").append(b);
  }
  for(const [v,label] of [[null,"Без ліміту"],[10000,"10 тис."],[15000,"15 тис."],[20000,"20 тис."],[30000,"30 тис."]]){
   const b=btn(label,null,"kr-filter-option");b.dataset.price=v==null?"any":String(v);b.setAttribute("aria-pressed","false");
   b.addEventListener("click",()=>{draft.maxPrice=v;sync()});Q("krPriceOptions").append(b);
  }
  for(const [key,label,hint] of choices){
   const line=document.createElement("label");line.className="kr-condition-row";
   const copy=document.createElement("span");copy.className="kr-condition-copy";
   const strong=document.createElement("strong");strong.textContent=label;
   const small=document.createElement("small");small.textContent=hint;copy.append(strong,small);
   const check=document.createElement("input");check.type="checkbox";check.dataset.key=key;
   check.addEventListener("change",()=>{draft[key]=check.checked;sync()});line.append(copy,check);Q("krConditionOptions").append(line);
  }
  Q("krMaxPriceInput").addEventListener("input",e=>{
   const x=e.target.value.trim();const n=x===""?null:Number(x);
   draft.maxPrice=n===null?null:Number.isFinite(n)?Math.min(1000000,Math.max(0,Math.floor(n))):null;
   Q("krPriceOptions").querySelectorAll("button").forEach(b=>{
    const v=b.dataset.price==="any"?null:Number(b.dataset.price);let selected=v===draft.maxPrice;
    b.classList.toggle("kr-selected",selected);b.setAttribute("aria-pressed",String(selected));
   });
  });
  Q("krFiltersClose").addEventListener("click",close);Q("krFiltersScrim").addEventListener("click",close);
  Q("krFiltersReset").addEventListener("click",()=>{draft={rooms:null,maxPrice:null,generator:false,gpon:false,lowFloor:false,pets:false,favs:false};sync()});
  Q("krFiltersApply").addEventListener("click",apply);
  Q("krFiltersSort").addEventListener("click",()=>{close();if(typeof openSortModal==="function")openSortModal()});
  modal.addEventListener("keydown",e=>{
   if(e.key==="Escape"){e.preventDefault();close();return}
   if(e.key!=="Tab")return;
   const nodes=[...modal.querySelectorAll("button:not([disabled]),input:not([disabled])")].filter(n=>n.getClientRects().length&&getComputedStyle(n).visibility!=="hidden");
   if(!nodes.length)return;
   if(e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes[nodes.length-1].focus()}
   else if(!e.shiftKey&&document.activeElement===nodes[nodes.length-1]){e.preventDefault();nodes[0].focus()}
  });
 }
 function init(){
  const bar=Q("filterBarWrapper"),legacy=Q("filterContainer");
  if(!bar||!legacy||Q("krFilterToolbar"))return;
  const heading=Q("krHero")?.querySelector("h1");if(heading)heading.textContent="Знайти квартиру";
  const strip=document.createElement("div");strip.id="krFilterToolbar";strip.className="kr-filter-toolbar";
  for(const [id,title,section] of [["krRoomsTrigger","Кімнати","rooms"],["krPriceTrigger","Ціна","price"],["krConditionsTrigger","Умови","conditions"]]){
   const chip=btn(title,id,"kr-filter-trigger");chip.setAttribute("aria-controls","krFiltersSheet");chip.setAttribute("aria-haspopup","dialog");chip.setAttribute("aria-expanded","false");
   chip.addEventListener("click",()=>open(section,chip));strip.append(chip);
  }
  const favorites=btn("", "krFavoritesShortcut", "kr-favorites-shortcut");
  favorites.innerHTML='<span class="kr-favorites-heart" aria-hidden="true">♡</span>'+
    '<span class="kr-favorites-label">Обрані</span>'+
    '<span class="kr-favorites-count" aria-hidden="true">0</span>';
  favorites.setAttribute("aria-pressed","false");
  favorites.addEventListener("click",toggleFavoritesShortcut);
  strip.append(favorites);
  legacy.classList.add("kr-legacy-filters");legacy.setAttribute("aria-hidden","true");legacy.inert=true;
  bar.insertBefore(strip,legacy);createSheet();document.documentElement.classList.add("kr-focused-filter-ui");
  const oldRender=window.renderAll;
  if(typeof oldRender==="function")window.renderAll=function(...args){const result=oldRender.apply(this,args);refreshChips();return result};
  refreshChips();
 }
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
 window.KyivRadarFilters=Object.freeze({open:section=>open(section||"rooms",Q("krRoomsTrigger")),close,isOpen:()=>Boolean(Q("krFiltersSheet")&&!Q("krFiltersSheet").hidden)});
})();