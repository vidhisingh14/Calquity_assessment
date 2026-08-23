import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/chat": "http://localhost:8000",
      "/actions": "http://localhost:8000",
      "/signals": "http://localhost:8000",
      "/users": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
