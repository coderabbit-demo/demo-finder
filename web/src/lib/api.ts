const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

export const api = {
  health: () => req<{ ok: boolean; dev_mode: boolean; github: boolean; llm: boolean }>("/health"),
  useCases: () => req<UseCase[]>("/use-cases"),
  createUseCase: (prompt: string) =>
    req("/use-cases/from-prompt", { method: "POST", body: JSON.stringify({ prompt }) }),
  candidates: (useCase?: string, minScore = 0) =>
    req<Scored[]>(`/candidates?min_score=${minScore}` + (useCase ? `&use_case=${useCase}` : "")),
  crawl: () => req("/crawl", { method: "POST" }),
  crawlStatus: () => req<CrawlStatus>("/crawl/status"),
  candidateDetail: (id: number) => req<CandidateDetail>(`/candidates/${id}`),
  exportCandidate: (id: number, useCase: string) =>
    req<ExportOut>(`/candidates/${id}/export?use_case=${useCase}`),
  search: (query: string) =>
    req<SearchOut>("/search", { method: "POST", body: JSON.stringify({ query }) }),
  suggestFork: (use_case_slug: string, extra_context = "", config_kind = "yaml") =>
    req<ForkSuggestion>("/fork-suggestions", {
      method: "POST",
      body: JSON.stringify({ use_case_slug, extra_context, config_kind }),
    }),
  executeFork: (id: number) =>
    req<{ fork_url: string; pr_url: string }>(`/fork-suggestions/${id}/execute`, { method: "POST" }),
  orgs: () => req<Org[]>("/sources/orgs"),
  toggleOrg: (id: number, included: boolean) =>
    req(`/sources/orgs/${id}?included=${included}`, { method: "PATCH" }),
  toggleRepo: (id: number, included: boolean) =>
    req(`/sources/repos/${id}?included=${included}`, { method: "PATCH" }),
  addOrg: (org_name: string, connection_type: string, repos: string[]) =>
    req("/sources/orgs", { method: "POST", body: JSON.stringify({ org_name, connection_type, repos }) }),
  deleteOrg: (id: number) => req(`/sources/orgs/${id}`, { method: "DELETE" }),
  flag: (candidate_id: number, use_case_slug: string) =>
    req<{ flagged: boolean }>("/examples", {
      method: "POST", body: JSON.stringify({ candidate_id, use_case_slug }),
    }),
  examples: (useCase?: string) =>
    req<FlaggedExample[]>("/examples" + (useCase ? `?use_case=${useCase}` : "")),
};

export interface UseCase {
  id: number; slug: string; name: string; category: string; is_custom: boolean;
  demo_script_notes: string; good_candidates: number; flagged_count: number;
  definition: string; doc_url: string;
  required_config: Record<string, unknown>;
}
export interface CrawlStatus {
  phase: string; repos_done: number; repos_total: number;
  discovered: number; backfilled: number; error: string | null; finished_at: string | null;
}
export interface CandidateDetail {
  pr: { number: number; title: string; url: string; repo: string; files: string[];
        stats: Record<string, unknown> };
  findings: { key: string; label: string; comment_url: string; proves: string[] }[];
  scores: { use_case: string; use_case_name: string; score: number;
            scored_by: string; rationale: string }[];
}
export interface FlaggedExample {
  id: number; use_case: string; demo_notes: string; candidate_id: number;
  pr: { title: string; url: string; repo: string; number: number };
}
export interface Scored {
  flagged: boolean;
  candidate_id: number; score: number; rationale: string; scored_by: string; use_case: string;
  pr: { number: number; title: string; url: string; repo: string; files: string[];
        anchor_url?: string | null;
        stats: { additions?: number; deletions?: number; files?: number; ci_status?: string } };
}
export interface SearchOut {
  intent: Record<string, unknown>;
  results: { score: number; use_case: string; rationale: string;
             pr: { title: string; url: string; repo: string; number: number } }[];
  suggest_manufacture: boolean;
}
export interface ForkSuggestion {
  id: number; base_repo_full_name: string; rationale: string;
  suggested_changes: { path: string; description?: string; content: string }[];
  suggested_config: string; config_kind: string;
  alternatives?: { repo: string; score: number; why: string }[];
}
export interface ExportOut {
  url: string; repo: string; use_case: string; talk_track: string;
  config_needed: Record<string, unknown>; markdown: string;
}
export interface Org {
  id: number; org_name: string; provider: string; connection_type: string; included: boolean;
  repos: { id: number; full_name: string; included: boolean; languages: string[]; stars: number }[];
}
