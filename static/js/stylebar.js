import { $, endEdit, hexToRgb, state, t, toast } from "./core.js";
import { fontKey, isCustomFont } from "./editor.js";
import { runAction } from "./files.js";
import { alignOf, isBoldFont, isItalicFont, sameLine, selectedItems, selectionAlign, sizesMixed, unionBox } from "./selection.js";
import { setSizeInput } from "./toolbar.js";
import { applyOps } from "./tools.js";
import { scaleFactor } from "./view.js";

export function showStyleBar() {
  const bar = $("#style-bar");
  const items = selectedItems();
  const usable = state.tool === "select" || state.tool === "replace";
  if (!usable || !items.length) {
    hideStyleBar();
    return;
  }
  bar.hidden = false;
  const every = (fn) => items.every(fn);
  bar.querySelector('[data-act="bold"]').classList.toggle("active", every((ln) => isBoldFont(ln.base_font)));
  bar.querySelector('[data-act="italic"]').classList.toggle("active", every((ln) => isItalicFont(ln.base_font)));
  bar.querySelector('[data-act="underline"]').classList.toggle("active", every((ln) => Boolean(ln.underlined)));
  // A single line only aligns within its own paragraph.
  const alignable = items.length > 1 || Boolean(alignOf(items[0]));
  const align = items.length > 1 ? selectionAlign(items) : alignOf(items[0]);
  bar.querySelectorAll("[data-align]").forEach((btn) => {
    btn.disabled = !alignable;
    btn.classList.toggle("active", alignable && btn.dataset.align === align);
    btn.title = t(alignable ? btn.dataset.i18nTitle : "style_align_hint");
  });
  const count = bar.querySelector(".style-count");
  count.hidden = items.length < 2;
  count.textContent = t("selected_lines", { n: items.length });
  const size = state.selected.size;
  bar.querySelector(".style-size").textContent = String(size);
  bar.querySelector(".style-mixed").hidden = !sizesMixed(items);
  setSizeInput(size);

  const box = unionBox(items);
  const s = scaleFactor();
  const h = bar.offsetHeight || 38;
  const w = bar.offsetWidth || 360;
  const pageWidth = $("#page-img").clientWidth;
  let top = box[1] / s - h - 8;
  if (top < 4) top = box[3] / s + 36; // no room above: sit below the selection and its ok/cancel buttons
  bar.style.left = `${Math.max(4, Math.min(box[0] / s, pageWidth - w - 4))}px`;
  bar.style.top = `${top}px`;
}

export function hideStyleBar() {
  $("#style-bar").hidden = true;
}

// Keeps the alignment, so the line does not jump.
export function styleOp(ln, text) {
  return {
    type: "replace_span",
    page: state.page,
    rect: ln.bbox,
    origin: ln.origin,
    text,
    font: fontKey(),
    base_font: ln.base_font,
    font_xref: fontKey() === "auto" ? ln.font_xref : 0,
    size: ln.size,
    color: hexToRgb(ln.color),
    align: alignOf(ln),
    block: ln.block || null,
    tracking: ln.tracking ?? 0,
    leading: ln.leading ?? null,
  };
}

// An open state.editor is saved first, with the text as typed.
export async function applyStyle(act, value) {
  const items = selectedItems();
  if (!items.length) return;
  // A+ and A- step from the size shown in the bar, in whole points.
  let target = null;
  if (act === "larger") target = state.selected.size + 1;
  if (act === "smaller") target = Math.max(1, state.selected.size - 1);
  if (act === "size") target = value;
  if ((act === "bold" || act === "italic") && isCustomFont(fontKey())) {
    toast(t("font_no_style"), true);
    return;
  }
  let editedLn = null;
  let editedText = null;
  if (state.edit) {
    editedLn = state.edit.ln;
    editedText = state.edit.text();
    endEdit(false);
  }
  const ops = [];
  if (act === "underline") {
    const enable = !items.every((ln) => ln.underlined);
    items.forEach((ln) => ops.push({ type: "set_underline", page: state.page, rect: ln.bbox, enabled: enable }));
  } else {
    const toggleBold = !items.every((ln) => isBoldFont(ln.base_font));
    const toggleItalic = !items.every((ln) => isItalicFont(ln.base_font));
    items.forEach((ln) => {
      const text = editedLn && sameLine(ln, editedLn) ? editedText : ln.text;
      if (!text.trim()) return;
      const op = styleOp(ln, text);
      if (target !== null) op.size = target;
      if (act === "bold") op.bold = toggleBold;
      if (act === "italic") op.italic = toggleItalic;
      if (act.startsWith("align-")) {
        op.align = act.slice(6);
        if (items.length > 1) op.block = unionBox(items);
      } else if (items.length > 1) {
        op.align = null;
        op.block = null;
      }
      ops.push(op);
    });
  }
  if (!ops.length) return;
  if (target !== null && state.selected) state.selected.size = target;
  await runAction(() => applyOps(ops));
}

export function bindStyleBar() {
  const bar = $("#style-bar");
  bar.addEventListener("mousedown", (e) => e.preventDefault());
  bar.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) applyStyle(btn.dataset.act);
  });
  // Typing a size in the top box sets the selected lines when no text is open for editing.
  $("#size").addEventListener("change", (e) => {
    if (state.editor || !selectedItems().length) return;
    const value = Number(e.target.value);
    if (value >= 1 && value <= 400) applyStyle("size", value);
    else setSizeInput(state.selected.size);
  });
}
