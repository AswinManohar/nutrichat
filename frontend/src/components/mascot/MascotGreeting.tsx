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

  useEffect(() => {
    if (!enabled) {
      setVisible(false)
      setMounted(false)
      return
    }
    if (show) {
      setMounted(true)
      // Tiny delay so the browser registers the initial state before
      // the visible class triggers the enter transition.
      requestAnimationFrame(() => setVisible(true))
    } else {
      setVisible(false)
      exitTimer.current = setTimeout(() => setMounted(false), 200)
    }
    return () => {
      if (exitTimer.current) clearTimeout(exitTimer.current)
    }
  }, [show, enabled])

  if (!mounted) return null

  return (
    <div
      className="flex justify-center pb-4 transition-all duration-200 ease-out"
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(8px)',
      }}
      aria-hidden="true"
    >
      <MascotSprite size={14} variant="wave" />
    </div>
  )
}
