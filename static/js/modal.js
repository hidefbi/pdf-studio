// ---------- dialogs ----------
// Every dialog gets the same keyboard behaviour here: Escape closes the top one,
// Tab stays inside it, the first control gets focus, and focus goes back to
// whatever opened it.

const FOCUSABLE = [
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

const openers = new Map();
let lastOutside = null;

function modals() {
  return [...document.querySelectorAll(".modal")];
}

function topModal() {
  const open = modals().filter((m) => !m.hidden);
  return open[open.length - 1] || null;
}

function focusables(modal) {
  return [...modal.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null);
}

function onToggle(modal) {
  if (!modal.hidden) {
    openers.set(modal, lastOutside);
    if (!modal.contains(document.activeElement)) {
      const first = focusables(modal)[0];
      if (first) first.focus();
    }
    return;
  }
  const back = openers.get(modal);
  openers.delete(modal);
  if (back && back.isConnected && typeof back.focus === "function") back.focus();
}

function onKeydown(e) {
  const modal = topModal();
  if (!modal) return;
  if (e.key === "Escape") {
    const cancel = modal.querySelector("[data-cancel]");
    if (cancel) {
      e.preventDefault();
      cancel.click();
    }
    return;
  }
  if (e.key !== "Tab") return;
  const items = focusables(modal);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  const outside = !modal.contains(active);
  if (e.shiftKey && (active === first || outside)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (active === last || outside)) {
    e.preventDefault();
    first.focus();
  }
}

export function bindModals() {
  document.addEventListener("focusin", (e) => {
    if (!e.target.closest(".modal")) lastOutside = e.target;
  });
  document.addEventListener("keydown", onKeydown);
  modals().forEach((modal) => {
    new MutationObserver(() => onToggle(modal)).observe(modal, { attributes: true, attributeFilter: ["hidden"] });
  });
}
