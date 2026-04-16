"use client";

import { useEffect, useState } from "react";
import { getBrand, listRuns } from "@/lib/api";
import type { BrandDetail, RunSummary, Source } from "@/types";
import AddSourceDrawer from "./AddSourceDrawer";
import { formatPlatform } from "@/lib/format";

export default function BrandView({
  brandId,
  onOpenRun,
  onStartScrape,
}: {
  brandId: string;
  onOpenRun: (sourceId: string, runId: string) => void;
  onStartScrape: (sourceId: string) => void | Promise<void>;
}) {
  const [detail, setDetail] = useState<BrandDetail | null>(null);
  const [runsBySource, setRunsBySource] = useState<Record<string, RunSummary[]>>(
    {}
  );
  const [adding, setAdding] = useState(false);
  const [editingSource, setEditingSource] = useState<Source | null>(null);

  async function reload() {
    const d = await getBrand(brandId);
    setDetail(d);
    const runs: Record<string, RunSummary[]> = {};
    for (const s of d.sources) runs[s.id] = await listRuns(brandId, s.id);
    setRunsBySource(runs);
  }
  useEffect(() => {
    reload();
  }, [brandId]);

  if (!detail) return <p className="text-sm text-muted-fg">Loading…</p>;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{detail.name}</h1>
      </div>

      {detail.sources.length === 0 && (
        <div className="rounded-2xl bg-card ring-1 ring-border p-8 text-center space-y-4">
          <p className="text-muted-fg">No sources yet.</p>
          <button
            onClick={() => setAdding(true)}
            className="rounded-xl bg-accent px-4 py-2 text-sm text-white hover:bg-accent-hover"
          >
            + Add source
          </button>
        </div>
      )}

      {detail.sources.map((source) => (
        <SourceCard
          key={source.id}
          source={source}
          latest={detail.latest_run_by_source[source.id] ?? null}
          onStartScrape={() => onStartScrape(source.id)}
          onOpenRun={(runId) => onOpenRun(source.id, runId)}
          onEdit={() => setEditingSource(source)}
        />
      ))}

      {detail.sources.length > 0 && (
        <button
          onClick={() => setAdding(true)}
          className="text-sm text-foreground/50 hover:text-foreground/80"
        >
          + Add source
        </button>
      )}

      <HistoryList
        sources={detail.sources}
        runsBySource={runsBySource}
        onOpenRun={onOpenRun}
      />

      <AddSourceDrawer
        open={adding || editingSource !== null}
        brandId={brandId}
        editingSource={editingSource}
        onClose={() => {
          setAdding(false);
          setEditingSource(null);
        }}
        onCreated={async () => {
          setAdding(false);
          setEditingSource(null);
          await reload();
        }}
      />
    </div>
  );
}

function SourceCard({
  source,
  latest,
  onStartScrape,
  onOpenRun,
  onEdit,
}: {
  source: Source;
  latest: RunSummary | null;
  onStartScrape: () => void;
  onOpenRun: (runId: string) => void;
  onEdit: () => void;
}) {
  return (
    <section className="space-y-4">
      <div className="rounded-2xl bg-card ring-1 ring-border p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="text-xs text-muted-fg uppercase tracking-wider">
            {formatPlatform(source.platform)} · {describeSpec(source)}
          </div>
          <button
            onClick={onEdit}
            className="text-xs text-foreground/50 hover:text-foreground/80 uppercase tracking-wider"
          >
            Edit
          </button>
        </div>
        {latest ? (
          <>
            <div className="text-lg text-foreground">
              {latest.aggregates.price_min !== null &&
              latest.aggregates.price_max !== null
                ? `$${latest.aggregates.price_min.toFixed(0)} – $${latest.aggregates.price_max.toFixed(0)}`
                : "—"}
            </div>
            <div className="text-sm text-muted-fg">
              {latest.aggregates.product_count} products
              {latest.aggregates.category_count !== null &&
                ` · ${latest.aggregates.category_count} categories`}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => onOpenRun(latest.id)}
                className="rounded-xl bg-accent/10 text-accent px-4 py-2 text-sm hover:bg-accent/20"
              >
                View snapshot
              </button>
              <button
                onClick={onStartScrape}
                className="rounded-xl bg-accent px-4 py-2 text-sm text-white hover:bg-accent-hover"
              >
                Scrape again
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm text-muted-fg">No runs yet.</p>
            <button
              onClick={onStartScrape}
              className="rounded-xl bg-accent px-4 py-2 text-sm text-white hover:bg-accent-hover"
            >
              Scrape now
            </button>
          </>
        )}
      </div>

    </section>
  );
}

function HistoryList({
  sources,
  runsBySource,
  onOpenRun,
}: {
  sources: Source[];
  runsBySource: Record<string, RunSummary[]>;
  onOpenRun: (sourceId: string, runId: string) => void;
}) {
  const entries = sources
    .flatMap((source) =>
      (runsBySource[source.id] ?? []).map((run) => ({ source, run }))
    )
    .sort((a, b) => (a.run.id < b.run.id ? 1 : -1));

  if (entries.length === 0) return null;

  return (
    <div className="space-y-1">
      <h3 className="text-sm font-semibold text-foreground/50 uppercase tracking-wider px-1">
        History
      </h3>
      <ul className="divide-y divide-border">
        {entries.map(({ source, run }) => (
          <li key={`${source.id}:${run.id}`}>
            <button
              onClick={() => onOpenRun(source.id, run.id)}
              className="w-full flex items-center gap-4 py-3 px-1 text-sm hover:bg-foreground/[0.02]"
            >
              <span className="text-foreground/80 text-left shrink-0">
                {formatRunDate(run.id)}
              </span>
              <span className="text-muted-fg text-left flex-1 truncate">
                {formatPlatform(source.platform)}
              </span>
              <span className="text-muted-fg shrink-0">
                {formatStatus(run)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatStatus(run: RunSummary): string {
  if (run.status === "ok") {
    return `OK · ${run.aggregates.product_count} products`;
  }
  return run.status;
}

function describeSpec(s: Source): string {
  if (s.platform === "official_site") return String(s.spec.brand_url ?? "");
  if (s.platform === "shopee") return String(s.spec.shop_url ?? "");
  return "";
}

function formatRunDate(runId: string): string {
  const m = runId.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
  if (!m) return runId;
  const d = new Date(
    Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6])
  );
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
