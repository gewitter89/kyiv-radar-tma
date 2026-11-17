/* Kyiv Radar 1.9 — real in-app Kyiv skyline, blue/yellow curve and listing photo gallery.
   Works on top of the existing catalog: no source records or Telegram credentials are changed. */
(() => {
  "use strict";

  const skyline = '<svg viewBox="0 0 300 100" preserveAspectRatio="xMidYMax meet" focusable="false" aria-hidden="true">' +
    '<path fill="#233d5e" d="M0 100V78h20V65h16V77h15V57h7V45h3V39h2v6h7v12h10V71h14V55h7V44h3v-7h3v7h7v11h9V70h11V61h11V77h12V66h13V57h4V48h3V41h3v7h4v9h13V75h18V62h12V71h11V56h14V100Z"/>' +
    '<path fill="#365474" d="M0 100V91h29V80h21V88h13V74h16V88h20V79h18V86h17V67h12V86h21V73h12V90h21V80h9V100Z"/>' +
    '<path fill="#1a3452" d="M148 100V62h8V49h4v-7h3V29h2V20h2v9h3v13h3v7h4v13h8v38Zm76 0V61h6v-6h3v-7h2v-9h2v9h2v7h3v6h7v39Z"/>' +
    '<path fill="#7c99b2" opacity=".66" d="M235 74l2-21 1-6 2-4-1-8-8-4-9 4-1 5-4 3-2-3 5-8 12-6 5 3 8-7 5-8 4 1-1 9-10 15-1 6 2 9 2 20Z"/>' +
    '<path fill="#d0a954" opacity=".52" d="M272 98v-7h28v9h-28Z"/>' +
    '</svg>';

  const wave = '<svg viewBox="0 0 400 18" preserveAspectRatio="none" focusable="false" aria-hidden="true">' +
    '<defs><linearGradient id="krUaWave19" x1="0%" y1="0%" x2="100%" y2="0%">' +
    '<stop offset="0%" stop-color="#22a5ff"/><stop offset="49%" stop-color="#3488e5"/>' +
    '<stop offset="77%" stop-color="#f1cd57"/><stop offset="100%" stop-color="#f5d464"/>' +
    '</linearGradient></defs>' +
    '<path d="M0 12 C67 -2 136 12 202 13 S323 3 400 11" fill="none" stroke="url(#krUaWave19)" stroke-width="2.6" stroke-linecap="round"/>' +
    '</svg>';

  const logo = '<svg viewBox="0 0 32 32" fill="none" focusable="false" aria-hidden="true">' +
    '<circle cx="16" cy="16" r="12.5" stroke="#78b8fb" stroke-width="2"/>' +
    '<circle cx="16" cy="16" r="7.8" stroke="#78b8fb" stroke-width="1.7"/>' +
    '<circle cx="16" cy="16" r="3.3" fill="#8fc7ff"/>' +
    '<path d="M16 16 23.4 8.6" stroke="#9ed0ff" stroke-width="1.6" stroke-linecap="round"/>' +
    '<circle cx="23.5" cy="8.5" r="2.6" fill="#f3ce60"/>' +
    '</svg>';

  function initKyivIdentity() {
    const hero = document.getElementById("krHero");
    if (hero && !hero.querySelector(".kr-ukraine-curve")) {
      const city = document.createElement("div");
      city.className = "kr-kyiv-skyline";
      city.setAttribute("aria-hidden", "true");
      city.innerHTML = skyline;
      const line = document.createElement("div");
      line.className = "kr-ukraine-curve";
      line.setAttribute("aria-hidden", "true");
      line.innerHTML = wave;
      hero.append(city, line);
    }
    const brand = document.querySelector(".kr-brand-label strong");
    if (brand) brand.textContent = "Київ Радар";
    const mark = document.querySelector(".kr-brand-mark");
    if (mark) mark.innerHTML = logo;
    const status = document.getElementById("krDataStatus");
    if (status) status.title = "Дані з джерел. Актуальність кожної квартири перевіряється окремо.";
  }

  function getPhotos(listingId) {
    const records = typeof LISTINGS !== "undefined" && Array.isArray(LISTINGS) ? LISTINGS : [];
    const item = records.find(entry => String(entry.id) === String(listingId));
    if (!item || !Array.isArray(item.images)) return [];
    const seen = new Set();
    const photos = [];
    for (const raw of item.images) {
      const url = typeof safePhotoUrl === "function" ? safePhotoUrl(raw) : "";
      if (url && !seen.has(url)) {
        seen.add(url);
        photos.push(url);
      }
    }
    return photos;
  }

  function enhanceCard(card) {
    if (card.dataset.krGalleryReady) return;
    card.dataset.krGalleryReady = "1";
    const onclick = card.getAttribute("onclick") || "";
    const match = onclick.match(/openDealModalById\((\d+)\)/);
    if (!match) return;
    const photos = getPhotos(match[1]);
    if (photos.length < 2) return;
    const frame = card.querySelector(":scope > .relative.h-48");
    const image = frame && frame.querySelector("img");
    if (!frame || !image) return;

    image.classList.add("kr-gallery-image");
    image.draggable = false;
    frame.setAttribute("role", "group");
    frame.setAttribute("aria-label", "Фотографії квартири. Гортайте вліво чи вправо.");
    frame.tabIndex = 0;
    const previousCount = frame.querySelector("span.font-mono");
    if (previousCount) previousCount.remove();

    const controls = document.createElement("div");
    controls.className = "kr-gallery-controls";
    const previous = document.createElement("button");
    previous.type = "button";
    previous.className = "kr-gallery-nav kr-gallery-prev";
    previous.setAttribute("aria-label", "Попереднє фото квартири");
    previous.textContent = "‹";
    const next = document.createElement("button");
    next.type = "button";
    next.className = "kr-gallery-nav kr-gallery-next";
    next.setAttribute("aria-label", "Наступне фото квартири");
    next.textContent = "›";
    const count = document.createElement("span");
    count.className = "kr-gallery-count";
    count.setAttribute("role", "status");
    count.setAttribute("aria-live", "polite");
    const dots = document.createElement("div");
    dots.className = "kr-gallery-dots";
    dots.setAttribute("aria-hidden", "true");
    controls.append(previous, next, dots, count);
    frame.append(controls);

    let index = 0;
    let suppressClickUntil = 0;
    function display() {
      image.src = photos[index];
      image.alt = "Фото квартири " + (index + 1) + " з " + photos.length;
      count.textContent = (index + 1) + "/" + photos.length;
      dots.replaceChildren();
      const visible = Math.min(5, photos.length);
      const start = Math.max(0, Math.min(index - Math.floor(visible / 2), photos.length - visible));
      for (let i = start; i < start + visible; i++) {
        const dot = document.createElement("span");
        dot.className = "kr-gallery-dot" + (i === index ? " is-active" : "");
        dots.append(dot);
      }
    }
    function navigate(delta) {
      index = (index + delta + photos.length) % photos.length;
      display();
    }
    previous.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      navigate(-1);
    });
    next.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      navigate(1);
    });
    frame.addEventListener("keydown", event => {
      if (event.target !== frame) return;
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      event.stopPropagation();
      navigate(event.key === "ArrowRight" ? 1 : -1);
    });
    let start = null;
    frame.addEventListener("touchstart", event => {
      if (event.touches.length !== 1) { start = null; return; }
      const t = event.touches[0];
      start = {x:t.clientX, y:t.clientY};
    }, {passive:true});
    frame.addEventListener("touchend", event => {
      if (!start || event.changedTouches.length !== 1) {start = null;return;}
      const t = event.changedTouches[0];
      const dx = t.clientX - start.x;
      const dy = t.clientY - start.y;
      start = null;
      if (Math.abs(dx) < 42 || Math.abs(dx) < Math.abs(dy) * 1.25) return;
      suppressClickUntil = Date.now() + 750;
      navigate(dx < 0 ? 1 : -1);
    }, {passive:true});
    frame.addEventListener("touchcancel", () => {start = null;}, {passive:true});
    frame.addEventListener("click", event => {
      if (Date.now() >= suppressClickUntil) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    }, true);

    // Imported source claims must not masquerade as a verified power capability.
    const badges = frame.querySelectorAll(".absolute.top-2\\.5.left-2\\.5 span");
    for (const badge of badges) {
      if (badge.textContent.trim() === "⚡ Генератор") badge.textContent = "⚡ Генератор · заявлено";
    }
    display();
  }

  function enhanceGallery() {
    const list = document.getElementById("listViewContainer");
    if (!list) return;
    for (const card of list.querySelectorAll(":scope > div[onclick]")) enhanceCard(card);
  }

  function init() {
    initKyivIdentity();
    const list = document.getElementById("listViewContainer");
    if (!list || list.dataset.krGalleryObserver) return;
    list.dataset.krGalleryObserver = "1";
    const observer = new MutationObserver(() => enhanceGallery());
    observer.observe(list, {childList:true});
    enhanceGallery();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
