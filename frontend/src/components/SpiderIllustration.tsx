/* ===========================================================================
   SpiderIllustration - the hero spider, drawn once and animated in CSS only.

   An ink creature on a single thread: a tapering pair of segments per leg, a
   domed carapace over a larger abdomen, a pale marking, and a small cluster of
   eyes. Keyframes live in landing.css; prefers-reduced-motion switches them off
   and the drawing simply rests.
   ========================================================================= */

interface Props {
  size?: number;
}

type Point = [number, number];

interface Leg {
  hip: Point;
  knee: Point;
  tip: Point;
}

/** The frame is 320 wide; legs are mirrored around this axis. */
const CENTRE_X = 320;

const LEFT_LEGS: Leg[] = [
  { hip: [148, 130], knee: [104, 94], tip: [80, 124] },
  { hip: [145, 141], knee: [86, 122], tip: [58, 160] },
  { hip: [145, 152], knee: [84, 170], tip: [60, 208] },
  { hip: [148, 161], knee: [106, 196], tip: [90, 232] },
];

function mirrored(leg: Leg): Leg {
  return {
    hip: [CENTRE_X - leg.hip[0], leg.hip[1]],
    knee: [CENTRE_X - leg.knee[0], leg.knee[1]],
    tip: [CENTRE_X - leg.tip[0], leg.tip[1]],
  };
}

const LEGS: Leg[] = [...LEFT_LEGS, ...LEFT_LEGS.map(mirrored)];

const femur = (leg: Leg) => `M ${leg.hip[0]} ${leg.hip[1]} L ${leg.knee[0]} ${leg.knee[1]}`;

/** The lower segment bows slightly outward, so the leg is not a ruler. */
const tibia = (leg: Leg) => {
  const [kx, ky] = leg.knee;
  const [tx, ty] = leg.tip;
  const cx = kx + (kx - CENTRE_X) * 0.06;
  const cy = (ky + ty) / 2;
  return `M ${kx} ${ky} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${tx} ${ty}`;
};

export default function SpiderIllustration({ size = 190 }: Props) {
  return (
    <svg
      className="sp-svg"
      width={size}
      height={size}
      viewBox="0 0 320 320"
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <radialGradient id="sp-abdomen" cx="38%" cy="26%" r="82%">
          <stop offset="0%" stopColor="#4b5a68" />
          <stop offset="46%" stopColor="#232d37" />
          <stop offset="100%" stopColor="#131a21" />
        </radialGradient>
        <radialGradient id="sp-carapace" cx="42%" cy="24%" r="86%">
          <stop offset="0%" stopColor="#5a6b7a" />
          <stop offset="55%" stopColor="#28323c" />
          <stop offset="100%" stopColor="#141a21" />
        </radialGradient>
      </defs>

      <g className="sp-hang">
        <g className="sp-dip">
          {/* The silk runs past the top edge of the frame, so it never lifts off. */}
          <path className="sp-thread" pathLength={1} d="M 160 -36 C 154 24 166 84 160 126" />

          <g className="sp-legs">
            {LEGS.map((leg, index) => (
              <g key={`leg-${index}`} className="sp-leg" style={{ transformOrigin: `${leg.hip[0]}px ${leg.hip[1]}px` }}>
                <path className="sp-leg-line" d={femur(leg)} />
                <path className="sp-leg-thin" d={tibia(leg)} />
                <circle className="sp-foot" cx={leg.tip[0]} cy={leg.tip[1]} r={1.7} />
              </g>
            ))}
          </g>

          <g className="sp-body">
            <ellipse className="sp-abdomen-shape" cx={160} cy={190} rx={29} ry={39} fill="url(#sp-abdomen)" />
            <path className="sp-mark" d="M 160 176 C 168 184 168 198 160 208 C 152 198 152 184 160 176 Z" />
            <ellipse className="sp-carapace-shape" cx={160} cy={144} rx={20} ry={18} fill="url(#sp-carapace)" />
            <path className="sp-carapace-light" d="M 148 136 C 154 130 166 130 172 136" />
            <g className="sp-eyes">
              <circle cx={153} cy={136} r={2.4} />
              <circle cx={167} cy={136} r={2.4} />
              <circle cx={158} cy={131} r={1.5} />
              <circle cx={162} cy={131} r={1.5} />
            </g>
            <path className="sp-palp" d="M 152 152 L 143 163" />
            <path className="sp-palp" d="M 168 152 L 177 163" />
          </g>
        </g>
      </g>
    </svg>
  );
}
