import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted fonts: no external requests, so the demo also works on a weak or offline connection.
import '@fontsource-variable/fraunces/opsz.css'
import '@fontsource-variable/fraunces/opsz-italic.css'
import '@fontsource-variable/dm-sans/wght.css'
import './index.css'
import { loadLanguage } from './i18n'

// The chosen language's words load first, then the app: some screens work out their text once, when their file loads.
loadLanguage()
  .catch(() => undefined)
  .then(() => import('./App.tsx'))
  .then(({ default: App }) => {
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    )
  })
