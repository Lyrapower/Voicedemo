import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig, loadEnv } from 'vite';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Reads `ui/sound-lab/.env` via Vite's loadEnv (no extra `dotenv` package — avoids
 * "Cannot find module 'dotenv'" if someone runs `pnpm dev` before a full install).
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '');
  const telemetryPort =
    env.TELEMETRY_PORT || process.env.TELEMETRY_PORT || '8788';

  return {
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: false,
      // HMR WebSocket stays on 5173 when the UI is opened via Aster proxy on 8787.
      hmr: {
        host: '127.0.0.1',
        port: 5173,
        clientPort: 5173,
      },
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${telemetryPort}`,
          changeOrigin: true,
        },
      },
    },
    build: {
      target: 'es2022',
      outDir: 'dist',
    },
  };
});
