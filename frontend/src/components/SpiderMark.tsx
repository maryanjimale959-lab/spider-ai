interface Props {
  size?: number;
}

/** The brand mark: an ink spider drawn with the current palette, so it follows the theme. */
export default function SpiderMark({ size = 26 }: Props) {
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <g stroke="var(--text)" strokeWidth="1.5" strokeLinecap="round" fill="none" opacity="0.82">
        <path d="M16 12 L8.5 4.5" />
        <path d="M16 12 L23.5 4.5" />
        <path d="M13.4 14.6 L4 12.4" />
        <path d="M18.6 14.6 L28 12.4" />
        <path d="M13.4 17.6 L5 22.6" />
        <path d="M18.6 17.6 L27 22.6" />
        <path d="M16 20.5 L11.5 29" />
        <path d="M16 20.5 L20.5 29" />
      </g>
      <ellipse cx="16" cy="18.4" rx="6.1" ry="5.4" fill="var(--text)" opacity="0.92" />
      <ellipse cx="16" cy="12.4" rx="3.9" ry="3.3" fill="var(--accent)" />
      <path d="M16 15.6 L18.1 18.4 L16 21.2 L13.9 18.4 Z" fill="var(--accent)" opacity="0.7" />
      <circle cx="14.8" cy="11.7" r="0.85" fill="var(--surface)" />
      <circle cx="17.2" cy="11.7" r="0.85" fill="var(--surface)" />
    </svg>
  );
}
