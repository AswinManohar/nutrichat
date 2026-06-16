interface MascotSpriteProps {
  size?: number
  className?: string
}

export function MascotSprite({ size = 10, className }: MascotSpriteProps) {
  const px = size * 4
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
      className={className}
      style={{ display: 'block', objectFit: 'contain' }}
    />
  )
}
