import { useEffect, useMemo, useRef, useState } from "react";
import SpiderIllustration from "../components/SpiderIllustration";
import SpiderMark from "../components/SpiderMark";
import "../styles/landing.css";

/* ===========================================================================
   LandingView - the public page.

   Scholarly and quiet: what the tool reads, what it reports, and the four
   things it refuses to do. No claims about where files live, no counts, no
   invented statistics - anything published here has to stay true on any
   machine.
   ========================================================================= */

interface Props {
  onEnter: () => void;
}

const REPORTS: { title: string; body: string; tone: string }[] = [
  {
    tone: "topic",
    title: "Subject and structure",
    body: "What the document is about, what it sets out to do, and how the argument is organised from opening to close.",
  },
  {
    tone: "figure",
    title: "Facts and figures",
    body: "Dates, names, definitions, quantities, decisions and action items, each returned with the sentence it was taken from.",
  },
  {
    tone: "keyword",
    title: "The vocabulary of the text",
    body: "The terms the document leans on, where they appear, and how they are distributed across the whole work.",
  },
  {
    tone: "writing",
    title: "Language and clarity",
    body: "Grammar, spelling, repetition, readability and tone - the passages where the writing gets in the reader's way.",
  },
  {
    tone: "logic",
    title: "Claims and reasoning",
    body: "Statements that carry no support inside the document, positions that contradict one another, and conclusions that may reach further than their evidence.",
  },
  {
    tone: "strength",
    title: "Revisions to consider",
    body: "Suggestions tied to a specific passage, which you can accept, set aside, or rewrite in your own words.",
  },
];

const PRINCIPLES: { title: string; body: string }[] = [
  {
    title: "Nothing without a quotation",
    body: "Every result has to be found again in the text it cites. A statement that cannot be located is discarded rather than shown.",
  },
  {
    title: "Absence is not proof",
    body: "When support for a claim is missing from the document, that is reported as a gap in the document - never as a verdict on whether the claim is true.",
  },
  {
    title: "No judgement about the author",
    body: "Style alone is not evidence. SPIDER AI comments on the writing that is on the page, not on the person who wrote it.",
  },
  {
    title: "Reading shown as reading",
    body: "The order of the walk, the passages examined and the results that were set aside are all part of the record, so the work can be checked rather than trusted.",
  },
];

type Focus = "subject" | "figures" | "language" | "reasoning";

const SAMPLE: { text: string; cat: Focus | null }[] = [
  { text: "Status note - phase two", cat: null },
  { text: "This report describes the second stage of the pilot and what changed after the first review.", cat: "subject" },
  { text: "Enrolment rose from 180 to 640 users between March and June.", cat: "figures" },
  { text: "The budget was revised twice and the final figure is not stated.", cat: "reasoning" },
  { text: "Onboarding is smooth. Onboarding works well. Onboarding is simple for new users.", cat: "language" },
  { text: "The team recommends a wider release in the next quarter.", cat: "subject" },
];

const FILTERS: { id: Focus; label: string; tone: string }[] = [
  { id: "subject", label: "Subject", tone: "topic" },
  { id: "figures", label: "Figures", tone: "figure" },
  { id: "language", label: "Language", tone: "writing" },
  { id: "reasoning", label: "Reasoning", tone: "logic" },
];

/** Fade each block in the first time it is scrolled into view. */
function useReveal() {
  const seen = useRef(0);
  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>(".reveal"));
    if (!nodes.length) return;
    const show = (node: Element) => node.classList.add("is-in");
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const delay = Math.min(160, (seen.current % 3) * 70);
          seen.current += 1;
          window.setTimeout(() => show(entry.target), delay);
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -40px" },
    );
    nodes.forEach((node) => observer.observe(node));
    // nothing may ever stay hidden because a reveal was missed
    const failsafe = window.setTimeout(() => nodes.forEach(show), 2600);
    return () => {
      window.clearTimeout(failsafe);
      observer.disconnect();
    };
  }, []);
}

export default function LandingView({ onEnter }: Props) {
  const [focus, setFocus] = useState<Focus>("subject");
  useReveal();

  const painted = useMemo(() => SAMPLE.filter((line) => line.cat === focus).length, [focus]);

  return (
    <div className="landing">
      <header className="lp-nav">
        <div className="lp-inner lp-nav__row">
          <span className="lp-brand">
            <span className="lp-brand__mark">
              <SpiderMark size={26} />
            </span>
            SPIDER <b>AI</b>
          </span>
          <nav className="lp-nav__links" aria-label="Page sections">
            <a href="#reports">What it reports</a>
            <a href="#principles">Principles</a>
            <a href="https://github.com/maryanjimale959-lab" target="_blank" rel="noreferrer">
              Source
            </a>
          </nav>
          <button className="btn primary" type="button" onClick={onEnter}>
            Enter the workspace
          </button>
        </div>
      </header>

      <main>
        <section className="lp-hero" aria-labelledby="lp-title">
          <div className="lp-inner lp-hero__grid">
            <div className="lp-hero__copy">
              <p className="lp-eyebrow">Document investigation</p>
              <h1 className="lp-title" id="lp-title">
                The spider walks your document<span className="lp-title__soft"> and tells you what it found</span>
              </h1>
              <p className="lp-lede">
                SPIDER AI reads a document the way a careful reviewer would: from the opening line to the last one,
                noticing its subject, its figures, its vocabulary, its language and the strength of its reasoning.
                Every result comes back with the exact passage it was taken from, and the spider shows you where it
                stood while it read.
              </p>
              <div className="lp-actions">
                <button className="btn primary lg" type="button" onClick={onEnter}>
                  Enter the workspace
                </button>
                <a className="btn ghost lg" href="#reports">
                  What it reports
                </a>
              </div>
              <p className="lp-formats">
                Written for PDF, Word, plain text, Markdown, HTML and spreadsheets - in English, Arabic and Somali.
              </p>
            </div>

            <figure className="lp-specimen">
              <div className="lp-specimen__page">
                <SpiderIllustration size={190} />
                <div className="lp-lines">
                  {SAMPLE.map((line, index) => (
                    <p
                      key={`${line.text}-${index}`}
                      className={`lp-line${line.cat === focus ? ` is-lit tone-${line.cat}` : ""}${line.cat === null ? " is-heading" : ""}`}
                      style={{ animationDelay: `${index * 45}ms` }}
                    >
                      {line.text}
                    </p>
                  ))}
                </div>
              </div>
              <figcaption className="lp-specimen__foot">
                <div className="lp-filters" role="group" aria-label="Choose what to look for">
                  {FILTERS.map((filter) => (
                    <button
                      key={filter.id}
                      type="button"
                      className={`lp-filter tone-${filter.tone}${focus === filter.id ? " is-on" : ""}`}
                      onClick={() => setFocus(filter.id)}
                      aria-pressed={focus === filter.id}
                    >
                      {filter.label}
                    </button>
                  ))}
                </div>
                <span className="lp-specimen__note">
                  Illustrative excerpt - {painted} line{painted === 1 ? "" : "s"} marked
                </span>
              </figcaption>
            </figure>
          </div>
        </section>

        <section className="lp-band" id="reports" aria-labelledby="lp-reports-title">
          <div className="lp-inner">
            <header className="lp-head reveal">
              <h2 className="lp-h2" id="lp-reports-title">
                What it reports
              </h2>
              <p className="lp-sub">
                Six readings of the same text, each returned as a quotation from the document rather than a summary of
                it.
              </p>
            </header>
            <div className="lp-reports">
              {REPORTS.map((report) => (
                <article className={`lp-report tone-${report.tone} reveal`} key={report.title}>
                  <span className="lp-report__rule" aria-hidden="true" />
                  <h3>{report.title}</h3>
                  <p>{report.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-band lp-band--quiet" id="principles" aria-labelledby="lp-principles-title">
          <div className="lp-inner lp-principles">
            <header className="lp-head lp-head--side reveal">
              <h2 className="lp-h2" id="lp-principles-title">
                Four things it will not do
              </h2>
              <p className="lp-sub">
                A reading tool is only useful if its results can be checked. These rules are built into the engine, not
                written on top of it.
              </p>
            </header>
            <ol className="lp-principle-list">
              {PRINCIPLES.map((principle, index) => (
                <li className="lp-principle reveal" key={principle.title}>
                  <span className="lp-principle__num">{index + 1}</span>
                  <div>
                    <h3>{principle.title}</h3>
                    <p>{principle.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>
      </main>

      <footer className="lp-foot">
        <div className="lp-inner lp-foot__row">
          <div>
            <p className="lp-foot__name">Built by Mariam Xasan Jimcaale</p>
            <p className="lp-foot__text">Design, research and engineering.</p>
          </div>
          <a className="lp-foot__link" href="https://github.com/maryanjimale959-lab" target="_blank" rel="noreferrer">
            github.com/maryanjimale959-lab
          </a>
        </div>
      </footer>
    </div>
  );
}
