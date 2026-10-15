import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend (backend/main.py) allows exactly this origin, so keep the port fixed.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
})
