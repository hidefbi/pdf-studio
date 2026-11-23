import { $, API_HEADERS, CLIENT_KEY, HEARTBEAT_MS, api, state, endEdit } from "./core.js";
import { takeNudgeOps } from "./selection.js";

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

// One lost beat is normal (a sleeping laptop, a busy disk). Only a run of misses means the server is gone.
const HEARTBEAT_MISSES = 3;
let heartbeatMisses = 0;

export function sendHeartbeat() {
  fetch("/api/heartbeat", {
    method: "POST",
    headers: API_HEADERS,
    keepalive: true,
    body: JSON.stringify({ id: CLIENT_ID }),
  }).then((res) => {
    if (!res.ok) throw new Error(String(res.status));
    heartbeatMisses = 0;
  }).catch(() => {
    heartbeatMisses += 1;
    if (heartbeatMisses >= HEARTBEAT_MISSES) showStopped();
  });
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

// Commit an unconfirmed edit or a pending arrow move when the page is closed, so nothing is lost.
export function commitPendingOnExit() {
  let ops = takeNudgeOps();
  if (state.edit && state.docId) {
    const edit = state.edit.pending();
    endEdit(false);
    if (edit) ops = [...ops, ...edit];
  }
  if (!ops.length || !state.docId) return;
  fetch(`/api/docs/${state.docId}/ops`, {
    method: "POST",
    headers: API_HEADERS,
    keepalive: true,
    body: JSON.stringify({ ops }),
  }).catch(() => {});
}
