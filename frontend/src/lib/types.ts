export type Role = "user" | "student" | "teacher" | "admin";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  institution?: string | null;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: User;
}

export interface DocumentSummary {
  id: string;
  title: string;
  owner_id: string;
  owner_name?: string | null;
  created_at: string;
  current_version_id?: string | null;
  file_format?: string | null;
  filename?: string | null;
  extraction_status?: string | null;
  language?: string | null;
  word_count?: number | null;
  page_count?: number | null;
  passage_count?: number | null;
}

export interface SourceLine {
  x: number;
  y: number;
  w: number;
  h: number;
  text: string;
}

export interface Passage {
  id: string;
  sort_index: number;
  kind: "title" | "heading" | "paragraph" | "list_item" | "table_row" | "caption";
  text: string;
  page_number?: number | null;
  bbox?: { x: number; y: number; w: number; h: number } | null;
  coordinate_source: "pdf_bbox" | "dom_element" | "container";
  section_id?: string | null;
  section_title?: string | null;
  char_start: number;
  char_end: number;
  words: number;
  source_lines?: SourceLine[];
}

export interface SectionNode {
  id: string;
  index: number;
  level: number;
  title: string;
  kind: string;
}

export interface PageDescriptor {
  number: number;
  width: number;
  height: number;
  image_scale: number;
  has_text: boolean;
  image_url: string;
}

export interface VersionContent {
  version_id: string;
  document_id: string;
  title: string;
  file_format: string;
  language: string;
  language_confidence: number;
  positioning_quality: string;
  extraction_status: string;
  extraction_error?: string | null;
  ocr_needed: boolean;
  word_count: number;
  page_count: number;
  page_geometry: { number: number; width: number; height: number; image_scale: number; has_text: boolean }[];
  notes: string[];
  sections: SectionNode[];
  passages: Passage[];
  pages: PageDescriptor[];
}

export interface EvidenceItem {
  id: string;
  passage_id: string;
  quote: string;
  char_start?: number | null;
  char_end?: number | null;
  validation: "verbatim" | "normalized";
  note?: string | null;
}

export type FindingKind =
  | "subject" | "purpose" | "central_idea" | "structure" | "argument" | "conclusion"
  | "fact" | "date" | "person" | "definition" | "statistic" | "decision" | "action_item" | "critical_statement"
  | "keyword_concept" | "writing_issue" | "logic_gap" | "unsupported_claim" | "contradiction"
  | "ambiguous_statement" | "overreaching_conclusion" | "strength" | "recommendation" | "clarifying_question";

export interface Finding {
  id: string;
  kind: FindingKind;
  category?: string | null;
  title: string;
  body: string;
  suggestion?: string | null;
  severity: "info" | "minor" | "major";
  confidence: number;
  primary_passage_id?: string | null;
  evidence: EvidenceItem[];
  extra?: Record<string, unknown> | null;
}

export interface Keyword {
  id: string;
  term: string;
  category: "primary" | "supporting" | "technical" | "concept" | "acronym" | "related";
  explanation?: string | null;
  occurrences: number;
  in_document: boolean;
  related_terms?: string[] | null;
  passage_ids?: string[] | null;
  score: number;
}

export interface Recommendation {
  id: string;
  finding_id?: string | null;
  passage_id?: string | null;
  kind: string;
  rationale: string;
  suggested_revision?: string | null;
  status: "pending" | "accepted" | "dismissed" | "edited";
  user_text?: string | null;
}

export interface GraphNodeData {
  id: string;
  node_type: string;
  label: string;
  ref_id?: string | null;
  passage_id?: string | null;
  weight: number;
  payload: Record<string, unknown> & { reveal_after?: number };
}

export interface GraphEdgeData {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relation: string;
  label?: string | null;
  strength: number;
}

export type CrawlStage = "arrival" | "exploration" | "investigation" | "discovery" | "connection" | "completion";

export interface CrawlEvent {
  seq: number;
  stage: CrawlStage;
  task: string;
  passage_id?: string | null;
  finding_ids: string[];
  keyword_ids: string[];
  node_ids?: string[];
  edge_ids?: string[];
  at: string;
  passage_kind?: string;
  checked?: number;
  kept?: number;
  rejected?: number;
  draft_kind?: string;
  category?: string | null;
}

export interface InvestigationMetrics {
  elapsed_seconds?: number;
  language?: string;
  language_confidence?: number;
  passages?: number;
  sentences?: number;
  words?: number;
  draft_findings?: number;
  validated_findings?: number;
  rejected_findings?: number;
  keywords?: number;
  recommendations?: number;
  events?: number;
  goals?: string[];
  resting_passage_id?: string | null;
  engine?: string;
  graph_counts?: { nodes: number; edges: number };
  positioning_quality?: string;
  ocr_needed?: boolean;
  rejected_evidence?: { finding: string; title: string; passage_id: string; reason: string }[];
}

export interface Investigation {
  id: string;
  version_id: string;
  status:
    | "queued" | "extracting" | "analyzing" | "validating" | "building_graph"
    | "completed" | "failed" | "cancelled";
  stage: string;
  detail: string;
  goals?: string[] | null;
  current_passage_id?: string | null;
  current_task?: string | null;
  error?: string | null;
  engine: string;
  started_at?: string | null;
  finished_at?: string | null;
  metrics: InvestigationMetrics | null;
}

export interface AiStatus {
  enabled: boolean;
  provider: string;
  model: string;
  local_engine: string;
  note: string;
}

export interface InvestigationResults {
  investigation: Investigation;
  findings: Finding[];
  keywords: Keyword[];
  recommendations: Recommendation[];
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
  events: CrawlEvent[];
  rejected_evidence: Record<string, unknown>[];
  ai: AiStatus;
}

export interface QuestionAnswer {
  id: string;
  question: string;
  answer: string;
  grounded: boolean;
  limitation?: string | null;
  citation_passage_ids?: string[] | null;
  citations_detail: {
    passage_id: string;
    quote: string;
    start?: number | null;
    end?: number | null;
    page_number?: number | null;
    relevance?: number;
  }[];
  engine: string;
  created_at: string;
}

export interface ReviewCommentData {
  id: string;
  text: string;
  passage_id?: string | null;
  finding_id?: string | null;
  recommendation_id?: string | null;
  include_with_student: boolean;
  created_at: string;
}

export interface TeacherReview {
  id: string;
  document_id: string;
  version_id: string;
  investigation_id?: string | null;
  teacher_id: string;
  teacher_name?: string | null;
  student_id: string;
  student_name?: string | null;
  document_title: string;
  status: "draft" | "finalized" | "shared";
  overall_note: string;
  rubric_id?: string | null;
  rubric_responses?: Record<string, string> | null;
  finalized_at?: string | null;
  shared_at?: string | null;
  share_url?: string | null;
  report_url?: string | null;
  comments: ReviewCommentData[];
}

export interface InboxItem {
  document_id: string;
  title: string;
  student_name: string;
  student_email: string;
  scope: string;
  granted_note?: string | null;
  version_id?: string | null;
  extraction_status?: string | null;
  language: string;
  word_count: number;
  page_count: number;
  investigation_id?: string | null;
  investigation_status: string;
  summary: { findings?: number | null; keywords?: number | null; language_engine?: string };
  review_id?: string | null;
  review_status?: string | null;
}

export interface Rubric {
  id: string;
  name: string;
  description?: string | null;
  criteria?: { id: string; label: string; descriptor: string }[] | null;
}

export const GOAL_LABELS: Record<string, string> = {
  understanding: "Document understanding",
  important_info: "Important information",
  keywords: "Keyword extraction",
  writing: "Writing investigation",
  logic_evidence: "Logic and evidence",
  recommendations: "Recommendations",
};

export const FINDING_GROUP: Record<string, "understanding" | "information" | "keywords" | "writing" | "logic" | "advice"> = {
  subject: "understanding",
  purpose: "understanding",
  central_idea: "understanding",
  structure: "understanding",
  argument: "understanding",
  conclusion: "understanding",
  strength: "understanding",
  fact: "information",
  date: "information",
  person: "information",
  definition: "information",
  statistic: "information",
  decision: "information",
  action_item: "information",
  critical_statement: "information",
  keyword_concept: "keywords",
  writing_issue: "writing",
  unsupported_claim: "logic",
  contradiction: "logic",
  logic_gap: "logic",
  ambiguous_statement: "logic",
  overreaching_conclusion: "logic",
  clarifying_question: "logic",
  recommendation: "advice",
};

export const KIND_LABEL: Record<string, string> = {
  subject: "Subject",
  purpose: "Purpose",
  central_idea: "Central idea",
  structure: "Structure",
  argument: "Argument",
  conclusion: "Conclusion",
  strength: "Strength",
  fact: "Fact",
  date: "Date",
  person: "Person or group",
  definition: "Definition",
  statistic: "Statistic",
  decision: "Decision",
  action_item: "Action item",
  critical_statement: "Critical statement",
  keyword_concept: "Key concept",
  writing_issue: "Writing",
  unsupported_claim: "Claim without in-document support",
  contradiction: "Possible contradiction",
  logic_gap: "Reasoning gap",
  ambiguous_statement: "Ambiguous statement",
  overreaching_conclusion: "Conclusion may exceed the evidence",
  clarifying_question: "Question to ask",
  recommendation: "Recommendation",
};
