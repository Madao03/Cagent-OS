import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output goes directly into uvicorn's static dir,
// so FastAPI StaticFiles serves React without any extra service.
export default defineConfig({
  plugins: [react()],
  base: "/static/react/",
  build: {
    outDir: "../src/cagent_os/interfaces/http/static/react",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/static": "http://localhost:8000",
    },
  },
});
