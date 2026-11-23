import { $, DOC_KEY, api, getJson, showError, state, t, toast } from "./core.js";
import { restoreScroll } from "./events.js";
import { drawTextLayer, clearSelection } from "./selection.js";

// ---------- document view ----------

export async function openDoc(id) {
  state.info = await getJson(`/api/docs/${id}`);
  state.docId = id;
  state.page = 0;
  state.hit = null;
  localStorage.setItem(DOC_KEY, id);
  renderAll();
}

export function clampPage() {
  const count = state.info ? state.info.pages.length : 0;
  state.page = Math.max(0, Math.min(state.page, count - 1));
}

export function renderAll() {
  const hasDoc = Boolean(state.info);
  $("#empty").hidden = hasDoc;
  $("#stage").hidden = !hasDoc;
  document.title = hasDoc ? `${state.info.name} - PDF Studio` : "PDF Studio";
  $("#undo").disabled = !hasDoc || state.info.undo_steps === 0;
  $("#redo").disabled = !hasDoc || state.info.redo_steps === 0;
  $("#delete-doc").disabled = !hasDoc;
  ["#insert-blank", "#stamp-open", "#toc-open", "#annots-open"].forEach((sel) => ($(sel).disabled = !hasDoc));
  if (hasDoc) clampPage();
  // Thumbnails follow the version, so an undo redraws them too.
  const key = hasDoc ? `${state.docId}:${state.info.version}:${state.info.pages.length}` : "";
  if (key !== state.thumbsKey) {
    renderThumbs();
    state.thumbsKey = key;
  }
  // A page added or removed under the selection makes it point at the wrong page.
  const layout = hasDoc ? `${state.docId}:${state.info.pages.length}` : "";
  if (layout !== state.layoutKey) {
    state.layoutKey = layout;
    clearSelection();
  }
  renderPage();
}

// Device resolution keeps text sharp.
export const RENDER_SCALE = Math.min(3, Math.max(2, window.devicePixelRatio || 1));
export const MAX_RENDER_SCALE = 4;

export function renderPage() {
  if (!state.info) return;
  const img = $("#page-img");
  const page = state.info.pages[state.page];
  img.onload = () => {
    restoreScroll();
    syncOverlay();
    drawTextLayer().catch(showError);
  };
  img.onerror = () => toast(t("page_load_failed"), true);
  // Fixed first, so the page does not collapse while the new image loads.
  img.style.width = `${page.width * state.zoom}px`;
  img.style.height = `${page.height * state.zoom}px`;
  const scale = Math.min(MAX_RENDER_SCALE, state.zoom * RENDER_SCALE);
  img.src = `/api/docs/${state.docId}/pages/${state.page}.png?zoom=${scale}&v=${state.info.version}`;
  const thumb = document.querySelectorAll(".thumb")[state.page];
  if (thumb) thumb.src = `/api/docs/${state.docId}/pages/${state.page}.png?zoom=${0.4 * RENDER_SCALE}&v=${state.info.version}`;
  $("#overlay").replaceChildren();
  renderPageLabel();
  document.querySelectorAll(".thumb").forEach((el, i) => el.classList.toggle("active", i === state.page));
}

export function renderPageLabel() {
  if (!state.info) {
    $("#page-label").textContent = "";
    return;
  }
  $("#page-label").textContent = t("page_of", { n: state.page + 1, total: state.info.pages.length });
  thumbLabels();
}

export function renderThumbs() {
  const box = $("#thumbs");
  box.replaceChildren();
  if (!state.info) return;
  state.info.pages.forEach((_, i) => {
    const img = document.createElement("img");
    img.className = "thumb";
    img.loading = "lazy";
    img.alt = "";
    img.tabIndex = 0;
    img.setAttribute("role", "button");
    img.src = `/api/docs/${state.docId}/pages/${i}.png?zoom=${0.4 * RENDER_SCALE}&v=${state.info.version}`;
    const go = () => {
      state.page = i;
      renderPage();
    };
    img.onclick = go;
    img.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      go();
    });
    box.appendChild(img);
  });
  thumbLabels();
}

// Thumbnails are buttons for screen readers, so each one names its page. Called again on a language change.
export function thumbLabels() {
  const total = state.info.pages.length;
  document.querySelectorAll(".thumb").forEach((el, i) => el.setAttribute("aria-label", t("page_of", { n: i + 1, total })));
}

export function syncOverlay() {
  const img = $("#page-img");
  const svg = $("#overlay");
  svg.setAttribute("width", img.clientWidth);
  svg.setAttribute("height", img.clientHeight);
  svg.setAttribute("viewBox", `0 0 ${img.clientWidth} ${img.clientHeight}`);
  if (state.hit && state.hit.page === state.page) {
    const s = scaleFactor();
    const [x0, y0, x1, y1] = state.hit.rect;
    svg.replaceChildren(svgShape("rect", {
      class: "hit", x: x0 / s, y: y0 / s, width: (x1 - x0) / s, height: (y1 - y0) / s,
    }));
  }
}

export const SVG_NS = "http://www.w3.org/2000/svg";

// Builds an SVG element from attributes, without parsing markup.
export function svgShape(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, String(value));
  return el;
}

export function scaleFactor() {
  return state.info.pages[state.page].width / $("#page-img").clientWidth;
}

export function toPdf(clientX, clientY) {
  const box = $("#overlay").getBoundingClientRect();
  const s = scaleFactor();
  return [(clientX - box.left) * s, (clientY - box.top) * s];
}
