"use client";

import { useState } from "react";
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

export default function Home() {
  const [view, setView] = useState<View>({ screen: "dashboard" });
  const [settingsOpen, setSettingsOpen] = useState(false);

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

  return (
    <main className="min-h-screen">
      <header className="px-8 py-8 flex items-center justify-between gap-4">
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
      <div className="mx-auto max-w-5xl px-6 pb-12">
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
