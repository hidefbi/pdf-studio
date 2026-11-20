import { $, getJson, t } from "./core.js";

// The About dialog: version, two links, and donation cards that copy the address.

const COPY_RESET_MS = 1500;

export function bindAbout() {
  $("#about-open").addEventListener("click", openAbout);
  $("#about-close").addEventListener("click", () => ($("#about-dialog").hidden = true));
  document.querySelectorAll(".donate-card").forEach((card) => {
    card.addEventListener("click", () => copyAddress(card));
  });
}

async function openAbout() {
  const label = $("#about-version");
  label.textContent = "";
  $("#about-dialog").hidden = false;
  try {
    const { version } = await getJson("/api/version");
    label.textContent = t("about_version", { n: version });
  } catch (_) {
    label.textContent = "";
  }
}

function copyAddress(card) {
  const state = card.querySelector(".copy-state");
  navigator.clipboard.writeText(card.dataset.copy).then(
    () => showState(state, "donate_copied"),
    () => showState(state, "donate_copy_failed"),
  );
}

function showState(el, key) {
  el.textContent = t(key);
  clearTimeout(el.resetTimer);
  el.resetTimer = setTimeout(() => (el.textContent = t("donate_copy")), COPY_RESET_MS);
}
