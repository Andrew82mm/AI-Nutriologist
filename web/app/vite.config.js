import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The frontend and the FastAPI backend are separate origins in dev (Vite on
// 5173, API on 8000). Proxy `/api` to the backend so the browser makes
// same-origin calls and there's no CORS dance during development.
const API_TARGET = process.env.VITE_API_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
    },
  },
});
