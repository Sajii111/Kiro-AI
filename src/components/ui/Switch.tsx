/** An on/off switch with a label. Announced as a switch, works with Space and Enter. */
export default function Switch({ checked, onChange, label }: { checked: boolean; onChange: (next: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-3 rounded-full py-1 pr-1 text-sm"
    >
      <span className={`relative h-6 w-11 rounded-full transition-colors ${checked ? 'bg-ink' : 'bg-ink/25'}`}>
        <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-paper shadow transition-transform ${checked ? 'translate-x-5' : ''}`} />
      </span>
      {label}
    </button>
  )
}
