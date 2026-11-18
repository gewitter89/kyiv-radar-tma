/* Kyiv Signal theme engine. Default is deliberate graphite, auto follows
   Telegram / OS only when selected. All preferences are device-local. */
(() => {
  "use strict";
  const KEY = "kr_theme_mode_v1";
  const MODES = ["dark", "light", "auto"];
  const COLORS = {
    dark: {header:"#161E29", background:"#10151D", bottom:"#0E2037"},
    light: {header:"#EDF2F7", background:"#F5F7F9", bottom:"#EDF2F7"}
  };
  let mode = "dark";
  try {
    const stored = localStorage.getItem(KEY);
    if (MODES.includes(stored)) mode = stored;
  } catch (_) {}
  const media = window.matchMedia?.("(prefers-color-scheme: light)");
  function activeTheme() {
    if (mode !== "auto") return mode;
    const telegram = window.Telegram?.WebApp?.colorScheme;
    if (telegram === "light" || telegram === "dark") return telegram;
    return media?.matches ? "light" : "dark";
  }
  function refreshButtons() {
    document.querySelectorAll(".kr-theme-option").forEach(btn => {
      btn.setAttribute("aria-pressed", String(btn.dataset.mode === mode));
    });
  }
  function apply() {
    const resolved = activeTheme();
    const colors = COLORS[resolved];
    document.documentElement.setAttribute("data-kr-theme", resolved);
    document.documentElement.style.colorScheme = resolved;
    // The native Telegram bar and the first pixel of the HTML masthead
    // must use exactly the same opaque color (not merely nearby shades).
    document.documentElement.style.setProperty("--kr-header", colors.header);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", colors.header);
    const tg = window.Telegram?.WebApp;
    try {
      tg?.setHeaderColor?.(colors.header);
      tg?.setBackgroundColor?.(colors.background);
      // The *open* Mini App bottom bar is a Telegram native surface.
      // This is NOT the separate minimized-app tab, whose label is native.
      tg?.setBottomBarColor?.(colors.bottom);
    } catch (_) { /* Telegram clients differ in supported API versions. */ }
    refreshButtons();
    return resolved;
  }
  function set(next) {
    if (!MODES.includes(next)) return false;
    mode = next;
    try { localStorage.setItem(KEY, next); } catch (_) {}
    apply();
    return true;
  }
  function insertControls() {
    const dialog = document.getElementById("krSimpleHelp");
    if (!dialog || dialog.querySelector(".kr-theme-controls")) return;
    const group = document.createElement("div");
    group.className = "kr-theme-controls";
    const title = document.createElement("strong");
    title.className = "kr-theme-heading";
    title.textContent = "Оформлення";
    const options = document.createElement("div");
    options.setAttribute("role", "group");
    options.setAttribute("aria-label", "Оберіть тему застосунку");
    options.className = "kr-theme-options";
    for (const [value, label] of [["dark","Темна"],["light","Світла"],["auto","Авто"]]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "kr-theme-option";
      btn.dataset.mode = value;
      btn.textContent = label;
      btn.setAttribute("aria-pressed", String(value === mode));
      btn.addEventListener("click", () => set(value));
      options.append(btn);
    }
    const hint = document.createElement("small");
    hint.className = "kr-theme-hint";
    hint.textContent = "Авто — тема Telegram або системи";
    group.append(title, options, hint);
    const done = dialog.lastElementChild;
    if (done) dialog.insertBefore(group, done);
    else dialog.append(group);
  }
  window.KyivRadarTheme = Object.freeze({
    set, getMode:()=>mode, getTheme:activeTheme,
    nativeColors:()=>COLORS[activeTheme()], apply
  });
  apply();
  function init() {
    insertControls();
    apply();
    if (media?.addEventListener) media.addEventListener("change", () => {if(mode === "auto") apply();});
    try {window.Telegram?.WebApp?.onEvent?.("themeChanged", () => {if(mode === "auto") apply();});} catch (_) {}
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded",init);
  else init();
})();