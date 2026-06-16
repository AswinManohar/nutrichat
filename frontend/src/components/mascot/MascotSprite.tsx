interface MascotSpriteProps {
  size?: number
  className?: string
}

export function MascotSprite({ size = 10, className }: MascotSpriteProps) {
  const px = size * 4
  return (
    <img
      src="/favicon.svg"
      width={px}
      height={px}
      aria-hidden="true"
      className={className}
      style={{ display: 'block' }}
    />
  )
}
