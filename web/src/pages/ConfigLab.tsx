export default function ConfigLab() {
  return (
    <div>
      <h1 className="text-lg font-bold">
        Config Lab <span className="ml-1 rounded-lg bg-purple-950 px-2 py-0.5 text-xs text-viol">v2 preview</span>
      </h1>
      <p className="mb-4 text-muted">
        Live config resolution per the Indeed spec — inheritance-by-default, first-writer-wins walk,
        includes, remote_config, global overrides, schema defaults, with a per-key "won by" trace.
      </p>
      <div className="rounded-xl border border-borderc bg-panel p-4">
        <p className="text-sm leading-relaxed text-muted">
          The engine already exists and is fully tested:{" "}
          <span className="font-mono text-xs text-info">api/app/services/config_engine/resolver.py</span>{" "}
          implements <span className="font-mono text-xs">get_repo_config()</span>,{" "}
          <span className="font-mono text-xs">accumulate()</span>,{" "}
          <span className="font-mono text-xs">fill_gaps</span> / <span className="font-mono text-xs">apply_overrides</span>,
          the <span className="font-mono text-xs">inheritance: false</span> opt-out, exclusive{" "}
          <span className="font-mono text-xs">remote_config</span> redirects, last-listed-wins includes, and
          identity-based list merging. The v1 fork engine uses it to keep generated configs resolution-valid.
        </p>
        <p className="mt-3 text-sm text-muted">
          This tab becomes interactive in v2: paste repo / central / org / workspace configs and watch the
          worked-example trace resolve live. Ask for it whenever you're ready.
        </p>
      </div>
    </div>
  );
}
