import { useEffect, useState } from "react";
import { api, ForkSuggestion, UseCase } from "../lib/api";

export default function Forge({ initialSlug }: { initialSlug: string | null }) {
  const [useCases, setUseCases] = useState<UseCase[]>([]);
  const [slug, setSlug] = useState(initialSlug ?? "mcp-client");
  const [extra, setExtra] = useState("");
  const [configKind, setConfigKind] = useState<"yaml" | "ts">("yaml");
  const [sug, setSug] = useState<ForkSuggestion | null>(null);
  const [busy, setBusy] = useState<"idle" | "gen" | "exec">("idle");
  const [result, setResult] = useState<{ fork_url: string; pr_url: string } | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => { api.useCases().then(setUseCases); }, []);
  useEffect(() => { if (initialSlug) setSlug(initialSlug); }, [initialSlug]);
  useEffect(() => {
    history.replaceState(null, "", `#/forge?uc=${encodeURIComponent(slug)}`);
  }, [slug]);

  const step = result ? 4 : sug ? 3 : 2;

  const generate = async () => {
    setBusy("gen"); setErr(""); setResult(null);
    try {
      setSug(await api.suggestFork(slug, extra, configKind));
    } catch (e) { setErr(String(e)); } finally { setBusy("idle"); }
  };

  const execute = async () => {
    if (!sug) return;
    setBusy("exec"); setErr("");
    try {
      setResult(await api.executeFork(sug.id));
    } catch (e) { setErr(String(e)); } finally { setBusy("idle"); }
  };

  return (
    <div>
      <h1 className="text-lg font-bold">Fork &amp; Configure</h1>
      <p className="mb-4 text-muted">
        No solid example? Pick the best forkable repo, get the change + config, open the PR.
      </p>

      <div className="mb-5 flex">
        {["Target use case", "Pick base repo", "Review change + config", "Fork & open PR"].map((s, i) => (
          <div key={s}
            className={`flex-1 border-b-2 pb-2 text-center text-xs ${
              i + 1 < step ? "border-ok text-ok" : i + 1 === step ? "border-accent font-semibold" : "border-borderc text-muted"
            }`}>
            {i + 1} · {s}
          </div>
        ))}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select value={slug} onChange={(e) => { setSlug(e.target.value); setSug(null); setResult(null); }}
          className="rounded-lg border border-borderc bg-panel2 px-3 py-2">
          {useCases.map((u) => <option key={u.slug} value={u.slug}>{u.name}</option>)}
        </select>
        <select value={configKind} onChange={(e) => setConfigKind(e.target.value as "yaml" | "ts")}
          className="rounded-lg border border-borderc bg-panel2 px-3 py-2">
          <option value="yaml">.coderabbit.yaml</option>
          <option value="ts">custom .ts methods</option>
        </select>
        <input value={extra} onChange={(e) => setExtra(e.target.value)}
          placeholder="extra context (e.g. must involve .sql migrations)"
          className="flex-1 rounded-lg border border-borderc bg-panel2 px-3 py-2" />
        <button onClick={generate} disabled={busy !== "idle"}
          className="rounded-lg bg-accent px-4 py-2 font-semibold text-white disabled:opacity-50">
          {busy === "gen" ? "generating…" : "Generate suggestion"}
        </button>
      </div>

      {err && <div className="mb-3 rounded-xl border border-red-900 bg-red-950/40 p-3 text-xs text-bad">{err}</div>}

      {sug && (
        <>
          <div className="mb-3 rounded-xl border border-borderc bg-panel p-4">
            <b>Base repo:</b> <span className="font-mono text-xs">{sug.base_repo_full_name}</span>
            <div className="mt-1 text-xs text-muted">{sug.rationale}</div>
            {!!sug.alternatives?.length && (
              <div className="mt-2 text-[11px] text-muted">
                Alternatives: {sug.alternatives.map((a) => `${a.repo} (${a.score})`).join(" · ")}
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-borderc bg-panel p-4">
              <b>Suggested change{sug.suggested_changes.length > 1 ? "s" : ""}</b>
              {sug.suggested_changes.map((c) => (
                <div key={c.path} className="mt-2">
                  <div className="font-mono text-[11px] text-info">{c.path}</div>
                  {c.description && <div className="text-[11px] text-muted">{c.description}</div>}
                  <pre className="mt-1 overflow-x-auto rounded-lg border border-borderc bg-[#0a0d12] p-2 text-[11px] leading-relaxed">
                    {c.content}
                  </pre>
                </div>
              ))}
            </div>
            <div className="rounded-xl border border-borderc bg-panel p-4">
              <b>Suggested {sug.config_kind === "ts" ? ".coderabbit/review.ts" : ".coderabbit.yaml"}</b>
              <pre className="mt-2 overflow-x-auto rounded-lg border border-borderc bg-[#0a0d12] p-2 text-[11px] leading-relaxed">
                {sug.suggested_config}
              </pre>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <button onClick={execute} disabled={busy !== "idle"}
              className="rounded-lg bg-accent px-4 py-2 font-semibold text-white disabled:opacity-50">
              {busy === "exec" ? "forking…" : "Fork to my env → commit → open PR"}
            </button>
            <button onClick={generate} className="rounded-lg border border-borderc px-4 py-2">Regenerate</button>
            <span className="text-xs text-muted">
              Requires GITHUB_TOKEN. Fork lands in your account; PR opens against the fork.
            </span>
          </div>
        </>
      )}

      {result && (
        <div className="mt-4 rounded-xl border border-green-900 bg-green-950/30 p-4">
          ✅ PR opened — CodeRabbit should start reviewing shortly.
          <div className="mt-2 flex gap-4 text-sm">
            <a className="text-info underline" href={result.fork_url} target="_blank" rel="noreferrer">Fork ↗</a>
            <a className="text-info underline" href={result.pr_url} target="_blank" rel="noreferrer">Pull request ↗</a>
          </div>
        </div>
      )}
    </div>
  );
}
