import { $, api, getJson, state, t } from "./core.js";
import { renderPage } from "./view.js";

// ---------- search ----------

export async function runSearch(query) {
  const list = $("#search-results");
  list.replaceChildren();
  if (!state.docId || !query.trim()) return;
  const res = await getJson(`/api/docs/${state.docId}/search?q=${encodeURIComponent(query)}`);
  if (!res.results.length) {
    const empty = document.createElement("li");
    empty.textContent = t("search_none");
    list.replaceChildren(empty);
    return;
  }
  res.results.forEach((hit) => {
    const li = document.createElement("li");
    li.textContent = t("hit_on_page", { n: hit.page + 1 });
    li.onclick = () => {
      state.page = hit.page;
      state.hit = hit;
      renderPage();
    };
    list.appendChild(li);
  });
}
