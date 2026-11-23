import { t } from "./core.js";
import { currentColor } from "./toolbar.js";
import { SVG_NS } from "./view.js";

export const KERNING_MIN = -200; // 1/1000 em, keep in step with TRACKING_MIN in app/main.py
export const KERNING_MAX = 1000; // 1/1000 em, keep in step with TRACKING_MAX in app/main.py
export const KERNING_STEP = 10;
export const LEADING_MIN = 1; // pt, keep in step with LEADING_MIN in app/main.py
export const LEADING_MAX = 200; // pt, keep in step with LEADING_MAX in app/main.py
export const LEADING_STEP = 1;
export const AUTO_LINE_HEIGHT = 1.2; // keep in step with LINE_HEIGHT in app/main.py

export function clampTo(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

// Empty field gives null (automatic). A value that is not a number gives the fallback.
export function readNumber(input, fallback) {
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

export function buildSpacingPanel({ kerning, leading, size }, onChange) {
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
