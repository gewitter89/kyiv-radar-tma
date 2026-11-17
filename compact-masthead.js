/* Kyiv Radar 1.10 — a single, compact masthead for the Telegram Mini App.
   Layout only. Retains native Telegram chrome and all existing functional controls. */
(() => {
  "use strict";

  function init() {
    const header = document.querySelector("body > header");
    const hero = document.getElementById("krHero");
    const brand = header?.querySelector("button.kr-brand");
    const search = document.getElementById("searchInput")?.parentElement;
    const add = header?.querySelector('button[onclick="openLandlordModal()"]');
    if (!header || !hero || !brand || !search || !add || header.classList.contains("kr-compact-masthead")) return;

    // Telegram already displays “Київ Радар”. Keep the city action but show
    // only its small radar mark, rather than repeating our full app name.
    brand.title = "Змінити місто";
    brand.setAttribute("aria-label", "Змінити місто, зараз Київ");
    add.setAttribute("aria-label", "Подати оголошення про квартиру");
    const searchRow = document.createElement("div");
    searchRow.className = "kr-compact-search-row";
    searchRow.append(brand, search, add);

    // The product statement now lives ABOVE the search field. The quiet Kyiv
    // skyline and the Ukrainian curve remain on this actual app component.
    // Keep the original #krHero ID and its live "Мій радар" action intact.
    header.append(hero, searchRow);
    header.classList.add("kr-compact-masthead");
    document.documentElement.classList.add("kr-compact");

    // Remove the redundant, straight flag stripe. Curved Ukrainian accents
    // inside the header and hero already carry the visual identity.
    const topStripe = document.body.firstElementChild;
    if (topStripe?.classList.contains("h-[2.5px]")) topStripe.hidden = true;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
