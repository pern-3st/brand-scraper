"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import Dashboard from "@/components/Dashboard";
import BrandView from "@/components/BrandView";
import ScrapingView from "@/components/ScrapingView";
import RunView from "@/components/RunView";
import EnrichmentProgress from "@/components/EnrichmentProgress";
import SettingsModal from "@/components/SettingsModal";
import Breadcrumb, { type Crumb } from "@/components/shell/Breadcrumb";
import { startScrape } from "@/lib/api";

type View =
  | { screen: "dashboard" }
  | { screen: "brand"; brandId: string }
  | { screen: "scraping"; brandId: string; sourceId: string; scrapeId: string }
  | { screen: "run"; brandId: string; sourceId: string; runId: string }
  | {
      screen: "enriching";
      brandId: string;
      sourceId: string;
      runId: string;
      sessionId: string;
    };

const isTransient = (s: View["screen"]) =>
  s === "scraping" || s === "enriching";

function viewToUrl(view: View): string {
  const params = new URLSearchParams();
  if (view.screen !== "dashboard") {
    params.set("brand", view.brandId);
  }
  if (view.screen === "scraping") {
    params.set("source", view.sourceId);
    params.set("scrape", view.scrapeId);
  } else if (view.screen === "run") {
    params.set("source", view.sourceId);
    params.set("run", view.runId);
  } else if (view.screen === "enriching") {
    params.set("source", view.sourceId);
    params.set("run", view.runId);
    params.set("session", view.sessionId);
  }
  const qs = params.toString();
  return qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
}

function subscribeURL(cb: () => void): () => void {
  window.addEventListener("popstate", cb);
  window.addEventListener("urlchange", cb);
  return () => {
    window.removeEventListener("popstate", cb);
    window.removeEventListener("urlchange", cb);
  };
}

function getURLSearch(): string {
  return window.location.search;
}

function getServerURLSearch(): string {
  return "";
}

function urlToView(search: string): View {
  const p = new URLSearchParams(search);
  const brand = p.get("brand");
  if (!brand) return { screen: "dashboard" };
  const source = p.get("source");
  const run = p.get("run");
  const scrape = p.get("scrape");
  const session = p.get("session");
  if (source && scrape) {
    return { screen: "scraping", brandId: brand, sourceId: source, scrapeId: scrape };
  }
  if (source && run && session) {
    return { screen: "enriching", brandId: brand, sourceId: source, runId: run, sessionId: session };
  }
  if (source && run) {
    return { screen: "run", brandId: brand, sourceId: source, runId: run };
  }
  return { screen: "brand", brandId: brand };
}

export default function Home() {
  const search = useSyncExternalStore(
    subscribeURL,
    getURLSearch,
    getServerURLSearch,
  );
  const view = useMemo(() => urlToView(search), [search]);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    const initial = urlToView(window.location.search);
    window.history.replaceState({ view: initial }, "", viewToUrl(initial));
  }, []);

  const setView = (next: View) => {
    const op =
      isTransient(next.screen) || isTransient(view.screen)
        ? "replaceState"
        : "pushState";
    window.history[op]({ view: next }, "", viewToUrl(next));
    window.dispatchEvent(new Event("urlchange"));
  };

  const crumbs: Crumb[] = (() => {
    if (view.screen === "dashboard") return [{ label: "Brand Scraper" }];
    const root: Crumb = {
      label: "Brand Scraper",
      onClick: () => setView({ screen: "dashboard" }),
    };
    if (view.screen === "brand") {
      return [root, { label: view.brandId }];
    }
    if (view.screen === "scraping") {
      return [
        root,
        {
          label: view.brandId,
          onClick: () =>
            setView({ screen: "brand", brandId: view.brandId }),
        },
        { label: "Scraping…" },
      ];
    }
    if (view.screen === "enriching") {
      return [
        root,
        {
          label: view.brandId,
          onClick: () => setView({ screen: "brand", brandId: view.brandId }),
        },
        {
          label: formatRun(view.runId),
          onClick: () =>
            setView({
              screen: "run",
              brandId: view.brandId,
              sourceId: view.sourceId,
              runId: view.runId,
            }),
        },
        { label: "Enriching…" },
      ];
    }
    return [
      root,
      {
        label: view.brandId,
        onClick: () => setView({ screen: "brand", brandId: view.brandId }),
      },
      { label: formatRun(view.runId) },
    ];
  })();

  const containerWidth =
    view.screen === "run" ? "max-w-[1600px]" : "max-w-5xl";

  return (
    <main className="min-h-screen">
      <div className={`mx-auto px-6 ${containerWidth}`}>
        <header className="py-8 flex items-center justify-between gap-4">
          <Breadcrumb crumbs={crumbs} />
          <button
            onClick={() => setSettingsOpen(true)}
            aria-label="Settings"
            title="Settings"
            className="cursor-pointer text-foreground/40 hover:text-foreground/80 transition-colors"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
        </header>
        <div className="pb-12">
        {view.screen === "dashboard" && (
          <Dashboard
            onOpenBrand={(brandId) => setView({ screen: "brand", brandId })}
          />
        )}
        {view.screen === "brand" && (
          <BrandView
            brandId={view.brandId}
            onOpenRun={(sourceId, runId) =>
              setView({
                screen: "run",
                brandId: view.brandId,
                sourceId,
                runId,
              })
            }
            onStartScrape={async (sourceId) => {
              const { scrape_id } = await startScrape(view.brandId, sourceId);
              setView({
                screen: "scraping",
                brandId: view.brandId,
                sourceId,
                scrapeId: scrape_id,
              });
            }}
          />
        )}
        {view.screen === "scraping" && (
          <ScrapingView
            brandId={view.brandId}
            sourceId={view.sourceId}
            scrapeId={view.scrapeId}
            onTerminated={() =>
              setView({ screen: "brand", brandId: view.brandId })
            }
          />
        )}
        {view.screen === "run" && (
          <RunView
            brandId={view.brandId}
            sourceId={view.sourceId}
            runId={view.runId}
            onStartEnrichment={({ session_id }) =>
              setView({
                screen: "enriching",
                brandId: view.brandId,
                sourceId: view.sourceId,
                runId: view.runId,
                sessionId: session_id,
              })
            }
          />
        )}
        {view.screen === "enriching" && (
          <EnrichmentProgress
            sessionId={view.sessionId}
            onTerminated={() =>
              setView({
                screen: "run",
                brandId: view.brandId,
                sourceId: view.sourceId,
                runId: view.runId,
              })
            }
          />
        )}
        </div>
      </div>
      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </main>
  );
}

function formatRun(runId: string): string {
  const m = runId.match(/^(\d{4})(\d{2})(\d{2})T/);
  if (!m) return runId;
  return `${m[1]}-${m[2]}-${m[3]}`;
}
