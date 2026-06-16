interface MascotSpriteProps {
  size?: number
  variant?: 'jump' | 'bounce' | 'sway'
  className?: string
}

export function MascotSprite({ size = 10, variant, className }: MascotSpriteProps) {
  const px = size * 4
  const variantClass = variant ? `mascot-${variant}` : ''
  return (
    <video
      src="/mascot.webm"
      width={px}
      height={px}
      autoPlay
      loop
      muted
      playsInline
      aria-hidden="true"
      className={[variantClass, className].filter(Boolean).join(' ') || undefined}
      style={{ display: 'block', objectFit: 'contain' }}
    />
  )
}
