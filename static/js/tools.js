import { $, HIGHLIGHT_COLOR, api, getJson, hexToRgb, normRect, postJson, showError, state, t, toast, endEdit } from "./core.js";
import { renderAll, scaleFactor, svgShape, toPdf } from "./view.js";
import { scrollSnapshot } from "./events.js";
import { fontKey, startEditor } from "./editor.js";
import { drawTextLayer, ensureLines, clearSelection } from "./selection.js";
import { hideStyleBar } from "./stylebar.js";
import { currentColor, currentSize } from "./toolbar.js";

// ---------- drawing and tools ----------

export function setTool(tool) {
  hideStyleBar();
  state.tool = tool;
  document.querySelectorAll(".tool").forEach((b) => b.classList.toggle("active", b.dataset.tool === tool));
  $("#overlay").classList.toggle("active", tool !== "select" && tool !== "replace");
  endEdit(true);
  drawTextLayer().catch(showError);
  if (tool === "replace") toast(t("hint_replace"));
  if (tool === "select" && state.info) toast(t("hint_select"));
  if (tool === "text") toast(t("hint_text"));
}

export function drawPreview() {
  const svg = $("#overlay");
  const s = scaleFactor();
  const d = state.drag;
  let shape = null;
  if (state.tool === "ink" && state.ink) {
    const pts = state.ink.map(([x, y]) => `${x / s},${y / s}`).join(" ");
    shape = svgShape("polyline", { points: pts, fill: "none", stroke: $("#color").value, "stroke-width": 2 });
  } else if (d && d.moved) {
    const [x0, y0, x1, y1] = normRect(d.start, d.last);
    shape = svgShape("rect", {
      class: "preview", x: x0 / s, y: y0 / s, width: (x1 - x0) / s, height: (y1 - y0) / s,
    });
  }
  svg.replaceChildren(...(shape ? [shape] : []));
}

// Pages moving, turning or going away make the selection point at the wrong place.
const RELAYOUT_OPS = new Set(["delete_page", "move_page", "rotate_page"]);

export async function applyOps(ops) {
  state.keepScroll = scrollSnapshot();
  if (ops.some((op) => RELAYOUT_OPS.has(op.type))) clearSelection();
  const res = await postJson(`/api/docs/${state.docId}/ops`, { ops });
  if (res.warnings && res.warnings.length) toast(t("overflow_warning"), true);
  state.info = await getJson(`/api/docs/${state.docId}`);
  renderAll(pagesTouched(ops));
}

// Only the pages an edit names need a new thumbnail. Page moves and deletes redraw them all.
function pagesTouched(ops) {
  if (ops.some((op) => RELAYOUT_OPS.has(op.type))) return null;
  return [...new Set(ops.map((op) => op.page))];
}

export async function finishTool(drag) {
  const tool = state.tool;
  const ink = state.ink;
  state.ink = null;
  $("#overlay").replaceChildren();
  const page = state.page;
  const rect = normRect(drag.start, drag.last);
  const tiny = !drag.moved;
  const color = hexToRgb($("#color").value);
  const size = Number($("#size").value) || 12;

  switch (tool) {
    case "text": {
      const r = tiny
        ? [drag.start[0], drag.start[1], drag.start[0] + 240, drag.start[1] + size * 1.6]
        : rect;
      startEditor({
        bbox: r,
        text: "",
        size,
        color: $("#color").value,
        bg: "transparent",
        // Read at confirm time, so edits made while typing count.
        onCommit: (value, settings) =>
          value.trim()
            ? [{ type: "text", page, rect: r, text: value, font: fontKey(), size: currentSize(size), color: hexToRgb(currentColor()), tracking: settings.kerning, leading: settings.leading }]
            : null,
      });
      break;
    }
    case "replace":
      break;
    case "highlight":
    case "underline":
    case "strikeout": {
      if (tiny) return;
      await applyOps([{ type: tool, page, rect, color: HIGHLIGHT_COLOR }]);
      break;
    }
    case "rect": {
      if (tiny) return;
      await applyOps([{ type: "rect", page, rect, color, width: 1.5 }]);
      break;
    }
    case "redact": {
      if (tiny) return;
      if (!confirm(t("confirm_redact"))) return;
      await applyOps([{ type: "redact", page, rect }]);
      toast(t("redact_done"));
      break;
    }
    case "note": {
      const text = prompt(t("prompt_note"));
      if (text) {
        const [x, y] = drag.start;
        await applyOps([{ type: "note", page, rect: [x, y, x, y], text }]);
      }
      break;
    }
    case "image": {
      state.pendingImageRect = tiny
        ? [drag.start[0], drag.start[1], drag.start[0] + 200, drag.start[1] + 150]
        : rect;
      $("#image-input").click();
      break;
    }
    case "ink": {
      if (!ink || ink.length < 2 || tiny) return;
      await applyOps([{ type: "ink", page, points: [ink], color, width: 2 }]);
      break;
    }
    default:
      break;
  }
}

export function bindCanvas() {
  const ov = $("#overlay");
  ov.addEventListener("pointerdown", (e) => {
    if (state.tool === "select" || !state.info) return;
    ov.setPointerCapture(e.pointerId);
    const p = toPdf(e.clientX, e.clientY);
    state.drag = { start: p, last: p, moved: false, screen: [e.clientX, e.clientY] };
    if (state.tool === "ink") state.ink = [p];
  });
  ov.addEventListener("pointermove", (e) => {
    const d = state.drag;
    if (!d) return;
    d.last = toPdf(e.clientX, e.clientY);
    if (Math.hypot(e.clientX - d.screen[0], e.clientY - d.screen[1]) > 4) d.moved = true;
    if (state.tool === "ink" && state.ink) state.ink.push(d.last);
    drawPreview();
  });
  ov.addEventListener("pointerup", async () => {
    const d = state.drag;
    if (!d) return;
    state.drag = null;
    try {
      await finishTool(d);
    } catch (err) {
      showError(err);
    }
  });
}

export async function recognizePage() {
  if (!state.info) return;
  const existing = await ensureLines();
  if (existing.length && !confirm(t("ocr_confirm"))) return;
  toast(t("ocr_busy"));
  let res;
  try {
    res = await postJson(`/api/docs/${state.docId}/pages/${state.page}/ocr`, {});
  } catch (err) {
    if (err.message === "ocr_not_installed") toast(t("ocr_unavailable"), true);
    else showError(err);
    return;
  }
  if (!res.lines.length) {
    toast(t("ocr_none"));
    return;
  }
  await applyOps(res.lines.map((l) => ({
    type: "ocr_text",
    page: state.page,
    rect: l.bbox,
    text: l.text,
    origin: l.origin,
    size: l.size,
    bold: Boolean(l.bold),
  })));
  toast(t("ocr_done", { n: res.lines.length }));
}
