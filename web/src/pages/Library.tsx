import { useEffect, useState } from "react";
import { api, FlaggedExample, UseCase } from "../lib/api";

export default function Library({ onManufacture, onOpenFinder }:
  { onManufacture: (slug: string) => void; onOpenFinder: (slug: string) => void }) {
  const [useCases, setUseCases] = useState<UseCase[]>([]);
  const [flagged, setFlagged] = useState<FlaggedExample[]>([]);
  const [prompt, setPrompt] = useState("");
  const [creating, setCreating] = useState(false);
  const [msg, setMsg] = useState("");

  const load = () => {
    api.useCases().then(setUseCases);
    api.examples().then(setFlagged);
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!prompt.trim()) return;
    setCreating(true);
    setMsg("");
    try {
      const r = (await api.createUseCase(prompt)) as { name: string };
      setMsg(`Created "${r.name}" — the finder and fork engine now know it.`);
      setPrompt("");
      load();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      <h1 className="text-lg font-bold">Use-Case Library</h1>
      <p className="mb-4 text-muted">
        Every capability, its heuristics, and how many good candidates (score ≥ 70) exist.
      </p>
      <div className="grid grid-cols-3 gap-2.5">
        {useCases.map((u) => {
          const mine = flagged.filter((f) => f.use_case === u.slug);
          return (
            <div key={u.slug}
              className="cursor-pointer rounded-xl border border-borderc bg-panel p-3 hover:border-accent"
              onClick={() => onOpenFinder(u.slug)}
              title="Open in PR Finder">
              <span className={`float-right text-[11px] ${u.good_candidates ? "text-ok" : "text-bad"}`}>
                {u.flagged_count > 0 && <span className="mr-1 text-warn">★{u.flagged_count}</span>}
                {u.good_candidates ? `${u.good_candidates} candidates` : "none yet"}
              </span>
              <h4 className="text-[13px] font-semibold">
                {u.name} {u.is_custom && <span className="text-[10px] text-viol">custom</span>}
                {u.doc_url && (
                  <a href={u.doc_url} target="_blank" rel="noreferrer" title="CodeRabbit docs"
                    onClick={(e) => e.stopPropagation()} className="ml-1 text-[11px] text-info hover:underline">
                    docs ↗
                  </a>
                )}
              </h4>
              <p className="mt-1 text-[11.5px] leading-snug text-muted">{u.definition || u.demo_script_notes}</p>
              {u.definition && u.demo_script_notes && (
                <p className="mt-1 text-[11px] italic leading-snug text-info/70">demo: {u.demo_script_notes}</p>
              )}
              {mine.map((f) => (
                <a key={f.id} href={f.pr.url} target="_blank" rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="mt-1 block truncate text-[11px] text-warn hover:underline">
                  ★ {f.pr.repo} #{f.pr.number}
                </a>
              ))}
              {u.good_candidates === 0 && (
                <button
                  onClick={(e) => { e.stopPropagation(); onManufacture(u.slug); }}
                  className="mt-2 rounded-lg border border-borderc px-2 py-1 text-[11px] text-muted hover:border-accent hover:text-txt">
                  🔧 Manufacture one
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-5 rounded-xl border border-borderc bg-panel p-4">
        <b>Need a use case that isn't here?</b>
        <div className="mt-2 flex gap-2">
          <input value={prompt} onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            placeholder="e.g. reviews of .sql migration files that flag missing indexes"
            className="flex-1 rounded-lg border border-borderc bg-panel2 px-3 py-2" />
          <button onClick={create} disabled={creating}
            className="rounded-lg bg-accent px-4 py-2 font-semibold text-white disabled:opacity-50">
            {creating ? "creating…" : "Create use case"}
          </button>
        </div>
        {msg && <div className="mt-2 text-xs text-info">{msg}</div>}
        <div className="mt-2 text-xs text-muted">
          Your description becomes detection heuristics + required config; finder, search, and the
          fork engine treat it like any built-in. GitHub &amp; GitLab examples only for now.
        </div>
      </div>
    </div>
  );
}
