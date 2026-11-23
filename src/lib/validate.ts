// Small form checks shared by the screens and the sample backend. Each returns a sentence to show, or null when fine.

export const PROFILE_NAME_MAX = 24
export const READING_NAME_MAX = 40
export const PASSWORD_MIN = 8
export const MESSAGE_MAX = 500

export function validateProfileName(raw: string): string | null {
  const name = raw.trim()
  if (!name) return 'Please give the profile a name.'
  if (name.length > PROFILE_NAME_MAX) return `Keep it to ${PROFILE_NAME_MAX} characters or fewer.`
  if (!/^[\p{L}\p{N} '’.-]+$/u.test(name)) return 'Keep it simple: letters and spaces are enough. Please leave out symbols, emails and phone numbers.'
  if (/\d{5,}/.test(name)) return 'That looks like a phone number. A first name or nickname is plenty.'
  return null
}

/** A reading's name as it is kept: no spaces at the ends, and every run of spaces or line breaks made one space. */
export function cleanReadingName(raw: string): string {
  return raw.split(/\s+/).filter(Boolean).join(' ')
}

/** A reading's name is optional, so an empty one is fine: the reading is then called by its date. Kept as simple as a profile's name. */
export function validateReadingName(raw: string): string | null {
  const name = cleanReadingName(raw)
  if (!name) return null
  if (name.length > READING_NAME_MAX) return `Keep the name to ${READING_NAME_MAX} characters or fewer.`
  if (!/^[\p{L}\p{N} '’.,!?&:()-]+$/u.test(name)) return 'Keep the name simple: letters, numbers and spaces are enough. Please leave out symbols, emails and links.'
  if (/\d{5,}/.test(name)) return 'That looks like a phone number. A short name is plenty.'
  return null
}

export function validateDisplayName(raw: string): string | null {
  const name = raw.trim()
  if (!name) return 'Please tell us what to call you.'
  if (name.length > PROFILE_NAME_MAX) return `Keep it to ${PROFILE_NAME_MAX} characters or fewer.`
  return null
}

export function validateEmail(raw: string): string | null {
  const email = raw.trim()
  if (!email) return 'Please enter your email.'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) return 'That email does not look right. Please check it.'
  return null
}

export function validatePassword(raw: string): string | null {
  if (!raw) return 'Please enter a password.'
  if (raw.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters.`
  return null
}
