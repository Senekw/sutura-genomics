import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

// Multi-page: the scripted story (index.html) and the live-align UI (align.html).
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        align: resolve(__dirname, "align.html"),
      },
    },
  },
});
