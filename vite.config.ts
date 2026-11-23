import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv, type Plugin } from 'vite'
import { BRAND } from './src/brand.ts'

// Puts the product name into index.html from the single BRAND constant.
function brandInHtml(): Plugin {
  return {
    name: 'brand-in-html',
    transformIndexHtml: (html) =>
      html.replaceAll('%APP_NAME%', BRAND.name).replaceAll('%APP_TAGLINE%', BRAND.tagline),
  }
}

// Writes build-info.json next to index.html, so anyone (and scripts/smoke.py) can tell which kind of build a folder
// holds: the one that runs on built-in sample data, or the one that talks to the real backend.
function buildInfo(mock: boolean, mode: string): Plugin {
  return {
    name: 'build-info',
    generateBundle() {
      const info = { mock, mode, builtAt: new Date().toISOString() }
      this.emitFile({ type: 'asset', fileName: 'build-info.json', source: JSON.stringify(info) + '\n' })
    },
  }
}

export default defineConfig(({ mode }) => {
  // `npm run build:server` (the mode "server") builds the website that the Python server hands out: the sample backend is
  // off, and the site calls /v1 on its own address. The two variables are set here, before Vite reads them, so a stray
  // line in .env.local cannot switch the sample backend back on in that build.
  if (mode === 'server') {
    process.env.VITE_USE_MOCK = 'false'
    process.env.VITE_API_URL = ''
  }

  const env = loadEnv(mode, process.cwd(), '')

  // While the real backend runs on this computer, the browser talks only to Vite and Vite passes the /v1 calls on.
  // One address means there is no CORS to set up, and the session cookie just works.
  // (With the sample backend on, which is the default, nothing ever calls /v1, so this does nothing.)
  const target = env.DEV_API_TARGET || 'http://127.0.0.1:8000'
  const proxy = { '/v1': { target } }

  // The same rule as src/config.ts: sample data unless VITE_USE_MOCK is exactly "false".
  const mock = (env.VITE_USE_MOCK ?? 'true') !== 'false'

  return {
    plugins: [react(), tailwindcss(), brandInHtml(), buildInfo(mock, mode)],
    server: { proxy },
    preview: { proxy },
    build: {
      // The 3D landing scene (three.js) is one big chunk on purpose: it loads only on the landing page, after the
      // intro, and never for the app screens. Raising the limit stops Vite warning about it on every build.
      chunkSizeWarningLimit: 1000,
    },
  }
})
