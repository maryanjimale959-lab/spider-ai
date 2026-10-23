import { useEffect, useMemo, useRef } from "react";
import { SpiderWalker } from "./walker";
import type { Vec } from "./geometry";

/* ===========================================================================
   SpiderOverlay

   One SVG layer over the document. The body is authored in a 100x100 unit space and
   lifted into page pixels; the eight legs are drawn in page pixels so their feet stay
   planted on the paper. Each leg is two tapered segments - a heavy femur and a lighter
   tibia - which is what makes it read as a creature rather than a diagram. The
   web-shooter draws real silk: a white strand that extends to an anchor, goes taut,
   and the spider swings along it onto the next line.
   ========================================================================= */

interface Props {
  walker: SpiderWalker;
  width: number;
  height: number;
  /** line rectangles (overlay pixels) the spider is standing on / scanning */
  scanRects?: { x: number; y: number; w: number; h: number }[];
  paused?: boolean;
  markers?: { id: string; x: number; y: number; kind: string; severity: string; active: boolean }[];
  showTrail?: boolean;
}

const LEG_COUNT = 8;

/** A bowed segment: joints bend outward slightly instead of snapping straight. */
function segment(from: Vec, to: Vec, bow: number): string {
  const mx = (from.x + to.x) / 2;
  const my = (from.y + to.y) / 2 + bow;
  return `M ${from.x.toFixed(2)} ${from.y.toFixed(2)} Q ${mx.toFixed(2)} ${my.toFixed(2)} ${to.x.toFixed(2)} ${to.y.toFixed(2)}`;
}

function straight(from: Vec, to: Vec): string {
  return `M ${from.x.toFixed(2)} ${from.y.toFixed(2)} L ${to.x.toFixed(2)} ${to.y.toFixed(2)}`;
}

/** Silk tapers from the body to the anchor, so the strand is drawn as a thin wedge. */
function strandPath(from: Vec, to: Vec, width: number): string {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const px = (-dy / length) * width;
  const py = (dx / length) * width;
  return `M ${(from.x + px).toFixed(1)} ${(from.y + py).toFixed(1)} L ${to.x.toFixed(1)} ${to.y.toFixed(1)} L ${(from.x - px).toFixed(1)} ${(from.y - py).toFixed(1)} Z`;
}

export default function SpiderOverlay({
  walker, width, height, scanRects = [], paused = false, markers = [], showTrail = true,
}: Props) {
  const bodyRef = useRef<SVGGElement | null>(null);
  const femurRefs = useRef<(SVGPathElement | null)[]>([]);
  const tibiaRefs = useRef<(SVGPathElement | null)[]>([]);
  const shadowRefs = useRef<(SVGPathElement | null)[]>([]);
  const footRefs = useRef<(SVGCircleElement | null)[]>([]);
  const kneeRefs = useRef<(SVGCircleElement | null)[]>([]);
  const strandRef = useRef<SVGPathElement | null>(null);
  const splashRef = useRef<SVGGElement | null>(null);
  const arcRef = useRef<SVGPathElement | null>(null);
  const hangRef = useRef<SVGPathElement | null>(null);
  const trailRef = useRef<SVGPathElement | null>(null);
  const coreRef = useRef<SVGGElement | null>(null);

  const legIndexes = useMemo(() => Array.from({ length: LEG_COUNT }, (_, i) => i), []);

  useEffect(() => {
    let frame = 0;
    let last = performance.now();

    const draw = () => {
      const pose = walker.pose();
      const body = bodyRef.current;
      if (body) {
        const deg = ((((pose.heading * 180) / Math.PI) % 360) + 360) % 360;
        body.setAttribute(
          "transform",
          `translate(${pose.pos.x.toFixed(2)} ${pose.pos.y.toFixed(2)}) rotate(${deg.toFixed(2)}) scale(${pose.scale.toFixed(4)})`,
        );
      }

      pose.legs.forEach((leg, index) => {
        const femur = femurRefs.current[index];
        const tibia = tibiaRefs.current[index];
        const shadow = shadowRefs.current[index];
        const foot = footRefs.current[index];
        const knee = kneeRefs.current[index];
        // bow the knee away from the body so the leg arces the way a real one does
        const outward = leg.knee.y <= leg.root.y ? -1 : 1;
        const bow = 2.2 * pose.scale * outward * (leg.swinging ? 1.5 : 1);
        if (femur) {
          femur.setAttribute("d", segment(leg.root, leg.knee, bow));
          femur.setAttribute("stroke-width", String(Math.max(1.6, 4.6 * pose.scale)));
        }
        if (tibia) {
          tibia.setAttribute("d", segment(leg.knee, leg.foot, bow * 0.4));
          tibia.setAttribute("stroke-width", String(Math.max(0.9, 2.5 * pose.scale * (leg.swinging ? 0.92 : 1))));
        }
        if (shadow) {
          shadow.setAttribute("d", `${segment({ x: leg.root.x + 1.2, y: leg.root.y + 2.4 }, { x: leg.knee.x + 1.2, y: leg.knee.y + 2.4 }, bow)} ${straight({ x: leg.knee.x + 1.2, y: leg.knee.y + 2.4 }, { x: leg.foot.x + 1.6, y: leg.foot.y + 2.8 })}`);
          shadow.setAttribute("stroke-width", String(Math.max(1.8, 5 * pose.scale)));
        }
        if (foot) {
          foot.setAttribute("cx", leg.foot.x.toFixed(2));
          foot.setAttribute("cy", leg.foot.y.toFixed(2));
          foot.setAttribute("r", String(Math.max(0.9, (leg.swinging ? 1.5 : 1.15) * pose.scale * 1.7)));
        }
        if (knee) {
          knee.setAttribute("cx", leg.knee.x.toFixed(2));
          knee.setAttribute("cy", leg.knee.y.toFixed(2));
          knee.setAttribute("r", String(Math.max(0.8, 1.5 * pose.scale)));
        }
      });

      // ---- the web shot ------------------------------------------------------
      const anchor = pose.webAnchor;
      const strand = strandRef.current;
      const splash = splashRef.current;
      if (strand && splash) {
        if (anchor && pose.webProgress > 0.02) {
          const t = pose.webProgress;
          const tip = { x: pose.pos.x + (anchor.x - pose.pos.x) * t, y: pose.pos.y + (anchor.y - pose.pos.y) * t };
          strand.setAttribute("d", strandPath(pose.pos, tip, 1.6 * pose.scale * 2.2));
          strand.style.opacity = String(0.55 + 0.45 * t);
          splash.setAttribute("transform", `translate(${tip.x.toFixed(1)} ${tip.y.toFixed(1)})`);
          splash.style.opacity = t > 0.55 ? String((t - 0.55) / 0.45) : "0";
        } else {
          strand.style.opacity = "0";
          splash.style.opacity = "0";
        }
      }

      // ---- the swing arc, left as a slack thread -----------------------------
      if (arcRef.current) {
        const points = pose.arc;
        if (showTrail && points.length > 1 && pose.phase === "swing") {
          let d = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
          for (let i = 1; i < points.length; i++) d += ` L ${points[i].x.toFixed(1)} ${points[i].y.toFixed(1)}`;
          arcRef.current.setAttribute("d", d);
          arcRef.current.style.opacity = "0.3";
        } else {
          arcRef.current.style.opacity = "0";
        }
      }

      if (trailRef.current) trailRef.current.setAttribute("d", showTrail ? pose.silkTrail : "");

      // a spider hangs from a line: keep a fading thread rising above it
      if (hangRef.current) {
        if (showTrail && pose.phase !== "idle") {
          hangRef.current.setAttribute(
            "d",
            `M ${pose.pos.x.toFixed(1)} ${(pose.pos.y - 8).toFixed(1)} L ${pose.pos.x.toFixed(1)} ${(pose.pos.y - 260).toFixed(1)}`,
          );
          hangRef.current.style.opacity = "0.5";
        } else {
          hangRef.current.style.opacity = "0";
        }
      }

      if (coreRef.current) {
        coreRef.current.classList.toggle("is-scanning", pose.phase === "scan");
        coreRef.current.classList.toggle("is-airborne", pose.phase === "swing" || pose.phase === "web");
      }
    };

    const loop = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (!paused) walker.update(dt);
      draw();
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [walker, paused, showTrail]);

  return (
    <svg className="spider-layer" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
      <defs>
        <radialGradient id="spider-abdomen" cx="34%" cy="24%" r="86%">
          <stop offset="0%" stopColor="#54626f" />
          <stop offset="40%" stopColor="#28313a" />
          <stop offset="100%" stopColor="#12181d" />
        </radialGradient>
        <radialGradient id="spider-carapace" cx="42%" cy="22%" r="88%">
          <stop offset="0%" stopColor="#66788a" />
          <stop offset="48%" stopColor="#2c353f" />
          <stop offset="100%" stopColor="#141a20" />
        </radialGradient>
        <linearGradient id="spider-leg" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#4f5b68" />
          <stop offset="55%" stopColor="#232b33" />
          <stop offset="100%" stopColor="#141a20" />
        </linearGradient>
        <linearGradient id="silk-fade" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" stopColor="rgba(140,150,162,0.55)" />
          <stop offset="100%" stopColor="rgba(140,150,162,0)" />
        </linearGradient>
        <linearGradient id="silk-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.95)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0.5)" />
        </linearGradient>
        <radialGradient id="silk-halo" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.22)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0)" />
        </radialGradient>
        <radialGradient id="spider-eye" cx="38%" cy="30%" r="78%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.92)" />
          <stop offset="60%" stopColor="rgba(206,220,231,0.7)" />
          <stop offset="100%" stopColor="rgba(120,136,150,0.5)" />
        </radialGradient>
      </defs>

      {/* findings hang from short silk threads pinned to their passage */}
      <g className="spider-markers">
        {markers.map((marker) => (
          <g
            key={marker.id}
            className={`marker marker-${marker.kind} marker-${marker.severity}${marker.active ? " is-active" : ""}`}
            transform={`translate(${marker.x.toFixed(1)} ${marker.y.toFixed(1)})`}
          >
            <path className="marker-strand" d="M 0 -20 L 0 0" />
            <circle className="marker-halo" r={marker.active ? 12 : 8} />
            <circle className="marker-core" r={marker.active ? 4.4 : 3.2} />
          </g>
        ))}
      </g>

      {/* the line of text being scanned */}
      <g className="spider-scan">
        {scanRects.map((rect, index) => (
          <rect
            key={`${rect.x}-${rect.y}-${index}`}
            className="scan-band"
            x={rect.x}
            y={rect.y}
            width={rect.w}
            height={rect.h}
            rx={Math.min(4, rect.h / 2.6)}
            style={{ animationDelay: `${index * 80}ms` }}
          />
        ))}
      </g>

      <path ref={hangRef} className="silk-hang" fill="none" stroke="url(#silk-fade)" strokeWidth={1.1} />
      <path ref={trailRef} className="silk-trail" fill="none" stroke="url(#silk-gradient)" strokeWidth={1} />
      <path ref={arcRef} className="silk-arc" fill="none" stroke="rgba(150,162,175,0.9)" strokeWidth={1} strokeDasharray="4 6" />
      <path ref={strandRef} className="silk-strand" fill="url(#silk-gradient)" />
      <g ref={splashRef} className="silk-splash">
        <circle r={9} fill="url(#silk-halo)" />
        <circle r={2.4} fill="#ffffff" />
        <path d="M -5.5 0 L 5.5 0 M 0 -5.5 L 0 5.5" stroke="rgba(255,255,255,0.75)" strokeWidth={0.8} />
      </g>

      <g className="spider-shadow">
        {legIndexes.map((legIndex) => (
          <path
            key={`shadow-${legIndex}`}
            ref={(el) => { shadowRefs.current[legIndex] = el; }}
            fill="none"
            stroke="rgba(16,20,25,0.22)"
            strokeLinecap="round"
          />
        ))}
      </g>

      <g className="spider-legs">
        {legIndexes.map((index) => (
          <path
            key={`femur-${index}`}
            ref={(el) => { femurRefs.current[index] = el; }}
            className="leg-femur"
            fill="none"
            stroke="url(#spider-leg)"
            strokeLinecap="round"
          />
        ))}
        {legIndexes.map((index) => (
          <path
            key={`tibia-${index}`}
            ref={(el) => { tibiaRefs.current[index] = el; }}
            className="leg-tibia"
            fill="none"
            stroke="url(#spider-leg)"
            strokeLinecap="round"
          />
        ))}
      </g>

      <g className="spider-joints">
        {legIndexes.map((index) => (
          <circle key={`knee-${index}`} ref={(el) => { kneeRefs.current[index] = el; }} className="leg-knee" fill="#1b2229" />
        ))}
        {legIndexes.map((index) => (
          <circle key={`foot-${index}`} ref={(el) => { footRefs.current[index] = el; }} className="leg-foot" fill="#141a20" />
        ))}
      </g>

      {/* body, head pointing along +X */}
      <g ref={bodyRef} className="spider-body">
        <ellipse className="body-halo" cx={0} cy={0} rx={44} ry={36} fill="url(#silk-halo)" />
        <ellipse className="body-contact" cx={-2} cy={4} rx={19} ry={7.5} fill="rgba(14,18,23,0.22)" />

        <g ref={coreRef} className="body-core">
          {/* abdomen */}
          <ellipse cx={-15} cy={0} rx={16} ry={12.4} fill="url(#spider-abdomen)" stroke="rgba(10,13,16,0.85)" strokeWidth={0.7} />
          <path d="M -22 -5 Q -15 -10 -7 -6" fill="none" stroke="rgba(224,236,246,0.16)" strokeWidth={1.5} strokeLinecap="round" />
          <path className="marking" d="M -15 -6.5 Q -9.5 -1 -15 6.5 Q -20.5 -1 -15 -6.5 Z" fill="rgba(226,236,244,0.2)" />

          {/* the join between abdomen and carapace */}
          <path d="M -1 0 L 3 0" stroke="#1a2128" strokeWidth={3.6} strokeLinecap="round" />

          {/* carapace */}
          <ellipse cx={8} cy={0} rx={10.6} ry={8.4} fill="url(#spider-carapace)" stroke="rgba(10,13,16,0.85)" strokeWidth={0.7} />
          <path d="M 2.5 -4 Q 8 -8 14 -3.4" fill="none" stroke="rgba(224,236,246,0.2)" strokeWidth={1.1} strokeLinecap="round" />

          {/* head, eyes, chelicerae */}
          <path className="head" d="M 15.5 -4.8 Q 22 -4.2 24 0 Q 22 4.2 15.5 4.8 Z" fill="#161c22" stroke="rgba(120,132,145,0.5)" strokeWidth={0.6} />
          <ellipse className="eye primary" cx={20.2} cy={-2.2} rx={2.2} ry={1.7} fill="url(#spider-eye)" />
          <ellipse className="eye primary" cx={20.2} cy={2.2} rx={2.2} ry={1.7} fill="url(#spider-eye)" />
          <circle className="eye small" cx={22.6} cy={-0.7} r={0.85} fill="url(#spider-eye)" />
          <circle className="eye small" cx={22.6} cy={0.7} r={0.85} fill="url(#spider-eye)" />
          <circle className="eye small" cx={17.4} cy={-3.8} r={0.8} fill="url(#spider-eye)" />
          <circle className="eye small" cx={17.4} cy={3.8} r={0.8} fill="url(#spider-eye)" />
          <path className="fang" d="M 23.6 -1.4 Q 26.6 -1 27.4 1.2" fill="none" stroke="rgba(196,208,220,0.8)" strokeWidth={0.8} strokeLinecap="round" />
          <path className="fang" d="M 23.6 1.4 Q 26.6 1 27.4 -1.2" fill="none" stroke="rgba(196,208,220,0.8)" strokeWidth={0.8} strokeLinecap="round" />

          {/* pedipalps, the short front appendages */}
          <path className="palp" d="M 14 -3.6 Q 18 -6.5 21 -8.5" fill="none" stroke="#1c242c" strokeWidth={1.3} strokeLinecap="round" />
          <path className="palp" d="M 14 3.6 Q 18 6.5 21 8.5" fill="none" stroke="#1c242c" strokeWidth={1.3} strokeLinecap="round" />

          {/* spinnerets: where the silk comes from */}
          <path
            className="spinneret"
            d="M -29 -1.5 L -31.6 -2.4 M -29.4 0 L -32.4 0 M -29 1.5 L -31.6 2.4"
            stroke="#2b343d"
            strokeWidth={0.9}
            strokeLinecap="round"
            fill="none"
          />
        </g>
      </g>
    </svg>
  );
}
