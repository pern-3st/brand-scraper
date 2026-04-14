"use client";

import { useEffect, useState } from "react";
import { useScrapeStream } from "@/hooks/useScrapeStream";
import { cancelScrape, resumeLogin, getBrand } from "@/lib/api";
import type { Source } from "@/types";
import LoginPausedBanner from "./shell/LoginPausedBanner";
import LogFeed from "./shell/LogFeed";
import OfficialSiteProgress from "./platforms/official_site/ProgressView";
import ShopeeProgress from "./platforms/shopee/ProgressView";

export default function ScrapingView({
  brandId,
  sourceId,
  scrapeId,
  onTerminated,
}: {
  brandId: string;
  sourceId: string;
  scrapeId: string;
  onTerminated: () => void;
}) {
  const { logs, categoryResults, products, doneInfo, status, pausedReason } =
    useScrapeStream(scrapeId);
  const [source, setSource] = useState<Source | null>(null);

  useEffect(() => {
    getBrand(brandId).then((d) =>
      setSource(d.sources.find((s) => s.id === sourceId) ?? null)
    );
  }, [brandId, sourceId]);

  const isStreaming = status === "connecting" || status === "streaming";
  const isTerminal =
    status === "done" || status === "cancelled" || status === "error";

  useEffect(() => {
    if (isTerminal) {
      const t = setTimeout(onTerminated, 800);
      return () => clearTimeout(t);
    }
  }, [isTerminal, onTerminated]);

  if (!source) return <p className="text-sm text-muted-fg">Loading…</p>;

  return (
    <div className="space-y-6">
      {pausedReason && (
        <LoginPausedBanner
          reason={pausedReason}
          onContinue={() => resumeLogin(scrapeId)}
          onCancel={() => cancelScrape(scrapeId)}
        />
      )}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3 space-y-4">
          {source.platform === "official_site" ? (
            <OfficialSiteProgress
              brand={String(source.spec.brand_url ?? "")}
              section={String(source.spec.section ?? "")}
              categories={(source.spec.categories as string[]) ?? []}
              categoryResults={categoryResults}
              logs={logs}
              isStreaming={isStreaming}
              isDone={isTerminal}
              status={status}
            />
          ) : (
            <ShopeeProgress
              products={products}
              logs={logs}
              doneInfo={doneInfo}
              isStreaming={isStreaming}
              status={status}
            />
          )}
        </div>
        <div className="lg:col-span-2">
          <div className="lg:sticky lg:top-6">
            <LogFeed logs={logs} streaming={isStreaming} />
          </div>
        </div>
      </div>

      {isStreaming && (
        <div className="flex justify-center">
          <button
            onClick={() => cancelScrape(scrapeId)}
            className="rounded-xl bg-danger/10 text-danger-fg px-6 py-2.5 text-sm font-medium ring-1 ring-danger/30 hover:bg-danger/20"
          >
            Stop Scraping
          </button>
        </div>
      )}
    </div>
  );
}
