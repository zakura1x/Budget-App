/**
 * Vite - runs on YOUR machine only. The server has no Node and no npm.
 *
 *   npm run dev     http://localhost:5173/ZBDGT/  (hot reload; /ZBDGT/api -> :8000)
 *   npm run build   writes ../app/web/static/dist/  - then COMMIT that folder
 *
 * Vite 6, not 7: Vite 7 needs Node 20.19+ or 22.12+, and this machine has 21.
 */
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig(({ command }) => ({
  plugins: [react()],

  // Built files are served by FastAPI from /ZBDGT/static/dist/. In dev the
  // app lives at /ZBDGT/ so client-side routes match production exactly.
  base: command === 'build' ? '/ZBDGT/static/dist/' : '/ZBDGT/',

  build: {
    outDir: '../app/web/static/dist',
    emptyOutDir: true, // outDir is outside frontend/, so this must be explicit
    // dist/.vite/manifest.json - FastAPI reads it at request time to find
    // the hashed filenames (app/web/router.py).
    manifest: true,
    sourcemap: false,
    target: 'es2020', // iOS Safari 14+
    chunkSizeWarningLimit: 700,
  },

  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/ZBDGT/api': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },
}));
