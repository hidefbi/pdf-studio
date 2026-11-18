import { $, api, getJson, showError, state, t, toast } from "./core.js";
import { MAX_FONT_MB } from "./files.js";
import { CJK_FONT } from "./editor.js";

// ---------- fonts ----------

export function renderFontSelect() {
  const sel = $("#font");
  const current = sel.value || "auto";
  sel.replaceChildren();
  sel.appendChild(new Option(t("auto_font"), "auto"));
  const group = (label, items) => {
    if (!items.length) return;
    const g = document.createElement("optgroup");
    g.label = label;
    items.forEach((f) => g.appendChild(new Option(f.name, f.id)));
    sel.appendChild(g);
  };
  group(t("font_builtin"), state.fonts.builtin);
  group(t("font_custom"), state.fonts.custom);
  sel.value = [...sel.options].some((o) => o.value === current) ? current : "auto";
}

export async function loadFonts() {
  state.fonts = await getJson("/api/fonts");
  renderFontSelect();
}

// ---------- font manager ----------

export const previewFaces = new Set();

export async function previewFamily(font) {
  const family = `ufont-${font.id}`;
  if (!previewFaces.has(font.id)) {
    previewFaces.add(font.id);
    try {
      const face = new FontFace(family, `url(/api/fonts/${font.id}/file)`);
      await face.load();
      document.fonts.add(face);
    } catch (_) {
      previewFaces.delete(font.id);
    }
  }
  return family;
}

export function builtinFamily(id) {
  return { helv: "Helvetica, Arial", tiro: "'Times New Roman', serif", cour: "'Courier New', monospace" }[id] || CJK_FONT;
}

export function fontRow(font, builtin) {
  const row = document.createElement("div");
  row.className = "font-row";
  const head = document.createElement("div");
  head.className = "font-head";
  const name = document.createElement("strong");
  name.textContent = font.name;
  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = builtin
    ? t("font_builtin_tag")
    : `${t("font_size_kb", { n: Math.max(1, Math.round(font.size / 1024)) })} · ${font.cjk ? t("font_cjk_yes") : t("font_cjk_no")}`;
  head.append(name, meta);
  if (!builtin) {
    const del = document.createElement("button");
    del.className = "btn small";
    del.textContent = t("font_delete");
    del.dataset.delete = font.id;
    head.appendChild(del);
  }
  const sample = document.createElement("div");
  sample.className = "sample";
  sample.textContent = t("font_sample");
  row.append(head, sample);
  if (builtin) {
    sample.style.fontFamily = builtinFamily(font.id);
  } else {
    previewFamily(font).then((family) => {
      sample.style.fontFamily = `"${family}", sans-serif`;
    });
  }
  return row;
}

export function renderFontList() {
  const box = $("#font-list");
  box.replaceChildren();
  state.fonts.builtin.forEach((f) => box.appendChild(fontRow(f, true)));
  state.fonts.custom.forEach((f) => box.appendChild(fontRow(f, false)));
  if (!state.fonts.custom.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = t("font_none");
    box.appendChild(p);
  }
}

export function openFontDialog() {
  renderFontList();
  $("#font-dialog").hidden = false;
}

export function closeFontDialog() {
  $("#font-dialog").hidden = true;
}

export async function uploadFonts(files) {
  for (const file of files) {
    try {
      if (file.size > MAX_FONT_MB * 1024 * 1024) throw new Error(t("font_too_large", { n: MAX_FONT_MB }));
      const form = new FormData();
      form.append("file", file);
      const res = await (await api("/api/fonts", { method: "POST", body: form })).json();
      toast(t("font_uploaded", { name: res.name }));
    } catch (err) {
      showError(err);
    }
  }
  await loadFonts();
  renderFontList();
}

export async function deleteFont(id) {
  if (!confirm(t("confirm_delete_font"))) return;
  await api(`/api/fonts/${id}`, { method: "DELETE" });
  await loadFonts();
  renderFontList();
}
