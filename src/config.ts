// Settings that change between "building the screens" and "talking to the real backend".
// Put overrides in a .env.local file (see .env.example). Nothing secret ever goes in the browser.

/** Base URL of the FastAPI backend, e.g. http://localhost:8000 */
export const API_URL: string = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

/**
 * true  = the app runs on built-in sample data (no backend needed). This is the default until the backend exists.
 * false = the app calls the FastAPI backend at VITE_API_URL.
 */
export const USE_MOCK: boolean = (import.meta.env.VITE_USE_MOCK ?? 'true') !== 'false'

/**
 * How long a guest session lasts before its temporary data is cleared.
 * Set VITE_GUEST_SESSION_MINUTES=1 in .env.local to see expiry happen quickly while demonstrating.
 */
export const GUEST_SESSION_MINUTES: number = (() => {
  const n = Number(import.meta.env.VITE_GUEST_SESSION_MINUTES)
  return Number.isFinite(n) && n > 0 ? n : 120
})()

/** The longest side, in pixels, of a photo before it is sent for analysis. The browser shrinks bigger photos first. */
export const MAX_PHOTO_SIDE = 1600

/** Biggest photo file we accept, before shrinking. */
export const MAX_PHOTO_BYTES = 15 * 1024 * 1024
