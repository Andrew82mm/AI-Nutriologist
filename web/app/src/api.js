// Single place that talks to the backend. Every screen imports from here and
// never calls `fetch` directly, so swapping endpoints or adding auth later is
// a one-file change. In dev, `/api` is proxied to the FastAPI server by Vite
// (see vite.config.js); in a packaged build it's same-origin.

const BASE = "/api";

async function request(path, { method = "GET", body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* non-JSON error body — keep statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  health: () => request("/health"),
  getInventory: () => request("/inventory"),
  getLastReceipt: () => request("/receipts/last"),
  importReceipt: (path) => request("/receipts/import", { method: "POST", body: { path } }),
  inventoryAction: (productId, action) =>
    request(`/inventory/${productId}/action`, { method: "POST", body: { action } }),
  cook: (name, ingredients, yieldGrams) =>
    request("/cook", { method: "POST", body: { name, ingredients, yield_grams: yieldGrams } }),
  getDiary: () => request("/diary/today"),
  getStats: (days = 7) => request(`/stats?days=${days}`),
  getProfile: () => request("/profile"),
  putProfile: (profile) => request("/profile", { method: "PUT", body: profile }),
  chat: (text) => request("/chat", { method: "POST", body: { text } }),
  planDay: () => request("/plan/day", { method: "POST" }),
  suggestRecipes: () => request("/recipes/suggest", { method: "POST" }),
  logMeal: (items, rawText, title) =>
    request("/meals", { method: "POST", body: { items, raw_text: rawText, title } }),
  addInventory: (items) => request("/inventory", { method: "POST", body: { items } }),
  // Live preview of unit + portion КБЖУ + fridge presence for typed positions.
  estimateMeal: (items) => request("/meals/estimate", { method: "POST", body: { items } }),
  updateMeal: (id, items, title) =>
    request(`/meals/${id}`, { method: "PUT", body: { items, title } }),
  deleteMeal: (id) => request(`/meals/${id}`, { method: "DELETE" }),
};
