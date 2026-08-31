import { useEffect, useRef, useState } from "react";
import { api, CandidateDetail, CrawlStatus, ExportOut, Scored, UseCase } from "../lib/api";

export default function Finder({ onManufacture, initialSlug, initialMin }:
  { onManufacture: (slug: string) => void; initialSlug?: string | null; initialMin?: number }) {
  const [useCases, setUseCases] = useState<UseCase[]>([]);
  const [slug, setSlug] = useState(initialSlug ?? "sequence-diagrams");
  const [minScore, setMinScore] = useState(initialMin ?? 60);
  useEffect(() => { if (initialSlug != null) setSlug(initialSlug); }, [initialSlug]);
  useEffect(() => { if (initialMin != null) setMinScore(initialMin); }, [initialMin]);
  // keep the URL in sync so the current view is always shareable (no history spam)
  useEffect(() => {
    history.replaceState(null, "", `#/finder?uc=${encodeURIComponent(slug)}&min=${minScore}`);
  }, [slug, minScore]);
  const [rows, setRows] = useState<Scored[]>([]);
  const [detail, setDetail] = useState<Scored | null>(null);
  const [drill, setDrill] = useState<CandidateDetail | null>(null);
  const openDetail = (r: Scored) => {
    setDetail(r);
    setDrill(null);
    api.candidateDetail(r.candidate_id).then(setDrill).catch(() => {});
  };
  const [exportOut, setExportOut] = useState<ExportOut | null>(null);
  const [crawl, setCrawl] = useState<CrawlStatus | null>(null);
  const [loadErr, setLoadErr] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = () =>
    api.candidates(slug || undefined, minScore).then(setRows).catch((e) => setLoadErr(String(e)));

  const startPolling = () => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      const s = await api.crawlStatus().catch(() => null);
      setCrawl(s);
      if (!s || s.phase === "done" || s.phase === "failed" || s.phase === "idle") {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        refresh();
        api.useCases().then(setUseCases);
      }
    }, 2000);
  };
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  useEffect(() => {
    api.useCases().then(setUseCases);
  }, []);
  useEffect(() => {
    setLoadErr("");
    api.candidates(slug || undefined, minScore)
      .then(setRows)
      .catch((e) => { setRows([]); setLoadErr(String(e)); });
  }, [slug, minScore]);

  const empties = useCases.filter((u) => u.good_candidates === 0).slice(0, 4);
  // rubric bands: >=85 verified · 70-84 strong · 50-69 usable · <50 weak
  const scoreColor = (s: number) => (s >= 85 ? "text-ok" : s >= 70 ? "text-info" : s >= 50 ? "text-warn" : "text-bad");
  const bandLabel = (s: number) => (s >= 85 ? "verified" : s >= 70 ? "strong" : s >= 50 ? "usable" : "weak");

  const doExport = async (r: Scored) => {
    const out = await api.exportCandidate(r.candidate_id, r.use_case);
    setExportOut(out);
    navigator.clipboard?.writeText(out.markdown).catch(() => {});
  };

  return (
    <div>
      <h1 className="text-lg font-bold">PR Finder</h1>
      <p className="mb-4 text-muted">Open PRs across your included repos, scored per use case.</p>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select value={slug} onChange={(e) => setSlug(e.target.value)}
          className="rounded-lg border border-borderc bg-panel2 px-3 py-2">
          <option value="">All use cases</option>
          {useCases.map((u) => (
            <option key={u.slug} value={u.slug}>{u.name}</option>
          ))}
        </select>
        <select value={minScore} onChange={(e) => setMinScore(Number(e.target.value))}
          className="rounded-lg border border-borderc bg-panel2 px-3 py-2">
          <option value={70}>Min score: 70</option>
          <option value={60}>Min score: 60</option>
          <option value={0}>Any score</option>
        </select>
        <button
          onClick={async () => { await api.crawl(); startPolling(); }}
          disabled={!!crawl && !["done", "failed", "idle"].includes(crawl.phase)}
          className="rounded-lg border border-borderc px-3 py-2 text-txt hover:border-accent disabled:opacity-50">
          ↻ Re-crawl
        </button>
      </div>

      {crawl && !["idle", "done", "failed"].includes(crawl.phase) && (
        <div className="mb-3 rounded-xl border border-blue-900 bg-[#1a2333] p-3 text-xs text-info">
          <span className="mr-2 inline-block animate-pulse">●</span>
          {crawl.phase}
          {crawl.repos_total > 0 && ` — repo ${crawl.repos_done}/${crawl.repos_total}`}
          {crawl.discovered > 0 && ` · ${crawl.discovered} discovered`}
          {crawl.backfilled > 0 && ` · ${crawl.backfilled} anchors backfilled`}
          {crawl.repos_total > 0 && (
            <div className="mt-2 h-1.5 overflow-hidden rounded bg-panel2">
              <div className="h-full bg-info transition-all"
                style={{ width: `${Math.round((100 * crawl.repos_done) / Math.max(1, crawl.repos_total))}%` }} />
            </div>
          )}
        </div>
      )}
      {crawl?.phase === "failed" && (
        <div className="mb-3 rounded-xl border border-red-900 bg-red-950/40 p-3 text-xs text-bad">
          Crawl failed: {crawl.error}
        </div>
      )}
      {crawl?.phase === "done" && (
        <div className="mb-3 rounded-xl border border-green-900 bg-green-950/30 p-3 text-xs text-ok">
          Crawl finished — {crawl.discovered} PRs discovered, {crawl.backfilled} anchors backfilled. Results refreshed.
        </div>
      )}

      {loadErr && (
        <div className="mb-3 rounded-xl border border-red-900 bg-red-950/40 p-3 text-xs text-bad">
          Failed to load candidates: {loadErr}
        </div>
      )}
      <div className="overflow-hidden rounded-xl border border-borderc bg-panel">
        <table className="w-full">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-muted">
              <th className="border-b border-borderc p-3">PR</th>
              <th className="border-b border-borderc p-3">Repo</th>
              <th className="border-b border-borderc p-3">Why</th>
              <th className="border-b border-borderc p-3">Score</th>
              <th className="border-b border-borderc p-3"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.candidate_id}-${r.use_case}`}
                className="cursor-pointer hover:bg-panel2" onClick={() => openDetail(r)}>
                <td className="border-b border-borderc p-3">
                  <a href={r.pr.anchor_url ?? r.pr.url} target="_blank" rel="noreferrer"
                    onClick={(e) => e.stopPropagation()} className="hover:text-accent">
                    <b>#{r.pr.number}</b> {r.pr.title}
                    {r.pr.anchor_url && <span title="links to the exact CodeRabbit comment"> 🎯</span>}
                  </a>
                  <div className="mt-1 text-[11px] text-muted">
                    {r.pr.stats.files} files · +{r.pr.stats.additions} −{r.pr.stats.deletions} · CI {r.pr.stats.ci_status}
                    {!slug && <span className="ml-2 text-info">{r.use_case}</span>}
                  </div>
                </td>
                <td className="border-b border-borderc p-3 font-mono text-xs">{r.pr.repo}</td>
                <td className="border-b border-borderc p-3 text-xs text-muted">{r.rationale}</td>
                <td className={`border-b border-borderc p-3 font-bold ${scoreColor(r.score)}`}>
                  {r.score}
                  <div className="text-[10px] font-normal opacity-70">{bandLabel(r.score)}</div>
                </td>
                <td className="border-b border-borderc p-3">
                  <div className="flex items-center gap-2">
                    <button title={r.flagged ? "Unflag" : "Flag as a keeper"}
                      onClick={async (e) => {
                        e.stopPropagation();
                        await api.flag(r.candidate_id, r.use_case);
                        api.candidates(slug || undefined, minScore).then(setRows);
                      }}
                      className={`text-lg ${r.flagged ? "text-warn" : "text-muted hover:text-warn"}`}>
                      {r.flagged ? "★" : "☆"}
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); doExport(r); }}
                      className="rounded-lg bg-accent px-3 py-1 text-xs font-semibold text-white">
                      Export
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={5} className="p-6 text-center text-muted">
                No candidates at this threshold — lower the score, re-crawl, or manufacture one.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {empties.length > 0 && (
        <div className="mt-4 rounded-xl border border-blue-900 bg-[#1a2333] p-3 text-info">
          💡 No good candidates yet for{" "}
          {empties.map((u, i) => (
            <span key={u.slug}>
              {i > 0 && ", "}
              <button className="underline hover:text-accent" onClick={() => onManufacture(u.slug)}>
                {u.name}
              </button>
            </span>
          ))}
          {" "}— manufacture one in Fork &amp; Configure.
        </div>
      )}

      {detail && (
        <Drawer onClose={() => setDetail(null)}>
          <h2 className="font-bold">#{detail.pr.number} {detail.pr.title}</h2>
          <div className="my-2 flex gap-2 text-xs">
            <span className="rounded-lg border border-borderc px-2 py-0.5 text-info">{detail.pr.repo}</span>
            <span className="rounded-lg border border-borderc px-2 py-0.5 text-ok">
              {detail.use_case} · {detail.score}
            </span>
            <span className="rounded-lg border border-borderc px-2 py-0.5 text-muted">
              scored by {detail.scored_by}
            </span>
          </div>
          <div className="mb-3 rounded-xl border border-borderc bg-panel2 p-3">
            <b>Why {detail.score}?</b>
            <div className="mt-1 text-xs text-muted">{detail.rationale}</div>
          </div>

          {drill && drill.findings.length > 0 && (
            <div className="mb-3 rounded-xl border border-green-900 bg-green-950/20 p-3">
              <b>Findings in CodeRabbit's review</b>
              <div className="mt-2 space-y-1.5">
                {drill.findings.map((f) => (
                  <div key={f.key} className="flex items-center gap-2 text-xs">
                    <span className="text-ok">✓</span>
                    <span className="capitalize">{f.label}</span>
                    {f.comment_url && (
                      <a href={f.comment_url} target="_blank" rel="noreferrer"
                        className="text-info hover:underline">view comment ↗</a>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {drill && drill.findings.length === 0 && (
            <div className="mb-3 rounded-xl border border-borderc bg-panel2 p-3 text-xs text-muted">
              No CodeRabbit review on this PR yet — score is predicted from PR shape,
              not verified findings.
            </div>
          )}

          {drill && drill.scores.length > 1 && (
            <div className="mb-3 rounded-xl border border-borderc bg-panel2 p-3">
              <b>Also demos</b>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {drill.scores.filter((s) => s.use_case !== detail.use_case && s.score >= 50)
                  .slice(0, 8).map((s) => (
                    <button key={s.use_case}
                      onClick={() => { setSlug(s.use_case); setDetail(null); setDrill(null); }}
                      className="rounded-lg border border-borderc px-2 py-0.5 text-[11px] text-muted hover:border-accent hover:text-txt">
                      {s.use_case_name} · <span className={s.score >= 85 ? "text-ok" : ""}>{s.score}</span>
                    </button>
                  ))}
              </div>
            </div>
          )}

          <div className="rounded-xl border border-borderc bg-panel2 p-3">
            <b>Files</b>
            <div className="mt-1 font-mono text-[11px] text-muted">
              {detail.pr.files.map((f) => <div key={f}>{f}</div>)}
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            {detail.pr.anchor_url && (
              <a href={detail.pr.anchor_url} target="_blank" rel="noreferrer"
                className="rounded-lg bg-accent px-4 py-2 font-semibold text-white">
                🎯 Jump to the exact comment ↗
              </a>
            )}
            <a href={detail.pr.url} target="_blank" rel="noreferrer"
              className={detail.pr.anchor_url
                ? "rounded-lg border border-borderc px-4 py-2 font-semibold"
                : "rounded-lg bg-accent px-4 py-2 font-semibold text-white"}>
              Open PR ↗
            </a>
          </div>
        </Drawer>
      )}

      {exportOut && (
        <Drawer onClose={() => setExportOut(null)}>
          <h2 className="font-bold">Demo export — copied to clipboard</h2>
          <pre className="mt-3 overflow-x-auto rounded-xl border border-borderc bg-[#0a0d12] p-3 text-xs leading-relaxed">
            {exportOut.markdown}
          </pre>
          <div className="mt-3 text-xs text-muted">Talk track: {exportOut.talk_track}</div>
        </Drawer>
      )}
    </div>
  );
}

export function Drawer({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-10 flex justify-end bg-black/40" onClick={onClose}>
      <div className="h-full w-[480px] overflow-y-auto border-l border-borderc bg-panel p-6"
        onClick={(e) => e.stopPropagation()}>
        <button className="float-right text-muted hover:text-txt" onClick={onClose}>✕</button>
        {children}
      </div>
    </div>
  );
}
