import { DOC_KEY, LANG_KEY, setLocale, showError, state } from "./core.js";
import { openDoc, renderAll, scaleFactor } from "./view.js";
import { setTool } from "./tools.js";
import { selectionAlign } from "./selection.js";
import { loadFonts } from "./fonts.js";
import { bindEvents } from "./events.js";
import { bindSizeAndColor, buildToolbarControls } from "./toolbar.js";
import { startLifecycle } from "./lifecycle.js";
import { bindPageTools } from "./dialogs.js";

// ---------- start ----------

async function init() {
  startLifecycle();
  bindEvents();
  bindPageTools();
  buildToolbarControls();
  bindSizeAndColor();
  setTool("select");
  const detected = { zh: "zh-CN", ja: "ja", ko: "ko" }[navigator.language.slice(0, 2)] || "en";
  const lang = localStorage.getItem(LANG_KEY) || detected;
  await setLocale(lang);
  await loadFonts();
  const saved = localStorage.getItem(DOC_KEY);
  if (saved) {
    try {
      await openDoc(saved);
    } catch (_) {
      localStorage.removeItem(DOC_KEY);
    }
  }
  renderAll();
}

// Test hook: lets the browser tests read app state. Not used by the app itself.
window.pdfStudio = { state, openDoc, scaleFactor, selectionAlign };

init().catch(showError);
