import { $, api, errorText, getJson, state, t, toast } from "./core.js";
import { runAction } from "./files.js";
import { renderAll } from "./view.js";

// ---------- watermarks ----------
// Rules are saved with the document. The page shows them, exports include them unless told otherwise.
// Hiding is a viewing choice only, so it is kept in this browser and never touches the file.

const MAX_RULES = 5;
const HIDE_KEY = "pdfstudio.watermarks";
const PAGES = /^(all|\d+(-\d+)?(,\d+(-\d+)?)*)$/;
const DEFAULT_RULE = {
  text: "{name}", rows: 2, cols: 2, size: 36, color: "#888888",
  opacity: 0.3, angle: 30, pages: "all", layer: "above", enabled: true,
};

let draft = null; // working copy while the dialog is open, null when closed
let selected = 0;
let hidden = readHidden();

function readHidden() {
  try {
    return localStorage.getItem(HIDE_KEY) === "1";
  } catch (_) {
    return false; // storage can be blocked; the choice then lasts until reload
  }
}

function writeHidden(value) {
  try {
    localStorage.setItem(HIDE_KEY, value ? "1" : "0");
  } catch (_) { /* blocked storage, see readHidden */ }
}

export function watermarkOpen() {
  return draft !== null;
}

// Page and thumbnail URLs add this, so a hidden or editing view asks for clean pages.
export function watermarkQuery() {
  return hidden || draft !== null ? "&watermark=0" : "";
}

export function syncWatermarkToggle() {
  const button = $("#watermark-toggle");
  button.disabled = !state.info;
  button.textContent = t(hidden ? "watermark_show" : "watermark_hide");
  button.setAttribute("aria-pressed", String(hidden));
}

export function bindWatermarks() {
  $("#watermark-open").addEventListener("click", () => runAction(openWatermarkDialog));
  $("#watermark-toggle").addEventListener("click", () => {
    hidden = !hidden;
    writeHidden(hidden);
    renderAll();
  });
  $("#wm-cancel").addEventListener("click", closeWatermarkDialog);
  $("#wm-add").addEventListener("click", addRule);
  $("#wm-delete").addEventListener("click", deleteRule);
  $("#wm-rule").addEventListener("change", () => {
    selected = Number($("#wm-rule").value);
    fillForm();
    renderWatermarkPreview();
  });
  const form = $("#watermark-form");
  form.addEventListener("input", onFormEdit);
  form.addEventListener("change", onFormEdit);
  form.addEventListener("submit", saveWatermarks);
}

function onFormEdit(event) {
  if (event.target.id === "wm-rule") return;
  readForm();
  renderWatermarkPreview();
}

async function openWatermarkDialog() {
  const res = await getJson(`/api/docs/${state.docId}/watermarks`);
  draft = res.rules.map((rule) => ({ ...rule }));
  selected = 0;
  $("#wm-error").hidden = true;
  $("#watermark-dialog").hidden = false;
  fillForm();
  // The page redraws without saved watermarks, so the draft preview is the only copy on screen.
  renderAll();
}

function closeWatermarkDialog() {
  draft = null;
  $("#watermark-dialog").hidden = true;
  renderWatermarkPreview(); // clears the draft copies
  renderAll();
}

function fillForm() {
  selected = Math.max(0, Math.min(selected, draft.length - 1));
  const select = $("#wm-rule");
  select.replaceChildren(...draft.map((_, i) => new Option(`${t("watermark_rule")} ${i + 1}`, String(i))));
  const rule = draft[selected];
  select.value = rule ? String(selected) : "";
  $("#wm-empty").hidden = draft.length > 0;
  $("#wm-fields").disabled = !rule;
  $("#wm-delete").disabled = !rule;
  $("#wm-add").disabled = draft.length >= MAX_RULES;
  if (!rule) return;
  $("#wm-text").value = rule.text;
  $("#wm-rows").value = rule.rows;
  $("#wm-cols").value = rule.cols;
  $("#wm-size").value = rule.size;
  $("#wm-color").value = rule.color;
  $("#wm-opacity").value = rule.opacity;
  $("#wm-angle").value = rule.angle;
  $("#wm-pages").value = rule.pages;
  $("#wm-layer").value = rule.layer;
  $("#wm-enabled").checked = rule.enabled;
}

function readForm() {
  const rule = draft[selected];
  if (!rule) return;
  rule.text = $("#wm-text").value;
  rule.rows = Number($("#wm-rows").value);
  rule.cols = Number($("#wm-cols").value);
  rule.size = Number($("#wm-size").value);
  rule.color = $("#wm-color").value;
  rule.opacity = Number($("#wm-opacity").value);
  rule.angle = Number($("#wm-angle").value);
  rule.pages = $("#wm-pages").value.trim();
  rule.layer = $("#wm-layer").value;
  rule.enabled = $("#wm-enabled").checked;
}

function addRule() {
  if (draft.length >= MAX_RULES) return showWmError(t("watermark_max_rules"));
  readForm();
  draft.push({ ...DEFAULT_RULE });
  selected = draft.length - 1;
  $("#wm-error").hidden = true;
  fillForm();
  renderWatermarkPreview();
}

function deleteRule() {
  if (!draft[selected]) return;
  draft.splice(selected, 1);
  selected = Math.max(0, selected - 1);
  fillForm();
  renderWatermarkPreview();
}

function problemWith(rules) {
  const whole = (n, low, high) => Number.isInteger(n) && n >= low && n <= high;
  for (const rule of rules) {
    if (!rule.text.trim()) return t("watermark_text_needed");
    if (!PAGES.test(rule.pages)) return t("watermark_bad_pages");
    const numbersOk = whole(rule.rows, 1, 10) && whole(rule.cols, 1, 10)
      && rule.size >= 4 && rule.size <= 200
      && rule.opacity >= 0.05 && rule.opacity <= 1
      && rule.angle >= -90 && rule.angle <= 90;
    if (!numbersOk) return t("watermark_invalid");
  }
  return "";
}

async function saveWatermarks(event) {
  event.preventDefault();
  readForm();
  const problem = problemWith(draft);
  if (problem) return showWmError(problem);
  try {
    await api(`/api/docs/${state.docId}/watermarks`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules: draft }),
    });
    // The revision in the document info changes, so the pages are fetched again with the new rules.
    state.info = await getJson(`/api/docs/${state.docId}`);
    closeWatermarkDialog();
    toast(t("watermark_saved"));
  } catch (err) {
    showWmError(errorText(err));
  }
}

function showWmError(message) {
  const el = $("#wm-error");
  el.textContent = message;
  el.hidden = false;
}

// ---------- draft preview (only while the dialog is open) ----------

const clamp = (n, low, high) => (Number.isFinite(n) ? Math.min(high, Math.max(low, n)) : low);

function onPage(spec, index) {
  if (spec === "all") return true;
  const page = index + 1;
  return spec.split(",").some((part) => {
    const [low, high = low] = part.split("-").map(Number);
    return page >= low && page <= high;
  });
}

// Copies are placed with the same grid and rotation as the server, so the draft looks close to the result.
// Rotation is mirrored because CSS turns clockwise for positive angles.
export function renderWatermarkPreview() {
  const box = $("#wm-preview");
  box.replaceChildren();
  if (!draft || !state.info) return;
  const img = $("#page-img");
  const width = img.clientWidth;
  const height = img.clientHeight;
  box.style.width = `${width}px`;
  box.style.height = `${height}px`;
  const total = state.info.pages.length;
  const name = state.info.name.replace(/\.pdf$/i, "");
  const today = new Date().toLocaleDateString("en-CA");
  for (const rule of draft) {
    if (!rule.enabled || !onPage(rule.pages, state.page)) continue;
    const text = rule.text
      .replaceAll("{page}", String(state.page + 1))
      .replaceAll("{total}", String(total))
      .replaceAll("{name}", name)
      .replaceAll("{date}", today);
    const rows = clamp(Math.round(rule.rows), 1, 10);
    const cols = clamp(Math.round(rule.cols), 1, 10);
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const span = document.createElement("span");
        span.textContent = text;
        span.style.left = `${(width * (col + 0.5)) / cols}px`;
        span.style.top = `${(height * (row + 0.5)) / rows}px`;
        span.style.fontSize = `${clamp(rule.size, 4, 200) * state.zoom}px`;
        span.style.color = rule.color;
        span.style.opacity = clamp(rule.opacity, 0.05, 1);
        span.style.transform = `translate(-50%, -50%) rotate(${-clamp(rule.angle, -90, 90)}deg)`;
        box.appendChild(span);
      }
    }
  }
}
