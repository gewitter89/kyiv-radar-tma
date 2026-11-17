/* Kyiv Radar v1.7 — an understandable first visit and trust-first conversion.
   Enhances existing application without secrets or unapproved backend actions. */
(() => {
  "use strict";
  const BOT_URL = "https://t.me/prostov_shrink_bot";
  const VALID_VIEW = "kr_preferred_view_v1";
  let lastDialogFocus = null;
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  function button(label, click, kind) {
    const b = el("button", "kr-action" + (kind ? " " + kind : ""), label);
    b.type = "button";
    b.addEventListener("click", click);
    return b;
  }
  function trapInDialog(event) {
    const root = document.getElementById("krHandoff");
    if (!root || root.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeDialog();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(root.querySelectorAll('button, a[href], input, select, [tabindex="0"]'))
      .filter(node => !node.disabled && node.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  function closeDialog() {
    const root = document.getElementById("krHandoff");
    if (root) { root.hidden = true; root.replaceChildren(); }
    document.removeEventListener("keydown", trapInDialog);
    lastDialogFocus?.focus?.();
  }
  function showDialog(options) {
    closeDialog();
    lastDialogFocus = document.activeElement;
    const root = el("div", "kr-handoff-backdrop");
    root.id = "krHandoff";
    root.setAttribute("role", "presentation");
    root.addEventListener("click", e => { if (e.target === root) closeDialog(); });
    const dialog = el("div", "kr-handoff-dialog");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "krDialogTitle");
    const x = button("✕", closeDialog);
    x.classList.add("kr-dialog-close");
    x.setAttribute("aria-label", "Закрити вікно");
    const kicker = el("p", "kr-dialog-kicker", options.kicker || "КИЇВ РАДАР");
    const title = el("h2", "", options.title);
    title.id = "krDialogTitle";
    dialog.append(x, kicker, title);
    (options.paragraphs || []).forEach(line => dialog.append(el("p", "", line)));
    const actions = el("div", "kr-dialog-actions");
    (options.actions || []).forEach(act => {
      if (act.url) {
        const a = el("a", "kr-action" + (act.primary ? " primary" : ""), act.label);
        a.href = act.url; a.target = "_blank"; a.rel = "noopener noreferrer";
        actions.append(a);
      } else {
        actions.append(button(act.label, act.action, act.primary ? "primary" : ""));
      }
    });
    actions.append(button("Зрозуміло", closeDialog));
    dialog.append(actions);
    root.append(dialog);
    document.body.append(root);
    x.focus();
    document.addEventListener("keydown", trapInDialog);
  }
  function about() {
    showDialog({
      kicker: "Як це працює",
      title: "Вибирайте за умовами, а не обіцянками",
      paragraphs: [
        "1. Вкажіть бюджет, район або назву квартири й потрібні умови: генератор, GPON, тварини.",
        "2. Порівнюйте характеристики, але пам’ятайте: імпортовані оголошення не пройшли незалежну перевірку.",
        "3. Перевірте оригінальне джерело. Контакт через бот доступний після входу в Telegram.",
        "«Мій радар» зберігає пошуки на цьому пристрої. Автоматичні повідомлення поки не підключені."
      ]
    });
  }
  function contactHandoff(dealId, title) {
    const safeId = Number(dealId);
    showDialog({
      kicker: "Контакт захищено",
      title: "Відкрийте квартиру в Telegram",
      paragraphs: [
        "Номер власника чи контактної особи не відкривається на публічному сайті.",
        "1. Відкрийте бота, натисніть «Старт» (/start), а тоді відкрийте застосунок «Київ Радар».",
        "2. У каталозі знайдіть оголошення №" + (Number.isInteger(safeId) ? safeId : "?") + " та натисніть «Отримати контакт».",
        title ? "Ви дивилися: " + String(title).slice(0, 115) : "",
        "Доступність номера та актуальність оголошення не гарантовані."
      ].filter(Boolean),
      actions: [
        { label: "Відкрити бота", url: BOT_URL, primary: true },
        { label: "Скопіювати № оголошення", action: () => {
          const value = String(Number.isInteger(safeId) ? safeId : "");
          if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(value).then(() => {
              closeDialog(); if (typeof showToast === "function") showToast("Номер оголошення скопійовано");
            }).catch(() => { if (typeof showToast === "function") showToast("Оголошення №" + value); });
          } else if (typeof showToast === "function") showToast("Оголошення №" + value);
        }}
      ]
    });
  }
  function contactError(detail, statusCode) {
    const missing = statusCode === 404;
    const limited = statusCode === 429;
    const unauthorized = statusCode === 401;
    const delivery = statusCode === 502;
    const title = missing ? "Контакт поки недоступний"
      : limited ? "Ліміт запитів вичерпано"
      : unauthorized ? "Відкрийте застосунок у Telegram"
      : delivery ? "Спробуйте ще раз через Telegram"
      : "Сервіс тимчасово недоступний";
    const guidance = missing
      ? "Для цієї квартири немає доступного контакту. Перевірте оригінальне оголошення за посиланням у картці, якщо воно є."
      : limited ? "Не повторюйте запити поспіль. Поверніться після поновлення ліміту."
      : unauthorized ? "Відкрийте бота та застосунок заново, щоб оновити авторизацію."
      : delivery ? "Відкрийте чат із ботом і натисніть /start, потім повторіть запит."
      : "Перевірте з’єднання та спробуйте пізніше. Результат попереднього запиту не підтверджений.";
    showDialog({
      kicker: "Контакт не надіслано",
      title,
      paragraphs: [
        "Не вдалося отримати контакт. " + (detail || "Сервер не підтвердив надсилання контакту."),
        guidance,
        "Номер не вигадуємо, а відсутність контакту не вважаємо успішною доставкою."
      ],
      actions: unauthorized || delivery ? [{label: "Відкрити бота", url: BOT_URL, primary: true}] : []
    });
  }
  window.krContactHandoff = contactHandoff;
  window.krContactError = contactError;
  window.krLandlordHandoff = () => showDialog({
    kicker: "Подати квартиру",
    title: "Оголошення надсилаються через Telegram",
    paragraphs: [
      "Щоб подати квартиру, спочатку відкрийте «Київ Радар» у Telegram.",
      "У боті натисніть /start, відкрийте застосунок, додайте правдиві характеристики й власні фотографії.",
      "Заявку переглядає модератор. Публікація та перевірка права власності — різні дії; не обіцяємо автоматичного схвалення."
    ],
    actions: [{label:"Відкрити бота",url:BOT_URL,primary:true}]
  });

  function updateStatus() {
    const n = document.getElementById("krResultsCount");
    const source = document.getElementById("krDataStatus");
    const reset = document.getElementById("krReset");
    const retry = document.getElementById("krRetry");
    if (!n || typeof getFilteredListings !== "function") return;
    const items = getFilteredListings();
    const count = items.length;
    const endsOne = count % 10 === 1 && count % 100 !== 11;
    const endsFew = count % 10 >= 2 && count % 10 <= 4 && !(count % 100 >= 12 && count % 100 <= 14);
    n.textContent = count + " " + (endsOne || endsFew ? "оголошення" : "оголошень");
    const mode = window.KR_CATALOG_MODE || "loading";
    const messages = {
      live: "не перевірено",
      static: "копія · не перевірено",
      cached: "копія · не перевірено",
      loading: "завантаження…"
    };
    if (source) source.textContent = messages[mode] || messages.cached;
    if (retry) retry.hidden = mode === "live" || mode === "loading";
    const f = ACTIVE_FILTERS || {};
    const selected = Boolean(searchQuery) || f.rooms !== null || f.maxPrice !== null ||
      f.generator || f.gpon || f.pets || f.lowFloor || f.favs;
    if (reset) reset.hidden = !selected;
    const mapNote = document.getElementById("krMapNote");
    if (mapNote) {
      const unavailable = window.KR_MAP_AVAILABLE === false;
      mapNote.textContent = unavailable
        ? "Мапа недоступна. Скористайтесь списком."
        : "Мітки позначають райони, а не точні адреси квартир.";
      mapNote.hidden = (typeof CURRENT_VIEW_MODE !== "undefined" && CURRENT_VIEW_MODE === "list");
    }
  }
  function resetFilters() {
    const input = document.getElementById("searchInput");
    if (input) input.value = "";
    searchQuery = "";
    setFilter("all");
    if (typeof updateFilterPillsUI === "function") updateFilterPillsUI();
    updateStatus();
    input?.focus();
  }
  let requestedDealOpened = false;
  function maybeOpenRequestedDeal() {
    if (requestedDealOpened) return;
    const raw = new URLSearchParams(window.location.search).get("deal");
    if (!raw || !/^[1-9]\d{0,9}$/.test(raw)) return;
    const id = Number(raw);
    if (!Array.isArray(LISTINGS) || !LISTINGS.some(d => d.id === id)) return;
    requestedDealOpened = true;
    setTimeout(() => {
      if (typeof window.openDealModalById === "function") window.openDealModalById(id);
    }, 0);
  }
  function shareListing(deal) {
    const url = new URL(window.location.href);
    url.searchParams.set("deal", String(deal.id));
    url.hash = "";
    const value = url.toString();
    if (navigator.share) {
      navigator.share({title:"Київ Радар · квартира",url:value}).catch(() => {});
      return;
    }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(value).then(() => {
        if (typeof showToast === "function") showToast("Посилання на квартиру скопійовано");
      }).catch(() => showDialog({
        title:"Посилання на квартиру",
        paragraphs:[value,"Збережіть посилання та надішліть його кому потрібно."]
      }));
      return;
    }
    showDialog({title:"Посилання на квартиру",paragraphs:[value]});
  }

  function enrichCards() {
    if (!Array.isArray(LISTINGS)) return;
    const byId = new Map(LISTINGS.map(x => [String(x.id), x]));
    const cards = Array.from(document.querySelectorAll(".carousel-card, #listViewContainer > div[onclick]"));
    cards.forEach(card => {
      const fromId = card.id && card.id.startsWith("card-") ? card.id.slice(5) : null;
      const attr = card.getAttribute("onclick") || "";
      const fromOnclick = attr.match(/openDealModalById\((\d+)\)/);
      const id = fromId || (fromOnclick && fromOnclick[1]);
      const deal = byId.get(id);
      if (!deal || card.querySelector(".kr-compare-button")) return;
      card.setAttribute("role", "button");
      card.setAttribute("tabindex", "0");
      card.setAttribute("aria-label", "Переглянути квартиру: " + (deal.title || "оголошення №" + id));
      card.addEventListener("keydown", event => {
        if (event.target !== card) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openDealModalById(deal.id);
        }
      });
      const tools = el("div", "kr-card-tools");
      const ownership = deal.isOwnerVerified === true;
      const availability = deal.actualityConfirmed === true;
      const trustMessage = ownership && availability ? "Власника та наявність підтверджено"
        : ownership ? "Власника підтверджено · наявність не перевірено"
        : availability ? "Наявність підтверджено · власника не перевірено"
        : "Власника та наявність не перевірено";
      tools.append(el("span", "kr-trust-note", trustMessage));
      const compare = el("button", "kr-compare-button", "Порівняти +");
      compare.type = "button";
      compare.setAttribute("aria-label", "Додати квартиру до порівняння");
      compare.addEventListener("click", event => {
        event.preventDefault(); event.stopPropagation();
        if (window.KyivRadarSmart?.addFromCard) window.KyivRadarSmart.addFromCard(deal.id);
      });
      const cardActions = card.querySelector(".kr-card-actions");
      if (cardActions) cardActions.append(compare);
      else {
        tools.append(compare);
        const target = card.querySelector(".flex-1.p-2\\.5, .p-3.text-xs") || card;
        target.append(tools);
      }
    });
  }
  function installMapDistrictSummary() {
    if (typeof map === "undefined" || !map || typeof L === "undefined") {
      // The list must keep rendering even if Leaflet, tiles or a CDN failed.
      window.renderMarkers = function() {};
      return;
    }
    // Area-level map, rather than potentially fabricated exact building pins.
    const centers = {
      "Дарницький": [50.395,30.645], "Дніпровський": [50.453,30.616],
      "Деснянський": [50.497,30.627], "Печерський": [50.426,30.553],
      "Голосіївський": [50.381,30.520], "Солом'янський": [50.439,30.461],
      "Святошинський": [50.450,30.370], "Подільський": [50.482,30.466],
      "Оболонський": [50.515,30.496], "Шевченківський": [50.462,30.499]
    };
    const normalize = x => {
      const value = String(x || "").toLocaleLowerCase("uk-UA");
      return Object.keys(centers).find(k => {
        const stem = k.slice(0, k.indexOf("ськ") > 0 ? k.indexOf("ськ") : 6).toLocaleLowerCase("uk-UA");
        return stem.length > 3 && value.includes(stem);
      }) || null;
    };
    const previous = window.renderMarkers;
    window.renderMarkers = function(items) {
      if (typeof markersCluster !== "undefined" && markersCluster) markersCluster.clearLayers();
      if (typeof mapMarkers !== "undefined") {
        Object.values(mapMarkers).forEach(m => { try { map.removeLayer(m); } catch (_) {} });
        mapMarkers = {};
      }
      const counts = new Map();
      items.forEach(item => {
        const district = normalize(item.cleanAddress) || normalize(item.district) ||
          (/^Київ, /.test(item.address || "") ? normalize(item.address) : null);
        if (district) counts.set(district, (counts.get(district) || 0) + 1);
      });
      counts.forEach((count, district) => {
        const center = centers[district];
        const markup = '<div style="min-width:86px;border:1px solid #91baff;border-radius:12px;padding:8px;background:#19304c;color:#e8f2ff;font:600 11px system-ui;text-align:center;box-shadow:0 6px 18px #0007">' +
          district + '<div style="font-size:14px;font-weight:750;color:#fff">' + count + ' проп.</div><div style="font-size:9px;color:#bed4f4">район ≈</div></div>';
        const icon = L.divIcon({className:"kr-district-pin",html:markup,iconSize:[104,62],iconAnchor:[52,31]});
        const pin = L.marker(center,{icon});
        pin.on("click", () => {
          const input = document.getElementById("searchInput");
          if (input) input.value = district;
          searchQuery = district;
          currentActiveId = null;
          renderAll();
          if (typeof showToast === "function") showToast("Район: " + district + " · без точної адреси");
        });
        pin.addTo(map);
        if (typeof mapMarkers !== "undefined") mapMarkers[district] = pin;
      });
    };
    window.KR_DISTRICT_MARKERS = true;
  }
  function enhanceFunctions() {
    // Overlay old exposed global functions after definitions, before DOM ready.
    if (typeof window.renderAll === "function") {
      const original = window.renderAll;
      window.renderAll = function() {
        const value = original.apply(this,arguments);
        enrichCards();
        updateStatus();
        maybeOpenRequestedDeal();
        return value;
      };
    }
    if (typeof window.renderListView === "function") {
      const old = window.renderListView;
      window.renderListView = function() { const x=old.apply(this,arguments); enrichCards(); return x; };
    }
    if (typeof window.openDealModalById === "function") {
      const old = window.openDealModalById;
      window.openDealModalById = function(id) {
        const x=old.call(this,id);
        const deal = Array.isArray(LISTINGS) ? LISTINGS.find(d => d.id === id) : null;
        const secure = Boolean(window.Telegram?.WebApp?.initData);
        const source = String(deal?.source || "").toUpperCase();
        const sourceFirst = ["OLX", "DOM.RIA"].includes(source)
          && deal?.contactVerified !== true
          && !(typeof deal?.phone === "string" && deal.phone.trim());
        const original = document.getElementById("modalOriginalLink");
        // Reuse the main application's validated OLX/DIM.RIA source link. Never
        // make a button from arbitrary data.url, and never assume it is active.
        let sourceHref = null;
        if (sourceFirst && original && !original.classList.contains("hidden")) {
          try {
            const address = new URL(original.getAttribute("href"), window.location.href);
            const host = address.hostname.toLowerCase();
            const matchingProvider = source === "OLX"
              ? (host === "olx.ua" || host.endsWith(".olx.ua"))
              : (host === "dom.ria.com" || host.endsWith(".dom.ria.com"));
            if (address.protocol === "https:" && matchingProvider &&
                !address.username && !address.password) sourceHref = address.href;
          } catch (_) {
            // A malformed or mismatched source must never become an outgoing CTA.
          }
        }
        const sourceAction = document.getElementById("krOriginalAction");
        if (sourceAction) {
          sourceAction.hidden = !sourceHref;
          sourceAction.classList.toggle("hidden", !sourceHref);
          sourceAction.style.display = sourceHref ? "flex" : "none";
          if (sourceHref) {
            sourceAction.href = sourceHref;
            sourceAction.textContent = source === "OLX" ? "Перевірити на OLX" : "Перевірити на DIM.RIA";
          } else {
            sourceAction.removeAttribute("href");
          }
        }
        const header = document.getElementById("modalPhoneHeaderTitle");
        if (header) header.textContent = sourceFirst ? "Контакт у джерелі" : "Контакт з оголошення";
        const info = document.getElementById("modalContactHint");
        if (info) info.textContent = sourceFirst
          ? "Контакт і наявність не перевірено. Перегляньте джерело."
          : "Якщо контакт доступний, надішлемо його в Telegram";
        const free = document.getElementById("freeTrialPill");
        if (free) {
          free.hidden = sourceFirst;
          free.classList.toggle("hidden", sourceFirst);
        }
        const action = document.getElementById("modalCallLabel");
        if (action) action.textContent = secure ? "Запросити контакт у чат" : "Відкрити Telegram";
        const primary = document.getElementById("modalCallBtn");
        if (primary) {
          primary.hidden = sourceFirst;
          primary.style.display = sourceFirst ? "none" : "";
          primary.style.backgroundColor = secure ? "#30d158" : "#85b5ff";
          const phoneIcon = primary.querySelector("svg");
          if (phoneIcon) phoneIcon.style.display = secure ? "" : "none";
        }
        const secondary = document.getElementById("modalChatBtn");
        if (secondary) secondary.hidden = true;
        const ownerTelegram = document.getElementById("modalTgBtn");
        if (ownerTelegram && sourceFirst) ownerTelegram.classList.add("hidden");
        const bar = document.getElementById("modalCallBtn")?.parentElement;
        if (bar) {
          let share = document.getElementById("krShareListing");
          if (!share) {
            share = button("Поділитися", () => shareListing(deal));
            share.id = "krShareListing";
            share.setAttribute("aria-label", "Поділитися посиланням на квартиру");
            bar.append(share);
          } else {
            share.onclick = () => shareListing(deal);
          }
        }
        return x;
      };
    }
    if (typeof window.setViewMode === "function") {
      const old=window.setViewMode;
      window.setViewMode=function(mode) {
        const result=old.apply(this,arguments);
        try { localStorage.setItem(VALID_VIEW,mode); } catch (_) {}
        enrichCards(); updateStatus();
        return result;
      };
    }
  }
  function start() {
    const header = document.querySelector("header");
    if (!header || document.getElementById("krHero")) return;
    const brand = header.querySelector("button[onclick='openCityModal()']");
    if (brand) {
      brand.className = "kr-brand";
      brand.replaceChildren();
      const mark = el("span","kr-brand-mark","◎");
      mark.setAttribute("aria-hidden","true");
      const label = el("span","kr-brand-label");
      label.append(el("strong","","КИЇВ РАДАР"), el("small","","Київ · оренда"));
      brand.append(mark,label);
      brand.setAttribute("aria-label","Київ Радар. Місто: Київ");
    }
    const hero = el("section","kr-hero"); hero.id = "krHero";
    const intro = el("div","kr-hero-copy");
    intro.append(el("p","kr-hero-eyebrow","Житло по суті"));
    intro.append(el("h1","","Квартира під ваші умови. Без здогадок."));
    intro.append(el("p","","Ціна, район і заявлені умови автономності. Перевірку кожного оголошення позначаємо окремо."));
    const actions = el("div","kr-hero-actions");
    const searchBtn = button("Знайти квартиру", () => document.getElementById("searchInput")?.focus(), "primary");
    searchBtn.id = "krStart";
    actions.append(searchBtn);
    actions.append(button("Як це працює",about,"ghost"));
    const radar = document.getElementById("smartRadarOpen");
    if (radar) {
      radar.className = "kr-action";
      radar.textContent = "Мій радар";
      radar.setAttribute("aria-label","Мій радар: збережені пошуки та порівняння");
      actions.append(radar);
    }
    hero.append(intro,actions);
    header.insertAdjacentElement("afterend",hero);
    const status = el("div","kr-results-bar"); status.id = "krResultsBar";
    const meta = el("div","kr-results-meta");
    meta.append(el("strong","", "Завантажуємо…"));
    meta.lastChild.id = "krResultsCount";
    const source = el("span","kr-source-status", "Завантажуємо каталог…");
    source.id = "krDataStatus";meta.append(source);
    status.append(meta);
    const reset=el("button","kr-reset","Скинути фільтри");
    reset.id="krReset";reset.type="button";reset.hidden=true;
    reset.addEventListener("click",resetFilters);
    status.append(reset);
    const retry = el("button", "kr-reset", "Оновити");
    retry.id = "krRetry"; retry.type = "button"; retry.hidden = true;
    retry.setAttribute("aria-label", "Спробувати завантажити актуальний каталог");
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      retry.textContent = "Оновлюємо…";
      try {
        await loadDeals();
      } finally {
        retry.disabled = false;
        retry.textContent = "Оновити";
        updateStatus();
      }
    });
    status.append(retry);
    // Put Map/List where people can see it without obscuring card actions.
    const viewSwitch = document.getElementById("floatingViewToggle");
    if (viewSwitch) status.append(viewSwitch);
    const filterBar = document.getElementById("filterBarWrapper");
    filterBar?.insertAdjacentElement("afterend",status);
    const mapEl = document.getElementById("map");
    if (mapEl) {
      const tip=el("div","kr-map-warning","Мітки позначають райони, а не точні адреси квартир.");
      tip.id = "krMapNote";
      mapEl.parentElement?.append(tip);
    }
    const searchField=document.getElementById("searchInput");
    if (searchField) searchField.setAttribute("aria-label","Пошук квартири за районом, вулицею або назвою оголошення");
    installMapDistrictSummary();
    try {
      const mode=localStorage.getItem(VALID_VIEW);
      if (mode === "list" && typeof setViewMode === "function") setViewMode("list");
    } catch (_) {}
    enhanceFunctions();
    // First meaningful paint: do not wait for the remote API. A checked
    // embedded snapshot is already available and is clearly labelled stale.
    if (Array.isArray(LISTINGS) && LISTINGS.length > 0) {
      if (typeof window.krQualityCatalog === "function") LISTINGS = window.krQualityCatalog(LISTINGS);
      if (typeof window.renderAll === "function") window.renderAll();
    }
    updateStatus();
  }
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",start);
  else start();
})();
