/* Geometry helpers for the spider's procedural walk. */

export interface Vec {
  x: number;
  y: number;
}

export const vec = (x: number, y: number): Vec => ({ x, y });

export const add = (a: Vec, b: Vec): Vec => ({ x: a.x + b.x, y: a.y + b.y });
export const sub = (a: Vec, b: Vec): Vec => ({ x: a.x - b.x, y: a.y - b.y });
export const scale = (a: Vec, k: number): Vec => ({ x: a.x * k, y: a.y * k });
export const len = (a: Vec): number => Math.hypot(a.x, a.y);
export const dist = (a: Vec, b: Vec): number => Math.hypot(a.x - b.x, a.y - b.y);
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;
export const lerpVec = (a: Vec, b: Vec, t: number): Vec => ({ x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t) });
export const clamp = (value: number, low: number, high: number): number => Math.min(high, Math.max(low, value));

export function normalize(a: Vec): Vec {
  const length = len(a) || 1;
  return { x: a.x / length, y: a.y / length };
}

export function rotate(a: Vec, angle: number): Vec {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return { x: a.x * cos - a.y * sin, y: a.x * sin + a.y * cos };
}

/** Shortest signed angular difference, in radians. */
export function angleDelta(from: number, to: number): number {
  let delta = to - from;
  while (delta > Math.PI) delta -= Math.PI * 2;
  while (delta < -Math.PI) delta += Math.PI * 2;
  return delta;
}

export function approachAngle(from: number, to: number, maxStep: number): number {
  const delta = angleDelta(from, to);
  if (Math.abs(delta) <= maxStep) return to;
  return from + Math.sign(delta) * maxStep;
}

/**
 * Two-bone inverse kinematics.
 * Returns the elbow (knee) position for a limb of lengths l1 + l2 reaching from
 * `root` to `target`, bending toward `bendSide` (+1 / -1).
 */
export function solveIk(root: Vec, target: Vec, l1: number, l2: number, bendSide: number): Vec {
  const difference = sub(target, root);
  const distance = clamp(len(difference), 0.0001, (l1 + l2) * 0.999);
  const direction = normalize(difference);
  // Cosine rule for the interior angle at the root joint.
  const cosA = clamp((l1 * l1 + distance * distance - l2 * l2) / (2 * l1 * distance), -1, 1);
  const angleA = Math.acos(cosA);
  const baseAngle = Math.atan2(direction.y, direction.x);
  const elbowAngle = baseAngle - bendSide * angleA;
  return { x: root.x + Math.cos(elbowAngle) * l1, y: root.y + Math.sin(elbowAngle) * l1 };
}

export const easeInOut = (t: number): number => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
export const easeOut = (t: number): number => 1 - Math.pow(1 - t, 3);

/** Catmull-Rom-ish smoothing used for the silk trail. */
export function polyline(points: Vec[], closed = false): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let path = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
  for (let i = 1; i < points.length; i++) {
    const previous = points[i - 1];
    const current = points[i];
    const mid = lerpVec(previous, current, 0.5);
    path += ` Q ${previous.x.toFixed(1)} ${previous.y.toFixed(1)} ${mid.x.toFixed(1)} ${mid.y.toFixed(1)}`;
  }
  const last = points[points.length - 1];
  path += ` L ${last.x.toFixed(1)} ${last.y.toFixed(1)}`;
  return closed ? `${path} Z` : path;
}
