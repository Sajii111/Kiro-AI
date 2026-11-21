import { useEffect, useRef } from 'react'

/** Shows an offscreen canvas (or image) inside the page, filling its box like object-fit: cover. */
export default function CanvasView({ source, className = '' }: { source: CanvasImageSource & { width: number; height: number }; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    c.width = source.width
    c.height = source.height
    c.getContext('2d')?.drawImage(source, 0, 0)
  }, [source])
  return <canvas ref={ref} className={`h-full w-full object-cover ${className}`} />
}
