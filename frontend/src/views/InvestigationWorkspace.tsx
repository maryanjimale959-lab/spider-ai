import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CrawlStage from "../components/CrawlStage";
import FindingsStrip, { type Category } from "../components/FindingsStrip";
import SpiderNetwork from "../components/SpiderNetwork";
import { SurfaceMeasure } from "../lib/coordinates";
import { api } from "../lib/api";
import { useCrawl } from "../lib/useCrawl";
import type {
  DocumentSummary, Finding, Investigation, InvestigationResults, Keyword, Passage, QuestionAnswer, Recommendation,
  VersionContent,
} from "../lib/types";
import { GOAL_LABELS } from "../lib/types";

/* ===========================================================================
   InvestigationWorkspace

   One document, the whole screen, results along the bottom. Nothing sits beside
   the page: the spider works in the middle of the text and the lines it has read
   stay painted where they are.

   Dropping a file in is enough - it is read, analysed and then walked, without
   anyone hunting for a button in a menu.
   ========================================================================= */

interface Props {
  initialVersionId?: string | null;
  className?: string;
  theme: "light" | "dark";
  onTheme: (next: "light" | "dark") => void;
}

const POLL_MS = 900;
const GOAL_HINTS: Record<string, string> = {
  understanding: "subject, purpose, structure, arguments, conclusions",
  important_info: "facts, dates, people, definitions, quantities, decisions",
  keywords: "the terms the document leans on and where they sit",
  writing: "grammar, spelling, clarity, flow, repetition, readability",
  logic_evidence: "claims with no support, contradictions, ambiguity, over-reach",
  recommendations: "revisions tied to a passage, for you to accept or set aside",
};

type Popover = "documents" | "run" | "outline" | "display" | "details" | null;

function PopoverPanel({
  open, onClose, children, align = "right", label,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  align?: "left" | "right";
  label: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className={`pop pop-${align}`} ref={ref} role="dialog" aria-label={label}>
      {children}
    </div>
  );
}

function ToggleRow({
  on, onToggle, name, hint,
}: {
  on: boolean;
  onToggle: () => void;
  name: string;
  hint?: string;
}) {
  return (
    <button className="toggle" type="button" aria-pressed={on} onClick={onToggle}>
      <span className="switch" aria-hidden="true" />
      <span>
        <span className="name">{name}</span>
        {hint && <span className="hint">{hint}</span>}
      </span>
    </button>
  );
}

export default function InvestigationWorkspace({ initialVersionId, className, theme, onTheme }: Props) {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [versionId, setVersionId] = useState<string | null>(initialVersionId ?? null);
  const [content, setContent] = useState<VersionContent | null>(null);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [results, setResults] = useState<InvestigationResults | null>(null);
  const [goals, setGoals] = useState<string[]>(Object.keys(GOAL_LABELS));
  const [mode, setMode] = useState<"crawl" | "network">("crawl");
  const [view, setView] = useState<"page" | "text">("page");
  // a wide screen can afford a bigger page; the document is the point of the screen
  const [zoom, setZoom] = useState(() => (typeof window !== "undefined" && window.innerWidth > 1280 ? 1.25 : 1));
  const [spiderSize, setSpiderSize] = useState(84);
  const [reducedMotion, setReducedMotion] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [category, setCategory] = useState<Category>("findings");
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [selectedKeywordId, setSelectedKeywordId] = useState<string | null>(null);
  const [selectedPassageId, setSelectedPassageId] = useState<string | null>(null);
  const [keywordBands, setKeywordBands] = useState<{ passageId: string; start: number; end: number }[]>([]);
  const [popover, setPopover] = useState<Popover>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<QuestionAnswer[]>([]);
  const [startToken, setStartToken] = useState(0);
  const surfaceEl = useRef<HTMLElement | null>(null);
  const measureCache = useRef<{ key: string; measure: SurfaceMeasure } | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const autoRun = useRef<string | null>(null);

  const passagesById = useMemo(() => {
    const map = new Map<string, Passage>();
    content?.passages.forEach((passage) => map.set(passage.id, passage));
    return map;
  }, [content]);

  const findings = useMemo(() => {
    if (!results) return [];
    const rank = (finding: Finding) => (finding.severity === "major" ? 0 : finding.severity === "minor" ? 1 : 2);
    return [...results.findings].sort((a, b) => rank(a) - rank(b));
  }, [results]);

  const measure = useCallback((): SurfaceMeasure | null => {
    const element = surfaceEl.current;
    if (!element || !content) return null;
    const key = `${content.version_id}:${content.passages.length}:${spiderSize}`;
    if (measureCache.current?.key === key) return measureCache.current.measure;
    const instance = new SurfaceMeasure(element as HTMLElement, content.passages, content.pages, spiderSize / 2);
    measureCache.current = { key, measure: instance };
    return instance;
  }, [content, spiderSize]);

  const crawl = useCrawl({
    measure,
    events: results?.events ?? [],
    findings,
    keywords: results?.keywords ?? [],
    allNodeIds: results?.nodes.map((node) => node.id) ?? [],
    restingPassageId: results?.investigation.metrics?.resting_passage_id ?? null,
    reducedMotion,
    spiderSize,
  });
  const { realign } = crawl;

  /* ------------------------------------------------------------- documents */
  const loadDocuments = useCallback(async () => {
    try {
      setDocuments(await api.listDocuments());
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Your documents could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  const openDocument = useCallback((document: DocumentSummary) => {
    if (!document.current_version_id) {
      setError("That document has no readable version yet.");
      return;
    }
    setDocumentId(document.id);
    setVersionId(document.current_version_id);
    setContent(null);
    setResults(null);
    setInvestigation(null);
    setSelectedFindingId(null);
    setSelectedKeywordId(null);
    setKeywordBands([]);
    setHistory([]);
    setPopover(null);
  }, []);

  /* ------------------------------------------------------------- open a version */
  useEffect(() => {
    if (!versionId) return;
    let active = true;
    setContent(null);
    (async () => {
      try {
        let payload = await api.content(versionId);
        if (!active) return;
        let guard = 0;
        while (payload.extraction_status === "pending" || payload.extraction_status === "extracting") {
          if (!active || guard++ > 60) return;
          await new Promise((resolve) => setTimeout(resolve, POLL_MS));
          payload = await api.content(versionId);
        }
        if (!active) return;
        setContent(payload);
        setView(payload.pages.length > 0 ? "page" : "text");
      } catch (requestError) {
        if (active) setError(requestError instanceof Error ? requestError.message : "The document could not be opened.");
      }
    })();
    return () => {
      active = false;
    };
  }, [versionId]);

  useEffect(() => {
    if (!versionId) return;
    let active = true;
    (async () => {
      try {
        const latest = await api.latest(versionId);
        if (!active || !latest) return;
        setInvestigation(latest);
        if (latest.status === "completed") {
          const payload = await api.results(latest.id);
          if (active) setResults(payload);
        }
      } catch {
        /* never read - normal */
      }
    })();
    return () => {
      active = false;
    };
  }, [versionId]);

  /* ------------------------------------------------------------- run + poll */
  const startInvestigation = useCallback(async () => {
    if (!versionId) return;
    setError(null);
    setResults(null);
    setPopover(null);
    try {
      setInvestigation(await api.start(versionId, goals));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "The reading could not start.");
    }
  }, [goals, versionId]);

  useEffect(() => {
    if (!investigation) return;
    if (["completed", "failed", "cancelled"].includes(investigation.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.status(investigation.id);
        setInvestigation(next);
        if (next.status === "completed") {
          setResults(await api.results(next.id));
          setStartToken((token) => token + 1);
        }
        if (next.status === "failed" || next.status === "cancelled") setError(next.error ?? `The reading ${next.status}.`);
      } catch {
        /* transient */
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [investigation]);

  /* a file that has just arrived is read on its own - no button to find */
  useEffect(() => {
    const pending = autoRun.current;
    if (!pending || !content || content.version_id !== pending) return;
    autoRun.current = null;
    void startInvestigation();
  }, [content, startInvestigation]);

  /* exactly one automatic walk per reading, never after an explicit skip */
  const autoStartedFor = useRef<string | null>(null);
  const crawlFinished = useRef(false);
  useEffect(() => {
    crawlFinished.current = crawl.state.finished;
  }, [crawl.state.finished]);

  useEffect(() => {
    if (!results || mode !== "crawl") return;
    const id = results.investigation.id;
    const timer = window.setTimeout(() => {
      if (autoStartedFor.current === id || crawlFinished.current) return;
      autoStartedFor.current = id;
      crawl.start();
    }, 260);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startToken, results, mode]);

  useEffect(() => {
    realign();
  }, [zoom, view, mode, realign]);

  /* ------------------------------------------------------------- selection */
  const selectedFinding = useMemo(
    () => findings.find((finding) => finding.id === selectedFindingId) ?? null,
    [findings, selectedFindingId],
  );

  const navigateToPassage = useCallback(
    (passageId: string) => {
      setSelectedPassageId(passageId);
      if (mode === "crawl") crawl.jumpToPassage(passageId);
      else {
        const surface = measure();
        const rect = surface?.passageRect(passageId);
        const scroller = document.querySelector(".doc-scroll");
        if (rect && scroller) scroller.scrollTo({ top: Math.max(0, rect.y - 120), behavior: reducedMotion ? "auto" : "smooth" });
      }
    },
    [crawl, measure, mode, reducedMotion],
  );

  const selectFinding = useCallback((finding: Finding) => {
    setSelectedKeywordId(null);
    setKeywordBands([]);
    setSelectedFindingId(finding.id);
    if (finding.primary_passage_id) navigateToPassage(finding.primary_passage_id);
  }, [navigateToPassage]);

  const selectKeyword = useCallback(async (keyword: Keyword) => {
    setSelectedFindingId(null);
    setSelectedKeywordId(keyword.id);
    const first = keyword.passage_ids?.[0];
    if (first) navigateToPassage(first);
    try {
      const payload = await api.keywordOccurrences(keyword.id);
      setKeywordBands(
        payload.hits.map((hit) => ({ passageId: hit.passage_id, start: hit.start, end: hit.end })),
      );
    } catch {
      setKeywordBands([]);
    }
  }, [navigateToPassage]);

  const ask = useCallback(async (question: string): Promise<QuestionAnswer | null> => {
    if (!investigation) return null;
    const answer = await api.ask(investigation.id, question);
    setHistory((previous) => [answer, ...previous].slice(0, 8));
    return answer;
  }, [investigation]);

  const decide = useCallback(async (recommendation: Recommendation, status: "accepted" | "dismissed" | "edited") => {
    await api.decide(recommendation.id, status);
    if (investigation) setResults(await api.results(investigation.id));
  }, [investigation]);

  const upload = useCallback(async (file: File) => {
    setUploading(true);
    setUploadError(null);
    setError(null);
    try {
      const created = await api.upload(file);
      const list = await api.listDocuments();
      setDocuments(list);
      const fresh = list.find((item) => item.id === created.id) ?? created;
      autoRun.current = fresh.current_version_id ?? null;
      openDocument(fresh);
    } catch (requestError) {
      setUploadError(requestError instanceof Error ? requestError.message : "The file could not be uploaded.");
    } finally {
      setUploading(false);
    }
  }, [openDocument]);

  /* convert keyword hits (passage-relative) into the absolute offsets the painter wants */
  const paintedKeywordBands = useMemo(() => keywordBands.flatMap((hit) => {
    const passage = passagesById.get(hit.passageId);
    if (!passage) return [];
    return [{ passageId: hit.passageId, start: passage.char_start + hit.start, end: passage.char_start + hit.end }];
  }), [keywordBands, passagesById]);

  const highlights = useMemo(() => {
    const out: { passageId: string; charStart: number; charEnd: number; tone: "select" | "evidence" | "keyword" | "note" }[] = [];
    selectedFinding?.evidence.forEach((evidence) => out.push({
      passageId: evidence.passage_id, charStart: evidence.char_start ?? 0, charEnd: evidence.char_end ?? 0, tone: "evidence",
    }));
    return out;
  }, [selectedFinding]);

  const showAllResults = mode === "network" || crawl.state.finished;
  const railFindings = showAllResults ? findings : crawl.state.revealedFindings;
  const railKeywords = showAllResults && results ? results.keywords : crawl.state.revealedKeywords;

  const busy = Boolean(investigation) && !["completed", "failed", "cancelled"].includes(investigation?.status ?? "");
  const statusText = uploading
    ? "Your file is arriving"
    : busy
      ? (investigation?.detail || "Reading the document")
      : results
        ? "Read - the results are listed below"
        : content
          ? "Not read yet"
          : "No document open";

  const activeDocument = documents.find((document) => document.id === documentId) ?? null;
  const setPop = (next: Popover) => setPopover((current) => (current === next ? null : next));
  const walkLabel = crawl.state.paused ? "Resume" : crawl.state.playing ? "Pause" : "Watch it again";
  const runLabel = investigation?.status === "completed" ? "Read it again" : "Read this document";

  return (
    <div
      className={`work${className ? ` ${className}` : ""}${dragging ? " is-dragging" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        if (!dragging) setDragging(true);
      }}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node)) return;
        setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        const file = event.dataTransfer.files?.[0];
        if (file) void upload(file);
      }}
    >
      <header className="toolbar">
        <div className="toolbar-doc">
          <button className="doc-pick" onClick={() => setPop("documents")} aria-expanded={popover === "documents"}>
            <span className="doc-pick-label">Document</span>
            <span className="doc-pick-name" title={content?.title ?? "Choose a document"}>
              {content?.title ?? "Choose or drop a file"}
            </span>
          </button>
          <PopoverPanel open={popover === "documents"} onClose={() => setPopover(null)} align="left" label="Documents">
            <div className="pop-head">
              <h3>Your documents</h3>
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.docx,.txt,.md,.markdown,.html,.htm,.csv,.tsv"
                style={{ display: "none" }}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void upload(file);
                  event.target.value = "";
                }}
              />
              <button className="btn sm primary" onClick={() => fileInput.current?.click()} disabled={uploading}>
                {uploading ? "Arriving" : "Upload"}
              </button>
            </div>
            {uploadError && <p className="error-text">{uploadError}</p>}
            <div className="pop-list">
              {documents.length === 0 && <p className="tiny muted">Nothing here yet. Choose a PDF, Word file, text, Markdown, HTML or spreadsheet.</p>}
              {documents.map((document) => (
                <div key={document.id} className={`pop-item${document.id === documentId ? " is-active" : ""}`}>
                  <button className="pop-item-main" onClick={() => openDocument(document)}>
                    <span className="pop-title" dir="auto">{document.title}</span>
                    <span className="pop-meta">
                      {document.file_format?.toUpperCase() ?? "-"} -{" "}
                      {document.extraction_status === "ready"
                        ? `${(document.word_count ?? 0).toLocaleString()} words`
                        : document.extraction_status === "failed"
                          ? "could not be read"
                          : document.extraction_status === "needs_ocr"
                            ? "no text layer"
                            : "still arriving"}
                      {document.language ? ` - ${document.language}` : ""}
                    </span>
                  </button>
                  <button
                    className="btn sm danger"
                    onClick={async () => {
                      await api.deleteDocument(document.id);
                      if (document.id === documentId) {
                        setDocumentId(null);
                        setVersionId(null);
                        setContent(null);
                        setResults(null);
                        setInvestigation(null);
                      }
                      void loadDocuments();
                    }}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
            <p className="pop-foot tiny muted">Removing a document also removes its stored file and everything drawn from it.</p>
          </PopoverPanel>
        </div>

        <div className="toolbar-status">
          <span className={`pulse-dot${busy ? "" : results ? " done" : " idle"}`} />
          <span className="status-text">{statusText}</span>
          {crawl.state.playing && (
            <span className="status-task" title={crawl.state.task}>
              {crawl.state.task}
              <span className="mono muted"> {Math.max(0, crawl.state.cursor + 1)}/{crawl.state.total}</span>
            </span>
          )}
        </div>

        <div className="toolbar-actions">
          <div className="segmented">
            <button aria-pressed={mode === "crawl"} onClick={() => setMode("crawl")}>The crawl</button>
            <button aria-pressed={mode === "network"} onClick={() => setMode("network")}>The web</button>
          </div>

          {mode === "crawl" && results && (
            <>
              <button className="btn sm" onClick={() => {
                if (crawl.state.finished && !crawl.state.playing) crawl.start();
                else crawl.toggle();
              }}>
                {walkLabel}
              </button>
              {!crawl.state.finished && (
                <button className="btn sm ghost" onClick={crawl.skipToEnd}>Skip to the results</button>
              )}
              <div className="segmented sm" role="group" aria-label="Reading pace">
                {[1, 2, 4].map((value) => (
                  <button key={value} aria-pressed={crawl.speed === value} onClick={() => crawl.setSpeed(value)}>
                    {value === 1 ? "Careful" : value === 2 ? "Normal" : "Quick"}
                  </button>
                ))}
              </div>
            </>
          )}

          <div className="pop-anchor">
            <button className="btn sm primary" onClick={() => setPop("run")} aria-expanded={popover === "run"} disabled={!content}>
              {runLabel}
            </button>
            <PopoverPanel open={popover === "run"} onClose={() => setPopover(null)} label="What to look for">
              <div className="pop-head"><h3>What should it look for?</h3></div>
              <div className="goal-list">
                {Object.entries(GOAL_LABELS).map(([key, label]) => (
                  <ToggleRow
                    key={key}
                    on={goals.includes(key)}
                    name={label}
                    hint={GOAL_HINTS[key]}
                    onToggle={() => setGoals((current) =>
                      current.includes(key) ? current.filter((item) => item !== key) : [...current, key])}
                  />
                ))}
              </div>
              <div className="pop-actions">
                <button className="btn primary block" onClick={() => void startInvestigation()} disabled={!content || busy}>
                  {busy ? "Reading" : runLabel}
                </button>
                <p className="tiny muted">
                  Anything that cannot be quoted back from the document is set aside by the evidence check, not shown.
                </p>
              </div>
            </PopoverPanel>
          </div>

          {content && content.sections.length > 0 && (
            <div className="pop-anchor">
              <button className="link-quiet" onClick={() => setPop("outline")} aria-expanded={popover === "outline"}>Contents</button>
              <PopoverPanel open={popover === "outline"} onClose={() => setPopover(null)} label="Document contents">
                <div className="pop-head"><h3>Contents</h3></div>
                <div className="toc">
                  {content.sections.map((section) => {
                    const passage = content.passages.find((item) => item.section_id === section.id);
                    return (
                      <button
                        key={section.id}
                        className={`level-${Math.min(2, section.level)}${passage?.id === selectedPassageId ? " active" : ""}`}
                        onClick={() => passage && navigateToPassage(passage.id)}
                        disabled={!passage}
                      >
                        {section.title}
                      </button>
                    );
                  })}
                </div>
              </PopoverPanel>
            </div>
          )}

          <div className="pop-anchor">
            <button className="link-quiet" onClick={() => setPop("display")} aria-expanded={popover === "display"}>Display</button>
            <PopoverPanel open={popover === "display"} onClose={() => setPopover(null)} label="Display settings">
              <div className="pop-head"><h3>Display</h3></div>
              <div className="pop-fields">
                <div>
                  <span className="label">Size of the page</span>
                  <div className="segmented block">
                    {[0.75, 1, 1.25, 1.5].map((value) => (
                      <button key={value} aria-pressed={zoom === value} onClick={() => setZoom(value)}>
                        {Math.round(value * 100)}%
                      </button>
                    ))}
                  </div>
                </div>
                {content && content.pages.length > 0 && (
                  <div>
                    <span className="label">Show the page as</span>
                    <div className="segmented block">
                      <button aria-pressed={view === "page"} onClick={() => setView("page")}>Its own pages</button>
                      <button aria-pressed={view === "text"} onClick={() => setView("text")}>Flowing text</button>
                    </div>
                  </div>
                )}
                <ToggleRow
                  on={theme === "dark"}
                  name="Ink theme"
                  hint="Dark paper, same calm colours."
                  onToggle={() => onTheme(theme === "dark" ? "light" : "dark")}
                />
                <ToggleRow
                  on={!reducedMotion}
                  name="Full movement"
                  hint="Turn this off to keep the spider still between lines."
                  onToggle={() => setReducedMotion((current) => !current)}
                />
                <div>
                  <span className="label">Size of the spider</span>
                  <input
                    className="slider"
                    type="range"
                    min={44}
                    max={120}
                    value={spiderSize}
                    onChange={(event) => setSpiderSize(Number(event.target.value))}
                  />
                </div>
              </div>
            </PopoverPanel>
          </div>

          {content && (
            <div className="pop-anchor">
              <button className="link-quiet" onClick={() => setPop("details")} aria-expanded={popover === "details"}>Details</button>
              <PopoverPanel open={popover === "details"} onClose={() => setPopover(null)} label="Document details">
                <div className="pop-head"><h3>How this document was read</h3></div>
                <div className="pop-body">
                  <div className="row wrap" style={{ gap: 6 }}>
                    <span className="chip">
                      {content.positioning_quality === "pdf_bbox" ? "positions taken from the PDF" : "positions taken from the rendered text"}
                    </span>
                    <span className="chip">{content.passages.length} passages</span>
                    <span className="chip">{content.word_count.toLocaleString()} words</span>
                    <span className="chip">{content.language}</span>
                  </div>
                  {content.notes.map((note) => <p key={note} className="notice tiny">{note}</p>)}
                  {content.ocr_needed && (
                    <p className="notice warn tiny">Some pages hold no text, so they are reported as unread rather than guessed.</p>
                  )}
                  {!!investigation?.metrics && (
                    <p className="tiny muted">
                      {investigation.metrics.draft_findings ?? 0} statements were drafted, {investigation.metrics.validated_findings ?? 0}
                      {" "}could be quoted back and were kept, {investigation.metrics.rejected_findings ?? 0} were set aside. The walk you see is
                      that same order replayed.
                    </p>
                  )}
                  {activeDocument && (
                    <p className="tiny muted">Yours since {new Date(activeDocument.created_at).toLocaleDateString()}.</p>
                  )}
                </div>
              </PopoverPanel>
            </div>
          )}
        </div>
      </header>

      {error && <div className="notice bad" style={{ margin: "0 18px" }}>{error}</div>}

      {content && !results && !busy && (
        <div className="prompt">
          <p>
            <strong>{content.title}</strong> is open and its {content.passages.length} passages are in place. Nothing
            has read it yet.
          </p>
          <button className="btn primary sm" type="button" onClick={() => void startInvestigation()}>
            {runLabel}
          </button>
        </div>
      )}

      {busy && (
        <div className="prompt is-busy">
          <span className="pulse-dot" />
          <p>{investigation?.detail || "Reading the document"}</p>
        </div>
      )}

      {content ? (
        mode === "crawl" ? (
          <CrawlStage
            content={content}
            crawl={crawl.state}
            walker={crawl.walker}
            measure={measure}
            mode={view}
            zoom={zoom}
            selectedPassageId={selectedPassageId}
            highlights={highlights}
            onPassageSelect={setSelectedPassageId}
            selectedFindingId={selectedFindingId}
            reducedMotion={reducedMotion}
            paintedFindings={railFindings}
            keywordBands={paintedKeywordBands}
            onSurface={(element) => {
              surfaceEl.current = element;
              measureCache.current = null;
            }}
          />
        ) : (
          <section className="canvas">
            <SpiderNetwork
              nodes={results?.nodes ?? []}
              edges={results?.edges ?? []}
              upToSeq={crawl.state.playing ? crawl.state.cursor : Number.MAX_SAFE_INTEGER - 2}
              revealedFindingIds={new Set(railFindings.map((finding) => finding.id))}
              selectedFindingId={selectedFindingId}
              selectedKeywordId={selectedKeywordId}
              onSelectFinding={(id) => {
                const finding = findings.find((item) => item.id === id);
                if (finding) selectFinding(finding);
              }}
              onSelectKeyword={(id) => {
                const keyword = results?.keywords.find((item) => item.id === id);
                if (keyword) void selectKeyword(keyword);
              }}
              reducedMotion={reducedMotion}
            />
          </section>
        )
      ) : (
        <section className="canvas canvas-empty">
          <div className="empty-card">
            <p className="lp-eyebrow">Document investigation</p>
            <h2>The spider walks your document and tells you what it found</h2>
            <p className="dim">
              Choose a file, or drop one anywhere on this screen. It is read from the first line to the last for
              subject, figures, vocabulary, language, reasoning and revisions - and every result comes back quoting the
              passage it was taken from.
            </p>
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx,.txt,.md,.markdown,.html,.htm,.csv,.tsv"
              style={{ display: "none" }}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.target.value = "";
              }}
            />
            <div className="row" style={{ gap: 10 }}>
              <button className="btn primary lg" onClick={() => fileInput.current?.click()} disabled={uploading}>
                {uploading ? "Your file is arriving" : "Choose a document"}
              </button>
              {documents.length > 0 && (
                <button className="btn ghost lg" onClick={() => setPop("documents")}>Open one of mine</button>
              )}
            </div>
            <p className="tiny muted">PDF, Word, plain text, Markdown, HTML or a spreadsheet.</p>
            {uploadError && <p className="error-text">{uploadError}</p>}
          </div>
          <div className="drop-veil" aria-hidden="true">
            <p>Drop it here</p>
          </div>
        </section>
      )}

      {results && (
        <FindingsStrip
          title={content?.title ?? ""}
          findings={railFindings}
          keywords={railKeywords}
          recommendations={showAllResults ? results.recommendations : []}
          totalFindings={findings.length}
          category={category}
          onCategory={setCategory}
          selectedFindingId={selectedFindingId}
          selectedKeywordId={selectedKeywordId}
          onSelectFinding={selectFinding}
          onSelectKeyword={(keyword) => void selectKeyword(keyword)}
          onClearFinding={() => setSelectedFindingId(null)}
          onClearKeyword={() => {
            setSelectedKeywordId(null);
            setKeywordBands([]);
          }}
          onGoTo={navigateToPassage}
          onDecide={(recommendation, status) => void decide(recommendation, status)}
          askingDisabled={investigation?.status !== "completed"}
          onAsk={ask}
          history={history}
          aiNote={results.ai.note}
          live={crawl.state.playing}
        />
      )}
    </div>
  );
}
