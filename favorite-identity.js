/* v1.30: stable, privacy-minimized favorite identities.
 * URL + source, never mutable catalog positions or transient numeric IDs.
 * A legacy numeric favorite is quarantined, never reassigned automatically.
 */
(function (global) {
  "use strict";
  const STORAGE_KEY = "kr_favs_v2";
  const LEGACY_KEY = "kr_favs";
  const MAX_ENTRIES = 2000;
  const SAFE_QUERY = new Set(["id", "offer_id", "listing_id", "object_id", "internal_id"]);
  const TRACKERS = new Set(["gclid", "fbclid", "yclid", "msclkid", "gbraid", "wbraid"]);

  function stableKey(item) {
    if (!item || typeof item !== "object" || typeof item.source !== "string" ||
        typeof item.url !== "string") return null;
    const source = item.source.normalize("NFC").trim().toLowerCase();
    if (!source || source.length > 80 || /[\x00-\x1f\x7f|]/.test(source)) return null;
    try {
      const url = new URL(item.url);
      if (url.protocol !== "https:" || url.username || url.password ||
          !url.hostname.includes(".") || url.hostname.endsWith(".local") ||
          item.url.length > 1800) return null;
      url.hash = "";
      // Discard tracking, but retain only explicitly recognized public listing IDs.
      const pairs = [];
      for (const [name, value] of url.searchParams.entries()) {
        const normalized = name.toLowerCase();
        if (normalized.startsWith("utm_") || TRACKERS.has(normalized)) continue;
        if (!SAFE_QUERY.has(normalized) || !/^[\w-]{1,100}$/.test(value))
          return null; // Unknown params might contain authorization tokens.
        pairs.push([normalized, value]);
      }
      if (!pairs.length && (url.pathname === "/" || url.pathname === "")) return null;
      pairs.sort(([a, v], [b, w]) => a.localeCompare(b) || v.localeCompare(w));
      url.search = "";
      for (const [k, v] of pairs) url.searchParams.append(k, v);
      // Prevent a trivial trailing slash difference from losing a saved card.
      if (url.pathname.length > 1) url.pathname = url.pathname.replace(/\/+$/, "");
      return "kr2|" + encodeURIComponent(source) + "|" + url.href;
    } catch (error) {
      return null;
    }
  }

  function load() {
    const keys = new Set();
    const legacy = new Set();
    try {
      const snapshot = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (snapshot && snapshot.version === 2 && Array.isArray(snapshot.keys)) {
        snapshot.keys.slice(0, MAX_ENTRIES).forEach(key => {
          if (typeof key === "string" && key.startsWith("kr2|") &&
              key.length < 2200) keys.add(key);
        });
      }
    } catch (error) { /* Private browsing: keep working in this session. */ }
    try {
      // Old storage only holds numbers. There is no proof that ID=17 still
      // refers to the exact same offer after a feed reorder. Never silently
      // upgrade it to a new URL/source key or show another owner's listing.
      const saved = JSON.parse(localStorage.getItem(LEGACY_KEY) || "[]");
      if (Array.isArray(saved)) saved.slice(0, MAX_ENTRIES).forEach(value => {
        const n = Number(value);
        if (Number.isSafeInteger(n) && n > 0) legacy.add(n);
      });
    } catch (error) { /* Ignore invalid legacy storage; don't erase it. */ }
    return { keys, legacy };
  }

  function save(keys) {
    if (!(keys instanceof Set) || keys.size > MAX_ENTRIES) return false;
    const list = [...keys];
    if (!list.every(x => typeof x === "string" && x.startsWith("kr2|") && x.length < 2200))
      return false;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 2, keys: list }));
      return true;
    } catch (error) {
      return false;
    }
  }

  function discardLegacy() {
    try { localStorage.removeItem(LEGACY_KEY); return true; }
    catch (error) { return false; }
  }
  global.KRFavoriteIdentity = Object.freeze({
    stableKey, load, save, discardLegacy, STORAGE_KEY, LEGACY_KEY
  });
})(window);
