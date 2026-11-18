import { $, api, getJson, state } from "./core.js";
import { scaleFactor } from "./view.js";
import { applyOps } from "./tools.js";
import { runAction } from "./files.js";
import { placeBox } from "./editor.js";
import { SELECT_SLOP, hideStyleBar, shiftBox, syncSelectionDom } from "./selection.js";

export async function ensureImages() {
  const key = `${state.docId}:${state.page}:${state.info.version}`;
  if (state.imageCache.key !== key) {
    const res = await getJson(`/api/docs/${state.docId}/pages/${state.page}/images`);
    state.imageCache = { key, images: res.images };
  }
  return state.imageCache.images;
}

export function isImageSelected(img) {
  const sel = state.imageSel;
  return Boolean(sel && img && sel.page === state.page && sel.xref === img.xref && sameBox(sel.bbox, img.bbox));
}

export function sameBox(a, b) {
  return a.every((v, i) => Math.abs(v - b[i]) < 0.5);
}

// The file renumbers objects on every save, so the picture is found by its place.
export function restoreImageSelection(images) {
  const sel = state.imageSel;
  if (!sel || sel.page !== state.page) {
    state.imageSel = null;
    return;
  }
  const cx = (sel.bbox[0] + sel.bbox[2]) / 2;
  const cy = (sel.bbox[1] + sel.bbox[3]) / 2;
  let best = null;
  let bestDist = 20;
  images.forEach((img) => {
    const d = Math.hypot((img.bbox[0] + img.bbox[2]) / 2 - cx, (img.bbox[1] + img.bbox[3]) / 2 - cy);
    if (d < bestDist) { bestDist = d; best = img; }
  });
  state.imageSel = best ? { page: state.page, xref: best.xref, bbox: best.bbox } : null;
  syncSelectionDom();
}

export function selectImage(img) {
  state.selected = null;
  state.imageSel = { page: state.page, xref: img.xref, bbox: img.bbox };
  hideStyleBar();
  syncSelectionDom();
}

export function bindImageBox(box, img) {
  box.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || state.tool !== "select") return;
    e.preventDefault();
    hideImageMenu();
    selectImage(img);
    startImageMove(e, img);
  });
  box.addEventListener("contextmenu", (e) => {
    if (state.tool !== "select") return;
    e.preventDefault();
    selectImage(img);
    showImageMenu(e.clientX, e.clientY);
  });
}

// A text box can sit on top of a picture, so look for the picture under the pointer too.
export function pictureUnderPoint(e) {
  return document.elementsFromPoint(e.clientX, e.clientY)
    .find((el) => el.classList && el.classList.contains("img-box")) || null;
}

export const MIN_PICTURE_PT = 10;

export function syncImageHandles(el, on) {
  const existing = el.querySelectorAll(".img-handle");
  if (!on) {
    existing.forEach((h) => h.remove());
    return;
  }
  if (existing.length) return;
  ["nw", "ne", "sw", "se"].forEach((corner) => {
    const handle = document.createElement("div");
    handle.className = `img-handle ${corner}`;
    handle.addEventListener("pointerdown", (e) => startImageResize(e, el.__img, corner));
    el.appendChild(handle);
  });
}

// Shift keeps the ratio. Size stops at MIN_PICTURE_PT.
export function resizedBox(box, corner, dx, dy, keepRatio) {
  const [x0, y0, x1, y1] = box;
  const w = x1 - x0;
  const h = y1 - y0;
  const left = corner.includes("w");
  const top = corner.includes("n");
  const ax = left ? x1 : x0;
  const ay = top ? y1 : y0;
  const px = (left ? x0 : x1) + dx;
  const py = (top ? y0 : y1) + dy;
  // Stops at the minimum, so the corner cannot pass the opposite one.
  let nw = Math.max(left ? ax - px : px - ax, 0);
  let nh = Math.max(top ? ay - py : py - ay, 0);
  if (keepRatio) {
    const k = Math.max(nw / w, nh / h, MIN_PICTURE_PT / Math.min(w, h));
    nw = w * k;
    nh = h * k;
  } else {
    nw = Math.max(nw, MIN_PICTURE_PT);
    nh = Math.max(nh, MIN_PICTURE_PT);
  }
  const nx0 = left ? ax - nw : ax;
  const ny0 = top ? ay - nh : ay;
  return [nx0, ny0, nx0 + nw, ny0 + nh];
}

export function startImageResize(e, img, corner) {
  if (e.button !== 0) return;
  e.preventDefault();
  e.stopPropagation();
  const s = scaleFactor();
  const start = { x: e.clientX, y: e.clientY };
  const ghost = document.createElement("div");
  ghost.className = "tl-ghost";
  placeBox(ghost, img.bbox);
  $("#stage").append(ghost);
  let target = img.bbox.slice();
  const onMove = (ev) => {
    target = resizedBox(img.bbox, corner, (ev.clientX - start.x) * s, (ev.clientY - start.y) * s, ev.shiftKey);
    placeBox(ghost, target);
  };
  const onUp = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    ghost.remove();
    const changed = target.some((v, i) => Math.abs(v - img.bbox[i]) > 0.5);
    if (changed) runAction(() => resizeImage(img, target));
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}

export async function resizeImage(img, target) {
  state.imageSel = { page: state.page, xref: img.xref, bbox: target };
  await applyOps([{ type: "resize_image", page: state.page, xref: img.xref, rect: img.bbox, dest: target }]);
}

export function showImageMenu(x, y) {
  const menu = $("#img-menu");
  menu.hidden = false;
  const w = menu.offsetWidth;
  const h = menu.offsetHeight;
  menu.style.left = `${Math.min(x, window.innerWidth - w - 6)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - h - 6)}px`;
}

export function hideImageMenu() {
  $("#img-menu").hidden = true;
}

export async function pictureAction(action) {
  const sel = state.imageSel;
  hideImageMenu();
  if (!sel || sel.page !== state.page) return;
  if (action === "delete") {
    state.imageSel = null;
    await runAction(() => applyOps([{ type: "delete_image", page: state.page, xref: sel.xref, rect: sel.bbox }]));
    return;
  }
  await runAction(() => applyOps([{
    type: "set_image_layer", page: state.page, xref: sel.xref, rect: sel.bbox, z: action,
  }]));
}

export function bindPictureMenu() {
  const menu = $("#img-menu");
  menu.addEventListener("mousedown", (e) => e.preventDefault());
  menu.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-img]");
    if (btn) pictureAction(btn.dataset.img);
  });
  document.addEventListener("pointerdown", (e) => {
    if (!menu.contains(e.target)) hideImageMenu();
  });
  window.addEventListener("scroll", hideImageMenu, true);
}

export function startImageMove(e, img) {
  const start = { x: e.clientX, y: e.clientY };
  const ghost = document.createElement("div");
  ghost.className = "tl-ghost";
  placeBox(ghost, img.bbox);
  $("#stage").append(ghost);
  let dx = 0, dy = 0;
  const onMove = (ev) => {
    dx = ev.clientX - start.x;
    dy = ev.clientY - start.y;
    ghost.style.transform = `translate(${dx}px, ${dy}px)`;
  };
  const onUp = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    ghost.remove();
    if (Math.hypot(dx, dy) > SELECT_SLOP) runAction(() => moveImage(img, dx, dy));
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}

export async function moveImage(img, dx, dy) {
  const s = scaleFactor();
  const page = state.info.pages[state.page];
  let pdx = dx * s;
  let pdy = dy * s;
  pdx = Math.max(-img.bbox[0], Math.min(page.width - img.bbox[2], pdx));
  pdy = Math.max(-img.bbox[1], Math.min(page.height - img.bbox[3], pdy));
  if (Math.abs(pdx) < 0.5 && Math.abs(pdy) < 0.5) return;
  state.imageSel = { page: state.page, xref: img.xref, bbox: shiftBox(img.bbox, pdx, pdy) };
  await applyOps([{
    type: "move_image",
    page: state.page,
    xref: img.xref,
    rect: img.bbox,
    dest: [img.bbox[0] + pdx, img.bbox[1] + pdy],
  }]);
}
