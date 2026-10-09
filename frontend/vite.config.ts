import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The page members open. In development it talks to a Grove service on this computer
// (./start.sh), which answers /community-api itself.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1', port: 5174, strictPort: true,
    proxy: { '/community-api': { target: 'http://127.0.0.1:8018' } },
  },
})
