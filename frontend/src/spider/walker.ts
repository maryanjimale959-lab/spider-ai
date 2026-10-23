import {
  Vec, add, angleDelta, clamp, dist, easeInOut, easeOut, lerp, len, polyline, rotate, scale as vscale, solveIk,
  sub,
} from "./geometry";

/* ===========================================================================
   SpiderWalker - web-shooting locomotion.

   Every move is a real Spider-Man sequence: the spider aims, fires a line of white
   web fluid at an anchor just past the next line, swings/jumps along a curved arc to
   land ON the text, tucks and re-plants its eight legs, then scans. It stands on the
   document surface, not beside it.
   ========================================================================= */

export type SpiderPhase = "idle" | "aim" | "web" | "swing" | "settle" | "scan" | "rest";

interface LegSpec {
  hip: Vec;
  rest: number;
  group: 0 | 1;
  l1: number;
  l2: number;
  bend: number;
}

const DEG = Math.PI / 180;

function legSpec(side: 1 | -1, index: number): LegSpec {
  const restAngle = [34, 74, 108, 145][index] * DEG;
  const hipX = [9, 4, -3, -10][index];
  const groupA = index % 2 === 0;
  const group: 0 | 1 = (side === 1 ? groupA : !groupA) ? 0 : 1;
  return { hip: { x: hipX, y: side * 5.5 }, rest: side === 1 ? restAngle : -restAngle, group, l1: 24, l2: 28, bend: side };
}

const LEG_SPECS: LegSpec[] = [
  legSpec(1, 0), legSpec(1, 1), legSpec(1, 2), legSpec(1, 3),
  legSpec(-1, 0), legSpec(-1, 1), legSpec(-1, 2), legSpec(-1, 3),
];

export interface LegPose {
  root: Vec;
  knee: Vec;
  foot: Vec;
  swinging: boolean;
  lift: number;
}

export interface SpiderPose {
  pos: Vec;
  heading: number;
  scale: number;
  phase: SpiderPhase;
  legs: LegPose[];
  bob: number;
  head: Vec;
  /** where the web line is attached in the world, and how far the shot has travelled */
  webAnchor: Vec | null;
  webProgress: number;
  /** the arc the body is currently travelling along, for the trail */
  arc: Vec[];
  scanProgress: number;
  silkTrail: string;
  gait: number;
}

export interface WalkerOptions {
  size?: number;
  reducedMotion?: boolean;
}

interface LegRuntime {
  foot: Vec;
  swinging: boolean;
  swingFrom: Vec;
  swingTo: Vec;
  swingT: number;
  lift: number;
}

interface Hop {
  from: Vec;
  to: Vec;
  control: Vec;
  anchor: Vec;
  distance: number;
}

const AIM_MS = 150;
const WEB_MS = 210;
const SETTLE_MS = 220;

export class SpiderWalker {
  pos: Vec = { x: 0, y: 0 };
  heading = -90 * DEG;
  scale = 0.66;
  phase: SpiderPhase = "idle";
  reducedMotion = false;

  private hops: Hop[] = [];
  private hop: Hop | null = null;
  private hopT = 0;
  private focus: Vec | null = null;
  private gait = 0;
  private timer = 0;
  private webProgress = 0;
  private webAnchor: Vec | null = null;
  private arc: Vec[] = [];
  private trail: Vec[] = [];
  private legs: LegRuntime[] = [];
  private scanRemaining = 0;
  private scanTotal = 0;
  private airborne = 0;

  constructor(options: WalkerOptions = {}) {
    this.scale = (options.size ?? 66) / 100;
    this.reducedMotion = options.reducedMotion ?? false;
    this.legs = LEG_SPECS.map(() => ({
      foot: { x: 0, y: 0 }, swinging: false, swingFrom: { x: 0, y: 0 }, swingTo: { x: 0, y: 0 }, swingT: 0, lift: 0,
    }));
  }

  /* --------------------------------------------------------------- placement */

  teleport(at: Vec, heading?: number) {
    this.pos = { ...at };
    if (heading !== undefined) this.heading = heading;
    this.hops = [];
    this.hop = null;
    this.webAnchor = null;
    this.phase = "idle";
    this.snapLegs();
  }

  setSize(size: number) {
    this.scale = size / 100;
    this.snapLegs();
  }

  private snapLegs() {
    LEG_SPECS.forEach((_spec, index) => {
      this.legs[index].foot = this.restFoot(index);
      this.legs[index].swinging = false;
      this.legs[index].lift = 0;
    });
  }

  private hipWorld(spec: LegSpec): Vec {
    return add(this.pos, vscale(rotate(spec.hip, this.heading), this.scale));
  }

  private restFoot(index: number): Vec {
    const spec = LEG_SPECS[index];
    const direction = { x: Math.cos(spec.rest), y: Math.sin(spec.rest) };
    return add(this.hipWorld(spec), vscale(direction, (spec.l1 + spec.l2) * this.scale * 0.78));
  }

  /**
   * Feet reach while standing (0.78) shrink while airborne (0.42) so the legs tuck
   * mid-jump and shoot forward to land - the detail that sells the jump.
   */
  private targetFoot(index: number, strideUnits: number): Vec {
    const spec = LEG_SPECS[index];
    const direction = { x: Math.cos(spec.rest), y: Math.sin(spec.rest) };
    const hip = this.hipWorld(spec);
    const reach = (spec.l1 + spec.l2) * this.scale * lerp(0.78, 0.44, this.airborne);
    const forward = vscale({ x: Math.cos(this.heading), y: Math.sin(this.heading) }, strideUnits * this.scale);
    return add(add(hip, vscale(direction, reach)), forward);
  }

  /* ------------------------------------------------------------------ orders */

  /**
   * Fire a web at each waypoint's anchor and jump to the waypoint. `anchorLift` is how
   * far above the landing point the silk attaches, in overlay pixels.
   */
  async jumpTo(points: Vec[], options: { focus?: Vec; scanMs?: number; anchorLift?: number } = {}) {
    if (points.length === 0) return;
    const lift = options.anchorLift ?? 34;
    this.focus = options.focus ? { ...options.focus } : { ...points[points.length - 1] };
    this.scanTotal = options.scanMs ?? 700;
    this.hops = points.map((point, index) => {
      const from = index === 0 ? this.pos : points[index - 1];
      const distance = dist(from, point);
      // the silk grabs above and slightly ahead of where the spider wants to stand
      const direction = normalize2(sub(point, from));
      const anchor = { x: point.x + direction.x * 18, y: point.y - lift };
      // a swing sags below the chord; a short hop arcs above it
      const sag = clamp(distance * 0.16, 12, 70) * (distance > 260 ? -1 : 1);
      const perpendicular = { x: -direction.y, y: direction.x };
      const middle = lerp2(from, point, 0.5);
      const control = add(middle, vscale(perpendicular, perpendicular.y > 0 ? -sag : sag));
      return { from, to: point, control, anchor, distance };
    });
    if (this.reducedMotion) {
      this.pos = { ...points[points.length - 1] };
      this.hops = [];
      this.faceFocus();
      this.snapLegs();
      this.beginScan();
      return;
    }
    this.startHop();
  }

  private startHop() {
    const next = this.hops.shift();
    if (!next) {
      this.beginScan();
      return;
    }
    this.hop = next;
    this.hopT = 0;
    this.webAnchor = null;
    this.webProgress = 0;
    this.arc = [];
    this.timer = AIM_MS / 1000;
    this.phase = "aim";
  }

  private beginScan() {
    this.phase = "scan";
    this.scanRemaining = this.scanTotal / 1000;
    this.webAnchor = null;
    if (this.scanRemaining <= 0) this.phase = "idle";
  }

  scan(ms: number) {
    this.scanTotal = ms;
    this.beginScan();
  }

  rest(at: Vec) {
    this.focus = { ...at };
    void this.jumpTo([at], { focus: at, scanMs: 0 });
    this.phase = "rest";
  }

  idle() {
    this.phase = "idle";
    this.hops = [];
    this.hop = null;
    this.scanRemaining = 0;
    this.webAnchor = null;
  }

  get target(): Vec | null {
    return this.focus;
  }

  get moving(): boolean {
    return this.phase === "swing" || this.phase === "aim" || this.phase === "web";
  }

  get progress(): number {
    return this.scanTotal > 0 ? clamp(1 - this.scanRemaining / this.scanTotal, 0, 1) : 0;
  }

  /* ---------------------------------------------------------------- internals */

  private faceFocus() {
    if (!this.focus) return;
    const toFocus = sub(this.focus, this.pos);
    if (len(toFocus) > 0.5) this.heading = Math.atan2(toFocus.y, toFocus.x);
  }

  private groupWindowOpen(group: 0 | 1): boolean {
    const duty = 0.34;
    const offset = group === 0 ? 0 : 0.5;
    return (this.gait + offset) % 1 < duty;
  }

  private bezier(hop: Hop, t: number): Vec {
    const u = 1 - t;
    return {
      x: u * u * hop.from.x + 2 * u * t * hop.control.x + t * t * hop.to.x,
      y: u * u * hop.from.y + 2 * u * t * hop.control.y + t * t * hop.to.y,
    };
  }

  update(dt: number) {
    const step = clamp(dt, 0, 0.05);

    switch (this.phase) {
      case "aim": {
        if (!this.hop) {
          this.startHop();
          break;
        }
        const desired = Math.atan2(this.hop.to.y - this.pos.y, this.hop.to.x - this.pos.x);
        const delta = angleDelta(this.heading, desired);
        this.heading += clamp(delta, -12 * step, 12 * step);
        this.timer -= step;
        if (this.timer <= 0 || Math.abs(delta) < 0.35) {
          this.heading = desired;
          this.phase = "web";
          this.timer = WEB_MS / 1000;
          this.webAnchor = this.hop.anchor;
          this.webProgress = 0;
        }
        break;
      }

      case "web": {
        this.timer -= step;
        this.webProgress = clamp(1 - this.timer / (WEB_MS / 1000), 0, 1);
        if (this.timer <= 0) {
          this.webProgress = 1;
          this.phase = "swing";
          this.hopT = 0;
        }
        break;
      }

      case "swing": {
        if (!this.hop) {
          this.startHop();
          break;
        }
        // the silk is taut: pull along the arc, faster at the start, easing into the landing
        const speed = clamp(1 / (0.26 + this.hop.distance / 900), 0.9, 4.2);
        this.hopT = Math.min(1, this.hopT + step * speed);
        const t = easeOut(this.hopT);
        this.pos = this.bezier(this.hop, t);
        this.airborne = Math.sin(Math.PI * this.hopT);
        const tangent = sub(this.bezier(this.hop, Math.min(1, this.hopT + 0.02)), this.pos);
        if (len(tangent) > 0.01) this.heading = Math.atan2(tangent.y, tangent.x);
        this.gait = (this.gait + step * 1.6) % 1;
        this.arc.push({ ...this.pos });
        if (this.arc.length > 22) this.arc.shift();
        // the line goes slack as the spider arrives
        this.webProgress = clamp(1 - (this.hopT - 0.72) / 0.28, 0, 1);
        if (this.hopT >= 1) {
          this.pos = { ...this.hop.to };
          this.airborne = 0;
          this.timer = SETTLE_MS / 1000;
          this.phase = "settle";
          this.pushTrail();
        }
        break;
      }

      case "settle": {
        this.timer -= step;
        this.faceFocus();
        this.gait = (this.gait + step * 2.4) % 1;
        if (this.timer <= 0) {
          this.hop = null;
          this.webAnchor = null;
          this.startHop();
        }
        break;
      }

      case "scan": {
        this.scanRemaining = Math.max(0, this.scanRemaining - step);
        this.faceFocus();
        this.gait = (this.gait + step * 0.22) % 1;
        if (this.scanRemaining === 0) this.phase = "idle";
        break;
      }

      case "rest": {
        if (this.hop) {
          const remaining = dist(this.pos, this.hop.to);
          if (remaining > 3) {
            const desired = Math.atan2(this.hop.to.y - this.pos.y, this.hop.to.x - this.pos.x);
            this.heading += clamp(angleDelta(this.heading, desired), -10 * step, 10 * step);
            const advance = Math.min(120 * step, remaining);
            this.pos = add(this.pos, vscale({ x: Math.cos(this.heading), y: Math.sin(this.heading) }, advance));
            this.gait = (this.gait + advance / 46) % 1;
          } else {
            this.hop = null;
            this.hops = [];
            this.phase = "idle";
          }
        } else {
          this.phase = "idle";
        }
        break;
      }

      default:
        this.gait = (this.gait + step * 0.08) % 1;
    }

    this.updateLegs(step);
  }

  private updateLegs(dt: number) {
    const stride = this.phase === "settle" ? 12 : 0;
    const trigger = 26 * this.scale;
    const duration = this.reducedMotion ? 0.02 : Math.max(0.09, 0.16 - this.airborne * 0.05);

    LEG_SPECS.forEach((spec, index) => {
      const leg = this.legs[index];
      const target = this.targetFoot(index, Math.sin(this.gait * Math.PI * 2 + index * 0.8) * stride);

      if (leg.swinging) {
        leg.swingT = Math.min(1, leg.swingT + dt / duration);
        const t = easeInOut(leg.swingT);
        leg.foot = { x: lerp(leg.swingFrom.x, leg.swingTo.x, t), y: lerp(leg.swingFrom.y, leg.swingTo.y, t) };
        leg.lift = Math.sin(Math.PI * leg.swingT) * 9 * this.scale;
        if (leg.swingT >= 1) {
          leg.swinging = false;
          leg.lift = 0;
        }
        return;
      }

      const drift = dist(leg.foot, target);
      // airborne: legs move straight to the tucked pose; grounded: alternate tripod stepping
      const shouldStep = this.airborne > 0.15 || drift > trigger || (this.groupWindowOpen(spec.group) && drift > trigger * 0.55);
      if (shouldStep && !this.reducedMotion) {
        leg.swinging = true;
        leg.swingT = 0;
        leg.swingFrom = { ...leg.foot };
        leg.swingTo = { ...target };
      } else if (this.reducedMotion) {
        leg.foot = target;
      }
    });
  }

  private pushTrail() {
    const last = this.trail[this.trail.length - 1];
    if (!last || dist(last, this.pos) > 30) {
      this.trail.push({ ...this.pos });
      if (this.trail.length > 18) this.trail.shift();
    }
  }

  /* -------------------------------------------------------------------- pose */

  pose(): SpiderPose {
    const bob = this.phase === "settle" ? Math.sin(this.gait * Math.PI * 4) * 1.2 * this.scale * 2 : 0;
    const legs: LegPose[] = LEG_SPECS.map((spec, index) => {
      const runtime = this.legs[index];
      const root = this.hipWorld(spec);
      const l1 = spec.l1 * this.scale;
      const l2 = spec.l2 * this.scale;
      // two IK solutions exist; a spider raises its knee away from its body
      const outward = solveIk(root, runtime.foot, l1, l2, spec.bend);
      const inward = solveIk(root, runtime.foot, l1, l2, -spec.bend);
      const knee = dist(outward, this.pos) >= dist(inward, this.pos) ? outward : inward;
      return { root, knee, foot: runtime.foot, swinging: runtime.swinging, lift: runtime.lift };
    });
    return {
      pos: { x: this.pos.x, y: this.pos.y + bob },
      heading: this.heading,
      scale: this.scale,
      phase: this.phase,
      legs,
      bob,
      head: add(this.pos, vscale(rotate({ x: 19, y: 0 }, this.heading), this.scale)),
      webAnchor: this.webAnchor,
      webProgress: this.webProgress,
      arc: this.arc.map((point) => ({ ...point })),
      scanProgress: this.progress,
      silkTrail: polyline(this.trail),
      gait: this.gait,
    };
  }
}

function normalize2(a: Vec): Vec {
  const length = len(a) || 1;
  return { x: a.x / length, y: a.y / length };
}

function lerp2(a: Vec, b: Vec, t: number): Vec {
  return { x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t) };
}
