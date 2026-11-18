import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In production the FastAPI backend serves the built frontend from the
// same origin, so API calls are relative. The proxy below is only for
// local `npm run dev` against a backend on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/sessions": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/admin": "http://localhost:8000",
    },
  },
});
