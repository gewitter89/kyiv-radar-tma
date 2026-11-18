/* Київ Радар v1.36 — truthful, field-specific listing passport.
 * No scraping, API calls or source rights inference. Displayed metadata
 * are never "verified" merely because a listing has been imported.
 * All untrusted strings are inserted using textContent, never innerHTML.
 */
(() => {
  "use strict";
  const FRESH_MS = 14 * 24 * 60 * 60 * 1000;
  const MAX_SOURCE_NAME = 90;

  function reviewedAt(value) {
    if (typeof value !== "string" ||
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/u.test(value)) return null;
    const time = Date.parse(value);
    return Number.isFinite(time) && time <= Date.now() && Date.now() - time <= FRESH_MS
      ? new Date(time) : null;
  }

  function validNumber(value, max) {
    return typeof value === "number" && Number.isFinite(value) && value > 0 && value <= max;
  }

  function makeRow(label, value, note, kind = "declared") {
    return {label, value, note, kind};
  }

  function snapshot(item) {
    if (!item || typeof item !== "object") return [];
    const rows = [];
    const source = typeof item.source === "string" && item.source.trim()
      ? item.source.trim().slice(0, MAX_SOURCE_NAME) : "Не зазначено";
    rows.push(makeRow("Джерело", source,
      "Назва джерела сама по собі не підтверджує права на публікацію або актуальність."));

    if (item.roomConflict === true) {
      rows.push(makeRow("Кімнатність", "Є суперечність",
        "Кількість кімнат не узгоджується із заголовком або описом. Потрібна перевірка.", "conflict"));
    } else if (Number.isSafeInteger(item.rooms) && item.rooms >= 1 && item.rooms <= 100) {
      rows.push(makeRow("Кімнатність", item.rooms + " кімн.",
        "Заявлено в каталозі; відповідність сторінці джерела окремо не підтверджена."));
    } else {
      rows.push(makeRow("Кімнатність", "Потрібно уточнити",
        "Немає надійної кількості кімнат. Не визначаємо її зі слів «студія» чи «спальня».", "unknown"));
    }

    rows.push(validNumber(item.price, 1_000_000_000)
      ? makeRow("Ціна", new Intl.NumberFormat("uk-UA").format(item.price) + " ₴",
          "Ціна заявлена в каталозі; валюту, період оренди та актуальність слід звірити у джерелі.")
      : makeRow("Ціна", "Немає даних", "Ціну не підтверджено.", "unknown"));

    rows.push(validNumber(item.area, 100_000)
      ? makeRow("Площа", item.area + " м²",
          "Площу заявлено в оголошенні. Незалежної перевірки немає.")
      : makeRow("Площа", "Немає даних", "Площу не вказано.", "unknown"));

    const floor = item.floor;
    const total = item.totalFloors;
    const goodFloor = Number.isSafeInteger(floor) && floor > 0 && floor <= 300;
    const goodTotal = Number.isSafeInteger(total) && total > 0 && total <= 300;
    rows.push(goodFloor && goodTotal && floor > total
      ? makeRow("Поверх", "Є суперечність",
          "Поверх квартири перевищує поверховість будинку. Потрібна перевірка.", "conflict")
      : goodFloor
        ? makeRow("Поверх", String(floor) + (goodTotal ? "/" + total : ""),
            "Інформацію про поверх незалежно не перевірено.")
        : makeRow("Поверх", "Немає даних", "Поверх не вказано.", "unknown"));

    const confirmedDate = item.reviewedByRadar === true &&
      item.actualityConfirmed === true ? reviewedAt(item.verifiedAt) : null;
    if (confirmedDate) {
      const date = new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "medium", timeZone: "Europe/Kyiv"
      }).format(confirmedDate);
      rows.push(makeRow("Наявність", "Перевіряли " + date,
        "Це дата окремої перевірки, не гарантія, що житло досі вільне.", "reviewed"));
    } else {
      rows.push(makeRow("Наявність", "Не підтверджена",
        "Поточну доступність незалежно не перевірено або дані старші за 14 днів.", "unknown"));
    }

    rows.push(item.isOwnerVerified === true && item.reviewedByRadar === true
      ? makeRow("Власник", "Є позначка модерації",
          "Позначка перевірки власника в каталозі; деталі документів не публікуються.")
      : makeRow("Власник", "Не підтверджено",
          "Оголошення та його фотографії не доводять право власності.", "unknown"));

    rows.push(item.contactVerified === true && item.reviewedByRadar === true
      ? makeRow("Контакт", "Є позначка модерації",
          "Контакт і право здавати житло перевіряються окремо.")
      : makeRow("Контакт", "Не підтверджено",
          "Наявність номера в оголошенні не означає, що контакт перевірено.", "unknown"));

    rows.push(item.commissionVerified === true && item.reviewedByRadar === true
      ? makeRow("Комісія", "Позначено 0%",
          "Підтвердження комісії в каталозі не замінює умов договору.")
      : makeRow("Комісія", "Потрібно уточнити",
          "Умови оплати та можливі додаткові платежі не підтверджені.", "unknown"));

    return rows;
  }

  function render(item) {
    const root = document.getElementById("krListingPassport");
    const rowsContainer = document.getElementById("krPassportRows");
    const headline = document.getElementById("krPassportHeadline");
    if (!root || !rowsContainer || !headline) return;

    const rows = snapshot(item);
    rowsContainer.replaceChildren();
    const disputed = rows.some(row => row.kind === "conflict");
    const at = item?.reviewedByRadar === true && item?.actualityConfirmed === true
      ? reviewedAt(item.verifiedAt) : null;
    headline.textContent = disputed
      ? "Є розбіжності — уточніть характеристики"
      : at ? "Дані частково перевірено" : "Характеристики ще не підтверджено";

    for (const row of rows) {
      const wrapper = document.createElement("div");
      wrapper.className = "kr-passport-row";
      wrapper.dataset.status = row.kind;
      const dt = document.createElement("dt");
      dt.className = "kr-passport-label";
      dt.textContent = row.label;
      const dd = document.createElement("dd");
      dd.className = "kr-passport-cell";
      const value = document.createElement("strong");
      value.className = "kr-passport-value";
      value.textContent = row.value;
      const note = document.createElement("p");
      note.className = "kr-passport-note";
      note.textContent = row.note;
      dd.append(value, note);
      wrapper.append(dt, dd);
      rowsContainer.append(wrapper);
    }
    // Never carry an expanded passport over to another apartment.
    root.open = false;
  }

  function refreshCatalog() {
    const modal = document.getElementById("dealModal");
    if (!modal || modal.classList.contains("hidden") ||
        typeof currentModalDeal === "undefined" || !currentModalDeal) return;
    // A redraw may replace JS objects while retaining the exact same,
    // unique HTTPS source identity. Rehydrate that listing instead of
    // closing a legitimate detail modal mid-interaction. NEVER use the
    // transient numeric ID to select a replacement.
    const current = Array.isArray(LISTINGS) ? LISTINGS : [];
    if (current.includes(currentModalDeal)) return;
    const key = typeof window.favoriteKey === "function"
      ? window.favoriteKey(currentModalDeal) : null;
    const matches = key ? current.filter(item =>
      window.favoriteKey(item) === key) : [];
    if (matches.length === 1 &&
        typeof window.openDealModalById === "function") {
      // Source identity is stable; refresh all visible claims and contacts
      // from the new authorized row, never keep stale detail object.
      window.openDealModalById(matches[0].id);
      return;
    }
    // Withdrawn, malformed, duplicate or replaced source: close both the
    // details and pending report rather than exposing stale contact actions.
    if (typeof closeReportModal === "function") closeReportModal();
    if (typeof closeDealModal === "function") closeDealModal();
    currentModalDeal = null;
    if (typeof showToast === "function") {
      showToast("Оголошення змінилося або стало недоступним. Оновіть пошук.");
    }
  }

  function init() {
    const reportButton = document.getElementById("krPassportReport");
    if (reportButton) {
      reportButton.addEventListener("click", () => {
        if (typeof openReportModal === "function") openReportModal();
      });
    }
    const original = window.openDealModalById;
    if (typeof original === "function") {
      window.openDealModalById = function(id) {
        const result = original.apply(this, arguments);
        if (typeof currentModalDeal !== "undefined" && currentModalDeal?.id === id) {
          render(currentModalDeal);
        }
        return result;
      };
    }
  }

  window.KRListingPassport = Object.freeze({render, refreshCatalog});
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else init();
})();
