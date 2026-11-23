import { copySelection, onPasteEvent } from "./clipboard.js";
import { $, api, getJson, hexToRgb, showError, state } from "./core.js";
import { openLineEditor, placeBox } from "./editor.js";
import { runAction } from "./files.js";
import { bindImageBox, bindPictureMenu, ensureImages, hideImageMenu, imageOfBox, isImageSelected, pictureAction, pictureUnderPoint, restoreImageSelection, selectImage, showImageMenu, syncImageHandles } from "./images.js";
import { hideStyleBar, showStyleBar } from "./stylebar.js";
import { applyOps } from "./tools.js";
import { scaleFactor } from "./view.js";

export async function ensureLines() {
  const key = `${state.docId}:${state.page}:${state.info.version}`;
  if (state.lineCache.key !== key) {
    const res = await getJson(`/api/docs/${state.docId}/pages/${state.page}/lines`);
    state.lineCache = { key, lines: res.lines };
  }
  return state.lineCache.lines;
}

let layerRun = 0;
let movingGhosts = [];
const lineBoxes = new WeakMap();
let marqueeLines = [];
let marqueeBound = false;

export async function drawTextLayer() {
  // A new page is on screen, so any move ghosts can go.
  clearGhosts();
  const run = ++layerRun;
  const layer = $("#textlayer");
  const active = (state.tool === "replace" || state.tool === "select") && Boolean(state.info);
  layer.classList.toggle("active", active);
  if (!active) {
    layer.replaceChildren();
    return;
  }
  const img = $("#page-img");
  layer.style.width = `${img.clientWidth}px`;
  layer.style.height = `${img.clientHeight}px`;
  const lines = await ensureLines();
  const images = await ensureImages();
  // A newer call has started since this one (tool or page changed), so it owns the layer.
  if (run !== layerRun || (state.tool !== "replace" && state.tool !== "select")) return;
  layer.replaceChildren();
  // Pictures sit under the text boxes, so text on top of a picture is still clickable.
  if (state.tool === "select") {
    images.forEach((pic) => {
      const box = document.createElement("div");
      box.className = "img-box";
      placeBox(box, pic.bbox);
      bindImageBox(box, pic);
      layer.appendChild(box);
    });
  }
  lines.forEach((ln) => {
    const box = document.createElement("div");
    box.className = "tl-box";
    box.title = ln.text;
    lineBoxes.set(box, ln);
    placeBox(box, ln.bbox);
    bindLineBox(box, ln, lines);
    layer.appendChild(box);
  });
  bindMarquee(layer, lines);
  restoreSelection(lines);
  restoreImageSelection(images);
}

// ---------- selection, multi-line selection and floating style bar ----------

export const BOLD_NAME = /bold|black|heavy|semibold|demi/i;
export const ITALIC_NAME = /italic|oblique/i;
export const SELECT_SLOP = 3; // screen pixels a press may move before it counts as a drag
export const SAME_LINE_TOLERANCE = 14; // points: how far a line may move on redraw and still be the same line

export function isBoldFont(name) {
  return BOLD_NAME.test(name || "");
}

export function isItalicFont(name) {
  return ITALIC_NAME.test(name || "");
}

export function sameLine(a, b) {
  return Boolean(a && b) && a.bbox.every((v, i) => Math.abs(v - b.bbox[i]) < 0.01);
}

export function selectedItems() {
  const sel = state.selected;
  return sel && sel.page === state.page ? sel.items : [];
}

export function isSelected(ln) {
  return selectedItems().some((item) => sameLine(item, ln));
}

export function unionBox(items) {
  return [
    Math.min(...items.map((ln) => ln.bbox[0])),
    Math.min(...items.map((ln) => ln.bbox[1])),
    Math.max(...items.map((ln) => ln.bbox[2])),
    Math.max(...items.map((ln) => ln.bbox[3])),
  ];
}

export function alignOf(ln) {
  const b = ln.block;
  if (!b) return null;
  // A one-line block has no paragraph width to align to.
  if (Math.abs((b[3] - b[1]) - (ln.bbox[3] - ln.bbox[1])) < 2) return null;
  const tol = 1.5;
  if (Math.abs(ln.bbox[0] - b[0]) < tol) return "left";
  if (Math.abs((ln.bbox[0] + ln.bbox[2]) / 2 - (b[0] + b[2]) / 2) < tol) return "center";
  if (Math.abs(ln.bbox[2] - b[2]) < tol) return "right";
  return null;
}

export function selectionAlign(items) {
  const tol = 1.5;
  const same = (vals) => Math.max(...vals) - Math.min(...vals) < tol;
  if (same(items.map((ln) => ln.bbox[0]))) return "left";
  if (same(items.map((ln) => (ln.bbox[0] + ln.bbox[2]) / 2))) return "center";
  if (same(items.map((ln) => ln.bbox[2]))) return "right";
  return null;
}

// Sizes are shown and stepped in whole points.
export function roundedSize(size) {
  return Math.max(1, Math.round(size));
}

// Most common size wins; on a tie the bigger one does.
export function majoritySize(items) {
  const counts = new Map();
  items.forEach((ln) => {
    const s = roundedSize(ln.size);
    counts.set(s, (counts.get(s) || 0) + 1);
  });
  let best = null;
  let bestCount = 0;
  counts.forEach((count, s) => {
    if (count > bestCount || (count === bestCount && s > best)) {
      best = s;
      bestCount = count;
    }
  });
  return best;
}

export function sizesMixed(items) {
  return new Set(items.map((ln) => roundedSize(ln.size))).size > 1;
}

export function setSelection(items, anchor) {
  state.imageSel = null;
  state.selected = {
    page: state.page,
    items,
    anchor: anchor || items[items.length - 1] || null,
    size: majoritySize(items),
  };
  syncSelectionDom();
  showStyleBar();
}

export function selectOnly(ln) {
  setSelection([ln], ln);
}

// Same as cut, minus the clipboard.
export function deleteSelection() {
  const items = selectedItems();
  if (!items.length) return;
  clearSelection();
  runAction(() => applyOps(items.map((ln) => ({ type: "erase_text", page: state.page, rect: ln.bbox, origin: ln.origin }))));
}

export function showTextMenu(x, y) {
  const menu = $("#text-menu");
  menu.hidden = false;
  const w = menu.offsetWidth;
  const h = menu.offsetHeight;
  menu.style.left = `${Math.min(x, window.innerWidth - w - 6)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - h - 6)}px`;
}

export function hideTextMenu() {
  $("#text-menu").hidden = true;
}

export function bindTextMenu() {
  const menu = $("#text-menu");
  menu.addEventListener("mousedown", (e) => e.preventDefault());
  menu.addEventListener("click", (e) => {
    if (!e.target.closest("button[data-text]")) return;
    hideTextMenu();
    deleteSelection();
  });
  document.addEventListener("pointerdown", (e) => {
    if (!menu.contains(e.target)) hideTextMenu();
  });
  window.addEventListener("scroll", hideTextMenu, true);
}

export function clearSelection() {
  state.selected = null;
  state.imageSel = null;
  syncSelectionDom();
  hideStyleBar();
}

export function syncSelectionDom() {
  document.querySelectorAll(".tl-box").forEach((el) => el.classList.toggle("selected", isSelected(lineBoxes.get(el))));
  document.querySelectorAll(".img-box").forEach((el) => {
    const on = isImageSelected(imageOfBox(el));
    el.classList.toggle("selected", on);
    syncImageHandles(el, on);
  });
}

export function extendSelection(lines, ln, range, toggle) {
  const sel = state.selected && state.selected.page === state.page ? state.selected : null;
  const anchor = sel && sel.anchor;
  if (range && anchor) {
    const a = lines.findIndex((l) => sameLine(l, anchor));
    const b = lines.indexOf(ln);
    if (a >= 0 && b >= 0) {
      setSelection(lines.slice(Math.min(a, b), Math.max(a, b) + 1), anchor);
      return;
    }
  }
  if (toggle) {
    const items = selectedItems();
    if (items.some((item) => sameLine(item, ln))) {
      const rest = items.filter((item) => !sameLine(item, ln));
      setSelection(rest, rest[rest.length - 1] || null);
    } else {
      setSelection([...items, ln], ln);
    }
    return;
  }
  selectOnly(ln);
}

// Lines barely move on redraw, so match on height first.
export function nearestLine(lines, bbox, used) {
  const cy = (b) => (b[1] + b[3]) / 2;
  const cx = (b) => (b[0] + b[2]) / 2;
  let best = null;
  let bestScore = Infinity;
  lines.forEach((ln) => {
    if (used.has(ln)) return;
    const dy = Math.abs(cy(ln.bbox) - cy(bbox));
    if (dy > SAME_LINE_TOLERANCE) return;
    const score = dy + Math.abs(cx(ln.bbox) - cx(bbox)) * 0.1;
    if (score < bestScore) { bestScore = score; best = ln; }
  });
  return best;
}

// Lines are re-read on redraw, so the selection is matched by place.
export function clearTextSelection() {
  state.selected = null;
  syncSelectionDom();
  hideStyleBar();
}

export function restoreSelection(lines) {
  const sel = state.selected;
  if (!sel || sel.page !== state.page || !sel.items.length) {
    clearTextSelection();
    return;
  }
  const used = new Set();
  const found = [];
  let anchor = null;
  sel.items.forEach((old) => {
    const best = nearestLine(lines, old.bbox, used);
    if (!best) return;
    used.add(best);
    found.push(best);
    if (sel.anchor && sameLine(old, sel.anchor)) anchor = best;
  });
  if (!found.length) {
    clearTextSelection();
    return;
  }
  // Same lines after a redraw, so keep the size the user is stepping from.
  const size = sel.size ?? majoritySize(found);
  state.selected = { page: state.page, items: found, anchor: anchor || found[found.length - 1], size };
  syncSelectionDom();
  showStyleBar();
}

export function bindLineBox(box, ln, lines) {
  box.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const modifier = e.shiftKey || e.metaKey || e.ctrlKey;
    if (modifier) {
      e.preventDefault();
      extendSelection(lines, ln, e.shiftKey, e.metaKey || e.ctrlKey);
      return;
    }
    if (state.tool !== "select") return; // replace tool: the click handler opens the state.editor
    e.preventDefault();
    if (!isSelected(ln)) selectOnly(ln);
    startGroupMove(e, ln);
  });
  box.addEventListener("click", (e) => {
    // Modifier clicks only change the selection.
    if (state.tool === "replace" && !(e.shiftKey || e.metaKey || e.ctrlKey)) openLineEditor(ln);
  });
  box.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    // Over a picture the picture menu still wins.
    const picture = state.tool === "select" ? pictureUnderPoint(e) : null;
    if (picture) {
      selectImage(imageOfBox(picture));
      showImageMenu(e.clientX, e.clientY);
      return;
    }
    // Right-click selects the line unless it is already in the selection, then offers delete.
    if (!isSelected(ln)) selectOnly(ln);
    showTextMenu(e.clientX, e.clientY);
  });
  box.addEventListener("dblclick", () => {
    if (state.tool === "select") openLineEditor(ln);
  });
}

export function clearGhosts() {
  movingGhosts.forEach((g) => g.remove());
  movingGhosts = [];
}

export function startGroupMove(e, pressed) {
  const items = selectedItems();
  const start = { x: e.clientX, y: e.clientY };
  const ghosts = items.map((ln) => {
    const ghost = document.createElement("div");
    ghost.className = "tl-ghost";
    placeBox(ghost, ln.bbox);
    $("#stage").append(ghost);
    return ghost;
  });
  let dx = 0, dy = 0;
  const onMove = (ev) => {
    dx = ev.clientX - start.x;
    dy = ev.clientY - start.y;
    ghosts.forEach((g) => { g.style.transform = `translate(${dx}px, ${dy}px)`; });
  };
  const onUp = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    if (Math.hypot(dx, dy) > SELECT_SLOP) {
      // The ghosts stay until the moved page is drawn, so the text does not jump back first.
      movingGhosts = ghosts;
      setTimeout(() => { if (movingGhosts === ghosts) clearGhosts(); }, 4000);
      const s = scaleFactor();
      runAction(() => moveLines(items, dx * s, dy * s));
    } else {
      ghosts.forEach((g) => g.remove());
      selectOnly(pressed);
    }
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}

// The layer lives as long as the page, so the listener is added once and reads the current lines.
export function bindMarquee(layer, lines) {
  marqueeLines = lines;
  if (marqueeBound) return;
  marqueeBound = true;
  layer.addEventListener("pointerdown", (e) => {
    if (e.target !== layer || e.button !== 0) return;
    if (state.tool !== "select" && state.tool !== "replace") return;
    e.preventDefault();
    const origin = layer.getBoundingClientRect();
    const x0 = e.clientX - origin.left;
    const y0 = e.clientY - origin.top;
    const keep = e.shiftKey || e.metaKey || e.ctrlKey ? selectedItems().slice() : [];
    const mark = document.createElement("div");
    mark.className = "tl-marquee";
    layer.append(mark);
    let dragged = false;
    const draw = (x, y) => {
      mark.style.left = `${Math.min(x0, x)}px`;
      mark.style.top = `${Math.min(y0, y)}px`;
      mark.style.width = `${Math.abs(x - x0)}px`;
      mark.style.height = `${Math.abs(y - y0)}px`;
    };
    const onMove = (ev) => {
      const x = ev.clientX - origin.left;
      const y = ev.clientY - origin.top;
      if (!dragged && Math.hypot(x - x0, y - y0) <= SELECT_SLOP) return;
      dragged = true;
      draw(x, y);
    };
    const onUp = (ev) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      mark.remove();
      if (!dragged) {
        if (!keep.length) clearSelection();
        return;
      }
      const x = ev.clientX - origin.left;
      const y = ev.clientY - origin.top;
      const s = scaleFactor();
      const rect = [Math.min(x0, x) * s, Math.min(y0, y) * s, Math.max(x0, x) * s, Math.max(y0, y) * s];
      const hit = marqueeLines.filter((ln) => {
        const xOverlap = ln.bbox[2] > rect[0] && ln.bbox[0] < rect[2];
        const top = Math.max(ln.bbox[1], rect[1]);
        const bottom = Math.min(ln.bbox[3], rect[3]);
        return xOverlap && bottom - top > 0.5 * (ln.bbox[3] - ln.bbox[1]);
      });
      const items = keep.concat(hit.filter((ln) => !keep.some((k) => sameLine(k, ln))));
      if (items.length) setSelection(items, hit[0] || keep[keep.length - 1]);
      else clearSelection();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
}

export function shiftBox(b, dx, dy) {
  return [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy];
}

// dx and dy are PDF points. Clamped to the page, so a move cannot push lines off it.
export async function moveLines(items, dx, dy) {
  const page = state.info.pages[state.page];
  const box = unionBox(items);
  let pdx = Math.max(-box[0], Math.min(page.width - box[2], dx));
  let pdy = Math.max(-box[1], Math.min(page.height - box[3], dy));
  if (Math.abs(pdx) < 0.5 && Math.abs(pdy) < 0.5) {
    clearGhosts();
    return;
  }
  const ops = items.map((ln) => ({ type: "erase_text", page: state.page, rect: ln.bbox, origin: ln.origin }));
  items.forEach((ln) => ops.push({
    type: "write_text",
    page: state.page,
    rect: ln.bbox,
    origin: ln.origin,
    dest: [ln.origin[0] + pdx, ln.origin[1] + pdy],
    text: ln.text,
    font: "auto",
    base_font: ln.base_font,
    font_xref: ln.font_xref,
    size: ln.size,
    color: hexToRgb(ln.color),
    tracking: ln.tracking ?? 0,
    leading: ln.leading ?? null,
  }));
  // The redraw matches the selection by place, so set it first.
  state.selected = {
    page: state.page,
    items: items.map((ln) => ({
      ...ln,
      bbox: shiftBox(ln.bbox, pdx, pdy),
      origin: [ln.origin[0] + pdx, ln.origin[1] + pdy],
    })),
    anchor: null,
  };
  try {
    await applyOps(ops);
  } catch (err) {
    clearGhosts();
    throw err;
  }
}

// Arrow keys move the selection one point at a time, ten with Shift.
// Moves run one after another, so a held key cannot start a write before the last one lands.
// The selection is read when the move runs, not when the key is pressed.
const ARROW_DIRS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
let nudgeQueue = Promise.resolve();

function nudgeSelection(dx, dy) {
  nudgeQueue = nudgeQueue.then(() => {
    const items = selectedItems();
    if (!items.length || !state.info) return;
    return runAction(() => moveLines(items, dx, dy));
  });
}

// Returns true when the key moved the selection, so the caller skips paging.
export function arrowNudge(e) {
  const dir = ARROW_DIRS[e.key];
  if (!dir || e.ctrlKey || e.metaKey || e.altKey) return false;
  if (state.editor || !selectedItems().length) return false;
  if (state.tool !== "select" && state.tool !== "replace") return false;
  const step = e.shiftKey ? 10 : 1;
  e.preventDefault();
  nudgeSelection(dir[0] * step, dir[1] * step);
  return true;
}

// Keys, paste and the pointer position for the selection. Bound once at startup.
export function bindSelectionKeys() {
  bindPictureMenu();
  bindTextMenu();
  document.addEventListener("paste", onPasteEvent);
  document.addEventListener("pointermove", (e) => { state.pointer = [e.clientX, e.clientY]; });
  document.addEventListener("keydown", (e) => {
    const typing = e.target && (e.target.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName));
    if ((e.key === "Delete" || e.key === "Backspace") && state.imageSel && !state.editor && !typing && state.tool === "select") {
      e.preventDefault();
      pictureAction("delete");
      return;
    }
    if ((e.key === "Delete" || e.key === "Backspace") && selectedItems().length && !state.editor && !typing
      && (state.tool === "select" || state.tool === "replace")) {
      e.preventDefault();
      deleteSelection();
      return;
    }
    if (e.key === "Escape" && !$("#text-menu").hidden) {
      hideTextMenu();
      return;
    }
    if (e.key === "Escape" && !$("#img-menu").hidden) {
      hideImageMenu();
      return;
    }
    if (e.key === "Escape" && !state.editor && (state.selected || state.imageSel)) {
      clearSelection();
      return;
    }
    const editable = e.target && (e.target.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName));
    if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A") && !state.editor && !editable
      && state.info && (state.tool === "select" || state.tool === "replace")) {
      e.preventDefault();
      ensureLines().then((lines) => {
        if (lines.length) setSelection(lines.slice(), lines[0]);
      }).catch(showError);
    }
    // Copy and cut need a selection. Paste comes in as a paste event, see onPasteEvent.
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !state.editor && !editable && state.info) {
      const key = e.key.toLowerCase();
      if ((key === "c" || key === "x") && selectedItems().length) {
        e.preventDefault();
        copySelection(key === "x");
      }
    }
  });
}
