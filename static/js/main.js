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
  const lang = localStorage.getItem(LANG_KEY) || (navigator.language.startsWith("zh") ? "zh-CN" : "en");
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
