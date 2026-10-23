import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend serves the API and rendered pages; vite proxies it so the app runs from
// one origin in development (no CORS juggling, cookies/tokens behave like production).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    chunkSizeWarningLimit: 900,
  },
});
