import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'

type Toast = { id: number; text: string }
const ToastContext = createContext<((text: string) => void) | null>(null)

/** Short confirmations ("Deleted Sam and 2 readings") that fade away by themselves. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const next = useRef(1)

  const show = useCallback((text: string) => {
    const id = next.current++
    setToasts((t) => [...t.slice(-2), { id, text }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000)
  }, [])

  const value = useMemo(() => show, [show])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 md:bottom-6">
        {toasts.map((t) => (
          <div key={t.id} className="page-in pointer-events-auto max-w-md rounded-2xl border border-ink/10 bg-ink px-5 py-3 text-sm text-paper shadow-xl">
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
