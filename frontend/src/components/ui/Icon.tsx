interface IconProps {
  name: string;
  className?: string;
  /** Filled variants are reserved for selected/active states. */
  filled?: boolean;
  title?: string;
}

/** Material Symbols glyph. Kept as a thin wrapper so the icon family, optical
 *  sizing and accessibility treatment stay uniform everywhere. */
export function Icon({ name, className = "text-[18px]", filled = false, title }: IconProps) {
  return (
    <span
      aria-hidden={title ? undefined : true}
      aria-label={title}
      role={title ? "img" : undefined}
      className={`material-symbols-outlined ${className}`}
      style={filled ? { fontVariationSettings: '"FILL" 1, "wght" 400, "GRAD" 0, "opsz" 24' } : undefined}
    >
      {name}
    </span>
  );
}
