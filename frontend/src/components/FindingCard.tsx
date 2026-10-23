import type { EvidenceItem, Finding, Passage } from "../lib/types";
import { KIND_LABEL } from "../lib/types";

interface Props {
  finding: Finding;
  selected: boolean;
  passagesById: Map<string, Passage>;
  onSelect: (finding: Finding) => void;
  onNavigate: (passageId: string) => void;
  onJumpToPassage?: (passageId: string) => void;
  commentSlot?: React.ReactNode;
  actions?: React.ReactNode;
}

const GROUP_TONE: Record<string, string> = {
  writing: "amber",
  logic: "rose",
  information: "cyan",
  understanding: "violet",
  keywords: "violet",
  advice: "green",
};

function toneFor(finding: Finding): string {
  if (finding.kind === "strength") return "green";
  if (finding.severity === "major") return "rose";
  if (finding.severity === "minor") return "amber";
  return GROUP_TONE[finding.kind.startsWith("keyword") ? "keywords" : "information"] ?? "cyan";
}

function locate(evidence: EvidenceItem, passagesById: Props["passagesById"]): string {
  const passage = passagesById.get(evidence.passage_id);
  const page = passage?.page_number;
  const prefix = page ? `page ${page}` : passage?.kind ?? "passage";
  const where = evidence.char_start != null ? ` - characters ${evidence.char_start}-${evidence.char_end}` : "";
  return `${prefix}${where} - quotation verified ${evidence.validation === "verbatim" ? "verbatim" : "with normalization"}`;
}

export default function FindingCard({
  finding, selected, passagesById, onSelect, onNavigate, commentSlot, actions,
}: Props) {
  const tone = toneFor(finding);
  return (
    <div
      className={`finding-item sev-${finding.severity} tone-${tone}${selected ? " is-selected" : ""}`}
      onClick={() => onSelect(finding)}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter") onSelect(finding);
      }}
    >
      <div className="kindline">
        <span className={`severity-dot ${finding.severity}`} />
        <span className="kind">{KIND_LABEL[finding.kind] ?? finding.kind}</span>
      </div>
      <div className="title">{finding.title}</div>
      {finding.body && <p className="body">{finding.body}</p>}
      {finding.category && finding.kind === "writing_issue" && (
        <p className="tiny mono muted">category: {finding.category.replace(/_/g, " ")}</p>
      )}
      {finding.suggestion && (
        <div className="suggestion">
          <span className="tiny muted" style={{ letterSpacing: "0.12em", textTransform: "uppercase" }}>
            Suggestion
          </span>
          <div>{finding.suggestion}</div>
        </div>
      )}
      {finding.evidence.length > 0 && (
        <div className="evidence-block">
          {finding.evidence.slice(0, 3).map((evidence) => (
            <div key={evidence.id}>
              <div
                className="quote"
                dir="auto"
                onClick={(event) => {
                  event.stopPropagation();
                  onNavigate(evidence.passage_id);
                }}
              >
                &ldquo;{evidence.quote}&rdquo;
              </div>
              <div className="loc">{locate(evidence, passagesById)}</div>
              {evidence.note && <div className="loc">{evidence.note}</div>}
            </div>
          ))}
          {finding.evidence.length > 3 && (
            <div className="loc tiny">+{finding.evidence.length - 3} more cited passages</div>
          )}
        </div>
      )}
      {actions}
      {commentSlot}
    </div>
  );
}
