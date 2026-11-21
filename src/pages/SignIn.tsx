import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { isMock } from '../api'
import { errorMessage } from '../api/errors'
import { BRAND } from '../brand'
import Logo from '../components/Logo'
import SoundToggle from '../components/SoundToggle'
import ThemeToggle from '../components/ThemeToggle'
import { PalmArt } from '../components/palm/PalmBase'
import Icon from '../components/ui/icons'
import Spinner from '../components/ui/Spinner'
import TextField from '../components/ui/TextField'
import StatusDot from '../components/StatusDot'
import Splash from '../app/Splash'
import { GUEST_SESSION_MINUTES } from '../config'
import { validateDisplayName, validateEmail, validatePassword } from '../lib/validate'
import { useSession } from '../state/session'
import { useUi } from '../state/ui'

type Mode = 'signin' | 'signup'
type LocationState = { from?: string; mode?: Mode } | null

export default function SignIn() {
  const { status, session, notice, clearNotice, signIn, signUp, startGuest } = useSession()
  const { theme, toggleTheme } = useUi()
  const navigate = useNavigate()
  const state = useLocation().state as LocationState
  const from = state?.from && state.from.startsWith('/app') ? state.from : '/app'

  const [mode, setMode] = useState<Mode>(state?.mode ?? 'signin')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ name?: string | null; email?: string | null; password?: string | null }>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'form' | 'guest' | null>(null)

  if (status === 'loading') return <Splash />
  // a signed-in person has no need for this page (a guest may still want to sign up)
  if (session?.kind === 'user') return <Navigate to={from} replace />

  const switchMode = (next: Mode) => {
    setMode(next)
    setErrors({})
    setFormError(null)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const found = {
      name: mode === 'signup' ? validateDisplayName(name) : null,
      email: validateEmail(email),
      password: mode === 'signup' ? validatePassword(password) : password ? null : 'Please enter your password.',
    }
    setErrors(found)
    setFormError(null)
    if (found.name || found.email || found.password) return
    setBusy('form')
    try {
      if (mode === 'signup') await signUp({ email, password, displayName: name })
      else await signIn({ email, password })
      navigate(from, { replace: true })
    } catch (err) {
      setFormError(errorMessage(err))
      setBusy(null)
    }
  }

  const guest = async () => {
    setBusy('guest')
    try {
      await startGuest()
      navigate(from === '/app' ? '/app/new' : from, { replace: true })
    } catch (err) {
      setFormError(errorMessage(err))
      setBusy(null)
    }
  }

  return (
    <div className="app-bg min-h-screen">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-4 md:px-8 md:py-5">
        <Link to="/" aria-label={`${BRAND.name} home`}>
          <Logo />
        </Link>
        <div className="flex items-center gap-2">
          <div className="hidden sm:block">
            <SoundToggle variant="inline" />
          </div>
          <ThemeToggle theme={theme} onToggle={toggleTheme} compact />
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-6xl gap-10 px-5 pb-16 pt-4 md:px-8 lg:grid-cols-[minmax(0,30rem)_1fr] lg:gap-20 lg:pt-10">
        <div className="page-in">
          {notice && (
            <p role="status" className="mb-6 flex items-start gap-3 rounded-2xl bg-accent2/25 p-4 text-sm">
              <Icon name="info" className="mt-0.5" />
              <span className="flex-1">{notice}</span>
              <button type="button" onClick={clearNotice} aria-label="Dismiss" className="text-muted hover:text-ink">
                <Icon name="x" size={16} />
              </button>
            </p>
          )}

          <p className="kicker">{mode === 'signin' ? 'Welcome back' : 'Create your account'}</p>
          <h1 className="mt-3 text-balance font-display text-4xl font-light leading-tight tracking-tight md:text-5xl">
            {mode === 'signin' ? 'Pick up where you left off.' : 'Keep your readings, privately.'}
          </h1>
          <p className="mt-4 text-muted">
            {mode === 'signin'
              ? 'Your hand profiles, readings and chats are waiting.'
              : 'An account keeps your hand profiles, readings and chats. Your photos are never kept, with or without one.'}
          </p>

          {session?.kind === 'guest' && mode === 'signup' && (
            <p className="mt-5 flex items-start gap-3 rounded-2xl border border-ink/10 bg-surface p-4 text-sm">
              <Icon name="info" className="mt-0.5" />
              <span>You are in a guest session. After you sign up we will ask whether you want to bring it with you. Nothing is moved unless you say yes.</span>
            </p>
          )}

          <div role="tablist" aria-label="Sign in or create an account" className="mt-8 inline-flex rounded-full border border-ink/15 bg-surface/70 p-1 text-sm">
            {(['signin', 'signup'] as const).map((m) => (
              <button
                key={m}
                role="tab"
                type="button"
                aria-selected={mode === m}
                onClick={() => switchMode(m)}
                className={`rounded-full px-5 py-2 transition-colors ${mode === m ? 'bg-ink text-paper' : 'text-ink/75 hover:text-ink'}`}
              >
                {m === 'signin' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          <form onSubmit={submit} noValidate className="mt-6 space-y-4">
            {mode === 'signup' && (
              <TextField label="What should we call you?" value={name} onChange={(e) => setName(e.target.value)} autoComplete="given-name" error={errors.name} hint="A first name or nickname." />
            )}
            <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" error={errors.email} />
            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
              error={errors.password}
              hint={mode === 'signup' ? 'At least 8 characters.' : undefined}
            />
            {formError && (
              <p role="alert" className="flex items-start gap-2 text-sm text-danger">
                <Icon name="alert" className="mt-0.5" /> {formError}
              </p>
            )}
            <button type="submit" disabled={!!busy} className="btn btn-primary w-full !py-4">
              {busy === 'form' && <Spinner />} {mode === 'signin' ? 'Sign in' : 'Create account'}
            </button>
          </form>

          {isMock && (
            <p className="mt-4 flex items-start gap-2 text-xs text-muted">
              <Icon name="info" size={14} className="mt-0.5" />
              Demo mode: no real account is created and everything stays in this browser. Sign-in only knows accounts made here.
            </p>
          )}

          <div className="my-8 flex items-center gap-4 text-xs uppercase tracking-widest text-muted">
            <span className="h-px flex-1 bg-ink/15" /> or <span className="h-px flex-1 bg-ink/15" />
          </div>

          <div className="card p-5">
            <h2 className="font-display text-xl font-normal">Just looking?</h2>
            <p className="mt-1.5 text-sm text-muted">
              Try the whole journey, chat included, with no account. It is temporary: nothing is saved, and the session ends by itself after {GUEST_SESSION_MINUTES >= 60 ? `${GUEST_SESSION_MINUTES / 60} hours` : `${GUEST_SESSION_MINUTES} minutes`}.
            </p>
            <button type="button" onClick={guest} disabled={!!busy} className="btn btn-ghost mt-4">
              {busy === 'guest' && <Spinner />} Continue as a guest <Icon name="arrow-right" size={16} />
            </button>
          </div>
        </div>

        <aside className="hidden lg:block" aria-hidden="false">
          <div className="sticky top-10 mx-auto max-w-md">
            <div className="card relative overflow-hidden p-6">
              <PalmArt className="mx-auto w-full" />
              <ul className="mt-4 flex flex-wrap justify-center gap-x-5 gap-y-2 text-sm">
                <li className="flex items-center gap-2"><StatusDot status="detected" /> Detected</li>
                <li className="flex items-center gap-2"><StatusDot status="uncertain" /> Uncertain</li>
                <li className="flex items-center gap-2"><StatusDot status="not_visible" /> Not visible</li>
              </ul>
            </div>
            <p className="mx-auto mt-5 max-w-sm text-center text-sm text-muted">
              Every line is marked for what it is. If something cannot be seen, the reading says so and never makes it up.
            </p>
          </div>
        </aside>
      </main>
    </div>
  )
}
