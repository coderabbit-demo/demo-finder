import { useEffect, useState } from "react";
import { api, Org } from "../lib/api";

export default function Sources() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [name, setName] = useState("");
  const [repos, setRepos] = useState("");
  const [type, setType] = useState("oss");
  const [open, setOpen] = useState<number | null>(null);
  const [err, setErr] = useState("");

  const load = () => api.orgs().then(setOrgs);
  useEffect(() => { load(); }, []);

  const add = async () => {
    if (!name.trim()) return;
    setErr("");
    try {
      await api.addOrg(name, type, repos.split(",").map((r) => r.trim()).filter(Boolean));
      setName(""); setRepos(""); load();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div>
      <h1 className="text-lg font-bold">Sources</h1>
      <p className="mb-4 text-muted">
        Choose which orgs/repos are crawled. Stored in the database. The coderabbitai org is always excluded.
      </p>
      <div className="overflow-hidden rounded-xl border border-borderc bg-panel">
        {orgs.map((o) => (
          <div key={o.id} className="border-b border-borderc p-3 last:border-0">
            <div className="flex items-center gap-3">
              <b>{o.org_name}</b>
              <span className="rounded-lg border border-borderc px-2 py-0.5 text-[11px] text-muted">
                {o.connection_type}
              </span>
              <button className="text-xs text-info underline" onClick={() => setOpen(open === o.id ? null : o.id)}>
                {o.repos.filter((r) => r.included).length}/{o.repos.length} repos
              </button>
              <button className="ml-auto text-xs text-muted hover:text-bad"
                onClick={async () => { await api.deleteOrg(o.id); load(); }}>
                remove
              </button>
              <button
                onClick={async () => { await api.toggleOrg(o.id, !o.included); load(); }}
                className={`h-5 w-9 rounded-full transition ${o.included ? "bg-ok" : "bg-borderc"}`}>
                <span className={`block h-4 w-4 translate-y-0 rounded-full bg-white transition ${o.included ? "translate-x-4" : "translate-x-0.5"}`} />
              </button>
            </div>
            {open === o.id && (
              <div className="mt-2 space-y-1 pl-2">
                {o.repos.map((r) => (
                  <label key={r.id} className="flex items-center gap-2 text-xs text-muted">
                    <input type="checkbox" checked={r.included}
                      onChange={async () => { await api.toggleRepo(r.id, !r.included); load(); }} />
                    <span className="font-mono">{r.full_name}</span>
                    <span>{(r.languages ?? []).join(", ")} · ★{r.stars}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        ))}
        <div className="p-3 text-xs text-muted">
          <b className="text-bad">coderabbitai</b> — permanently excluded
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-borderc bg-panel p-4">
        <b>Connect a source</b>
        <div className="mt-2 flex flex-wrap gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="org or user name"
            className="rounded-lg border border-borderc bg-panel2 px-3 py-2" />
          <select value={type} onChange={(e) => setType(e.target.value)}
            className="rounded-lg border border-borderc bg-panel2 px-3 py-2">
            <option value="oss">open source</option>
            <option value="personal">personal</option>
            <option value="org">org</option>
          </select>
          <input value={repos} onChange={(e) => setRepos(e.target.value)}
            placeholder="repos, comma-separated — leave empty to auto-discover from GitHub"
            className="flex-1 rounded-lg border border-borderc bg-panel2 px-3 py-2" />
          <button onClick={add} className="rounded-lg bg-accent px-4 py-2 font-semibold text-white">Add</button>
        </div>
        {err && <div className="mt-2 text-xs text-bad">{err}</div>}
        <div className="mt-2 text-[11px] text-muted">
          Auto-discovery needs GITHUB_TOKEN set in api/.env. GitLab groups land in v2.
        </div>
      </div>
    </div>
  );
}
