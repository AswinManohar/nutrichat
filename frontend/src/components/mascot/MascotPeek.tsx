import { useEffect, useState } from 'react'
import { useMascotStore } from '../../stores/mascotStore'
import { MascotSprite } from './MascotSprite'

export function MascotPeek() {
  const enabled = useMascotStore((s) => s.enabled)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!enabled) return

    let lastInteraction = Date.now()

    const trackInteraction = () => {
      lastInteraction = Date.now()
    }
    window.addEventListener('pointermove', trackInteraction, { passive: true })

    const timer = setTimeout(() => {
      const idleMs = Date.now() - lastInteraction
      if (!document.hidden && idleMs >= 30_000) {
        setVisible(true)
        setTimeout(() => setVisible(false), 3300)
      }
    }, 60_000)

    return () => {
      clearTimeout(timer)
      window.removeEventListener('pointermove', trackInteraction)
    }
  }, [enabled])

  if (!visible) return null

  return (
    <div
      className="fixed bottom-0 right-8 z-40 mascot-peek-wrapper"
      aria-hidden="true"
    >
      <MascotSprite size={10} />
    </div>
  )
}
