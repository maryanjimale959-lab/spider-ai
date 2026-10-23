import { memo } from "react";
import type { Passage, VersionContent } from "../lib/types";
import { useProtectedImage } from "../lib/useProtectedImage";

/* ===========================================================================
   DocumentSurface

   Two renderings of the same extracted passages:
     - "page"  : the real PDF pages as images, with the spider walking over the text
                 coordinates that came out of the file.
     - "text"  : a reflowed reading view (also used for DOCX/TXT/MD/HTML/CSV), where
                 every passage is a DOM element the spider can be anchored to.
   Either way each passage keeps its stable passage id, which is what links the
   analysis, the animation, and the graph together.
   ========================================================================= */

interface Highlight {
  passageId: string;
  charStart: number;
  charEnd: number;
  tone: "select" | "evidence" | "keyword" | "note";
}

interface Props {
  content: VersionContent;
  mode: "page" | "text";
  zoom: number;
  selectedPassageId?: string | null;
  highlights: Highlight[];
  onPassageSelect?: (passageId: string) => void;
  pageImageBaseUrl: string;
}

function isRightToLeft(text: string): boolean {
  let rtl = 0;
  let ltr = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    if (code >= 0x0590 && code <= 0x08ff) rtl += 1;
    else if ((code >= 0x41 && code <= 0x7a) || code >= 0xac00) ltr += 1;
  }
  return rtl > ltr;
}

function passageClass(passage: Passage): string {
  return `doc-passage kind-${passage.kind}`;
}

const MarkedText = memo(function MarkedText({
  passage,
  highlights,
}: {
  passage: Passage;
  highlights: Highlight[];
}) {
  const mine = highlights
    .filter((h) => h.passageId === passage.id)
    .map((h) => ({ start: Math.max(0, h.charStart - passage.char_start), end: Math.min(passage.text.length, h.charEnd - passage.char_start), tone: h.tone }))
    .filter((h) => h.end > h.start)
    .sort((a, b) => a.start - b.start);

  if (mine.length === 0) return <>{passage.text}</>;

  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  mine.forEach((span, index) => {
    if (span.start > cursor) nodes.push(<span key={`t${index}`}>{passage.text.slice(cursor, span.start)}</span>);
    nodes.push(
      <mark key={`m${index}`} className={`doc-mark tone-${span.tone}`}>
        {passage.text.slice(span.start, span.end)}
      </mark>,
    );
    cursor = span.end;
  });
  if (cursor < passage.text.length) nodes.push(<span key="tail">{passage.text.slice(cursor)}</span>);
  return <>{nodes}</>;
});

function PassageBlock({
  passage,
  highlights,
  selected,
  onSelect,
}: {
  passage: Passage;
  highlights: Highlight[];
  selected: boolean;
  onSelect?: (id: string) => void;
}) {
  const rtl = isRightToLeft(passage.text);
  return (
    <div
      data-passage={passage.id}
      data-sort={passage.sort_index}
      className={`${passageClass(passage)}${selected ? " is-selected" : ""}`}
      dir={rtl ? "rtl" : "ltr"}
      lang={rtl ? "ar" : undefined}
      onClick={onSelect ? () => onSelect(passage.id) : undefined}
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onKeyDown={
        onSelect
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect(passage.id);
              }
            }
          : undefined
      }
    >
      <MarkedText passage={passage} highlights={highlights} />
    </div>
  );
}

function PageImage({ url, width, alt }: { url: string; width: number; alt: string }) {
  const { src, error } = useProtectedImage(url);
  if (error) {
    return (
      <div className="page-missing">
        <p>{error}</p>
        <p className="muted tiny">The page could not be rendered from the stored file.</p>
      </div>
    );
  }
  if (!src) return <div className="page-loading" style={{ width, aspectRatio: "1 / 1.414" }} />;
  return <img className="page-image" src={src} width={width} alt={alt} draggable={false} />;
}

export default function DocumentSurface({
  content,
  mode,
  zoom,
  selectedPassageId,
  highlights,
  onPassageSelect,
  pageImageBaseUrl,
}: Props) {
  if (mode === "page" && content.pages.length > 0) {
    return (
      <div className="doc-pages" style={{ width: Math.round(760 * zoom) }}>
        {content.pages.map((page) => (
          <div key={page.number} className="doc-page" data-page={page.number}>
            <PageImage
              url={`${pageImageBaseUrl}/${page.number}.png`}
              width={Math.round(760 * zoom)}
              alt={`Page ${page.number} of ${content.title}`}
            />
            {!page.has_text && (
              <div className="page-flag" dir="ltr">
                No text layer on this page - it needs OCR before the spider can read it.
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  const headingIds = new Set(content.sections.map((s) => s.id));

  return (
    <article className="doc-text" style={{ fontSize: `${Math.round(16 * zoom)}px` }} data-has-headings={headingIds.size > 0}>
      <header className="doc-header" dir={isRightToLeft(content.title) ? "rtl" : "ltr"}>
        <h1 className="doc-title">{content.title}</h1>
        <div className="doc-meta mono tiny muted">
          {content.file_format.toUpperCase()} - {content.word_count.toLocaleString()} words -{" "}
          {content.passages.length} passages - language {content.language}
        </div>
      </header>
      {content.passages.map((passage) => (
        <PassageBlock
          key={passage.id}
          passage={passage}
          highlights={highlights}
          selected={passage.id === selectedPassageId}
          onSelect={onPassageSelect}
        />
      ))}
    </article>
  );
}
