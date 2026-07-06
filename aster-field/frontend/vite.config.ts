import { defineConfig } from 'vite';
export default defineConfig({
  server: { proxy: { '/state': 'http://127.0.0.1:8790', '/chat': 'http://127.0.0.1:8790', '/diary': 'http://127.0.0.1:8790' } },
  build: { outDir: 'dist', target: 'es2020' },
});
