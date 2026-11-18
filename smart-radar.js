/* Kyiv Radar v1.35 — local saved searches and identity-safe apartment comparisons.
   This is an on-device feature: no push alerts, account sync or paid functionality.
   All user-controlled text is rendered with textContent, never as HTML. */
(() => {
  "use strict";
  const SEARCH_KEY = "kr_saved_searches_v1";
  const COMPARE_KEY = "kr_compare_keys_v2";
  const LEGACY_COMPARE_KEY = "kr_compare_ids_v1";
  const MAX_SEARCHES = 8;
  const MAX_COMPARE = 3;
  let searches = [];
  let compareKeys = [];
  let legacyCompareCount = 0;
  let lastFocus = null;

  function read(key) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || "[]");
      return Array.isArray(value) ? value : [];
    } catch (_) { return []; }
  }
  function persist(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; }
    catch (_) { notice("Не вдалося зберегти на цьому пристрої"); return false; }
  }

  // Reuse the same *unique source + public permalink* identity as favorites.
  // The existing favoriteKey rejects invalid/missing URLs and duplicate keys.
  function listingKey(deal) {
    return typeof favoriteKey === "function" ? favoriteKey(deal) : null;
  }
  function identitySet(deals) {
    return [...new Set((Array.isArray(deals) ? deals : []).map(listingKey).filter(Boolean))];
  }
  function readCompareKeys() {
    try {
      const snapshot = JSON.parse(localStorage.getItem(COMPARE_KEY) || "null");
      if (!snapshot || snapshot.version !== 2 || !Array.isArray(snapshot.keys)) return [];
      return [...new Set(snapshot.keys.filter(key =>
        typeof key === "string" && key.startsWith("kr2|") && key.length < 2200))].slice(0, MAX_COMPARE);
    } catch (_) { return []; }
  }
  function persistCompare(keys) {
    if (!Array.isArray(keys) || keys.length > MAX_COMPARE ||
        keys.some(key => typeof key !== "string" || !key.startsWith("kr2|") || key.length >= 2200)) return false;
    return persist(COMPARE_KEY, {version: 2, keys});
  }
  function oldCompareCount() {
    return [...new Set(read(LEGACY_COMPARE_KEY)
      .filter(v => (typeof v === "number" || typeof v === "string") &&
        Number.isSafeInteger(Number(v)) && Number(v) > 0))].length;
  }
  function discardLegacyCompare() {
    try {
      localStorage.removeItem(LEGACY_COMPARE_KEY);
      legacyCompareCount = 0;
      render();
      notice("Старі номери порівняння видалено; нові порівняння збережено");
    } catch (_) { notice("Не вдалося видалити старі номери"); }
  }

  function notice(message) {
    if (typeof showToast === "function") showToast(message);
  }
  function safeFilters(raw) {
    const x = raw && typeof raw === "object" ? raw : {};
    return {
      rooms: [1, 2, 3].includes(x.rooms) ? x.rooms : null,
      maxPrice: [15000, 20000].includes(x.maxPrice) ? x.maxPrice : null,
      generator: x.generator === true, gpon: x.gpon === true,
      lowFloor: x.lowFloor === true, pets: x.pets === true,
      favs: x.favs === true
    };
  }
  function criteriaNow() {
    return { query: String(searchQuery || "").trim().slice(0, 100),
      filters: safeFilters(ACTIVE_FILTERS) };
  }
  function matches(deal, criteria) {
    const f = safeFilters(criteria.filters);
    const query = String(criteria.query || "").toLocaleLowerCase("uk-UA");
    const haystack = [deal.title, deal.district, deal.address, deal.metro]
      .map(v => String(v || "")).join(" ").toLocaleLowerCase("uk-UA");
    if (query && !haystack.includes(query)) return false;
    // Imported room-count conflicts are unknown, not safe filter matches.
    if (f.rooms != null && deal.roomConflict === true) return false;
    const rooms = typeof getDealRooms === "function" ? getDealRooms(deal) : null;
    if (f.rooms != null && !(f.rooms === 3 ? rooms >= 3 : rooms === f.rooms)) return false;
    if (f.maxPrice != null && !(Number(deal.price) <= f.maxPrice)) return false;
    if (f.generator && deal.generator !== true) return false;
    if (f.gpon && deal.gpon !== true) return false;
    if (f.lowFloor && !(Number(deal.floor) <= 4)) return false;
    if (f.pets && deal.pets !== true) return false;
    if (f.favs && !(listingKey(deal) && FAVORITES.has(listingKey(deal)))) return false;
    return true;
  }
  function matchesFor(criteria) {
    return (Array.isArray(LISTINGS) ? LISTINGS : []).filter(d => matches(d, criteria));
  }
  function elem(tag, className, label) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (label !== undefined) el.textContent = label;
    return el;
  }
  function button(label, onClick, className = "px-3 py-2 rounded-xl bg-[#2c2c2e] text-white text-xs font-medium") {
    const el = elem("button", className, label);
    el.type = "button"; el.addEventListener("click", onClick);
    return el;
  }
  function formatPrice(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString("uk-UA") + " ₴" : "Ціна не вказана";
  }
  function useSearch(id) {
    const search = searches.find(s => s.id === id);
    if (!search) return;
    ACTIVE_FILTERS = safeFilters(search.criteria.filters);
    searchQuery = String(search.criteria.query || "");
    const input = document.getElementById("searchInput");
    if (input) input.value = searchQuery;
    currentActiveId = null;
    updateFilterPillsUI();
    renderAll();
    close();
    notice("Збережений пошук застосовано");
  }
  function saveSearch() {
    if (searches.length >= MAX_SEARCHES) {
      notice("Можна зберегти до 8 пошуків");
      return;
    }
    const criteria = criteriaNow();
    const field = document.getElementById("smartRadarName");
    const title = String(field?.value || "").trim().slice(0, 50) ||
      (criteria.query ? "Пошук: " + criteria.query.slice(0, 38) : "Мій пошук " + (searches.length + 1));
    const knownKeys = identitySet(matchesFor(criteria));
    const id = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
    const next = searches.concat([{ id, title, criteria, knownKeys }]);
    if (!persist(SEARCH_KEY, next)) return;
    searches = next;
    if (field) field.value = "";
    render();
    notice("Пошук збережено на цьому пристрої");
  }
  function deleteSearch(id) {
    const next = searches.filter(s => s.id !== id);
    if (persist(SEARCH_KEY, next)) { searches = next; render(); }
  }
  function markRead(id) {
    const item = searches.find(s => s.id === id);
    if (!item) return;
    const updated = searches.map(s => s.id === id
      ? { ...s, knownKeys: identitySet(matchesFor(item.criteria)) }
      : s);
    if (persist(SEARCH_KEY, updated)) { searches = updated; render(); }
  }
  function addCompare() {
    const key = document.getElementById("smartRadarCompareSelect")?.value;
    if (!key || compareKeys.includes(key)) return;
    if (compareKeys.length >= MAX_COMPARE) {
      notice("Можна порівняти до 3 квартир");
      return;
    }
    const selected = (Array.isArray(LISTINGS) ? LISTINGS : []).filter(d => listingKey(d) === key);
    if (selected.length !== 1) {
      notice("Посилання на квартиру відсутнє або неоднозначне");
      return;
    }
    const next = compareKeys.concat(key);
    if (persistCompare(next)) { compareKeys = next; render(); }
  }
  function removeCompare(key) {
    const next = compareKeys.filter(value => value !== key);
    if (persistCompare(next)) { compareKeys = next; render(); }
  }
  function renderSearches() {
    const root = document.getElementById("smartRadarSearches");
    root.replaceChildren();
    if (!searches.length) {
      root.append(elem("p", "text-sm text-[#8e8e93] py-3",
        "Поки що немає збережених пошуків. Налаштуйте фільтри та натисніть «Зберегти»."));
      return;
    }
    searches.forEach(search => {
      const matching = matchesFor(search.criteria);
      const hasStableBaseline = Array.isArray(search.knownKeys);
      const known = new Set(hasStableBaseline ? search.knownKeys : []);
      const fresh = hasStableBaseline
        ? identitySet(matching).filter(key => !known.has(key)).length : 0;
      const card = elem("div", "rounded-2xl bg-[#252528] border border-white/10 p-3 space-y-2");
      const name = elem("p", "text-sm font-semibold text-white", search.title);
      const summary = elem("p", "text-xs text-[#b2b7c3]",
        hasStableBaseline
          ? matching.length + " зараз підходить · " + fresh + " нових від останньої перевірки"
          : matching.length + " зараз підходить · облік нових потребує оновлення");
      const actions = elem("div", "flex flex-wrap gap-2");
      actions.append(button("Показати", () => useSearch(search.id), "px-3 py-2 rounded-xl bg-[#0a84ff] text-white text-xs font-medium"));
      if (fresh || !hasStableBaseline) actions.append(button("Переглянуто", () => markRead(search.id)));
      actions.append(button("Видалити", () => deleteSearch(search.id)));
      card.append(name, summary, actions);
      root.append(card);
    });
  }
  function renderComparison() {
    const select = document.getElementById("smartRadarCompareSelect");
    const container = document.getElementById("smartRadarComparison");
    select.replaceChildren();
    container.replaceChildren();
    const deals = Array.isArray(LISTINGS) ? LISTINGS : [];
    const option = elem("option", "", "Оберіть квартиру");
    option.value = ""; select.append(option);
    deals.filter(d => listingKey(d) && !compareKeys.includes(listingKey(d)))
      .slice(0, 500).forEach(d => {
        const opt = elem("option", "", String(d.title || d.address || "Квартира").slice(0, 65));
        opt.value = listingKey(d);
        select.append(opt);
      });

    if (legacyCompareCount > 0) {
      const warning = elem("div",
        "rounded-xl border border-amber-500/40 p-3 text-xs text-amber-100 space-y-2");
      warning.setAttribute("role", "status");
      warning.append(elem("p", "", "Є старі порівняння, прив’язані лише до номерів (" +
        legacyCompareCount + "). Після оновлення каталогу ці номери можуть означати інші квартири, тому ми їх не переносимо."));
      warning.append(button("Видалити старі номери", discardLegacyCompare));
      container.append(warning);
    }

    if (!compareKeys.length) {
      container.append(elem("p", "text-xs text-[#8e8e93] py-2",
        "Додайте 2–3 квартири, щоб побачити реальні відмінності."));
      return;
    }
    compareKeys.forEach(key => {
      const matches = deals.filter(d => listingKey(d) === key);
      if (matches.length !== 1) {
        const missing = elem("div", "rounded-2xl border border-amber-500/40 p-3 space-y-2");
        missing.append(elem("p", "text-sm font-semibold",
          "Збережене порівняння недоступне"));
        missing.append(elem("p", "text-xs",
          "Оголошення знято, змінило адресу або його ідентичність неоднозначна. Ми не замінюємо квартиру іншою."));
        missing.append(button("Прибрати зі списку", () => removeCompare(key)));
        container.append(missing);
        return;
      }
      const d = matches[0];
      const card = elem("div", "rounded-2xl bg-[#252528] border border-white/10 p-3 space-y-2");
      card.append(elem("p", "text-sm font-semibold text-white", d.title || d.address || "Квартира"));
      const lines = [
        formatPrice(d.price),
        d.roomConflict ? "Кімнатність уточнюється" : (d.rooms ? d.rooms + " кімн." : "Кімнати не вказані"),
        d.area ? d.area + " м²" : "Площа не вказана",
        "Генератор у будинку: " + (d.generator ? "заявлено" : "не вказано"),
        "Інтернет під час відключень: " + (d.gpon ? "заявлено" : "не вказано"),
        "Тварини: " + (d.pets ? "дозволено за оголошенням" : "уточнюйте"),
        "Джерело: " + (d.source || "не вказано"),
        d.isOwnerVerified ? "Власник перевірений" : "Власника не перевірено"
      ];
      lines.forEach(t => card.append(elem("p", "text-xs text-[#b2b7c3]", t)));
      card.append(button("Прибрати", () => removeCompare(key)));
      container.append(card);
    });
  }
  function render() { renderSearches(); renderComparison(); }
  function open() {
    const panel = document.getElementById("smartRadarPanel");
    if (!panel) return;
    lastFocus = document.activeElement;
    panel.hidden = false;
    panel.style.display = "flex";
    render();
    document.getElementById("smartRadarName")?.focus();
  }
  function close() {
    const panel = document.getElementById("smartRadarPanel");
    if (panel) { panel.hidden = true; panel.style.display = "none"; }
    lastFocus?.focus?.();
  }
  function init() {
    if (!document.getElementById("filterContainer")) return;
    searches = read(SEARCH_KEY).filter(s => s && typeof s.id === "string" &&
      typeof s.title === "string" && s.criteria && typeof s.criteria === "object").slice(0, MAX_SEARCHES);
    compareKeys = readCompareKeys();
    legacyCompareCount = oldCompareCount();

    const trigger = button("◎ Мій радар", open,
      "shrink-0 px-3 py-1.5 rounded-full border border-[#0a84ff]/40 bg-[#0a84ff]/15 text-[#6bb6ff] font-semibold text-xs");
    trigger.id = "smartRadarOpen";
    document.getElementById("filterContainer").append(trigger);

    const overlay = elem("div", "fixed inset-0 z-[90] bg-black/70 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4");
    overlay.id = "smartRadarPanel"; overlay.hidden = true; overlay.style.display = "none";
    overlay.setAttribute("role", "dialog"); overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "smartRadarTitle");
    overlay.addEventListener("click", event => { if (event.target === overlay) close(); });
    const sheet = elem("div", "w-full sm:max-w-xl max-h-[90vh] overflow-y-auto rounded-t-[28px] sm:rounded-[28px] bg-[#1c1c1e] border border-white/10 p-4 sm:p-5 space-y-4");
    const top = elem("div", "flex items-center justify-between gap-3");
    const title = elem("h2", "text-white text-lg font-bold", "Мій розумний радар"); title.id = "smartRadarTitle";
    top.append(title, button("Закрити", close));
    sheet.append(top);
    sheet.append(elem("p", "text-xs text-[#b2b7c3]",
      "Збережені пошуки працюють на цьому пристрої. Нові збіги перевіряються під час відкриття застосунку. Telegram-сповіщення ще не підключені."));
    const name = elem("input", "w-full rounded-xl bg-[#2c2c2e] border border-white/10 p-3 text-sm text-white");
    name.id = "smartRadarName"; name.placeholder = "Назва пошуку (необов'язково)";
    name.maxLength = 50;
    sheet.append(name, button("Зберегти поточні фільтри", saveSearch,
      "w-full p-3 rounded-xl bg-[#0a84ff] font-semibold text-sm text-white"));
    const searchesTitle = elem("h3", "text-sm font-bold text-white", "Збережені пошуки");
    const searchesRoot = elem("div", "space-y-2"); searchesRoot.id = "smartRadarSearches";
    sheet.append(searchesTitle, searchesRoot);
    sheet.append(elem("h3", "text-sm font-bold text-white pt-2", "Порівняння квартир"));
    const select = elem("select", "flex-1 min-w-0 rounded-xl p-3 bg-[#2c2c2e] text-white text-xs border border-white/10");
    select.id = "smartRadarCompareSelect"; select.setAttribute("aria-label", "Квартира для порівняння");
    const cmpRow = elem("div", "flex items-center gap-2");
    cmpRow.append(select, button("Додати", addCompare,
      "px-4 py-3 rounded-xl bg-[#0a84ff] text-white text-xs font-medium"));
    sheet.append(cmpRow);
    const compared = elem("div", "grid grid-cols-1 sm:grid-cols-3 gap-2");
    compared.id = "smartRadarComparison"; sheet.append(compared);
    overlay.append(sheet);
    document.body.append(overlay);
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && !overlay.hidden) close();
    });
    render();
  }

  function addFromCard(value) {
    // Existing card buttons pass catalog numeric IDs, but never persist them.
    const matches = (Array.isArray(LISTINGS) ? LISTINGS : [])
      .filter(d => String(d.id) === String(value));
    if (matches.length !== 1) {
      notice("Ця квартира недоступна для порівняння");
      return false;
    }
    const key = listingKey(matches[0]);
    if (!key) {
      notice("Немає однозначного посилання на квартиру");
      return false;
    }
    if (compareKeys.includes(key)) {
      open();
      notice("Квартира вже є у порівнянні");
      return true;
    }
    if (compareKeys.length >= MAX_COMPARE) {
      open();
      notice("Можна порівнювати до 3 квартир");
      return false;
    }
    const next = compareKeys.concat(key);
    if (!persistCompare(next)) return false;
    compareKeys = next;
    render();
    notice("Квартиру додано до порівняння (" + compareKeys.length + "/3)");
    if (compareKeys.length > 1) open();
    return true;
  }

  window.KyivRadarSmart = {
    open,
    addFromCard,
    compareCount: () => compareKeys.length,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
