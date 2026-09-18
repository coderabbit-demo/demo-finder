import { useState } from "react";
import { api, SearchOut } from "../lib/api";

export default function Ask({ onManufacture }: { onManufacture: (slug: string) => void }) {
  const [query, setQuery] = useState("");
  const [out, setOut] = useState<SearchOut | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (!query.trim()) return;
    setBusy(true);
    try {
      setOut(await api.search(query));
    } finally {
      setBusy(false);
    }
  };

  const intentSlugs = (out?.intent as { use_case_slugs?: string[] })?.use_case_slugs ?? [];
  const effortText = {
    ready: "verified example ready",
    quick: "quick setup",
    configure: "configuration needed",
    setup: "product setup needed",
  };

  return (
    <div>
      <h1 className="text-lg font-bold">Ask</h1>
      <p className="mb-4 text-muted">
        Find the right CodeRabbit capability first, then the strongest and quickest PR to demo it.
      </p>
      <div className="flex gap-2">
        <input value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="a terraform PR where coderabbit flags a security misconfig with a committable fix"
          className="flex-1 rounded-lg border border-borderc bg-panel2 px-3 py-2" />
        <button onClick={run} disabled={busy}
          className="rounded-lg bg-accent px-5 py-2 font-semibold text-white disabled:opacity-50">
          {busy ? "searching…" : "Search"}
        </button>
      </div>

      {out && (
        <div className="mt-5 space-y-3">
          <div className="rounded-xl border border-borderc bg-panel p-3 text-xs">
            <span className="text-muted">Parsed intent · {(out.intent as { parser?: string }).parser}: </span>
            {intentSlugs.map((s) => (
              <span key={s} className="mr-1 rounded-lg border border-blue-900 px-2 py-0.5 text-info">{s}</span>
            ))}
            {((out.intent as { keywords?: string[] }).keywords ?? []).map((k) => (
              <span key={k} className="mr-1 rounded-lg border border-borderc px-2 py-0.5 text-muted">{k}</span>
            ))}
          </div>

          {out.recommendations.length > 0 && (
            <section>
              <div className="mb-2 flex items-end justify-between">
                <div>
                  <h2 className="font-semibold">Recommended use cases</h2>
                  <p className="text-xs text-muted">Ranked from CodeRabbit documentation, available evidence, and demo effort.</p>
                </div>
              </div>
              <div className="divide-y divide-borderc overflow-hidden rounded-xl border border-borderc bg-panel">
                {out.recommendations.map((recommendation, index) => (
                  <div key={recommendation.slug} className="grid gap-3 p-4 md:grid-cols-[1fr_auto]">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-bold text-muted">#{index + 1}</span>
                        <span className="font-semibold">{recommendation.name}</span>
                        <span className="text-xs text-info">{Math.round(recommendation.confidence)}% match</span>
                        <span className="text-xs text-ok">{effortText[recommendation.effort]}</span>
                      </div>
                      <p className="mt-1 text-xs text-muted">{recommendation.demo_notes}</p>
                      <p className="mt-2 text-xs text-muted">
                        {recommendation.verified_examples > 0
                          ? `${recommendation.verified_examples} verified example${recommendation.verified_examples === 1 ? "" : "s"}`
                          : `${recommendation.candidate_count} predicted candidate${recommendation.candidate_count === 1 ? "" : "s"}`}
                        {recommendation.why[0] ? ` · ${recommendation.why[0]}` : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      <a href={recommendation.doc_url} target="_blank" rel="noreferrer"
                        className="text-info hover:underline">Docs</a>
                      <button onClick={() => onManufacture(recommendation.slug)}
                        className="rounded-lg border border-borderc px-3 py-1.5 font-semibold hover:border-accent hover:text-accent">
                        Manufacture
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {out.results.length > 0 && <h2 className="pt-2 font-semibold">Best matching PRs</h2>}

          {out.results.map((r, i) => (
            <div key={i} className="rounded-xl border border-borderc bg-panel p-3">
              <div className="flex items-center justify-between">
                <a href={r.pr.url} target="_blank" rel="noreferrer" className="font-semibold hover:text-accent">
                  {r.pr.repo} #{r.pr.number} — {r.pr.title}
                </a>
                <span className={`font-bold ${r.score >= 75 ? "text-ok" : "text-warn"}`}>{r.score}</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-2 text-xs text-muted">
                <a href={r.doc_url} target="_blank" rel="noreferrer" className="text-info hover:underline">{r.use_case}</a>
                <span>·</span>
                <span className={r.verified ? "text-ok" : "text-warn"}>{r.verified ? "verified in review" : "predicted"}</span>
                <span>·</span>
                <span>{r.demo_effort} demo</span>
              </div>
              <div className="mt-1 text-xs text-muted">{r.rationale}</div>
              {r.match_reasons.length > 0 && (
                <div className="mt-2 text-xs text-muted">Why it matched: {r.match_reasons.join(" · ")}</div>
              )}
            </div>
          ))}
          {out.results.length === 0 && <div className="text-muted">No indexed matches.</div>}

          {out.suggest_manufacture && (
            <div className="rounded-xl border border-blue-900 bg-[#1a2333] p-3 text-info">
              Nothing strong enough for this exact combination.{" "}
              <button className="font-semibold underline hover:text-accent"
                onClick={() => onManufacture(intentSlugs[0] ?? "code-review")}>
                Manufacture it in Fork &amp; Configure →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
