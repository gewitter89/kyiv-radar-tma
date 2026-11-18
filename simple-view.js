/* Kyiv Radar 1.7.2: declutter, do not remove capabilities.
   Primary results are apartments; map and complex filters are optional. */
(() => {
  "use strict";
  const LAST_VIEW = "kr_preferred_view_v1";
  function createButton(label, onClick, className) {
    const button = document.createElement("button");
    button.type = "button"; button.textContent = label;
    if (className) button.className = className;
    button.addEventListener("click", onClick);
    return button;
  }
  function createHelp() {
    const dialog = document.createElement("dialog");
    dialog.id = "krSimpleHelp";
    dialog.setAttribute("aria-label", "Що означають позначки у квартирах");
    dialog.style.cssText = "max-width:min(92vw,510px);border:1px solid #41546f;border-radius:20px;padding:24px;background:#172235;color:#f5f8ff;box-shadow:0 18px 65px #0009;";
    const heading = document.createElement("h2");
    heading.textContent = "Що означають позначки?";
    heading.style.cssText = "font-size:20px;font-weight:750;margin-bottom:14px";
    dialog.append(heading);
    [
      ["⚡ Генератор у будинку", "В оголошенні заявлено генератор. Уточніть, чи працюють саме ваша квартира, ліфт, вода й опалення."],
      ["🌐 Інтернет під час відключень", "Зазначено оптоволоконне підключення (GPON). Для роботи без світла потрібні живлення роутера й оптичного термінала та резервне живлення обладнання провайдера."],
      ["Перевірка", "Позначка «заявлено» не означає, що ми перевірили умову. Власника, актуальність житла та комісію потрібно уточнювати."],
      ["Джерело", "Ми зберігаємо походження оголошень та посилання на оригінал у подробицях квартири, щоб ви могли перевірити інформацію."]
    ].forEach(([title,description]) => {
      const p = document.createElement("p");
      p.style.cssText = "font-size:14px;line-height:1.55;margin:0 0 12px;color:#c0cce0";
      const b = document.createElement("strong");
      b.textContent = title; b.style.cssText = "display:block;color:#f7f9ff;margin-bottom:3px";
      p.append(b,document.createTextNode(description)); dialog.append(p);
    });
    // A manual, user-gesture fallback if Telegram rejects auto fullscreen.
    // Keep it in the info panel rather than cluttering the catalog header.
    const shell = window.KyivRadarTelegramShell;
    if (shell?.supported) {
      const full = createButton("", () => {
        if (shell.isFullscreen()) shell.exit(true);
        else shell.request(true);
      });
      full.id = "krTelegramFullscreenToggle";
      full.style.cssText = "min-height:44px;background:transparent;color:#dceaff;border:1px solid #5c7394;padding:9px 14px;border-radius:11px;font-size:13px;font-weight:650;width:100%;margin:4px 0 12px;";
      const refresh = active => {
        full.textContent = active ? "Повернути звичайний вигляд" : "Відкрити на весь екран";
        full.setAttribute("aria-pressed", String(active));
      };
      shell.listen(refresh);
      refresh(shell.isFullscreen());
      dialog.append(full);
    }
    const done = createButton("Зрозуміло", () => dialog.close());
    done.style.cssText = "min-height:44px;background:#e5eeff;color:#152945;padding:9px 20px;border-radius:11px;font-size:14px;font-weight:700;width:100%;";
    dialog.append(done);
    dialog.addEventListener("click", event => { if(event.target === dialog) dialog.close(); });
    document.body.append(dialog);
    return dialog;
  }
  function init() {
    if (!document.getElementById("filterContainer")) return;
    document.documentElement.classList.add("kr-simple");
    const hero = document.querySelector("#krHero");
    if (hero) {
      const title = hero.querySelector("h1");
      const desc = hero.querySelector(".kr-hero-copy > p:not(.kr-hero-eyebrow)");
      if (title) title.textContent = "Квартири в Києві — легко знайти";
      if (desc) desc.textContent = "Ціна, район та умови під час відключень";
    }

    const filters = document.getElementById("filterContainer");
    filters.dataset.more = "false";
    ["btnSortFilter", "filter20k", "filterPower", "filterPets", "filterFavs"]
      .forEach(id => document.getElementById(id)?.classList.add("kr-extra-filter"));

    // Give separate, meaningful controls for power and fiber internet.
    const generator = document.querySelector("#filterPower span:last-child");
    if (generator) generator.textContent = "Генератор у будинку";
    const internet = createButton("🌐 Інтернет під час відключень", () => setFilter("gpon"),
      "kr-extra-filter font-medium text-white");
    internet.id = "filterInternet";
    internet.setAttribute("aria-label","Інтернет під час відключень: заявлене оптоволокно");
    document.getElementById("filterPower")?.insertAdjacentElement("afterend",internet);

    const more = createButton("Фільтри", () => {
      const expanded = filters.dataset.more !== "true";
      filters.dataset.more = expanded ? "true" : "false";
      more.setAttribute("aria-expanded",String(expanded));
      more.textContent = expanded ? "Сховати" : "Фільтри";
    });
    more.id = "krMoreFilters";
    more.setAttribute("aria-expanded","false");
    more.setAttribute("aria-controls","filterContainer");
    document.getElementById("filter15k")?.insertAdjacentElement("afterend",more);

    // One honest note for the whole list is clearer than repeating warnings.
    const help = createHelp();
    const status = document.getElementById("krResultsBar");
    if (status) {
      const info = createButton("ⓘ Про дані", () => help.showModal(), "kr-reset");
      info.id = "krSimpleInfo";
      info.setAttribute("aria-label","Дізнатися про перевірку оголошень та інтернет під час відключень");
      const mode = document.getElementById("floatingViewToggle");
      status.insertBefore(info,mode || null);
    }

    const search = document.getElementById("searchInput");
    if (search) search.placeholder = "Район або назва квартири…";

    // New visitors should see apartments, not a map filling their whole screen.
    let savedView;
    try { savedView = localStorage.getItem(LAST_VIEW); } catch(_) {}
    if (typeof setViewMode === "function" && savedView !== "map") setViewMode("list");

    // Retain active advanced filters in view so no invisible criterion confuses.
    const oldRender = window.renderAll;
    if (typeof oldRender === "function") {
      window.renderAll = function() {
        const out = oldRender.apply(this,arguments);
        const f = ACTIVE_FILTERS || {};
        if (f.gpon || f.generator || f.pets || f.favs || f.maxPrice === 20000) {
          filters.dataset.more = "true";
          more.textContent = "Сховати";
          more.setAttribute("aria-expanded","true");
        }
        const all = document.getElementById("filterAll");
        if (all) all.textContent = "Усі";
        const internetButton = document.getElementById("filterInternet");
        if (internetButton) {
          internetButton.setAttribute("aria-pressed",String(Boolean(f.gpon)));
          internetButton.style.background = f.gpon ? "#285da7" : "";
        }
        return out;
      };
    }
    const all = document.getElementById("filterAll");
    if(all) all.textContent = "Усі";
    if (typeof window.renderAll === "function") window.renderAll();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded",init);
  else init();
})();
