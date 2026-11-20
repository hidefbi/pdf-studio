import { $, PASTE_OFFSET, hexToRgb, state } from "./core.js";
import { toPdf } from "./view.js";
import { applyOps } from "./tools.js";
import { runAction } from "./files.js";
import { currentColor, currentSize } from "./toolbar.js";
import { clearSelection, selectedItems, shiftBox, unionBox } from "./selection.js";

// ---------- text clipboard ----------

// Plain text we put on the system clipboard lately. A paste that finds one of these
// gets our own lines, even when the system copy is a little behind.
const ownTexts = [];

// Lines keep their font and color in-app. The plain text also goes to the system clipboard.
export function copySelection(cut) {
  const items = selectedItems();
  if (!items.length) return;
  const box = unionBox(items);
  const text = items.map((ln) => ln.text).join("\n");
  const clip = {
    docId: state.docId,
    ref: [box[0], box[1]],
    size: [box[2] - box[0], box[3] - box[1]],
    items: items.map((ln) => ({ ...ln })),
    text,
    written: false,
  };
  state.clipboard = clip;
  ownTexts.push(text);
  if (ownTexts.length > 20) ownTexts.shift();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => { clip.written = true; }).catch(() => {});
  }
  if (!cut) return;
  clearSelection();
  runAction(() => applyOps(items.map((ln) => ({ type: "erase_text", page: state.page, rect: ln.bbox, origin: ln.origin }))));
}

export function pointerInPage() {
  const p = state.pointer;
  const img = $("#page-img").getBoundingClientRect();
  if (!p || p[0] < img.left || p[0] > img.right || p[1] < img.top || p[1] > img.bottom) return null;
  return toPdf(p[0], p[1]);
}

// Text from another app lands as new text in the current font. Our own copy keeps its format.
export async function pasteText(text) {
  const page = state.info.pages[state.page];
  const size = currentSize(12);
  const lines = text.split(/\r?\n/);
  const width = Math.min(page.width - 72, Math.max(...lines.map((l) => l.length)) * size * 0.6 + 8);
  const height = lines.length * size * 1.2;
  let [x, y] = pointerInPage() || [36, 36];
  x = Math.max(0, Math.min(page.width - width, x));
  y = Math.max(0, Math.min(page.height - height, y));
  await applyOps([{
    type: "text",
    page: state.page,
    rect: [x, y, x + width, y + height],
    text: lines.join("\n"),
    font: $("#font").value || "auto",
    size,
    color: hexToRgb(currentColor()),
  }]);
}

// Cmd+V and Ctrl+V fire a paste event, so this only runs on the user's own key press.
export function onPasteEvent(e) {
  if (e.target.matches("input, select, textarea") || e.target.isContentEditable) return;
  if (!state.info || state.editor) return;
  const text = (e.clipboardData && e.clipboardData.getData("text/plain")) || "";
  const clip = state.clipboard;
  // Our own lines win when the system clipboard holds our text, has no text,
  // or never took our copy (then its text may be older than the copy).
  if (clip && clip.items.length && (!text.trim() || ownTexts.includes(text) || !clip.written)) {
    e.preventDefault();
    runAction(pasteClipboard);
  } else if (text.trim()) {
    e.preventDefault();
    runAction(() => pasteText(text));
  }
}

export async function pasteClipboard() {
  const clip = state.clipboard;
  if (!clip || !state.info) return;
  const page = state.info.pages[state.page];
  const [w, h] = clip.size;
  let [x, y] = pointerInPage() || [clip.ref[0] + PASTE_OFFSET, clip.ref[1] + PASTE_OFFSET];
  x = Math.max(0, Math.min(page.width - w, x));
  y = Math.max(0, Math.min(page.height - h, y));
  const dx = x - clip.ref[0];
  const dy = y - clip.ref[1];
  const sameDoc = clip.docId === state.docId;
  const items = clip.items.map((ln) => ({
    ...ln,
    bbox: shiftBox(ln.bbox, dx, dy),
    origin: [ln.origin[0] + dx, ln.origin[1] + dy],
    block: ln.block ? shiftBox(ln.block, dx, dy) : null,
  }));
  // Same as a move: the redraw matches the selection by place.
  state.selected = { page: state.page, items, anchor: null };
  await applyOps(items.map((ln) => ({
    type: "write_text",
    page: state.page,
    rect: ln.bbox,
    origin: ln.origin,
    dest: ln.origin,
    text: ln.text,
    font: "auto",
    base_font: ln.base_font,
    font_xref: sameDoc ? ln.font_xref : 0,
    size: ln.size,
    color: hexToRgb(ln.color),
    tracking: ln.tracking ?? 0,
    leading: ln.leading ?? null,
  })));
}
