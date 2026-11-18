/* Kyiv Radar v1.37: supported Telegram immersive mode, NEVER CSS overlays
 * over a native Telegram surface. Unsupported clients retain normal UI.
 * No token, authentication or server changes.
 */
(() => {
  "use strict";
  const KEY = "kr_tg_fullscreen_choice_v1";
  const root = document.documentElement;
  const tg = window.Telegram?.WebApp;
  const supported = !!(tg && typeof tg.requestFullscreen === "function" &&
    ["ios", "android"].includes(String(tg.platform || "").toLowerCase()) &&
    typeof tg.initData === "string" && tg.initData.length > 0);
  const listeners = new Set();
  // Native close removes the Mini App session. A swipe to minimize instead
  // leaves Telegram's own Mini App Bar with the bot @username visible.
  // Never attempt to manipulate Telegram's native bar with CSS.
  const canClose = !!(tg && typeof tg.close === "function" &&
    typeof tg.initData === "string" && tg.initData.length > 0);
  function closeCompletely() {
    if (!canClose) return false;
    try {
      // Only call from an explicit "Close app" button user gesture.
      tg.close();
      return true;
    } catch (_) { return false; }
  }

  function preference() {
    try { return localStorage.getItem(KEY); } catch (_) { return null; }
  }
  function save(value) {
    try { localStorage.setItem(KEY, value); } catch (_) {}
  }
  function sync() {
    const active = supported && tg.isFullscreen === true;
    root.classList.toggle("kr-telegram-fullscreen", active);
    root.classList.toggle("kr-telegram-fullscreen-supported", supported);
    for (const cb of listeners) { try { cb(active); } catch (_) {} }
    return active;
  }
  function request(userChoice = false) {
    if (!supported) return false;
    if (userChoice) save("on");
    if (tg.isFullscreen === true) return sync();
    try {
      tg.requestFullscreen();
      // Do NOT add the fullscreen class before Telegram confirms the mode.
      // On older clients the request may be ignored or explicitly rejected.
      return true;
    } catch (_) {
      sync();
      return false;
    }
  }
  function exit(userChoice = false) {
    if (!supported || typeof tg.exitFullscreen !== "function") return false;
    if (userChoice) save("off");
    try {
      tg.exitFullscreen();
      return true;
    } catch (_) {
      sync();
      return false;
    }
  }
  function listen(callback) {
    if (typeof callback !== "function") return () => {};
    listeners.add(callback);
    return () => listeners.delete(callback);
  }
  function init() {
    sync();
    if (!supported) return;
    try {
      tg.onEvent?.("fullscreenChanged", sync);
      tg.onEvent?.("fullscreenFailed", sync);
      tg.onEvent?.("contentSafeAreaChanged", sync);
      tg.onEvent?.("safeAreaChanged", sync);
    } catch (_) { /* no native event bridge; normal view is safe */ }
    // The bot's @username in native UI cannot be hidden by page CSS. Ask
    // Telegram to use its official immersive mode on eligible phones.
    if (preference() !== "off") request();
  }
  window.KyivRadarTelegramShell = Object.freeze({
    supported, request, exit, listen, sync, canClose, closeCompletely,
    isFullscreen: () => !!(supported && tg.isFullscreen === true)
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, {once:true});
  } else init();
})();