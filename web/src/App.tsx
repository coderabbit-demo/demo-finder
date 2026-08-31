import { useEffect, useState } from "react";
import { api } from "./lib/api";
import Finder from "./pages/Finder";
import Library from "./pages/Library";
import Ask from "./pages/Ask";
import Forge from "./pages/Forge";
import Sources from "./pages/Sources";
import ConfigLab from "./pages/ConfigLab";

const TABS = [
  { id: "finder", label: "🔎 PR Finder" },
  { id: "library", label: "📚 Use-Case Library" },
  { id: "ask", label: "💬 Ask" },
  { id: "forge", label: "🔧 Fork & Configure" },
  { id: "sources", label: "🗂 Sources" },
  { id: "configlab", label: "🧪 Config Lab", badge: "v2" },
] as const;

export type TabId = (typeof TABS)[number]["id"];

function parseHash(): { tab: TabId; params: URLSearchParams } {
  const h = window.location.hash.replace(/^#\/?/, "");
  const [path, qs] = h.split("?");
  const tab = (TABS.find((t) => t.id === path)?.id ?? "finder") as TabId;
  return { tab, params: new URLSearchParams(qs ?? "") };
}

/** Navigate = change the URL. State follows the hash, so every view is a real,
 *  shareable deep link: #/finder?uc=sequence-diagrams&min=70, #/forge?uc=mcp-client */
export function nav(tab: TabId, params?: Record<string, string>) {
  const qs = params && Object.keys(params).length ? "?" + new URLSearchParams(params) : "";
  window.location.hash = `/${tab}${qs}`;
}

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const [health, setHealth] = useState<{ dev_mode: boolean; github: boolean; llm: boolean } | null>(null);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    api.health().then(setHealth).catch(() => setHealth(null));
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const { tab, params } = route;
  const uc = params.get("uc");
  const min = params.get("min");

  return (
    <div className="flex min-h-screen text-sm">
      <nav className="w-56 shrink-0 border-r border-borderc bg-panel p-3">
        <div className="mb-4 flex items-center gap-2 px-2 font-bold">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-orange-500">
            🐇
          </span>
          Demo Finder
        </div>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => nav(t.id)}
            className={`mb-0.5 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left ${
              tab === t.id ? "bg-panel2 text-txt" : "text-muted hover:text-txt"
            }`}
          >
            {t.label}
            {"badge" in t && t.badge && (
              <span className="ml-auto rounded-lg bg-purple-950 px-1.5 text-[10px] text-viol">{t.badge}</span>
            )}
          </button>
        ))}
        {health && (
          <div className="mt-6 space-y-1 px-2 text-[11px] text-muted">
            <div>{health.dev_mode ? "🟡 dev fixtures" : "🟢 live data"}</div>
            <div>{health.github ? "🟢 GitHub token" : "⚪ no GitHub token"}</div>
            <div>{health.llm ? "🟢 LLM scoring" : "⚪ heuristics only"}</div>
          </div>
        )}
      </nav>
      <main className="max-w-5xl flex-1 p-7">
        {tab === "finder" && (
          <Finder onManufacture={(s) => nav("forge", { uc: s })}
            initialSlug={uc} initialMin={min ? Number(min) : undefined} />
        )}
        {tab === "library" && (
          <Library onManufacture={(s) => nav("forge", { uc: s })}
            onOpenFinder={(s) => nav("finder", { uc: s, min: "0" })} />
        )}
        {tab === "ask" && <Ask onManufacture={(s) => nav("forge", { uc: s })} />}
        {tab === "forge" && <Forge initialSlug={uc} />}
        {tab === "sources" && <Sources />}
        {tab === "configlab" && <ConfigLab />}
      </main>
    </div>
  );
}
