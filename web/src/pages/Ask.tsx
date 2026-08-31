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

  return (
    <div>
      <h1 className="text-lg font-bold">Ask</h1>
      <p className="mb-4 text-muted">
        Natural-language search across indexed open-source + your included org repos.
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

          {out.results.map((r, i) => (
            <div key={i} className="rounded-xl border border-borderc bg-panel p-3">
              <div className="flex items-center justify-between">
                <a href={r.pr.url} target="_blank" rel="noreferrer" className="font-semibold hover:text-accent">
                  {r.pr.repo} #{r.pr.number} — {r.pr.title}
                </a>
                <span className={`font-bold ${r.score >= 75 ? "text-ok" : "text-warn"}`}>{r.score}</span>
              </div>
              <div className="mt-1 text-xs text-muted">{r.use_case} · {r.rationale}</div>
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
