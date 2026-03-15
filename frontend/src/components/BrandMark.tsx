type BrandMarkProps = {
  size?: 'sm' | 'md' | 'lg'
}

export function BrandMark({ size = 'md' }: BrandMarkProps) {
  return (
    <div className={`brand-mark brand-mark--${size}`} aria-hidden="true">
      <svg viewBox="0 0 64 64" role="presentation">
        <circle cx="32" cy="32" r="30" fill="#fff7df" stroke="#d8c37c" strokeWidth="1.5" />
        <path
          d="M26.8 22.4c1.2-2.5 2.8-3.8 5.2-4.4 2.5.6 4.1 1.9 5.2 4.4"
          fill="none"
          stroke="#1b2d47"
          strokeLinecap="round"
          strokeWidth="1.9"
        />
        <path d="M26.6 22.7l-3.1-3.3" fill="none" stroke="#1b2d47" strokeLinecap="round" strokeWidth="1.7" />
        <path d="M37.4 22.7l3.1-3.3" fill="none" stroke="#1b2d47" strokeLinecap="round" strokeWidth="1.7" />
        <ellipse cx="23.8" cy="31" rx="8.8" ry="7" fill="#fffef7" stroke="#1b2d47" strokeWidth="1.6" />
        <ellipse cx="40.2" cy="31" rx="8.8" ry="7" fill="#fffef7" stroke="#1b2d47" strokeWidth="1.6" />
        <circle cx="32" cy="28.8" r="4.9" fill="#f6c64f" stroke="#1b2d47" strokeWidth="1.8" />
        <path
          d="M32 30.9c-5.3 0-9.6 4.2-9.6 9.6 0 6.1 4.3 10.8 9.6 10.8s9.6-4.7 9.6-10.8c0-5.4-4.3-9.6-9.6-9.6Z"
          fill="#f6c64f"
          stroke="#1b2d47"
          strokeWidth="1.8"
        />
        <path d="M26.9 36.1h10.2" stroke="#1b2d47" strokeLinecap="round" strokeWidth="1.8" />
        <path d="M26.5 40.6h10.9" stroke="#1b2d47" strokeLinecap="round" strokeWidth="1.8" />
        <path d="M29.8 45.2 31.8 47l4.5-5.2" fill="none" stroke="#fffaf0" strokeLinecap="round" strokeWidth="2.2" />
        <path d="M32 51.3 29.9 55h4.2L32 51.3Z" fill="#1b2d47" />
      </svg>
    </div>
  )
}
