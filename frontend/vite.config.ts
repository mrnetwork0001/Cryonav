import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The dashboard talks to the FastAPI backend through a dev proxy so the browser only ever
// sees a same-origin /api path -- no CORS negotiation, no hardcoded host in the bundle.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    strictPort: false,
    proxy: {
      "/api": {
        target: process.env.CRYONAV_API ?? "http://127.0.0.1:8008",
        changeOrigin: true,
      },
    },
  },
});
