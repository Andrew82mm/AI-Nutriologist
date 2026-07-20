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
  getDiary: () => request("/diary/today"),
  getProfile: () => request("/profile"),
  putProfile: (profile) => request("/profile", { method: "PUT", body: profile }),
  chat: (text) => request("/chat", { method: "POST", body: { text } }),
  logMeal: (items, rawText) => request("/meals", { method: "POST", body: { items, raw_text: rawText } }),
  addInventory: (items) => request("/inventory", { method: "POST", body: { items } }),
  addManualMeal: (items) => request("/meals/manual", { method: "POST", body: { items } }),
  updateMeal: (id, items) => request(`/meals/${id}`, { method: "PUT", body: { items } }),
  deleteMeal: (id) => request(`/meals/${id}`, { method: "DELETE" }),
};
