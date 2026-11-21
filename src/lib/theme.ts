export type Theme = 'light' | 'dark'

// Night Sky (dark) is the default. The saved choice lives under a new key, so a browser that only ever saw the old
// default (light) is not stuck on it; and nothing is saved until someone actually picks a theme.
const KEY = 'kiro-theme-v2'

export const THEME_COLOR: Record<Theme, string> = { dark: '#080B1C', light: '#FFF4E8' }

export function getInitialTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

/** Puts a theme on the page. This is only the look: it does not remember anything. */
export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[theme])
}

/** Remembers a theme the person chose. */
export function rememberTheme(theme: Theme) {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    /* private browsing: the choice just won't be remembered */
  }
}
