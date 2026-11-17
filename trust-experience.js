/* Kyiv Radar 1.8 — clear, evidence-based information at the decision point.
   The card remains quiet; verification details are shown inside the listing. */
(() => {
  "use strict";
  const FRESH_MS = 14 * 24 * 60 * 60 * 1000;
  const imported = item => ["OLX", "DOM.RIA"].includes(String(item?.source || "").toUpperCase());
  const fresh = value => {
    if (!value || typeof value !== "string") return false;
    const ms = Date.parse(value);
    return Number.isFinite(ms) && Date.now() - ms >= -5 * 60 * 1000
      && Date.now() - ms <= FRESH_MS;
  };
  const textElement = (tag, text, cls) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    el.textContent = text;
    return el;
  };

  function updateDetails(id) {
    const item = Array.isArray(LISTINGS) ? LISTINGS.find(v => v && v.id === id) : null;
    if (!item || !imported(item)) return;
    const verified = item.reviewedByRadar === true
      && item.actualityConfirmed === true && fresh(item.verifiedAt);
    const verification = document.getElementById("modalVerifiedDate");
    const label = verified ? "Наявність перевірено" : "Наявність не перевірена";
    if (verification) {
      verification.textContent = verified
        ? label + " · " + new Intl.DateTimeFormat("uk-UA", {
          dateStyle: "medium", timeZone: "Europe/Kyiv"
        }).format(new Date(item.verifiedAt))
        : label;
    }

    const badge = document.getElementById("modalVerificationTag");
    if (badge) {
      badge.textContent = verified ? "Перевірено" : "Не перевірено";
      badge.className = "kr-trust-badge" + (verified ? " verified" : "");
    }
    const details = document.getElementById("modalSourceDetails");
    if (details) {
      details.replaceChildren();
      const source = String(item.source || "зовнішнього джерела");
      const from = textElement("p", "Оголошення з " + source + ".", "kr-trust-source");
      const summary = verified
        ? "Наявність підтверджено під час перевірки. Власника, комісію та умови під час відключень перевіряють окремо."
        : "Наявність, комісію та власника не перевірено. Перед домовленістю уточніть умови за оригінальним оголошенням.";
      details.append(from, textElement("p", summary, "kr-trust-description"));
    }
  }

  function init() {
    const original = window.openDealModalById;
    if (typeof original === "function") {
      window.openDealModalById = function(id) {
        const result = original.apply(this, arguments);
        updateDetails(id);
        return result;
      };
    }
    const badge = document.getElementById("modalSourceBadge");
    if (badge) badge.setAttribute("aria-hidden", "true");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded",init);
  else init();
})();
