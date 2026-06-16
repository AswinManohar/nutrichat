interface MascotSpriteProps {
  size?: number
  state?: 'walk' | 'idle' | 'peek'
  className?: string
}

export function MascotSprite({ size = 10, state = 'idle', className }: MascotSpriteProps) {
  const w = size * 4

  const isWalk = state === 'walk'
  const isIdle = state === 'idle' || state === 'peek'

  return (
    <svg
      viewBox="0 0 40 48"
      style={{ width: w, imageRendering: 'pixelated' }}
      xmlns="http://www.w3.org/2000/svg"
      shapeRendering="crispEdges"
      className={className}
      aria-hidden="true"
    >
      {/* Body */}
      <g className={isWalk ? 'mascot-walk-body' : undefined}>
        {/* Row 0: cols 2-7 */}
        <rect x="8" y="0" width="24" height="4" fill="#C47A4A" />
        {/* Rows 1-2: cols 1-8 */}
        <rect x="4" y="4" width="32" height="8" fill="#C47A4A" />
        {/* Row 3: col 1, cols 4-5, col 8 (eye gaps at cols 2-3 and 6-7) */}
        <rect x="4" y="12" width="4" height="4" fill="#C47A4A" />
        <rect x="16" y="12" width="8" height="4" fill="#C47A4A" />
        <rect x="32" y="12" width="4" height="4" fill="#C47A4A" />
        {/* Rows 4-6: cols 1-8 */}
        <rect x="4" y="16" width="32" height="12" fill="#C47A4A" />
        {/* Row 7: cols 2-7, shadow */}
        <rect x="8" y="28" width="24" height="4" fill="#A55E32" />
      </g>

      {/* Eyes */}
      <g>
        <rect x="8"  y="12" width="8" height="4" fill="#1A1A1A" />
        <rect x="24" y="12" width="8" height="4" fill="#1A1A1A" />
        {/* Eye shine (1 logical pixel each) */}
        <rect x="8"  y="12" width="2" height="2" fill="#FFFFFF" />
        <rect x="24" y="12" width="2" height="2" fill="#FFFFFF" />
      </g>

      {/* Eyelids (blink overlay, scaleY(0) by default via CSS, scales to 1 on blink) */}
      {isIdle && (
        <g>
          <rect x="8"  y="12" width="8" height="4" fill="#C47A4A" className="mascot-idle-eyelid" />
          <rect x="24" y="12" width="8" height="4" fill="#C47A4A" className="mascot-idle-eyelid" />
        </g>
      )}

      {/* Left leg */}
      <g className={isWalk ? 'mascot-walk-leg-l' : undefined}>
        <rect x="8" y="32" width="8" height="16" fill="#C47A4A" />
      </g>

      {/* Right leg */}
      <g className={isWalk ? 'mascot-walk-leg-r' : undefined}>
        <rect x="24" y="32" width="8" height="16" fill="#C47A4A" />
      </g>
    </svg>
  )
}
