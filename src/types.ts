export type Profile = "research" | "survey" | "theory";
export interface VenueRequest {
  name: string;
  website: string;
  track: string;
}
export interface VenueSource {
  url: string;
  title: string;
  retrieved_at: string;
  sha256: string;
  passages: string[];
}
export interface VenueContext extends VenueRequest {
  sources: VenueSource[];
  warnings: string[];
}
export interface Section {
  id: string;
  title: string;
  role: string;
  page_start: number;
  page_end: number;
  text: string;
  word_count: number;
}
export interface Paper {
  title: string;
  filename: string;
  pages: number;
  word_count: number;
  sha256: string;
  sections: Section[];
  warnings: string[];
}
export interface Dimension {
  key: string;
  label: string;
  score: number;
  confidence: number;
  weight: number;
  probabilities: Record<string, number>;
  finding: string;
  suggestion: string;
}
export interface SectionResult {
  section_id: string;
  score: number;
  confidence: number;
  dimensions: Dimension[];
  excerpt: string;
  chunk_count: number;
  latency_ms: number;
  model: string;
}
export interface Summary {
  score: number | null;
  confidence: number | null;
  decision: string;
  complete: boolean;
  reviewed: number;
  total: number;
  dimensions: Record<string, number>;
  section_weights: Record<string, number>;
  strengths: string[];
  improvements: string[];
  notes: string[];
}
export interface Report {
  review_id: string;
  created_at: string;
  paper: Paper;
  results: SectionResult[];
  summary: Summary;
  rubric_version: string;
  profile: Profile;
  elapsed_ms: number;
  input_tokens: number;
  output_tokens: number;
  venue?: VenueContext | null;
}
export interface ReviewState {
  status:
    "idle" | "uploading" | "reviewing" | "complete" | "error" | "cancelled";
  filename?: string;
  paper?: Paper;
  results: SectionResult[];
  summary?: Summary;
  active: string[];
  message: string;
  report?: Report;
  error?: string;
  venue?: VenueContext | null;
}
export type StreamEvent =
  | { type: "status" | "heartbeat"; message: string }
  | {
      type: "paper";
      paper: Paper;
      review_id: string;
      created_at: string;
      profile: Profile;
      rubric_version: string;
      venue?: VenueContext | null;
    }
  | { type: "section_start"; section_id: string }
  | { type: "venue"; venue: VenueContext }
  | { type: "section_result"; result: SectionResult; summary: Summary }
  | { type: "complete"; report: Report }
  | { type: "error"; message: string };
export interface Rubric {
  version: string;
  dimensions: Record<
    string,
    {
      label: string;
      weight: number;
      question: string;
      criteria: string[];
      suggestion: string;
    }
  >;
  role_weights: Record<string, number>;
  purposes: Record<string, string>;
  thresholds: { minimum: number; label: string }[];
  confidence_floor: number;
  venue_dimensions?: Rubric["dimensions"];
}
