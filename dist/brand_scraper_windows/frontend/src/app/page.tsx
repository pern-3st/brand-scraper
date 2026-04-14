"use client";

import { useState } from "react";
import Dashboard from "@/components/Dashboard";
import BrandView from "@/components/BrandView";
import ScrapingView from "@/components/ScrapingView";
import RunView from "@/components/RunView";
import Breadcrumb, { type Crumb } from "@/components/shell/Breadcrumb";
import { startScrape } from "@/lib/api";

type View =
  | { screen: "dashboard" }
  | { screen: "brand"; brandId: string }
  | { screen: "scraping"; brandId: string; sourceId: string; scrapeId: string }
  | { screen: "run"; brandId: string; sourceId: string; runId: string };

export default function Home() {
  const [view, setView] = useState<View>({ screen: "dashboard" });

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
      <header className="px-8 py-8">
        <Breadcrumb crumbs={crumbs} />
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
          />
        )}
      </div>
    </main>
  );
}

function formatRun(runId: string): string {
  const m = runId.match(/^(\d{4})(\d{2})(\d{2})T/);
  if (!m) return runId;
  return `${m[1]}-${m[2]}-${m[3]}`;
}
