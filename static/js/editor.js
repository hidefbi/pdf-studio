import { $, hexToRgb, state, t } from "./core.js";
import { SVG_NS, scaleFactor } from "./view.js";
import { applyOps } from "./tools.js";
import { runAction } from "./files.js";
import { alignOf, isBoldFont, selectOnly } from "./selection.js";
import { currentColor, currentSize, setColor, setSizeInput, stepSize } from "./toolbar.js";

// ---------- inline text editing ----------

export const CJK_FONT = '"Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif';

export function fontKey() {
  return $("#font").value || "auto";
}

// Uploaded fonts have no bold or italic version; the built-in standard fonts do.
export function isCustomFont(key) {
  return key !== "auto" && !(state.fonts.builtin || []).some((f) => f.id === key);
}

export function placeBox(el, bbox) {
  const s = scaleFactor();
  el.style.left = `${bbox[0] / s}px`;
  el.style.top = `${bbox[1] / s}px`;
  el.style.width = `${(bbox[2] - bbox[0]) / s}px`;
  el.style.height = `${(bbox[3] - bbox[1]) / s}px`;
}

export function sampleBackground(bbox) {
  const img = $("#page-img");
  if (!img.naturalWidth) return "#ffffff";
  const k = img.naturalWidth / state.info.pages[state.page].width;
  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  const m = 4;
  const x0 = Math.max(0, Math.floor((bbox[0] - m) * k));
  const y0 = Math.max(0, Math.floor((bbox[1] - m) * k));
  const x1 = Math.min(canvas.width - 1, Math.ceil((bbox[2] + m) * k));
  const y1 = Math.min(canvas.height - 1, Math.ceil((bbox[3] + m) * k));
  const w = x1 - x0 + 1;
  const h = y1 - y0 + 1;
  if (w < 2 || h < 2) return "#ffffff";
  const data = ctx.getImageData(x0, y0, w, h).data;
  const reds = [], greens = [], blues = [];
  const add = (x, y) => {
    const i = (y * w + x) * 4;
    reds.push(data[i]); greens.push(data[i + 1]); blues.push(data[i + 2]);
  };
  for (let x = 0; x < w; x++) { add(x, 0); add(x, h - 1); }
  for (let y = 0; y < h; y++) { add(0, y); add(w - 1, y); }
  const median = (a) => a.sort((p, q) => p - q)[Math.floor(a.length / 2)];
  return `rgb(${median(reds)}, ${median(greens)}, ${median(blues)})`;
}

export function openLineEditor(ln) {
  selectOnly(ln);
  setSizeInput(ln.size);
  setColor(ln.color, false);
  startEditor({
    bbox: ln.bbox,
    text: ln.text,
    size: ln.size,
    color: ln.color,
    bold: isBoldFont(ln.base_font),
    bg: sampleBackground(ln.bbox),
    kerning: ln.tracking ?? 0,
    leading: ln.leading ?? null,
    onCommit: (value, settings) => {
      const size = currentSize(ln.size);
      const color = currentColor();
      if (value === ln.text && size === ln.size && color === ln.color && fontKey() === "auto"
        && settings.kerning === (ln.tracking ?? 0) && settings.leading === (ln.leading ?? null)) return null;
      return [{
        type: "replace_span",
        page: state.page,
        rect: ln.bbox,
        origin: ln.origin,
        text: value,
        font: fontKey(),
        base_font: ln.base_font,
        font_xref: fontKey() === "auto" ? ln.font_xref : 0,
        size,
        color: hexToRgb(color),
        align: alignOf(ln),
        block: ln.block || null,
        tracking: settings.kerning,
        leading: settings.leading,
      }];
    },
  });
  if (state.editor) state.editor.__ln = ln;
}

// Line handlers prevent default, so the state.editor never blurs; commit it here.
export function onPagePress(e) {
  if (e.target.closest(".toolbar, #style-bar")) return;
  const active = document.activeElement;
  if (active && active.closest(".toolbar")) active.blur();
  if (!state.editor || state.editor.contains(e.target) || e.target.closest(".tl-tools")) return;
  state.editor.__finish(true);
}

export const KERNING_MIN = -200; // 1/1000 em, keep in step with TRACKING_MIN in app/main.py
export const KERNING_MAX = 1000; // 1/1000 em, keep in step with TRACKING_MAX in app/main.py
export const KERNING_STEP = 10;
export const LEADING_MIN = 1; // pt, keep in step with LEADING_MIN in app/main.py
export const LEADING_MAX = 200; // pt, keep in step with LEADING_MAX in app/main.py
export const LEADING_STEP = 1;
const AUTO_LINE_HEIGHT = 1.2; // keep in step with LINE_HEIGHT in app/main.py

function clampTo(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

// Empty field gives null (automatic). A value that is not a number gives the fallback.
function readNumber(input, fallback) {
  if (input.value.trim() === "") return null;
  const v = Number(input.value);
  return Number.isFinite(v) ? v : fallback;
}

function svgIcon(build) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "18");
  svg.setAttribute("height", "18");
  svg.setAttribute("aria-hidden", "true");
  build(svg);
  return svg;
}

function drawStroke(parent, d, width) {
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", d);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", String(width));
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  parent.append(path);
}

// Line spacing: a vertical arrow beside three lines.
function leadingIcon() {
  return svgIcon((svg) => {
    drawStroke(svg, "M5 3 V21 M2.5 6 L5 3 L7.5 6 M2.5 18 L5 21 L7.5 18", 1.6);
    drawStroke(svg, "M11 6 H21 M11 12 H21 M11 18 H21", 2.4);
  });
}

// Kerning: "AV" above a horizontal arrow.
function kerningIcon() {
  return svgIcon((svg) => {
    const text = document.createElementNS(SVG_NS, "text");
    text.setAttribute("x", "12");
    text.setAttribute("y", "11");
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("font-size", "10");
    text.setAttribute("font-weight", "700");
    text.setAttribute("font-family", "Helvetica, Arial, sans-serif");
    text.setAttribute("fill", "currentColor");
    text.textContent = "AV";
    svg.append(text);
    drawStroke(svg, "M2 18 H22 M2 18 L5 15.5 M2 18 L5 20.5 M22 18 L19 15.5 M22 18 L19 20.5", 1.6);
  });
}

// One setting: icon, "-" button, number field, "+" button. Buttons move the value by one step.
function buildStepper({ field, icon, titleKey, value, min, max, step, base, placeholder, onChange }) {
  const wrap = document.createElement("div");
  wrap.className = "tl-step";
  wrap.dataset.field = field;
  wrap.title = t(titleKey);
  const iconBox = document.createElement("span");
  iconBox.className = "tl-step-icon";
  iconBox.append(icon);
  const minus = document.createElement("button");
  minus.type = "button";
  minus.className = "tl-step-btn";
  minus.dataset.step = "-1";
  minus.textContent = "\u2212";
  minus.title = t("spacing_decrease");
  const input = document.createElement("input");
  input.type = "number";
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.placeholder = placeholder;
  input.value = value === null ? "" : String(value);
  const plus = document.createElement("button");
  plus.type = "button";
  plus.className = "tl-step-btn";
  plus.dataset.step = "1";
  plus.textContent = "+";
  plus.title = t("spacing_increase");
  const nudge = (direction) => {
    const current = readNumber(input, null);
    const start = current === null ? base() : current;
    input.value = String(clampTo(start + direction * step, min, max));
    onChange();
  };
  minus.addEventListener("click", () => nudge(-1));
  plus.addEventListener("click", () => nudge(1));
  input.addEventListener("input", onChange);
  wrap.append(iconBox, minus, input, plus);
  return { wrap, input };
}

function buildSpacingPanel({ kerning, leading, size }, onChange) {
  const panel = document.createElement("div");
  panel.className = "tl-spacing";
  const lead = buildStepper({
    field: "leading", icon: leadingIcon(), titleKey: "leading_title", value: leading,
    min: LEADING_MIN, max: LEADING_MAX, step: LEADING_STEP,
    base: () => size * AUTO_LINE_HEIGHT, placeholder: t("leading_auto"), onChange,
  });
  const kern = buildStepper({
    field: "kerning", icon: kerningIcon(), titleKey: "kerning_title", value: kerning,
    min: KERNING_MIN, max: KERNING_MAX, step: KERNING_STEP,
    base: () => 0, placeholder: "0", onChange,
  });
  panel.append(lead.wrap, kern.wrap);
  return { panel, kerningInput: kern.input, leadingInput: lead.input };
}

export function startEditor({ bbox, text, size, color, bold, bg, kerning = 0, leading = null, onCommit }) {
  if (state.editor && state.editor.__finish) state.editor.__finish(true);
  const s = scaleFactor();
  const ed = document.createElement("div");
  ed.className = "tl-edit";
  ed.contentEditable = "true";
  ed.spellcheck = false;
  placeBox(ed, bbox);
  ed.style.width = "auto";
  ed.style.height = "auto";
  ed.style.minWidth = `${(bbox[2] - bbox[0]) / s}px`;
  ed.style.minHeight = `${(bbox[3] - bbox[1]) / s}px`;
  ed.style.fontSize = `${size / s}px`;
  ed.style.color = color;
  ed.style.fontWeight = bold ? "700" : "400";
  ed.style.fontFamily = `Helvetica, Arial, ${CJK_FONT}`;
  ed.textContent = text;
  // The sampled background only covers the line's own place, so a wider preview
  // draws over its neighbours instead of hiding them.
  const backdrop = document.createElement("div");
  backdrop.className = "tl-backdrop";
  placeBox(backdrop, bbox);
  backdrop.style.background = bg;

  const { panel: spacingPanel, kerningInput, leadingInput } =
    buildSpacingPanel({ kerning, leading, size }, () => {
      applyPreview();
      placeTools();
    });
  const readSettings = () => {
    const k = readNumber(kerningInput, 0);
    const l = readNumber(leadingInput, null);
    return {
      kerning: clampTo(k === null ? 0 : k, KERNING_MIN, KERNING_MAX),
      leading: l === null ? null : clampTo(l, LEADING_MIN, LEADING_MAX),
    };
  };
  const applyPreview = () => {
    const { kerning: k, leading: l } = readSettings();
    // The preview gaps match the saved ones: thousandths of an em times the size, and the line step.
    ed.style.letterSpacing = `${((k / 1000) * size) / s}px`;
    // A single line keeps its own box, so the line step only shows once the text has two lines.
    const stacked = ed.innerText.includes("\n");
    ed.style.lineHeight = `${((stacked && l !== null) ? l : size * AUTO_LINE_HEIGHT) / s}px`;
  };
  applyPreview();

  // mousedown is prevented, so these buttons do not blur the state.editor. The inputs keep focus.
  const tools = document.createElement("div");
  tools.className = "tl-tools";
  const okBtn = document.createElement("button");
  okBtn.className = "ok";
  okBtn.textContent = "✓";
  okBtn.title = t("editor_save");
  const cancelBtn = document.createElement("button");
  cancelBtn.className = "cancel";
  cancelBtn.textContent = "✕";
  cancelBtn.title = t("editor_cancel");
  tools.append(spacingPanel, okBtn, cancelBtn);
  tools.addEventListener("mousedown", (e) => {
    if (!e.target.closest("input")) e.preventDefault();
  });
  $("#stage").append(backdrop, ed, tools);
  // The row sits under the box's bottom edge and follows it as the text grows.
  function placeTools() {
    tools.style.left = `${ed.offsetLeft}px`;
    tools.style.top = `${ed.offsetTop + ed.offsetHeight + 4}px`;
  }
  placeTools();
  ed.addEventListener("input", () => {
    applyPreview();
    placeTools();
  });
  state.editor = ed;

  let done = false;
  const finish = (save) => {
    if (done) return;
    done = true;
    const value = ed.innerText.replace(/\n+$/, "");
    const settings = readSettings();
    ed.remove();
    tools.remove();
    backdrop.remove();
    if (state.editor === ed) state.editor = null;
    if (!save) return;
    const ops = onCommit(value, settings);
    if (ops) runAction(() => applyOps(ops));
  };
  ed.__finish = finish;
  ed.__pending = () => onCommit(ed.innerText.replace(/\n+$/, ""), readSettings());
  spacingPanel.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      finish(true);
    } else if (e.key === "Escape") {
      e.preventDefault();
      finish(false);
    }
  });
  okBtn.addEventListener("click", () => finish(true));
  cancelBtn.addEventListener("click", () => finish(false));

  // Safari can send the confirming Enter after compositionend, so keyCode alone is not enough.
  let composing = false;
  let composedAt = -Infinity;
  ed.addEventListener("compositionstart", () => { composing = true; });
  ed.addEventListener("compositionend", () => {
    composing = false;
    composedAt = performance.now();
  });

  ed.addEventListener("keydown", (e) => {
    e.stopPropagation();
    // Enter during composition only picks a candidate.
    if (e.isComposing || composing || e.keyCode === 229) return;
    if (e.key === "Enter" && !e.shiftKey && performance.now() - composedAt < 120) {
      // This Enter only confirmed the candidate, so keep the state.editor open.
      e.preventDefault();
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      finish(false);
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      finish(true);
    } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "<" || e.key === ">")) {
      e.preventDefault();
      stepSize(e.key === ">" ? 1 : -1);
    }
  });
  // Safari gives buttons no focus on click, so wait for focus to settle.
  ed.addEventListener("blur", () => {
    setTimeout(() => {
      if (done) return;
      const active = document.activeElement;
      if (active && (active === ed || (active.closest && (active.closest(".toolbar") || active.closest(".tl-spacing"))))) return;
      finish(true);
    }, 0);
  });
  ed.focus();
  const range = document.createRange();
  range.selectNodeContents(ed);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}
