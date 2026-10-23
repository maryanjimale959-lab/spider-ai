import type { PageDescriptor, Passage, SourceLine } from "./types";

/* ===========================================================================
   SurfaceMeasure - the coordinate system that maps passages to visible positions.

   Two source truths:
     - PDF passages carry real text bounding boxes in PDF points, plus per-line
       rectangles. We scale points -> pixels with the page's rendered width.
     - Everything else is rendered as DOM paragraphs, so we measure the element.
   Nothing is guessed: when a passage has no measurable position the caller gets
   null and shows the documented limitation instead of inventing a location.
   ========================================================================= */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PassageAnchor {
  rect: Rect;
  lines: Rect[];
  /** where the spider's body centre stands (beside the text, not on it) */
  stand: { x: number; y: number };
  /** kept for callers that want a resting point near the landing spot */
  lane: { x: number; y: number };
  /** the point the head orients toward while scanning */
  focus: { x: number; y: number };
  page?: number | null;
  measuredBy: "pdf_bbox" | "dom_element" | "container";
}


export class SurfaceMeasure {
  private overlay: HTMLElement;
  private passagesById: Map<string, Passage>;
  private pages: PageDescriptor[];
  private pageRectCache: Map<number, Rect> = new Map();
  private usePageImages: boolean;
  /** half the spider's span, so the lane never clips it at the page edge */
  private spiderHalf: number;

  constructor(overlay: HTMLElement, passages: Passage[], pages: PageDescriptor[], spiderHalf = 30) {
    this.overlay = overlay;
    this.passagesById = new Map(passages.map((p) => [p.id, p]));
    this.pages = pages;
    this.usePageImages = pages.length > 0;
    this.spiderHalf = spiderHalf;
  }

  clearCache() {
    this.pageRectCache.clear();
  }

  private baseRect(): DOMRect {
    return this.overlay.getBoundingClientRect();
  }

  private pageRect(pageNumber: number): Rect | null {
    const cached = this.pageRectCache.get(pageNumber);
    if (cached) return cached;
    const element = this.overlay.querySelector<HTMLElement>(`[data-page="${pageNumber}"]`);
    const geometry = this.pages.find((p) => p.number === pageNumber);
    if (!element || !geometry) return null;
    const box = element.getBoundingClientRect();
    const base = this.baseRect();
    const rect = { x: box.left - base.left, y: box.top - base.top, w: box.width, h: box.height };
    this.pageRectCache.set(pageNumber, rect);
    return rect;
  }

  passage(id: string): Passage | undefined {
    return this.passagesById.get(id);
  }

  /** Full-document content size, used to size the overlay canvas. */
  contentSize(): { width: number; height: number } {
    const child = this.overlay.firstElementChild as HTMLElement | null;
    if (!child) return { width: this.overlay.clientWidth, height: this.overlay.clientHeight };
    return { width: child.scrollWidth || child.offsetWidth, height: child.scrollHeight || child.offsetHeight };
  }

  /** Overlay-space rectangle of a passage. */
  passageRect(id: string): Rect | null {
    const passage = this.passagesById.get(id);
    if (!passage) return null;

    if (this.usePageImages && passage.bbox && passage.page_number) {
      const page = this.pageRect(passage.page_number);
      if (!page) return null;
      const geometry = this.pages.find((p) => p.number === passage.page_number)!;
      const scale = page.w / (geometry.width || page.w);
      return {
        x: page.x + passage.bbox.x * scale,
        y: page.y + passage.bbox.y * scale,
        w: passage.bbox.w * scale,
        h: passage.bbox.h * scale,
      };
    }

    const element = this.overlay.querySelector<HTMLElement>(`[data-passage="${id}"]`);
    if (!element) return null;
    const box = element.getBoundingClientRect();
    const base = this.baseRect();
    return { x: box.left - base.left, y: box.top - base.top, w: box.width, h: box.height };
  }

  /**
   * Line rectangles inside a passage. For PDFs these come from the file. For DOM
   * passages they are measured from the rendered element's own client rects, which is
   * exact for the wrapped text.
   */
  passageLines(id: string): Rect[] {
    const passage = this.passagesById.get(id);
    if (!passage) return [];

    if (this.usePageImages && passage.page_number && passage.source_lines?.length) {
      const page = this.pageRect(passage.page_number);
      const geometry = this.pages.find((p) => p.number === passage.page_number);
      if (!page || !geometry) return [];
      const scale = page.w / (geometry.width || page.w);
      return passage.source_lines.map((line: SourceLine) => ({
        x: page.x + line.x * scale,
        y: page.y + line.y * scale,
        w: line.w * scale,
        h: line.h * scale,
      }));
    }

    const element = this.overlay.querySelector<HTMLElement>(`[data-passage="${id}"]`);
    if (!element) return [];
    const base = this.baseRect();
    const range = document.createRange();
    range.selectNodeContents(element);
    const rects = Array.from(range.getClientRects());
    range.detach?.();
    const usable = rects.filter((r) => r.width > 2 && r.height > 2);
    if (usable.length === 0) {
      const box = element.getBoundingClientRect();
      return [{ x: box.left - base.left, y: box.top - base.top, w: box.width, h: box.height }];
    }
    return usable.map((r) => ({ x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height }));
  }

  /**
   * Rectangles covering a character range inside a passage.
   * PDF: the lines whose text spans the range, with the x extent interpolated by
   *      character proportion within each line (the honest approximation - the file
   *      gives line boxes, not glyph boxes for a re-flowed view).
   * DOM: measured from a real Range, so it is exact.
   */
  quoteRects(id: string, charStart: number, charEnd: number): Rect[] {
    const passage = this.passagesById.get(id);
    if (!passage) return [];
    const start = Math.max(0, charStart - passage.char_start);
    const end = Math.min(passage.text.length, charEnd - passage.char_start);
    if (end <= start) return this.passageLines(id);

    if (this.usePageImages && passage.page_number && passage.source_lines?.length) {
      const lines = this.passageLines(id);
      const out: Rect[] = [];
      let cursor = 0;
      passage.source_lines.forEach((line, index) => {
        const lineLength = line.text.length;
        const lineStart = cursor;
        const lineEnd = cursor + lineLength;
        cursor = lineEnd + 1; // blocks are joined with newlines
        if (lineEnd < start || lineStart > end) return;
        const rect = lines[index];
        if (!rect) return;
        const from = clampFraction((Math.max(start, lineStart) - lineStart) / Math.max(1, lineLength));
        const to = clampFraction((Math.min(end, lineEnd) - lineStart) / Math.max(1, lineLength));
        out.push({ x: rect.x + rect.w * from, y: rect.y, w: rect.w * (to - from), h: rect.h });
      });
      return out.length ? out : lines;
    }

    const element = this.overlay.querySelector<HTMLElement>(`[data-passage="${id}"]`);
    const textNode = element ? firstTextNode(element) : null;
    if (!element || !textNode) return this.passageLines(id);
    const base = this.baseRect();
    const range = document.createRange();
    try {
      range.setStart(textNode, Math.min(start, textNode.data.length));
      range.setEnd(textNode, Math.min(end, textNode.data.length));
    } catch {
      return this.passageLines(id);
    }
    const rects = Array.from(range.getClientRects()).filter((r) => r.width > 1 && r.height > 1);
    range.detach?.();
    if (!rects.length) return this.passageLines(id);
    return rects.map((r) => ({ x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height }));
  }

  /**
   * Where the spider lands. It stands ON the line of text - at the words the finding
   * quoted when the file gives us that precision, otherwise a little way into the line -
   * so the crawl reads as investigating the text, not hovering beside it.
   */
  anchor(id: string): PassageAnchor | null {
    const rect = this.passageRect(id);
    if (!rect) return null;
    const lines = this.passageLines(id);
    const passage = this.passagesById.get(id);
    const pageNumber = passage?.page_number ?? null;
    const first = lines[0] ?? rect;
    const bounds = pageNumber ? this.pageRect(pageNumber) : null;

    // land on the quoted words when the source gives us their box
    let landingX = first.x + Math.min(first.w * 0.18, 96);
    const quote = this.quoteRects(id, passage?.char_start ?? 0, passage?.char_end ?? 0);
    if (quote.length) landingX = quote[0].x + Math.min(quote[0].w * 0.35, 70);

    const half = this.spiderHalf;
    const minX = (bounds?.x ?? rect.x) + half * 0.4;
    const maxX = (bounds ? bounds.x + bounds.w - half : rect.x + rect.w);
    const standX = clampNumber(landingX, minX, Math.max(minX, maxX));
    const standY = first.y + first.h / 2;

    return {
      rect,
      lines: lines.length ? lines : [rect],
      stand: { x: standX, y: standY },
      lane: { x: standX, y: standY },
      focus: { x: Math.min(standX + 46, rect.x + rect.w), y: standY },
      page: pageNumber,
      measuredBy: passage?.coordinate_source === "pdf_bbox" && this.usePageImages ? "pdf_bbox" : "dom_element",
    };
  }

  /**
   * Hop points to reach a landing spot. Long distances are broken into two jumps with a
   * resting line between them, because a single 900px web-shot looks like teleporting.
   */
  routeTo(anchor: PassageAnchor, from: { x: number; y: number }): { x: number; y: number }[] {
    const target = anchor.stand;
    const distance = Math.hypot(target.x - from.x, target.y - from.y);
    if (distance < 260) return [target];
    const steps = distance > 900 ? 3 : 2;
    const points: { x: number; y: number }[] = [];
    for (let step = 1; step <= steps; step++) {
      const t = step / steps;
      const x = from.x + (target.x - from.x) * t;
      const y = from.y + (target.y - from.y) * t;
      // intermediate stops land in the whitespace between paragraphs when we can find it
      points.push(step === steps ? target : { x, y });
    }
    return points;
  }
}

function clampNumber(value: number, low: number, high: number): number {
  if (!Number.isFinite(value)) return low;
  return Math.min(high, Math.max(low, value));
}

function clampFraction(value: number): number {
  return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
}

function firstTextNode(element: HTMLElement): Text | null {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const first = walker.nextNode();
  return first as Text | null;
}
