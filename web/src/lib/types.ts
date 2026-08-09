/** Wire types — mirrors the FastAPI payloads (dicts from the domain layer). */

export interface Links {
  portal?: string;
  archive?: string;
}

export interface Conflict {
  draft: string;
  draft_idx?: number;
  candidate: string;
  meta: {
    gr_code?: string;
    department?: string;
    date?: string;
    gr_number?: string;
    subject?: string;
    distance?: number;
  };
  reason: string;
  explanation: string;
  value1?: string;
  value2?: string;
  benefit?: string;
  links?: Links | null;
}

export interface ReviewResult {
  error?: string;
  n_clauses?: number;
  n_pairs?: number;
  n_muril_flagged?: number | null;
  conflicts?: Conflict[];
  verdicts?: Array<{ label: string; reason: string }>;
}

export interface Score {
  pct: number;
  score: number;
  max_score: number;
  checks: Array<{ id?: string; desc: string; weight: number; passed: boolean }>;
}

export interface Terms {
  primary_lang: "mr" | "en";
  n_flags: number;
  flags: Array<{
    kind: string;
    found: string;
    approved_mr: string;
    approved_en: string;
    context: string;
    note?: string;
  }>;
}

export interface Refs {
  n_citations: number;
  linked: Array<{
    cited: string;
    via: string;
    match: { gr_code?: string; department?: string; date?: string; subject?: string };
    links?: Links | null;
  }>;
  stale: Array<{ cited: string; superseded_by: string; successor_subject?: string }>;
  newer_related: Array<{
    cited_date: string;
    newer: Array<{ gr_code: string; date: string; subject: string }>;
  }>;
  unknown: string[];
}

export interface FullReview {
  score: Score;
  terms: Terms;
  refs?: Refs;
  review: ReviewResult;
  max_distance?: number;
  audit_ts?: string;
  audit_error?: string;
}

export interface Precedent {
  gr_code: string;
  date_iso?: string;
  distance: number;
  subject?: string;
  links?: Links | null;
}

export interface GRForm {
  lang?: string;
  subject?: string;
  department?: string;
  dept_code?: string;
  gr_number?: string;
  date?: string;
  references?: Array<{ text: string }>;
  background?: string;
  clauses?: string[];
  budget_head?: string;
  signatory?: string;
  designation?: string;
  precedents?: Precedent[];
  topic?: string;
  code?: string;
  ai_used?: boolean;
  ai_error?: string | null;
  copy_to?: string[];
}

export interface Generated {
  draft: string;
  form?: GRForm;
  audit?: { ok: boolean; invented: string[]; dropped: string[] };
  ai_used?: boolean;
  ai_error?: string | null;
  score: Score;
  terms: Terms;
  short_clauses: string[];
}

export interface Health {
  status: "warming" | "ready" | "degraded";
  llm_mode: string;
  muril_on: boolean;
  models: Record<string, string>;
  warm?: Record<string, unknown>;
  corpus?: { n_grs: number; n_clauses: number; index_mismatch?: string | null };
}
