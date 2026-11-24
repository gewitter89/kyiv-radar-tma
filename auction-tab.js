/* Isolated staging & production tab. No requests or navigation when flag is off. */
(() => {
  'use strict';
  if (window.KR_AUCTIONS_STAGING !== true && window.KR_AUCTIONS_ENABLED !== true) return;
  const ID = /^(?:ALE001|CSE001)-UA-\d{8}-\d{5}$/;
  const KEY = 'kr_auction_favs_v1';
  const fmt = new Intl.NumberFormat('uk-UA', {style:'currency',currency:'UAH',maximumFractionDigits:2});
  const date = new Intl.DateTimeFormat('uk-UA',{timeZone:'Europe/Kyiv',dateStyle:'short',timeStyle:'short'});
  const el = (tag, text, attrs={}) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    Object.entries(attrs).forEach(([k,v]) => node.setAttribute(k,v));
    return node;
  };
  let saved = new Set();
  try {
    const value = JSON.parse(localStorage.getItem(KEY) || '[]');
    if (Array.isArray(value)) saved = new Set(value.filter(x=>typeof x==='string' && ID.test(x)).slice(0,2000));
  } catch (_) {}
  let rows = [], seq = 0, refreshTimer, expiryTimer;
  const nav = el('button','Аукціони',{type:'button',id:'krAuctionsNav','aria-haspopup':'dialog'});
  const panel = el('dialog',undefined,{id:'krAuctionDialog','aria-labelledby':'krAuctionTitle'});
  const title = el('h2','Аукціони',{id:'krAuctionTitle'});
  const close = el('button','Закрити',{type:'button','aria-label':'Закрити аукціони'});
  const header = el('div',undefined,{class:'kr-auction-header'});
  header.append(title,close);
  const note = el('p','Prozorro.Продажі · Офіційні відкриті дані. Стартова ціна не є остаточною вартістю продажу. Можуть нараховуватись додаткові збори та ПДВ. Обов’язково перевіряйте оригінал лота за посиланням. Вибірка неповна, не відображає весь ринок.');
  const filters = el('div',undefined,{class:'kr-auction-filters'});
  const max = el('input',undefined,{type:'number',min:'0',step:'1',placeholder:'Без обмежень',id:'krAuctionMax'});
  const maxLabel = el('label','Макс. стартова ціна, грн',{for:'krAuctionMax'});
  const sort = el('select',undefined,{id:'krAuctionSort','aria-label':'Сортування аукціонів'});
  for (const [v,t] of [['deadline','За терміном'],['price','За ціною']]) sort.append(el('option',t,{value:v}));
  const only = el('input',undefined,{type:'checkbox',id:'krAuctionOnlyFav'});
  const onlyLabel = el('label','Обрані',{for:'krAuctionOnlyFav'}); onlyLabel.prepend(only);
  filters.append(maxLabel,max,sort,onlyLabel);
  const status = el('p','',{role:'status','aria-live':'polite'});
  const list = el('div',undefined,{id:'krAuctionList'});
  panel.append(header,note,filters,status,list);
  const host = document.querySelector('body > header');
  if (!host || typeof panel.showModal !== 'function') return;
  host.append(nav); document.body.append(panel);

  const API_ENDPOINT = (window.location.origin === 'https://gewitter89.github.io')
    ? 'https://vmi3445944.contaboserver.net/api/auctions'
    : '/api/auctions';

  function normalize(r) {
    if (!r || typeof r.auction_id!=='string' || !ID.test(r.auction_id) ||
        r.source!=='prozorro_sale' || r.kind!=='sale_auction' || r.city!=='Київ' ||
        r.asset_class!=='apartment_classified' || typeof r.vat_included!=='boolean' ||
        r.source_url!=='https://prozorro.sale/auction/'+r.auction_id+'/' ||
        typeof r.starting_bid_uah!=='string' || !/^\d{1,13}\.\d{2}$/.test(r.starting_bid_uah)) return null;
    const price=Number(r.starting_bid_uah), end=Date.parse(r.bidding_ends_at),
          seen=Date.parse(r.observed_at), valid=Date.parse(r.valid_until), now=Date.now();
    if (!(price>0 && price<=1e12 && Number.isFinite(end) && Number.isFinite(seen) &&
          Number.isFinite(valid) && seen<=now && valid<=Math.min(end,seen+3600000) &&
          now<valid && valid<=now+60000)) return null;
    return {id:r.auction_id,url:r.source_url,price,end,seen,valid,vat:r.vat_included};
  }
  function render() {
    clearTimeout(expiryTimer);
    rows=rows.filter(r=>r.valid>Date.now());
    list.replaceChildren();
    const cap=max.value===''?Infinity:Number(max.value);
    const visible=rows.filter(r=>r.price<=cap && (!only.checked||saved.has(r.id)))
      .sort((a,b)=>sort.value==='price'?a.price-b.price||a.end-b.end:a.end-b.end||a.price-b.price);
    for (const r of visible) {
      const card=el('article',undefined,{class:'kr-auction-card'});
      const heart=el('button',saved.has(r.id)?'В обраному':'До обраного',
        {type:'button','aria-pressed':String(saved.has(r.id)),'aria-label':saved.has(r.id)?'Прибрати з обраного':'Додати в обрані'});
      heart.addEventListener('click',()=>{
        if(saved.has(r.id)) saved.delete(r.id); else if(saved.size<2000) saved.add(r.id);
        try{localStorage.setItem(KEY,JSON.stringify([...saved]));}catch(_){}
        render();
      });
      const link=el('a','Переглянути оригінал',{href:r.url,target:'_blank',rel:'noopener noreferrer'});
      link.addEventListener('click',event=>{
        if(r.valid<=Date.now()){event.preventDefault();render();return;}
        const tg=window.Telegram?.WebApp;
        if(typeof tg?.openLink==='function'){
          try{tg.openLink(r.url);event.preventDefault();}catch(_){}
        }
      });
      const vatText = r.vat ? 'з ПДВ' : 'без ПДВ (ПДВ нараховується додатково)';
      card.append(el('p','Київ · Квартира'),el('h3',fmt.format(r.price)),
        el('p','Стартова ціна · '+vatText),
        el('p','Додаткові збори сплачуються окремо'),
        el('p','Заявки до: '+date.format(r.end)),el('p','Перевірено: '+date.format(r.seen)),
        el('p',r.id),heart,link);
      list.append(card);
    }
    status.textContent=visible.length?'Показано: '+visible.length:'Немає підтверджених об’єктів за умовами вибірки.';
    if(rows.length) expiryTimer=setTimeout(render,Math.max(0,Math.min(...rows.map(r=>r.valid))-Date.now()+5));
  }
  async function refresh(){
    const n=++seq;
    rows=[]; list.replaceChildren(); status.textContent='Оновлення…';
    const controller = new AbortController();
    const timeout = setTimeout(()=>controller.abort(),5000);
    try{
      const response=await fetch(API_ENDPOINT,{cache:'no-store',signal:controller.signal,redirect:'error'});
      if(!response.ok) throw Error();
      const body=await response.json();
      if(body.available!==true || body.coverage_complete!==false || !Array.isArray(body.auctions)||body.auctions.length>2000) throw Error();
      const normalized=body.auctions.map(normalize);
      if(normalized.some(x=>!x)||new Set(normalized.map(x=>x.id)).size!==normalized.length) throw Error();
      if(n!==seq||!panel.open)return;
      if(document.hidden){status.textContent='Оновлення після повернення';return;}
      rows=normalized;render();
    }catch(_){if(n===seq&&panel.open){rows=[];list.replaceChildren();status.textContent='Дані тимчасово недоступні.';}}
    finally{clearTimeout(timeout);}
  }
  nav.addEventListener('click',()=>{clearInterval(refreshTimer);clearTimeout(expiryTimer);panel.showModal();refresh();refreshTimer=setInterval(()=>{if(!document.hidden)refresh();},20000);});
  close.addEventListener('click',()=>panel.close());
  panel.addEventListener('close',()=>{if(panel.open)return;seq++;clearInterval(refreshTimer);clearTimeout(expiryTimer);rows=[];list.replaceChildren();nav.focus();});
  for(const input of [max,sort,only])input.addEventListener('input',render);
  document.addEventListener('visibilitychange',()=>{if(!panel.open)return;seq++;rows=[];list.replaceChildren();if(!document.hidden)refresh();});
})();
