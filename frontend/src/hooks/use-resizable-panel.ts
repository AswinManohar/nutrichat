import { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'dashboard_panel_width'
const DEFAULT_WIDTH = 384 // matches the old w-96
const MIN_WIDTH = 280
const MAX_WIDTH = 640

/** Drag-to-resize state for the dashboard panel (anchored to the right edge). */
export function useResizablePanel() {
  const [width, setWidth] = useState(() => {
    const stored = Number(localStorage.getItem(STORAGE_KEY))
    return stored >= MIN_WIDTH && stored <= MAX_WIDTH ? stored : DEFAULT_WIDTH
  })
  const dragging = useRef(false)

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    dragging.current = true
  }, [])

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return
      const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, window.innerWidth - e.clientX))
      setWidth(next)
    }
    const onUp = () => {
      if (!dragging.current) return
      dragging.current = false
      localStorage.setItem(STORAGE_KEY, String(width))
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [width])

  return { width, onPointerDown }
}
