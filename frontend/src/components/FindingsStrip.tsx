import { useState } from "react";
import type { Finding, Keyword, QuestionAnswer, Recommendation } from "../lib/types";
import { FINDING_GROUP, KIND_LABEL } from "../lib/types";

/* ===========================================================================
   FindingsStrip

   Results live along the bottom, the way a reader actually wants them: a count,
   a few category filters, and a scrollable list of what was found. Clicking a row
   takes the spider to that line and opens the detail above the strip - the document
   keeps the whole screen.
   ========================================================================= */

export type Category = "findings" | "keywords" | "advice" | "ask";

interface Props {
  title: string;
  findings: Finding[];
  keywords: Keyword[];
  recommendations: Recommendation[];
  totalFindings: number;
  category: Category;
  onCategory: (next: Category) => void;
  selectedFindingId: string | null;
  selectedKeywordId: string | null;
  onSelectFinding: (finding: Finding) => void;
  onSelectKeyword: (keyword: Keyword) => void;
  onClearFinding: () => void;
  onClearKeyword: () => void;
  onGoTo: (passageId: string) => void;
  onDecide: (recommendation: Recommendation, status: "accepted" | "dismissed" | "edited") => void;
  askingDisabled: boolean;
  onAsk: (question: string) => Promise<QuestionAnswer | null>;
  history: QuestionAnswer[];
  aiNote: string;
  live: boolean;
}

const GROUP_LABEL: Record<string, string> = {
  understanding: "Understanding", information: "Facts", keywords: "Concepts", writing: "Writing",
  logic: "Logic", advice: "Advice",
};

function groupOf(finding: Finding): string {
  return FINDING_GROUP[finding.kind] ?? "understanding";
}

export default function FindingsStrip({
  title, findings, keywords, recommendations, totalFindings, category, onCategory, selectedFindingId,
  selectedKeywordId, onSelectFinding, onSelectKeyword, onClearFinding, onClearKeyword, onGoTo, onDecide,
  askingDisabled, onAsk, history, aiNote, live,
}: Props) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<QuestionAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [group, setGroup] = useState<string>("all");

  const selectedFinding = findings.find((finding) => finding.id === selectedFindingId) ?? null;
  const selectedKeyword = keywords.find((keyword) => keyword.id === selectedKeywordId) ?? null;
  const shownFindings = group === "all" ? findings : findings.filter((finding) => groupOf(finding) === group);
  const groups = Object.keys(GROUP_LABEL).filter((key) => findings.some((finding) => groupOf(finding) === key));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim() || askingDisabled) return;
    setAsking(true);
    setAskError(null);
    try {
      const result = await onAsk(question.trim());
      if (result) {
        // an answer takes over the detail panel, so drop whatever was selected
        setAnswer(result);
        setQuestion("");
        onClearFinding();
        onClearKeyword();
      }
    } catch (error) {
      setAskError(error instanceof Error ? error.message : "The question could not be answered");
    } finally {
      setAsking(false);
    }
  }

  const detail = selectedFinding ?? selectedKeyword ?? answer;

  return (
    <div className="results">
      {detail && (
        <section className="detail" aria-live="polite">
          {selectedFinding && (
            <>
              <div className="detail-head">
                <span className={`tone-dot tone-${selectedFinding.severity}`} />
                <h3>{selectedFinding.title}</h3>
                <span className="chip">{KIND_LABEL[selectedFinding.kind] ?? selectedFinding.kind}</span>
                <span className="grow" />
                <button className="btn sm ghost" onClick={onClearFinding}>Close</button>
              </div>
              <p className="detail-body">{selectedFinding.body}</p>
              {selectedFinding.suggestion && (
                <p className="detail-suggestion"><span className="label">Suggestion</span>{selectedFinding.suggestion}</p>
              )}
              {selectedFinding.evidence.map((evidence) => (
                <button
                  key={evidence.id}
                  className="quote"
                  onClick={() => onGoTo(evidence.passage_id)}
                  title="Take the spider to this line"
                >
                  <span className="quote-text" dir="auto">&ldquo;{evidence.quote}&rdquo;</span>
                  <span className="quote-loc">
                    {evidence.validation === "verbatim" ? "quoted from the passage" : "matched with normalisation"}
                    {evidence.char_start != null ? ` - characters ${evidence.char_start}-${evidence.char_end}` : ""}
                  </span>
                </button>
              ))}
            </>
          )}

          {selectedKeyword && !selectedFinding && (
            <>
              <div className="detail-head">
                <h3>{selectedKeyword.term}</h3>
                <span className="chip accent">{selectedKeyword.category}</span>
                <span className="chip">{selectedKeyword.occurrences} occurrences</span>
                <span className="grow" />
                <button className="btn sm ghost" onClick={onClearKeyword}>Close</button>
              </div>
              {selectedKeyword.explanation && <p className="detail-body">{selectedKeyword.explanation}</p>}
              <p className="tiny muted">
                {selectedKeyword.in_document
                  ? "This term appears in the document. The painted lines show every occurrence."
                  : "Suggested related concept - it does not appear in the document."}
              </p>
            </>
          )}

          {answer && !selectedFinding && !selectedKeyword && (
            <>
              <div className="detail-head">
                <h3>{answer.question}</h3>
                <span className={`chip ${answer.grounded ? "accent" : ""}`}>
                  {answer.grounded ? "answered from the document" : "the document does not answer this"}
                </span>
                <span className="grow" />
                <button className="btn sm ghost" onClick={() => setAnswer(null)}>Close</button>
              </div>
              <p className="detail-body">{answer.answer}</p>
              {answer.limitation && <p className="notice warn">{answer.limitation}</p>}
              {answer.citations_detail.map((citation, index) => (
                <button key={`${citation.passage_id}-${index}`} className="quote" onClick={() => onGoTo(citation.passage_id)}>
                  <span className="quote-text" dir="auto">&ldquo;{citation.quote}&rdquo;</span>
                  <span className="quote-loc">{citation.page_number ? `page ${citation.page_number}` : "passage"}</span>
                </button>
              ))}
            </>
          )}
        </section>
      )}

      <footer className="strip">
        <div className="strip-bar">
          <span className="strip-title">{live ? "Found so far" : "Found"}</span>
          <span className="strip-doc" title={title}>{title}</span>

          <div className="strip-cats" role="tablist">
            {(["findings", "keywords", "advice", "ask"] as Category[]).map((key) => (
              <button
                key={key}
                role="tab"
                aria-selected={category === key}
                className={`strip-cat${category === key ? " is-active" : ""}`}
                onClick={() => onCategory(key)}
              >
                {key === "findings" ? `Findings ${findings.length}` : key === "keywords" ? `Vocabulary ${keywords.length}`
                  : key === "advice" ? `Revisions ${recommendations.length}` : "Ask a question"}
              </button>
            ))}
          </div>

          <span className="strip-count">
            {category === "findings" && `${shownFindings.length} of ${totalFindings} shown`}
            {category === "keywords" && `${keywords.length} terms`}
            {category === "advice" && `${recommendations.length} suggestions`}
            {category === "ask" && "grounded answers"}
          </span>
        </div>

        {category === "findings" && (
          <>
            <div className="strip-groups">
              <button className={`chip clickable${group === "all" ? " accent" : ""}`} onClick={() => setGroup("all")}>
                All {findings.length}
              </button>
              {groups.map((key) => (
                <button
                  key={key}
                  className={`chip clickable${group === key ? " accent" : ""}`}
                  onClick={() => setGroup(key)}
                >
                  {GROUP_LABEL[key]} {findings.filter((finding) => groupOf(finding) === key).length}
                </button>
              ))}
            </div>
            <div className="strip-rows">
              {shownFindings.length === 0 && <p className="strip-empty">Nothing here yet - the spider is still reading.</p>}
              {shownFindings.map((finding) => (
                <button
                  key={finding.id}
                  className={`strip-row${finding.id === selectedFindingId ? " is-active" : ""}`}
                  onClick={() => onSelectFinding(finding)}
                >
                  <span className={`tone-dot tone-${finding.severity}`} />
                  <span className="row-main">{finding.title}</span>
                  <span className="row-tag">{KIND_LABEL[finding.kind] ?? finding.kind}</span>
                </button>
              ))}
            </div>
          </>
        )}

        {category === "keywords" && (
          <div className="strip-rows">
            {keywords.length === 0 && <p className="strip-empty">Keywords appear once that pass has run.</p>}
            {keywords.map((keyword) => (
              <button
                key={keyword.id}
                className={`strip-row${keyword.id === selectedKeywordId ? " is-active" : ""}`}
                onClick={() => onSelectKeyword(keyword)}
              >
                <span className="row-main">{keyword.term}</span>
                <span className="row-tag">{keyword.occurrences}x - {keyword.category}</span>
              </button>
            ))}
          </div>
        )}

        {category === "advice" && (
          <div className="strip-rows">
            {recommendations.length === 0 && <p className="strip-empty">Recommendations are written after the findings are validated.</p>}
            {recommendations.map((recommendation) => (
              <div key={recommendation.id} className={`strip-row is-static${recommendation.status !== "pending" ? " is-decided" : ""}`}>
                <span className="row-main">{recommendation.rationale}</span>
                <span className="row-actions">
                  <button className="btn sm" onClick={() => onDecide(recommendation, "accepted")} disabled={recommendation.status === "accepted"}>
                    Accept
                  </button>
                  <button className="btn sm ghost" onClick={() => onDecide(recommendation, "dismissed")} disabled={recommendation.status === "dismissed"}>
                    Dismiss
                  </button>
                  {recommendation.passage_id && (
                    <button className="btn sm ghost" onClick={() => onGoTo(recommendation.passage_id!)}>Show line</button>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}

        {category === "ask" && (
          <form className="strip-ask" onSubmit={submit}>
            <input
              className="input"
              placeholder="Ask this document something, using words that appear in it"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={askingDisabled}
            />
            <button className="btn primary" type="submit" disabled={askingDisabled || asking || !question.trim()}>
              {asking ? "Searching" : "Ask"}
            </button>
            {askError && <span className="error-text">{askError}</span>}
            {history.slice(0, 3).map((item) => (
              <button key={item.id} type="button" className="chip clickable" onClick={() => setAnswer(item)}>
                {item.question.slice(0, 44)}
              </button>
            ))}
            <span className="tiny muted strip-note">{aiNote}</span>
          </form>
        )}
      </footer>
    </div>
  );
}
