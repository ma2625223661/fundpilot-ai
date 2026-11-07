import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The Python backend serves the built files. During development Vite proxies
// API calls to it: local edition on 8765 (start.cmd), cloud preview on 8080.
const backend = process.env.FUNDPILOT_BACKEND ?? 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: false },
      '/session-context.js': { target: backend, changeOrigin: false },
    },
  },
  build: {
    // Kept apart from the old dist/ until the new frontend is accepted.
    outDir: 'dist-react',
    emptyOutDir: true,
    // Flat output: the cloud server only serves files directly inside its web folder.
    assetsDir: '',
    // Lets the backend work out which files the public login page needs.
    manifest: true,
    rollupOptions: {
      input: {
        index: path.resolve(__dirname, 'index.html'),
        login: path.resolve(__dirname, 'login.html'),
        // Public explanation of the AI service, reachable before logging in.
        'ai-service': path.resolve(__dirname, 'ai-service.html'),
      },
    },
  },
});
