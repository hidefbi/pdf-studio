import { $, api, showError, t, toast } from "./core.js";

// ---------- page actions ----------

export async function runAction(fn) {
  try {
    await fn();
  } catch (err) {
    showError(err);
  }
}

export const MAX_UPLOAD_MB = 500;
export const MAX_FONT_MB = 30;

export async function uploadPdf(file) {
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) throw new Error(t("upload_too_large", { n: MAX_UPLOAD_MB }));
  let password = "";
  for (;;) {
    const form = new FormData();
    form.append("file", file);
    form.append("password", password);
    try {
      const body = await (await api("/api/docs", { method: "POST", body: form })).json();
      if (body.unlocked) toast(t("unlocked_copy_notice"));
      return body;
    } catch (err) {
      if (err.status !== 401) throw err;
      const hint = err.message === "wrong password" ? t("password_wrong") : t("password_needed");
      const answer = await askPassword(hint);
      if (answer === null) throw new Error(t("password_cancelled"));
      password = answer;
    }
  }
}

// Resolves with the typed password, or null when the dialog is cancelled.
export function askPassword(hint) {
  return new Promise((resolve) => {
    const dialog = $("#password-dialog");
    const form = $("#password-form");
    const input = $("#pw-input");
    const cancel = $("#pw-cancel");
    $("#pw-hint").textContent = hint;
    input.value = "";
    dialog.hidden = false;
    input.focus();
    const done = (value) => {
      dialog.hidden = true;
      form.removeEventListener("submit", onSubmit);
      cancel.removeEventListener("click", onCancel);
      resolve(value);
    };
    const onSubmit = (e) => {
      e.preventDefault();
      done(input.value);
    };
    const onCancel = () => done(null);
    form.addEventListener("submit", onSubmit);
    cancel.addEventListener("click", onCancel);
  });
}

export async function download(url, fallbackName) {
  const res = await api(url);
  const cd = res.headers.get("Content-Disposition") || "";
  const match = cd.match(/filename\*=UTF-8''([^;]+)/);
  const name = match ? decodeURIComponent(match[1]) : fallbackName;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await res.blob());
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
