/* Kyiv Radar 1.11 — purpose-built mobile controls, no duplicate chrome.
 * DOM layout only; existing handlers, cards, and published data are unchanged.
 */
(() => {
  "use strict";

  function initMainToolbar() {
    const header = document.querySelector("body > header.kr-compact-masthead");
    const hero = document.getElementById("krHero");
    const filterBar = document.getElementById("filterBarWrapper");
    const filters = document.getElementById("filterContainer");
    const switcher = document.getElementById("floatingViewToggle");
    const radar = document.getElementById("smartRadarOpen");
    const results = document.getElementById("krResultsBar");
    if (!header || !hero || !filterBar || !filters || !switcher || !radar || !results
        || document.documentElement.classList.contains("kr-unified-111")) return;

    // The native Telegram bar already says “Київ Радар”. This is the content
    // title, not another brand or advertising claim.
    const heading = hero.querySelector("h1");
    if (heading) heading.textContent = "Квартири в Києві";

    // Put the map/list mode next to the title, not in a second standalone bar.
    // The mode buttons and handlers are moved, not re-created.
    hero.appendChild(switcher);
    switcher.setAttribute("role", "group");
    switcher.setAttribute("aria-label", "Відображення квартир: карта або список");

    // Put saved searches where people actually choose criteria. The original
    // button keeps the exact Smart Radar click listener.
    const radarSlot = document.createElement("div");
    radarSlot.id = "krRadarSlot";
    radarSlot.className = "kr-radar-slot";
    radar.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true" focusable="false">' +
      '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/>' +
      '<path d="M12 12 18 6"/><circle cx="18" cy="6" r="1.2" fill="currentColor" stroke="none"/></svg>' +
      '<span class="kr-radar-label">Мій радар</span>';
    radar.setAttribute("aria-label", "Мій радар: збережені пошуки та порівняння");
    radar.title = "Мій радар";
    radarSlot.appendChild(radar);
    filterBar.appendChild(radarSlot);

    const filterMore = document.getElementById("krMoreFilters");
    if (filterMore) filterMore.setAttribute("aria-label", "Показати або приховати додаткові фільтри");

    // The source remains visible as plain text, with its disclosure button.
    const source = document.getElementById("krDataStatus");
    if (source) source.title = "Дані імпортовані з джерел. Наявність, власник і комісія не перевірені для кожної пропозиції.";

    document.documentElement.classList.add("kr-unified-111");
  }

  function setDialogViewport() {
    const visual = window.visualViewport;
    if (!visual) return;
    // Handles iPhone/Android keyboard shrinking the usable viewport.
    document.documentElement.style.setProperty("--kr-landlord-vh", Math.max(240, visual.height) + "px");
  }

  function initLandlordSheet() {
    const modal = document.getElementById("landlordModal");
    if (!modal || modal.dataset.krScrollReady) return;
    modal.dataset.krScrollReady = "1";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", "Опублікувати квартиру");
    const formScroll = modal.querySelector(":scope > div > div:last-child");
    if (formScroll) {
      formScroll.id = "krLandlordScroll";
      formScroll.setAttribute("tabindex", "0");
      formScroll.setAttribute("aria-label", "Форма подання квартири. Прокрутіть для всіх полів.");
    }
    const submit = document.getElementById("llSubmitBtn");
    if (submit) submit.setAttribute("type", "button");
    setDialogViewport();
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", setDialogViewport, {passive:true});
    }
    // Restore the top of the sheet when opened again; do not reset form fields.
    const observer = new MutationObserver(() => {
      if (modal.classList.contains("hidden")) return;
      setDialogViewport();
      if (formScroll) formScroll.scrollTop = 0;
    });
    observer.observe(modal,{attributes:true,attributeFilter:["class"]});
  }

  function init() {
    initMainToolbar();
    initLandlordSheet();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded",init);
  else init();
})();