import { $, PALETTE, SIZE_STEPS, state } from "./core.js";
import { scaleFactor } from "./view.js";

// ---------- font size and color ----------

export function currentSize(fallback = 12) {
  const v = Number($("#size").value);
  return v > 0 ? v : fallback;
}

export function currentColor() {
  return $("#color").value;
}

export function setSizeInput(value) {
  $("#size").value = String(value);
}

export function markSwatch(hex) {
  document.querySelectorAll(".swatch").forEach((b) => b.classList.toggle("active", b.dataset.color === hex));
}

export function previewEditor() {
  if (!state.editor || !state.info) return;
  const s = scaleFactor();
  state.editor.style.fontSize = `${currentSize() / s}px`;
  state.editor.style.color = currentColor();
}

export function setColor(hex, refocus = true) {
  $("#color").value = hex;
  markSwatch(hex);
  previewEditor();
  if (refocus && state.editor) state.editor.focus();
}

export function stepSize(dir) {
  const cur = currentSize();
  const next = dir > 0
    ? SIZE_STEPS.find((v) => v > cur + 1e-6) ?? cur + 1
    : [...SIZE_STEPS].reverse().find((v) => v < cur - 1e-6) ?? Math.max(1, cur - 1);
  setSizeInput(next);
  previewEditor();
}

export function buildToolbarControls() {
  const box = $("#swatches");
  box.replaceChildren();
  PALETTE.forEach((hex) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "swatch";
    b.style.background = hex;
    b.title = hex;
    b.dataset.color = hex;
    box.appendChild(b);
  });
  box.addEventListener("click", (e) => {
    const hex = e.target.dataset.color;
    if (hex) setColor(hex);
  });
  // Pressing a toolbar button must not move focus away from an open state.editor.
  document.querySelector(".toolbar").addEventListener("mousedown", (e) => {
    if (e.target.closest("button")) e.preventDefault();
  });
  const list = $("#size-list");
  list.replaceChildren();
  SIZE_STEPS.forEach((v) => list.appendChild(new Option(String(v), String(v))));
  markSwatch(currentColor());
}

export function bindSizeAndColor() {
  $("#size-up").addEventListener("click", () => stepSize(1));
  $("#size-down").addEventListener("click", () => stepSize(-1));
  $("#size").addEventListener("input", previewEditor);
  $("#size").addEventListener("change", previewEditor);
  $("#size").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && state.editor) {
      e.preventDefault();
      state.editor.__finish(true);
    }
  });
  $("#color").addEventListener("input", (e) => setColor(e.target.value, false));
  document.querySelector(".toolbar").addEventListener("focusout", () => {
    setTimeout(() => {
      const active = document.activeElement;
      if (!state.editor || (active && (active.closest(".toolbar") || state.editor.contains(active)))) return;
      state.editor.__finish(true);
    }, 0);
  });
}
