import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { execSync } from 'child_process'
import { existsSync, statSync } from 'fs'
import { join } from 'path'

/**
 * Vite plugin to ensure TypeScript types are generated from backend schemas
 * before building the application.
 */
function generateTypesPlugin() {
  return {
    name: 'generate-types',
    buildStart() {
      const typesFile = join(__dirname, 'src/types/generated/api.ts')
      const schemasDir = join(__dirname, '../schemas')

      // Check if generated types file exists
      if (!existsSync(typesFile)) {
        console.log('🔧 Generated types not found, generating...')
        try {
          execSync('npm run generate:types', { stdio: 'inherit' })
        } catch (error) {
          console.error('✗ Failed to generate types')
          throw error
        }
        return
      }

      // Check if schemas are newer than generated types
      if (existsSync(schemasDir)) {
        const typesTime = statSync(typesFile).mtimeMs
        const schemasTime = statSync(schemasDir).mtimeMs

        if (schemasTime > typesTime) {
          console.log('🔧 Schemas updated, regenerating types...')
          try {
            execSync('npm run generate:types', { stdio: 'inherit' })
          } catch (error) {
            console.error('✗ Failed to regenerate types')
            throw error
          }
        }
      }
    }
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  define: {
    __VITE_API_URL__: JSON.stringify(process.env.VITE_API_URL || ''),
    __VITE_WS_URL__: JSON.stringify(process.env.VITE_WS_URL || ''),
  },
  plugins: [
    generateTypesPlugin(),
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png', 'masked-icon.svg'],
      manifest: {
        name: 'Psychoanalyst App',
        short_name: 'PsychoAnalyst',
        description: 'Virtual LLM-Driven Psychoanalyst application',
        theme_color: '#1976d2',
        background_color: '#ffffff',
        display: 'standalone',
        icons: [
          {
            src: 'pwa-192x192.png',
            sizes: '192x192',
            type: 'image/png'
          },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png'
          }
        ]
      }
    })
  ],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: true
  }
})
