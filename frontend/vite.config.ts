import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
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
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }

          if (/[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom)[\\/]/.test(id)) {
            return 'vendor-react'
          }

          if (/[\\/]node_modules[\\/](@mui|@emotion)[\\/]/.test(id)) {
            return 'vendor-mui'
          }

          if (/[\\/]node_modules[\\/](axios|date-fns|lucide-react)[\\/]/.test(id)) {
            return 'vendor-shared'
          }

          return 'vendor'
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://localhost/',
      },
    },
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
    exclude: ['e2e/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.d.ts', 'src/main.tsx', 'src/vite-env.d.ts'],
      thresholds: {
        branches: 80,
        functions: 80,
        lines: 80,
        statements: 80,
      },
    },
  }
})
