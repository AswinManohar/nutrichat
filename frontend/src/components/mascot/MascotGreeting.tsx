import { useEffect, useRef, useState } from 'react'
import { useMascotStore } from '../../stores/mascotStore'
import { MascotSprite } from './MascotSprite'

interface MascotGreetingProps {
  show: boolean
}

export function MascotGreeting({ show }: MascotGreetingProps) {
  const enabled = useMascotStore((s) => s.enabled)
  const [mounted, setMounted] = useState(show && enabled)
  const [visible, setVisible] = useState(show && enabled)
  const exitTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rafHandle = useRef<number | null>(null)

  useEffect(() => {
    if (!enabled) {
      if (exitTimer.current) clearTimeout(exitTimer.current)
      setVisible(false)
      setMounted(false)
      return
    }
    if (show) {
      setMounted(true)
      // Tiny delay so the browser registers the initial state before
      // the visible class triggers the enter transition.
      rafHandle.current = requestAnimationFrame(() => setVisible(true))
    } else {
      setVisible(false)
      exitTimer.current = setTimeout(() => setMounted(false), 200)
    }
    return () => {
      if (rafHandle.current) cancelAnimationFrame(rafHandle.current)
      if (exitTimer.current) clearTimeout(exitTimer.current)
    }
  }, [show, enabled])

  if (!mounted) return null

  return (
    <div
      className="flex flex-col items-center gap-3 pb-4 transition-[opacity,transform] duration-200 ease-out"
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(8px)',
      }}
      aria-hidden="true"
    >
      <div
        className="rounded-full bg-sage-soft flex items-center justify-center overflow-hidden"
        style={{ width: 140, height: 140 }}
      >
        <MascotSprite size={35} variant="wave" />
      </div>
      <span className="text-[13px] font-medium text-muted">Nori · your companion</span>
    </div>
  )
}
