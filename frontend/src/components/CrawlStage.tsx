import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import DocumentSurface from "./DocumentSurface";
import SpiderOverlay from "../spider/SpiderOverlay";
import type { SurfaceMeasure } from "../lib/coordinates";
import type { CrawlState } from "../lib/useCrawl";
import type { Finding, VersionContent } from "../lib/types";
import type { SpiderWalker } from "../spider/walker";

/* ===========================================================================
   CrawlStage

   The document, full width, with the spider working over it. As the crawl
   progresses each quoted span is painted where it actually sits - a soft
   highlighter band with a short label - so the page ends up looking read,
   not decorated. The paint layer and the spider share one coordinate space,
   so both stay aligned through scroll, zoom and resize.
   ========================================================================= */

export type Tone = "topic" | "figure" | "writing" | "keyword" | "logic" | "strength";

export interface Band {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  tone: Tone;
  label: string;
  /** the band belonging to whatever the reader has selected, drawn stronger */
  selected: boolean;
}

interface Props {
  content: VersionContent;
  crawl: CrawlState;
  walker: SpiderWalker;
  measure: () => SurfaceMeasure | null;
  mode: "page" | "text";
  zoom: number;
  selectedPassageId: string | null;
  highlights: { passageId: string; charStart: number; charEnd: number; tone: "select" | "evidence" | "keyword" | "note" }[];
  onPassageSelect: (passageId: string) => void;
  selectedFindingId: string | null;
  reducedMotion: boolean;
  /** findings whose quotations should be painted on the page */
  paintedFindings: Finding[];
  /** keyword occurrences to paint when a keyword is being explored */
  keywordBands?: { passageId: string; start: number; end: number }[];
  onSurface?: (element: HTMLElement | null) => void;
}

const TONE_BY_KIND: Record<string, Tone> = {
  subject: "topic", purpose: "topic", central_idea: "topic", structure: "topic", argument: "topic",
  conclusion: "topic", keyword_concept: "keyword", fact: "figure", date: "figure", person: "figure",
  definition: "figure", statistic: "figure", decision: "figure", action_item: "figure",
  critical_statement: "figure", writing_issue: "writing", unsupported_claim: "logic", contradiction: "logic",
  logic_gap: "logic", ambiguous_statement: "logic", overreaching_conclusion: "logic", strength: "strength",
  clarifying_question: "keyword", recommendation: "strength",
};

const MAX_BANDS = 90;
/** Only the most important lines carry a written note, or the page turns to noise. */
const MAX_LABELS = 8;

function labelFor(quote: string): string {
  const clean = quote.replace(/\s+/g, " ").trim();
  if (clean.length <= 26) return clean;
  return `${clean.slice(0, 24).trimEnd()}\u2026`;
}

export default function CrawlStage({
  content, crawl, walker, measure, mode, zoom, selectedPassageId, highlights, onPassageSelect,
  selectedFindingId, reducedMotion, paintedFindings, keywordBands = [], onSurface,
}: Props) {
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 760, height: 1200 });
  const [markers, setMarkers] = useState<{ id: string; x: number; y: number; kind: string; severity: string; active: boolean }[]>([]);
  const [bands, setBands] = useState<Band[]>([]);

  useLayoutEffect(() => {
    const node = surfaceRef.current;
    onSurface?.(node);
    if (!node) return;
    const update = () => {
      const inner = node.firstElementChild as HTMLElement | null;
      const width = node.scrollWidth || inner?.offsetWidth || 760;
      const height = node.scrollHeight || inner?.offsetHeight || 1200;
      setSize((previous) =>
        Math.abs(previous.width - width) > 1 || Math.abs(previous.height - height) > 1 ? { width, height } : previous,
      );
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    const inner = node.firstElementChild;
    if (inner) observer.observe(inner);
    return () => observer.disconnect();
  }, [mode, zoom, content, onSurface]);

  /* paint the quotations the crawl has produced, and pin a marker on each passage */
  useEffect(() => {
    const surface = measure();
    if (!surface) return;
    const nextBands: Band[] = [];
    const nextMarkers: typeof markers = [];
    let labelBudget = MAX_LABELS;

    paintedFindings.slice(0, MAX_BANDS).forEach((finding) => {
      const passageId = finding.primary_passage_id;
      if (!passageId) return;
      const anchor = surface.anchor(passageId);
      if (anchor) {
        nextMarkers.push({
          id: finding.id,
          x: Math.min(anchor.rect.x + anchor.rect.w + 12, size.width - 16),
          y: anchor.rect.y + anchor.rect.h / 2,
          kind: finding.kind,
          severity: finding.severity,
          active: finding.id === selectedFindingId,
        });
      }
      const evidence = finding.evidence[0];
      if (!evidence) return;
      const tone = TONE_BY_KIND[finding.kind] ?? "keyword";
      const rects = evidence.char_start != null
        ? surface.quoteRects(evidence.passage_id, evidence.char_start, evidence.char_end ?? evidence.char_start)
        : surface.passageLines(evidence.passage_id).slice(0, 1);
      const isSelected = finding.id === selectedFindingId;
      // findings arrive ordered by severity, so the first few notes are the important ones
      const wantsLabel = isSelected || labelBudget > 0;
      if (wantsLabel && !isSelected) labelBudget -= 1;
      rects.slice(0, 4).forEach((rect, index) => {
        if (rect.w < 6 || rect.h < 4) return;
        nextBands.push({
          id: `${finding.id}-${index}`,
          x: rect.x,
          y: rect.y,
          w: rect.w,
          h: rect.h,
          tone,
          label: index === 0 && wantsLabel ? labelFor(evidence.quote) : "",
          selected: isSelected,
        });
      });
    });

    keywordBands.slice(0, MAX_BANDS).forEach((hit, index) => {
      const rects = surface.quoteRects(hit.passageId, hit.start, hit.end);
      rects.forEach((rect, sub) => {
        nextBands.push({
          id: `kw-${index}-${sub}`, x: rect.x, y: rect.y, w: rect.w, h: rect.h, tone: "keyword", label: "", selected: false,
        });
      });
    });

    setBands(nextBands);
    setMarkers(nextMarkers);
  }, [paintedFindings, keywordBands, measure, selectedFindingId, size.width, size.height, zoom, mode, content]);

  /* keep the passage under investigation in view, without yanking the reader around */
  useEffect(() => {
    const container = scrollRef.current;
    const surface = measure();
    const passageId = crawl.currentPassageId;
    if (!container || !surface || !passageId) return;
    const rect = surface.passageRect(passageId);
    if (!rect) return;
    const viewTop = container.scrollTop;
    const viewBottom = viewTop + container.clientHeight;
    const margin = 120;
    if (rect.y - margin < viewTop || rect.y + rect.h + margin > viewBottom) {
      container.scrollTo({
        top: Math.max(0, rect.y - container.clientHeight * 0.4),
        behavior: reducedMotion ? "auto" : "smooth",
      });
    }
  }, [crawl.currentPassageId, measure, reducedMotion, size.height]);

  const pageBase = useMemo(() => `/api/versions/${content.version_id}/pages`, [content.version_id]);

  return (
    <div className={`stage${crawl.paused ? " crawl-is-paused" : ""}`}>
      <div className="doc-scroll" ref={scrollRef} data-mode={mode}>
        <div className="doc-surface" ref={surfaceRef}>
          <DocumentSurface
            content={content}
            mode={mode}
            zoom={zoom}
            selectedPassageId={selectedPassageId}
            highlights={highlights}
            onPassageSelect={onPassageSelect}
            pageImageBaseUrl={pageBase}
          />

          {/* the lines the spider has read stay painted on the page */}
          <div className="paint-layer" aria-hidden="true">
            {bands.map((band) => (
              <div
                key={band.id}
                className={`paint tone-${band.tone}${band.selected ? " is-selected" : ""}`}
                style={{ left: band.x, top: band.y, width: band.w, height: band.h }}
              >
                {band.label && band.w > 96 && <span className="paint-label">{band.label}</span>}
              </div>
            ))}
          </div>

          <SpiderOverlay
            walker={walker}
            width={size.width}
            height={size.height}
            scanRects={crawl.scanRects}
            markers={markers}
            paused={crawl.paused}
            showTrail={!reducedMotion}
          />
        </div>
      </div>
    </div>
  );
}
