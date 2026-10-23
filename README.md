# SPIDER AI

A document investigation tool with a cybernetic spider on it, built by
[Mariam Xasan Jimcaale](https://github.com/maryanjimale959-lab).

You choose a PDF, Word file, Markdown note, HTML page or spreadsheet. The spider walks the
real pages, **shoots a line of white web fluid at the next line of text and swings onto it**,
reads that passage, and reports only what it can quote straight back to you.

---

## Run it (Windows)

Double-click **`start.bat`** in this folder. The first run builds the environment, then opens
`http://localhost:5173` on the landing page.

There is no demo data and no shared account. The workspace starts empty: choose *Create one* on
the sign-in page, use your own email, and upload your own files. The database, the uploads and
the page renders all live in `backend/`, which is git-ignored, so nothing here is committed by
accident.

A minimized window named "SPIDER AI server" is the analysis API; leave it open while you
work, close it to stop.

To run the whole product from one process, the way a server would, build the interface once
and open `http://localhost:8000`:

```bash
cd frontend && npm run build
cd ../backend && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

See **[DEPLOYING.md](DEPLOYING.md)** for the Docker image and the Railway settings.

### Manual

```bash
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

cd ../frontend && npm install && npm run dev      # http://localhost:5173
```

API docs: `http://127.0.0.1:8000/docs`. Sample files used by the tests live in
`backend/samples/`; `backend/tools/make_site_report.py` regenerates the five-page one, and
`backend/tools/cleanup_probe_runs.py` removes the accounts and uploads that the verification
runs leave behind.

---

## The spider

**It walks on the text.** For PDFs, the spider lands on the actual line rectangles that
PyMuPDF reads out of the file, at the words the finding quoted when the file gives that
precision. For Word, text, Markdown, HTML and CSV it lands on the rendered paragraph. It
stands *on* the words, slightly transparent so the text stays readable, and moves on.

**It shoots web.** Every move is a real sequence: aim, fire a tapering strand of web fluid at
an anchor just above the next line, the splash lands, the line goes taut, the body swings along
a curved arc, legs tuck in mid-air and shoot forward to plant, then it settles and scans. Long
distances are broken into two or three hops so it never looks like teleporting. A silk thread
also rises above the spider as it works, the way a spider hangs while it reads.

**Eight articulated legs.** Two-bone inverse kinematics per leg, with the joint that sits
farther from the body chosen each frame - which is what makes a back leg bend like a leg
instead of folding under the abdomen. Feet stay planted in page coordinates while the body
turns, so the gait reads as walking rather than a sprite sliding.

**The lines it reads stay painted.** As the crawl advances, each quoted span is painted where
it actually sits - a light wash with a thin rule at its left edge, in one of six calm colours:
steel blue for structure and ideas, ochre for facts and figures, rose for writing problems,
slate for terms, violet for logic, green for strengths and revisions. The washes are deliberately
faint, because several findings can land on one line and the text has to stay readable. Only the
most important lines carry a written note - at most eight - plus the one you have selected.
Choosing a term paints every place it appears.

**Controls.** The document is read on its own the moment it arrives - no menu to find. Then:
*The crawl* / *The web*, Pause, Resume, *Watch it again*, *Skip to the results*, a pace of
*Careful / Normal / Quick*, *Read it again* with the six readings you want included, plus
*Contents*, *Display* (page size, its own pages or flowing text, ink theme, full movement, size
of the spider) and *Details*, which says where the coordinates came from and how many statements
the evidence check threw away. Dropping a file anywhere on the screen uploads it.

---

## Two views of one result set

**The crawl** - the document owns the screen. Results live in a strip along the bottom
(*Found*, category filters, one row per finding) and clicking a row opens the detail above it:
the observation, the suggestion, and the verified quotation with its character range. Nothing
sits beside the page.

**The web** - the same validated results as an interactive web with the spider at the
hub. Each kind of branch owns an arc: sections overhead, keywords and topics to the right,
facts and claims below, writing issues and contradictions to the left, recommendations and
questions innermost, packed on rings so nothing overlaps. A 137-branch web is honest but
unreadable, so the default shows the strongest six of each kind; **Show every branch** puts
the rest on. Nodes are draggable, and clicking one opens what it came from.

Switching views keeps your selected finding and the crawl position.

### Why you can trust what it says

The backend records a genuine event log while it works - which passage it examined, in what
order, what each step produced - and the frontend replays that log. Nothing is invented for
the animation.

Then `app/analysis/evidence.py` checks every quotation against the stored passage text before
anything is saved. A quote that is not really in the passage, or is attached to the wrong
passage, drops the whole finding. The results payload reports how many drafts were produced
and how many the evidence check threw out, and each surviving quote is labelled `verbatim` or
`normalized` - the second one honestly gives up on exact character offsets.

---

## What it looks for

Chosen under *Read it again*; a reading you leave off does not run, and the API rejects unknown
goals.

- **Understanding** - subject, purpose, central ideas, structure, arguments, conclusions, strengths.
- **Important information** - facts, dates, people, definitions, statistics, decisions, action items.
- **Keywords** - TF with length normalisation plus co-occurrence scoring; primary / supporting / technical / acronym / concept; occurrence counts, the passages each term appears in, and an explanation built from the document itself. Every term it lists literally appears in the document.
- **Writing** - grammar, spelling, punctuation, clarity, paragraph structure, flow, repetition, tone, vocabulary, terminology consistency, readability, audience fit.
- **Logic and evidence** - claims with no support inside the document, contradiction candidates, reasoning gaps, ambiguous statements, conclusions that may exceed the evidence, questions worth asking. Wording stays careful: a missing citation is reported as *no support found here*, never as a false claim.
- **Recommendations** - tied to a passage and an observation, with suggested wording built from the author's own words, plus accept / dismiss / edit that is saved.
- **Questions** - BM25-style retrieval over the document's own sentences. The answer quotes them; if the document cannot answer, it says so and explains why.

### Languages

Detected per document (script first, then stopword rates): **English**, **Arabic**, **Somali**,
each with its own rules. Arabic gets punctuation-mixing, alef/hamza/ta-marbuta variant and
sentence-length checks (unvowelled text is never faulted). Somali gets doubled-letter typos,
variant pairs like `waxaa`/`waxa`, and long-sentence checks - Latin punctuation is correct in
Somali and is never flagged.

---

## Formats and what the spider can stand on

| Format | Coordinates | Page numbers |
| --- | --- | --- |
| PDF | text bounding boxes **and per-line rectangles from the file** (PDF points, scaled at render time) | yes |
| DOCX | rendered paragraph element | not reported |
| TXT / Markdown / HTML | rendered paragraph element | not reported |
| CSV / TSV | rendered row element | n/a |
| Scanned PDF | none until OCR is enabled - pages are flagged `needs_ocr` and said out loud | - |

Source coordinates (PDF points plus page geometry) are stored separately from screen
positions, which are recomputed on scroll, zoom, resize and page change. `positioning_quality`
and the parser's own notes are shown under *Details* rather than hidden.

---

## Architecture

```
upload -> validate (extension + magic bytes + size) -> private storage
       -> parser -> sections + passages with stable IDs and source coordinates
       -> goals selected -> analysis engine (local, deterministic) -> finding drafts
       -> evidence validator (quote must exist in the passage) -> accepted findings
       -> recommendations -> graph builder (validated results only) -> event log
       -> frontend replays the log as the crawl
```

- **Backend** Python 3, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PyMuPDF, python-docx.
- **Frontend** React 19, TypeScript, Vite, React Flow, hand-authored SVG/CSS for the spider. Styling is a token-based CSS system ("Ink & Paper": warm paper surfaces, ink text, one slate-blue accent, six faint semantic washes, Source Serif 4 for headings + Manrope for interface) with an ink dark variant, rather than Tailwind - the spec allows any consistent styling system.
- **Database** SQLite by default; PostgreSQL via `SPIDER_DATABASE_URL`, with `alembic upgrade head`.
- **Jobs** a two-worker thread pool with real states: `queued, extracting, analyzing, validating, building_graph, completed, failed, cancelled`. No simulated percentages.
- **Updates** polling every 900 ms; the endpoints are shaped so SSE can drop in without changing the client.

### API

| Area | Endpoints |
| --- | --- |
| Session | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me` |
| Documents | `POST /api/documents`, `GET /api/documents`, `GET/DELETE /api/documents/{id}`, `GET /api/versions/{id}/content`, `GET /api/versions/{id}/pages/{n}.png` |
| Investigation | `POST /api/versions/{id}/investigations`, `GET /api/investigations/{id}`, `GET /api/investigations/{id}/results`, `GET /api/versions/{id}/investigations/latest`, `POST /api/investigations/{id}/cancel`, `POST /api/recommendations/{id}/decision` |
| Knowledge | `GET /api/keywords/{id}/occurrences`, `POST/GET /api/investigations/{id}/questions` |
| Meta | `GET /api/health`, `GET /api/limits` |

The server still carries a teacher-review API (`/api/reviews*`, `/api/documents/{id}/access`,
`/api/rubrics`, `/api/reports/{token}`) with its own tests. It is **not reachable from the
interface any more** - you said student and teacher roles are not needed. Say the word and
I will delete those endpoints and their tables too.

### Data model

`users` - `documents` - `document_versions` - `sections` - **`passages`** (stable ID, page,
source bbox, per-line rectangles, `coordinate_source`) - `document_pages` - `investigations` -
`findings` - `evidence_references` - `keywords` - `recommendations` - `document_questions` -
`graph_nodes` / `graph_edges` - `audit_events` (plus the review tables above).

---

## Security and privacy

Bearer tokens (HS256), scrypt password hashing from the standard library, per-document
ownership checks on every endpoint. Uploads are checked by extension **and** magic bytes,
size-capped, stored under `storage/uploads/<user_id>/<uuid>` with names the client cannot
choose, and page renders are served only to the authenticated owner (the browser fetches them
as authorised blobs). Nothing is sent outside the deployment unless a provider key is
configured. Deleted documents are purged from disk, and a sweep removes anything soft-deleted
more than 30 days ago. Uploaded text is treated as untrusted data - the AI layer wraps it in
explicit data-only markers and instructs the model that text inside the excerpt is never an
instruction.

The landing page deliberately says nothing about where files live: hosted on your own machine
the answer is "this folder", hosted on a server it is "that server's storage directory", and a
public page should not be making promises the operator has not chosen.

## Optional external model

The local engine is always the source of findings. To add one, copy `.env.example` to
`backend/.env`:

```
SPIDER_AI_PROVIDER=openai_compatible
SPIDER_AI_BASE_URL=https://api.openai.com/v1
SPIDER_AI_API_KEY=...
SPIDER_AI_MODEL=gpt-4o-mini
```

`app/ai/provider.py` is provider-independent. When enabled it adds keyword definitions,
related concepts explicitly labelled `in_document: false`, and model-written answers to
questions - every citation re-validated against the source, and the UI says which engine
produced the text.

---

## Testing

```bash
cd backend  && .venv\Scripts\python.exe -m pytest -q      # 40 tests
cd frontend && npx tsc --noEmit                            # strict typecheck
cd frontend && node tools/verify-ui.mjs                    # 32 headless checks
cd frontend && node tools/verify-hosted.mjs                # 7 checks against the built, hosted origin
```

`tests/test_evidence.py` attacks the validator with invented quotes, wrong passages and
misattributed passages and asserts the findings die. `tests/test_api.py` covers the whole
product over HTTP: upload, extraction, investigation, every quotation verified against the
passage it cites, event ordering, graph integrity, keyword honesty, goal selection,
cross-account privacy, deletion, and all six parsers.

`tools/verify-ui.mjs` is deliberately real: it reads the published landing page and asserts it
makes no claim about where files live, checks the sign-in page arrives empty, registers a fresh
account, uploads `backend/samples/site_report.pdf` - five pages, so the walk has to cross a page
break - and confirms the document is read without anyone pressing a button. Then it measures
that the spider stands inside the text column, that a silk strand actually fires, that it hangs
from a thread, that eight two-segment legs change geometry between frames, that pause freezes
and resume continues, that the lines it read stay painted in several tones, that a term paints
all its occurrences, that answers are quoted from the document, that the web and the ink theme
render, and that an Arabic upload reads right-to-left. Screenshots go to `frontend/tools/shots/`.
`tools/verify-hosted.mjs` repeats the essential path against `http://localhost:8000`, where the
API and the built interface share one origin - the thing a public host runs.

## Deployment

One image, one process: `Dockerfile` builds `frontend/dist`, installs the backend, and serves
both from `$PORT`, with the database and the uploads under `/data`. `railway.toml` points at it.

```bash
docker build -t spider-ai .
docker run -p 8000:8000 -v spider-data:/data spider-ai    # http://localhost:8000
```

Set `SPIDER_SECRET_KEY` (`python -c "import secrets;print(secrets.token_urlsafe(48))"`) before
letting anyone else sign in. **[DEPLOYING.md](DEPLOYING.md)** covers the hosted variables,
Postgres with `alembic upgrade head`, and what still needs work before the public.

---

## Known limitations

1. **The engine is rule-based.** It finds structure, terms, numbers, patterns and internal
   contradictions and explains them; it does not understand a document like a person does.
2. **No dictionary spellchecker.** Spelling findings come from built-in typo/confusable/variant
   lists and inconsistency inside the document itself.
3. **Sentence-level PDF highlighting is interpolated.** The file gives line boxes; the x-extent
   inside a line is proportional to character count, not measured per glyph.
4. **Non-PDF formats have no page numbers.** Positioning is `dom_element`, stated in the UI.
5. **OCR is a hook, not a working path.** Scanned pages are reported, never guessed. Enabling
   it means installing an OCR engine and wiring it into `app/parsing/pdf.py`.
6. **Arabic and Somali writing rules are narrower than English** - morphology-aware checking is
   out of scope; structure, information, keywords, flow and consistency all work.
7. **Polled, not streamed**, and the crawl is a replay of a finished run (local analysis takes
   well under a second, so a live feed would be a blur).
8. **Two worker threads, not a queue** - fine on one machine, not on a server.
9. **The teacher-review API is still in the backend** (endpoints plus tests) while the interface
   no longer offers any of it. Say the word and it, and those tables, get deleted.
10. **Mobile is functional, not signature-grade**: panels stack, the spider keeps its landing
    spots, text stays readable.

## Repository layout

```
Dockerfile  railway.toml  DEPLOYING.md  start.bat
backend/
  app/  api/ analysis/ ai/ core/ parsing/ alembic/  models.py  services.py  worker.py
  samples/  storage/  tests/  tools/ (make_site_report.py, cleanup_probe_runs.py, seed_demo.py)
frontend/
  src/
    spider/    geometry (IK), walker (web-shot + swing + gait), SpiderOverlay (SVG)
    lib/       api client, types, SurfaceMeasure (passage -> screen coordinates), useCrawl
    components/ CrawlStage, DocumentSurface, FindingsStrip, FindingCard, SpiderNetwork,
               SpiderMark, SpiderIllustration
    views/     LandingView, AuthView, InvestigationWorkspace
    styles/    base (Ink & Paper tokens), landing (page + sign-in), workspace, spider, network
  tools/       verify-ui.mjs, verify-hosted.mjs, probe-landing.mjs, shots/
```
