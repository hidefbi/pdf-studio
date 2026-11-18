import { $, api, getJson, postJson, state, t, toast } from "./core.js";
import { renderAll } from "./view.js";
import { download, runAction } from "./files.js";

// ---------- page, bookmark and comment tools ----------

export function bindPageTools() {
  $("#insert-blank").addEventListener("click", () => runAction(async () => {
    await postJson(`/api/docs/${state.docId}/pages/blank`, { after: state.page });
    state.page += 1;
    state.info = await getJson(`/api/docs/${state.docId}`);
    renderAll();
    toast(t("page_inserted"));
  }));

  $("#stamp-open").addEventListener("click", () => {
    $("#st-error").hidden = true;
    $("#stamp-dialog").hidden = false;
    $("#st-text").focus();
  });
  $("#st-cancel").addEventListener("click", () => ($("#stamp-dialog").hidden = true));
  $("#stamp-form").addEventListener("submit", submitStamp);

  $("#toc-open").addEventListener("click", () => runAction(openTocDialog));
  $("#toc-add").addEventListener("click", () => {
    state.tocDraft.push({ level: 1, title: "", page: state.page + 1 });
    renderTocRows();
  });
  $("#toc-cancel").addEventListener("click", () => ($("#toc-dialog").hidden = true));
  $("#toc-save").addEventListener("click", () => runAction(saveToc));

  $("#annots-open").addEventListener("click", () => runAction(openAnnotsDialog));
  $("#annots-close").addEventListener("click", () => ($("#annots-dialog").hidden = true));
}

export function showToolError(id, message) {
  const el = $(id);
  el.textContent = message;
  el.hidden = false;
}

export async function submitStamp(event) {
  event.preventDefault();
  const body = {
    text: $("#st-text").value,
    where: $("#st-where").value,
    size: Number($("#st-size").value),
    color: $("#st-color").value,
    opacity: Number($("#st-opacity").value),
    angle: Number($("#st-angle").value),
    pages: $("#st-pages").value,
    page: state.page,
    behind: $("#st-behind").checked,
  };
  try {
    await postJson(`/api/docs/${state.docId}/stamp`, body);
    $("#stamp-dialog").hidden = true;
    state.info = await getJson(`/api/docs/${state.docId}`);
    renderAll();
    toast(t("stamp_done"));
  } catch (err) {
    showToolError("#st-error", err.message);
  }
}


export async function openTocDialog() {
  $("#toc-error").hidden = true;
  state.tocDraft = (await getJson(`/api/docs/${state.docId}/toc`)).items;
  renderTocRows();
  $("#toc-dialog").hidden = false;
}

export function renderTocRows() {
  const box = $("#toc-rows");
  box.replaceChildren();
  if (!state.tocDraft.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = t("toc_empty");
    box.append(empty);
    return;
  }
  state.tocDraft.forEach((item) => {
    const row = document.createElement("div");
    row.className = "row";
    const title = document.createElement("input");
    title.className = "grow";
    title.type = "text";
    title.value = item.title;
    title.addEventListener("input", () => (item.title = title.value));
    const level = document.createElement("input");
    level.className = "narrow";
    level.type = "number";
    level.min = 1;
    level.max = 10;
    level.title = t("toc_level");
    level.value = item.level;
    level.addEventListener("input", () => (item.level = Number(level.value)));
    const page = document.createElement("input");
    page.className = "narrow";
    page.type = "number";
    page.min = 1;
    page.max = state.info.pages.length;
    page.title = t("toc_page");
    page.value = item.page;
    page.addEventListener("input", () => (item.page = Number(page.value)));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn small";
    remove.textContent = t("toc_remove");
    remove.addEventListener("click", () => {
      state.tocDraft = state.tocDraft.filter((other) => other !== item);
      renderTocRows();
    });
    row.append(title, level, page, remove);
    box.append(row);
  });
}

export async function saveToc() {
  if (state.tocDraft.some((item) => !item.title.trim())) return showToolError("#toc-error", t("toc_need_title"));
  try {
    await sendJson("PUT", `/api/docs/${state.docId}/toc`, { items: state.tocDraft });
    $("#toc-dialog").hidden = true;
    toast(t("toc_saved"));
  } catch (err) {
    showToolError("#toc-error", err.message);
  }
}

export async function sendJson(method, path, body) {
  return (await api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })).json();
}

export async function openAnnotsDialog() {
  $("#annots-error").hidden = true;
  await renderAnnotRows();
  $("#annots-dialog").hidden = false;
}

export async function renderAnnotRows() {
  const items = (await getJson(`/api/docs/${state.docId}/annotations`)).items;
  const box = $("#annots-rows");
  box.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = t("annots_empty");
    box.append(empty);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "row";
    const where = document.createElement("span");
    where.className = "label";
    where.textContent = t("page_of", { n: item.page + 1, total: state.info.pages.length });
    const kind = document.createElement("span");
    kind.className = "label";
    kind.textContent = item.type;
    const content = document.createElement("input");
    content.className = "grow";
    content.type = "text";
    content.value = item.content;
    const save = document.createElement("button");
    save.type = "button";
    save.className = "btn small";
    save.textContent = t("save");
    save.addEventListener("click", () => runAction(async () => {
      await sendJson("PATCH", `/api/docs/${state.docId}/annotations/${item.xref}`, { content: content.value });
      await refreshAfterAnnotChange();
      toast(t("annots_saved"));
    }));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn small";
    remove.textContent = t("annots_delete");
    remove.addEventListener("click", () => runAction(async () => {
      if (!confirm(t("confirm_delete_annot"))) return;
      await api(`/api/docs/${state.docId}/annotations/${item.xref}`, { method: "DELETE" });
      await refreshAfterAnnotChange();
      toast(t("annots_deleted"));
    }));
    row.append(where, kind, content, save, remove);
    box.append(row);
  });
}

export async function refreshAfterAnnotChange() {
  state.info = await getJson(`/api/docs/${state.docId}`);
  renderAll();
  await renderAnnotRows();
}

// ---------- read-only export ----------

export function openReadonlyDialog() {
  $("#ro-error").hidden = true;
  $("#readonly-dialog").hidden = false;
  $("#ro-owner").focus();
}

export function closeReadonlyDialog() {
  $("#readonly-dialog").hidden = true;
  ["#ro-owner", "#ro-owner2", "#ro-open"].forEach((sel) => ($(sel).value = ""));
}

export function showFormError(message) {
  const el = $("#ro-error");
  el.textContent = message;
  el.hidden = false;
}

export function filenameFrom(res, fallback) {
  const match = (res.headers.get("Content-Disposition") || "").match(/filename\*=UTF-8''([^;]+)/);
  return match ? decodeURIComponent(match[1]) : fallback;
}

export async function exportReadonly(event) {
  event.preventDefault();
  const owner = $("#ro-owner").value;
  if (owner.length < 6) return showFormError(t("err_password_short"));
  if (owner !== $("#ro-owner2").value) return showFormError(t("err_password_mismatch"));
  const body = {
    owner_password: owner,
    open_password: $("#ro-open").value || null,
    printing: $("#ro-print").value,
    changes: $("#ro-changes").value,
    allow_copy: $("#ro-copy").checked,
  };
  $("#ro-error").hidden = true;
  try {
    const res = await api(`/api/docs/${state.docId}/export/readonly`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filenameFrom(res, "readonly.pdf");
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    closeReadonlyDialog();
    toast(t("readonly_done"));
  } catch (_) {
    // Never echo server messages here: validation errors can contain the typed password.
    showFormError(t("readonly_failed"));
  }
}
