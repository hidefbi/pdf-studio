import { $, DOC_KEY, api, getJson, postJson, readAsDataUrl, setLocale, state, t, toast } from "./core.js";
import { openDoc, renderAll, renderPage } from "./view.js";
import { applyOps, bindCanvas, recognizePage, setTool } from "./tools.js";
import { download, runAction, uploadPdf } from "./files.js";
import { closeFontDialog, deleteFont, openFontDialog, renderFontSelect, uploadFonts } from "./fonts.js";
import { runSearch } from "./search.js";
import { onPagePress } from "./editor.js";
import { applyStyle, bindStyleBar } from "./selection.js";
import { closeReadonlyDialog, exportReadonly, openReadonlyDialog } from "./dialogs.js";

// ---------- events ----------

export function bindEvents() {
  bindCanvas();
  document.addEventListener("pointerdown", onPagePress, true);

  $("#lang").addEventListener("change", (e) => runAction(() => setLocale(e.target.value)));

  $("#file-input").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) runAction(async () => openDoc((await uploadPdf(file)).id));
  });

  $("#merge-input").addEventListener("change", (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    if (!files.length || !state.docId) {
      if (files.length) toast(t("open_first"), true);
      return;
    }
    runAction(async () => {
      const ids = [state.docId];
      for (const f of files) ids.push((await uploadPdf(f)).id);
      const merged = await postJson("/api/merge", { ids, name: `${state.info.name.replace(/\.pdf$/i, "")}-merged.pdf` });
      await openDoc(merged.id);
      toast(t("merge_done"));
    });
  });

  $("#undo").addEventListener("click", () => runAction(async () => {
    state.keepScroll = scrollSnapshot();
    await postJson(`/api/docs/${state.docId}/undo`, {});
    state.info = await getJson(`/api/docs/${state.docId}`);
    renderAll();
  }));

  $("#redo").addEventListener("click", () => runAction(async () => {
    state.keepScroll = scrollSnapshot();
    await postJson(`/api/docs/${state.docId}/redo`, {});
    state.info = await getJson(`/api/docs/${state.docId}`);
    renderAll();
  }));

  $("#delete-doc").addEventListener("click", () => runAction(async () => {
    if (!state.docId || !confirm(t("confirm_delete_doc"))) return;
    if (state.editor && state.editor.__finish) state.editor.__finish(false);
    await api(`/api/docs/${state.docId}`, { method: "DELETE" });
    state.info = null;
    state.docId = null;
    localStorage.removeItem(DOC_KEY);
    renderAll();
  }));

  // Leaving with an unconfirmed edit asks first, so the browser prompt decides instead of a silent commit.
  window.addEventListener("beforeunload", (e) => {
    if (!state.editor || !state.editor.__pending || !state.editor.__pending()) return;
    e.preventDefault();
    e.returnValue = "";
  });

  $("#export").addEventListener("change", (e) => {
    const fmt = e.target.value;
    e.target.value = "";
    if (fmt === "readonly") {
      if (state.docId) openReadonlyDialog();
      return;
    }
    if (!fmt || !state.docId) return;
    let url = `/api/docs/${state.docId}/export/${fmt}`;
    if (fmt === "png") url += `?page=${state.page}`;
    runAction(() => download(url, `export.${fmt === "images" ? "zip" : fmt}`));
  });

  document.querySelectorAll(".tool").forEach((btn) =>
    btn.addEventListener("click", () => setTool(btn.dataset.tool))
  );

  $("#fonts-btn").addEventListener("click", openFontDialog);
  $("#font-close").addEventListener("click", closeFontDialog);
  $("#font-dialog").addEventListener("click", (e) => {
    if (e.target.id === "font-dialog") closeFontDialog();
  });
  $("#font-input").addEventListener("change", (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    if (files.length) runAction(() => uploadFonts(files));
  });
  $("#font-list").addEventListener("click", (e) => {
    const id = e.target.dataset.delete;
    if (id) runAction(() => deleteFont(id));
  });
  $("#readonly-form").addEventListener("submit", exportReadonly);
  $("#ro-cancel").addEventListener("click", closeReadonlyDialog);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeFontDialog();
      closeReadonlyDialog();
    }
  });

  // With no selection, the font only applies to new text.
  $("#font").addEventListener("change", () => {
    renderFontSelect();
    runAction(() => applyStyle("font"));
  });

  $("#image-input").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    const rect = state.pendingImageRect;
    state.pendingImageRect = null;
    if (!file || !rect) return;
    runAction(async () => {
      const image = await readAsDataUrl(file);
      await applyOps([{ type: "image", page: state.page, rect, image }]);
    });
  });

  $("#rotate").addEventListener("click", () =>
    runAction(() => applyOps([{ type: "rotate_page", page: state.page, angle: 90 }]))
  );

  $("#delete-page").addEventListener("click", () => {
    if (!state.info || !confirm(t("confirm_delete_page"))) return;
    runAction(() => applyOps([{ type: "delete_page", page: state.page }]));
  });

  $("#ocr-page").addEventListener("click", () => runAction(recognizePage));
  bindStyleBar();
  $("#extract").addEventListener("click", () => {
    if (!state.docId) return;
    const spec = prompt(t("extract_prompt"), `1-${state.info.pages.length}`);
    if (!spec) return;
    runAction(async () => {
      const res = await postJson(`/api/docs/${state.docId}/extract`, { pages: spec });
      await openDoc(res.id);
      toast(t("extract_done"));
    });
  });

  $("#zoom-in").addEventListener("click", () => setZoom(state.zoom + 0.25));
  $("#zoom-out").addEventListener("click", () => setZoom(state.zoom - 0.25));
  $("#prev").addEventListener("click", () => goPage(-1));
  $("#next").addEventListener("click", () => goPage(1));

  $("#search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    runAction(() => runSearch($("#search-input").value));
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select, textarea") || e.target.isContentEditable) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      $(e.shiftKey ? "#redo" : "#undo").click();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
      e.preventDefault();
      $("#redo").click();
    } else if (e.key === "ArrowRight") {
      goPage(1);
    } else if (e.key === "ArrowLeft") {
      goPage(-1);
    }
  });
}

export function setZoom(value) {
  state.zoom = Math.max(0.5, Math.min(3, Math.round(value * 100) / 100));
  if (state.info) renderPage();
}

export function goPage(delta) {
  if (!state.info) return;
  const next = state.page + delta;
  if (next < 0 || next >= state.info.pages.length) return;
  state.page = next;
  state.hit = null;
  renderPage();
}

export function scrollSnapshot() {
  const sc = $("#scroller");
  return { top: sc.scrollTop, left: sc.scrollLeft };
}

export function restoreScroll() {
  if (!state.keepScroll) return;
  const sc = $("#scroller");
  sc.scrollTop = state.keepScroll.top;
  sc.scrollLeft = state.keepScroll.left;
  state.keepScroll = null;
}
