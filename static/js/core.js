import { renderPageLabel } from "./view.js";
import { renderFontSelect } from "./fonts.js";

export const $ = (sel) => document.querySelector(sel);
export const LANG_KEY = "pdfstudio.lang";
export const DOC_KEY = "pdfstudio.doc";
export const HIGHLIGHT_COLOR = [1, 0.9, 0.2];
export const SIZE_STEPS = [4, 6, 8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 32, 36, 40, 48, 56, 64, 72, 96, 120, 144];
export const PALETTE = ["#000000", "#4d4d4d", "#999999", "#ffffff", "#e53935", "#fb8c00", "#fdd835", "#7cb342",
  "#2e7d32", "#00897b", "#00acc1", "#1e88e5", "#1a237e", "#3949ab", "#8e24aa", "#d81b60", "#f48fb1", "#6d4c41"];
export const HEARTBEAT_MS = 3000;
export const CLIENT_KEY = "pdfstudio.client";
export const API_HEADERS = { "Content-Type": "application/json", "X-PDF-Studio": "1" };
export const PASTE_OFFSET = 12; // PDF points

export const state = {
  thumbsKey: "",
  keepScroll: null,
  lineCache: { key: "", lines: [] },
  editor: null,
  imageCache: { key: "", images: [] },
  heartbeatTimer: null,
  tocDraft: [],
  lang: "en",
  locale: {},
  docId: null,
  info: null,
  page: 0,
  zoom: 1.5,
  tool: "select",
  fonts: { builtin: [], custom: [] },
  drag: null,
  ink: null,
  pendingImageRect: null,
  hit: null,
  selected: null,
  imageSel: null,
  clipboard: null,
  pointer: null,
};

// ---------- helpers ----------

export async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let message = res.statusText;
    try {
      message = (await res.json()).detail || message;
    } catch (_) { /* keep status text */ }
    const error = new Error(typeof message === "string" ? message : JSON.stringify(message));
    error.status = res.status;
    throw error;
  }
  return res;
}

export async function getJson(path) {
  return (await api(path)).json();
}

export async function postJson(path, body) {
  return (await api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })).json();
}

export function t(key, vars = {}) {
  let s = state.locale[key] || key;
  for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
  return s;
}

export function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = isError ? "toast error show" : "toast show";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.className = "toast"), 3500);
}

export function showError(err) {
  toast(err.message || String(err), true);
}

export function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

export function normRect(a, b) {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}

export function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

// ---------- locale ----------

export async function setLocale(lang) {
  state.locale = await getJson(`/locales/${lang}.json`);
  state.lang = lang;
  localStorage.setItem(LANG_KEY, lang);
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  document.querySelectorAll("[data-i18n-title]").forEach((el) => (el.title = t(el.dataset.i18nTitle)));
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => (el.placeholder = t(el.dataset.i18nPlaceholder)));
  $("#lang").value = lang;
  renderFontSelect();
  renderPageLabel();
}
