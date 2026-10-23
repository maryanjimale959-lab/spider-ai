import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SurfaceMeasure } from "./coordinates";
import { SpiderWalker } from "../spider/walker";
import type { CrawlEvent, Finding, Keyword } from "./types";

/* ===========================================================================
   useCrawl - replays the investigation's real event log through the spider.

   The backend produced these events while it worked: which passage it examined, in
   what order, and which findings each step produced. This controller does not invent
   steps; it paces the genuine ones. Findings are only revealed if they survived
   evidence validation (they arrive from the results payload already filtered).
   ========================================================================= */

export interface CrawlState {
  playing: boolean;
  paused: boolean;
  cursor: number;
  total: number;
  stage: string;
  task: string;
  currentPassageId: string | null;
  revealedFindings: Finding[];
  revealedKeywords: Keyword[];
  revealedNodeIds: string[];
  scanRects: { x: number; y: number; w: number; h: number }[];
  finished: boolean;
}

interface Options {
  measure: () => SurfaceMeasure | null;
  events: CrawlEvent[];
  findings: Finding[];
  keywords: Keyword[];
  allNodeIds: string[];
  restingPassageId?: string | null;
  reducedMotion: boolean;
  spiderSize: number;
}

const SCAN_MS = 620;

export function useCrawl({
  measure, events, findings, keywords, allNodeIds, restingPassageId, reducedMotion, spiderSize,
}: Options) {
  const walker = useMemo(() => new SpiderWalker({ size: spiderSize, reducedMotion }), []);

  const [state, setState] = useState<CrawlState>({
    playing: false, paused: false, cursor: -1, total: events.length, stage: "idle",
    task: "Waiting to start", currentPassageId: null, revealedFindings: [], revealedKeywords: [],
    revealedNodeIds: [], scanRects: [], finished: false,
  });
  const [speed, setSpeed] = useState(2);
  const speedRef = useRef(speed);
  speedRef.current = speed;

  const pausedRef = useRef(false);
  const runToken = useRef(0);
  const findingsById = useMemo(() => new Map(findings.map((f) => [f.id, f])), [findings]);
  const keywordsRef = useRef(keywords);
  keywordsRef.current = keywords;

  useEffect(() => {
    walker.reducedMotion = reducedMotion;
  }, [reducedMotion, walker]);

  useEffect(() => {
    walker.setSize(spiderSize);
  }, [spiderSize, walker]);

  /* ---------------------------------------------------------------- painting */

  const paint = useCallback(
    (passageId: string | null, reveal: boolean) => {
      const surface = measure();
      if (!surface) return;
      if (!passageId) return;
      const anchor = surface.anchor(passageId);
      if (!anchor) return;
      const route = surface.routeTo(anchor, walker.pos);
      // web-shot, swing, land on the line, then scan it
      void walker.jumpTo(route, {
        focus: anchor.focus,
        scanMs: Math.round(SCAN_MS / speedRef.current),
        anchorLift: 30 + spiderSize * 0.5,
      });
      setState((previous) => ({
        ...previous,
        currentPassageId: passageId,
        scanRects: reveal ? anchor.lines.slice(0, 5) : [],
      }));
    },
    [measure, walker],
  );

  /** Snap the spider onto the passage it is investigating after a layout change. */
  const realign = useCallback(() => {
    const surface = measure();
    if (!surface) return;
    surface.clearCache();
    setState((previous) => {
      if (!previous.currentPassageId) return previous;
      const anchor = surface.anchor(previous.currentPassageId);
      if (!anchor) return previous;
      walker.teleport(anchor.stand, Math.atan2(anchor.focus.y - anchor.stand.y, anchor.focus.x - anchor.stand.x));
      return { ...previous, scanRects: anchor.lines.slice(0, 5) };
    });
  }, [measure, walker]);

  useEffect(() => {
    const onResize = () => realign();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [realign]);

  /* --------------------------------------------------------------- the replay */

  const waitForArrival = useCallback(
    () =>
      new Promise<void>((resolve) => {
        const deadline = performance.now() + 5200 / speedRef.current;
        const check = () => {
          if (!walker.moving || performance.now() > deadline) {
            resolve();
            return;
          }
          requestAnimationFrame(check);
        };
        check();
      }),
    [walker],
  );

  const sleep = useCallback((ms: number) => {
    return new Promise<void>((resolve) => {
      let elapsed = 0;
      let last = performance.now();
      const tick = () => {
        const now = performance.now();
        const delta = now - last;
        last = now;
        if (!pausedRef.current) elapsed += delta;
        if (elapsed >= ms) resolve();
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }, []);

  const runFrom = useCallback(
    async (startIndex: number) => {
      const token = ++runToken.current;
      const surface = measure();
      if (!surface) return;

      setState((previous) => ({ ...previous, playing: true, finished: false, total: events.length }));

      for (let index = startIndex; index < events.length; index++) {
        if (token !== runToken.current) return;
        while (pausedRef.current) {
          await sleep(80);
          if (token !== runToken.current) return;
        }
        const event = events[index];
        const passageId = event.passage_id ?? null;

        setState((previous) => ({
          ...previous,
          cursor: index,
          stage: event.stage,
          task: event.task,
          scanRects: [],
          currentPassageId: passageId ?? previous.currentPassageId,
        }));

        if (passageId) {
          paint(passageId, event.stage === "investigation" || event.stage === "discovery");
          await waitForArrival();
          if (token !== runToken.current) return;
          await sleep(Math.round(120 / speedRef.current));
          if (token !== runToken.current) return;
        }

        const newFindings = (event.finding_ids ?? []).map((id) => findingsById.get(id)).filter(Boolean) as Finding[];
        const shouldRevealKeywords = event.stage === "investigation" && (event as { keyword_ids?: string[] }).keyword_ids?.length;
        const nodeIds = (event as { node_ids?: string[] }).node_ids ?? [];

        setState((previous) => {
          const revealedFindings = newFindings.length
            ? [...previous.revealedFindings, ...newFindings.filter((f) => !previous.revealedFindings.some((x) => x.id === f.id))]
            : previous.revealedFindings;
          const revealedKeywords = shouldRevealKeywords ? keywordsRef.current : previous.revealedKeywords;
          const revealedNodeIds = nodeIds.length ? Array.from(new Set([...previous.revealedNodeIds, ...nodeIds])) : previous.revealedNodeIds;
          return { ...previous, revealedFindings, revealedKeywords, revealedNodeIds };
        });

        if (event.stage === "connection") {
          setState((previous) => ({ ...previous, revealedNodeIds: allNodeIds }));
        }

        if (event.stage === "completion") {
          const rest = restingPassageId ? surface.anchor(restingPassageId) : null;
          if (rest) {
            walker.rest(rest.stand);
            await sleep(Math.round(420 / speedRef.current));
          }
          setState((previous) => ({
            ...previous,
            playing: false,
            finished: true,
            stage: "complete",
            task: "Read to the end - the spider has stopped on the last line",
            scanRects: [],
            revealedNodeIds: allNodeIds,
            revealedKeywords: keywordsRef.current,
            revealedFindings: findings,
          }));
          return;
        }
      }

      setState((previous) => ({ ...previous, playing: false, finished: true, stage: "complete", scanRects: [] }));
    },
    [allNodeIds, events, findings, findingsById, measure, paint, restingPassageId, sleep, waitForArrival, walker],
  );

  /* ---------------------------------------------------------------- controls */

  const start = useCallback(() => {
    pausedRef.current = false;
    const surface = measure();
    if (surface && events.length) {
      const first = events[0].passage_id ? surface.anchor(events[0].passage_id) : null;
      if (first) walker.teleport(first.stand);
    }
    setState((previous) => ({
      ...previous,
      revealedFindings: [],
      revealedKeywords: [],
      revealedNodeIds: [],
      cursor: -1,
      paused: false,
    }));
    void runFrom(0);
  }, [events, measure, runFrom, walker]);

  const pause = useCallback(() => {
    pausedRef.current = true;
    walker.idle();
    setState((previous) => ({ ...previous, paused: true }));
  }, [walker]);

  const resume = useCallback(() => {
    if (!pausedRef.current) return;
    pausedRef.current = false;
    setState((previous) => ({ ...previous, paused: false }));
    void runFrom(Math.max(0, state.cursor));
  }, [runFrom, state.cursor]);

  const toggle = useCallback(() => (pausedRef.current ? resume() : pause()), [pause, resume]);

  /** Jump the crawl to the event that investigated a passage (or the closest before it). */
  const jumpToPassage = useCallback(
    (passageId: string) => {
      const surface = measure();
      if (!surface) return;
      const anchor = surface.anchor(passageId);
      if (!anchor) return;
      const index = events.findIndex((event, position) => event.passage_id === passageId && position >= 0);
      walker.teleport(anchor.stand, Math.atan2(anchor.focus.y - anchor.stand.y, anchor.focus.x - anchor.stand.x));
      walker.scan(Math.round(SCAN_MS / speedRef.current));
      setState((previous) => ({
        ...previous,
        currentPassageId: passageId,
        scanRects: anchor.lines.slice(0, 5),
        task: index >= 0 ? events[index].task : previous.task,
        stage: index >= 0 ? events[index].stage : previous.stage,
      }));
    },
    [events, measure, walker],
  );

  const stopScanning = useCallback(() => {
    walker.idle();
    setState((previous) => ({ ...previous, scanRects: [] }));
  }, [walker]);

  const skipToEnd = useCallback(() => {
    runToken.current += 1;
    pausedRef.current = false;
    setState((previous) => ({
      ...previous,
      playing: false,
      paused: false,
      finished: true,
      total: events.length,
      cursor: events.length - 1,
      stage: "complete",
      task: "Investigation complete",
      revealedFindings: findings,
      revealedKeywords: keywords,
      revealedNodeIds: allNodeIds,
      scanRects: [],
    }));
    const surface = measure();
    if (surface && restingPassageId) {
      const rest = surface.anchor(restingPassageId);
      if (rest) walker.teleport(rest.stand);
    }
  }, [allNodeIds, events.length, findings, keywords, measure, restingPassageId, walker]);

  useEffect(() => () => { runToken.current += 1; }, []);

  return {
    walker,
    state,
    speed,
    setSpeed,
    start,
    pause,
    resume,
    toggle,
    realign,
    jumpToPassage,
    stopScanning,
    skipToEnd,
  };
}
