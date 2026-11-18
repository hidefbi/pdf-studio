import { $, API_HEADERS, CLIENT_KEY, HEARTBEAT_MS, api, state } from "./core.js";

// ---------- lifecycle ----------

export function newId() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function clientId() {
  try {
    let id = sessionStorage.getItem(CLIENT_KEY);
    if (!id) {
      id = newId();
      sessionStorage.setItem(CLIENT_KEY, id);
    }
    return id;
  } catch (_) {
    return newId();
  }
}

export const CLIENT_ID = clientId();

export function showStopped() {
  clearInterval(state.heartbeatTimer);
  state.heartbeatTimer = null;
  $("#stopped").hidden = false;
}

export function sendHeartbeat() {
  fetch("/api/heartbeat", {
    method: "POST",
    headers: API_HEADERS,
    keepalive: true,
    body: JSON.stringify({ id: CLIENT_ID }),
  }).catch(showStopped);
}

export function startLifecycle() {
  sendHeartbeat();
  state.heartbeatTimer = setInterval(sendHeartbeat, HEARTBEAT_MS);
  window.addEventListener("pagehide", () => {
    commitPendingOnExit();
    fetch("/api/leave", {
      method: "POST",
      headers: API_HEADERS,
      keepalive: true,
      body: JSON.stringify({ id: CLIENT_ID }),
    }).catch(() => {});
  });
}

// Commit an unconfirmed edit when the page is closed, so typed text is not lost.
export function commitPendingOnExit() {
  if (!state.editor || !state.editor.__pending || !state.docId) return;
  const ops = state.editor.__pending();
  state.editor.__finish(false);
  if (!ops) return;
  fetch(`/api/docs/${state.docId}/ops`, {
    method: "POST",
    headers: API_HEADERS,
    keepalive: true,
    body: JSON.stringify({ ops }),
  }).catch(() => {});
}
