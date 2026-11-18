import { $, PASTE_OFFSET, hexToRgb, state } from "./core.js";
import { toPdf } from "./view.js";
import { applyOps } from "./tools.js";
import { runAction } from "./files.js";
import { clearSelection, selectedItems, shiftBox, unionBox } from "./selection.js";

// ---------- text clipboard ----------

// In-app only, so no browser clipboard permission is needed.
export function copySelection(cut) {
  const items = selectedItems();
  if (!items.length) return;
  const box = unionBox(items);
  state.clipboard = {
    docId: state.docId,
    ref: [box[0], box[1]],
    size: [box[2] - box[0], box[3] - box[1]],
    items: items.map((ln) => ({ ...ln })),
  };
  if (!cut) return;
  clearSelection();
  runAction(() => applyOps(items.map((ln) => ({ type: "erase_text", page: state.page, rect: ln.bbox }))));
}

export function pointerInPage() {
  const p = state.pointer;
  const img = $("#page-img").getBoundingClientRect();
  if (!p || p[0] < img.left || p[0] > img.right || p[1] < img.top || p[1] > img.bottom) return null;
  return toPdf(p[0], p[1]);
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
  })));
}
